# streamlit_admin_resumes.py
import io
import os
import re
import pickle
from pathlib import Path
from typing import List, Dict, Tuple

import streamlit as st
import pandas as pd
import chromadb
from pypdf import PdfReader
from docx import Document as Docx

# Reuse cleaning/tokenization from the standalone utils
from utils_r import clean_text, tokenize, stable_id_from_bytes

# Config for the RESUMES corpus (isolated DB + indexes)
from config_jds_resumes import (
    CHROMA_DIR_RESUMES, CHROMA_COLLECTION_RESUMES,
    RESUMES_STORE_DIR, RESUMES_INDEX_DIR,
    BM25_RESUMES_CORPUS_PATH, BM25_RESUMES_META_PATH, BM25_RESUMES_DOCIDS_PATH,
    EMBED_MODEL,
)

# --------------------------- Streamlit page ---------------------------
st.set_page_config(page_title="Admin – Resume Indexer (Separate Corpus)", page_icon="📄", layout="wide")
st.title("Admin – Resume Indexer (Separate Corpus)")
st.caption("Ingest resumes into their own Chroma collection and BM25 index — fully isolated from your JD corpus.")

# --------------------------- Helpers ---------------------------

def sanitize_metadata(md: dict) -> dict:
    """Ensure all values are Bool/Int/Float/Str; drop/convert Nones and odd types."""
    clean = {}
    for k, v in (md or {}).items():
        if v is None:
            continue
        if isinstance(v, (bool, int, float, str)):
            clean[k] = v
        else:
            clean[k] = str(v)
    return clean

def chunk_text(text: str, size: int, overlap: int) -> List[str]:
    n = len(text)
    if n == 0:
        return []
    size = max(1, int(os.getenv("RES_CHUNK_SIZE", "600")))
    overlap = max(0, int(os.getenv("RES_CHUNK_OVERLAP", "120")))
    if overlap >= size:
        overlap = size // 4
    chunks, start = [], 0
    while start < n:
        end = min(n, start + size)
        chunks.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks

def read_text_from_bytes(data: bytes, filename: str) -> Tuple[str, str]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        with io.BytesIO(data) as f:
            reader = PdfReader(f, strict=False)
            text = " ".join((page.extract_text() or "") for page in reader.pages)
    elif ext == ".docx":
        with io.BytesIO(data) as f:
            doc = Docx(f)
            text = "\n".join(p.text for p in doc.paragraphs)
    elif ext in {".txt", ".rtf", ".md"}:
        text = data.decode(errors="ignore")
    else:
        # try raw decode
        text = data.decode(errors="ignore")
    return clean_text(text), ext

def extract_resume_metadata(text: str, fallback_name: str) -> Dict:
    """
    Very lightweight metadata extraction for resumes.
    - candidate_name: first non-empty short line OR fallback to file stem
    - email: first email regex match
    - phone: first phone regex match
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # candidate name: choose first line that's not too long and lacks obvious section headers
    name = None
    for ln in lines[:10]:
        if 2 <= len(ln) <= 60 and not re.search(r"(?i)summary|experience|education|skills|profile|contact", ln):
            name = ln
            break
    candidate_name = name or fallback_name

    email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    email = email_match.group(0) if email_match else ""

    # simple phone finder; covers international/space/dash/paren formats
    phone_match = re.search(r"(\+\d{1,3}\s?)?(\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{4}", text)
    phone = phone_match.group(0) if phone_match else ""

    return {
        "candidate_name": candidate_name or "",
        "email": email or "",
        "phone": phone or "",
    }

def get_chroma():
    client = chromadb.PersistentClient(path=CHROMA_DIR_RESUMES)
    coll = client.get_or_create_collection(name=CHROMA_COLLECTION_RESUMES)
    os.makedirs(RESUMES_INDEX_DIR, exist_ok=True)
    os.makedirs(RESUMES_STORE_DIR, exist_ok=True)
    return coll

def get_embedder():
    # Lazy import so the UI can load without Ollama running
    from langchain_community.embeddings import OllamaEmbeddings
    return OllamaEmbeddings(model=EMBED_MODEL)

def load_bm25():
    if os.path.exists(BM25_RESUMES_CORPUS_PATH):
        with open(BM25_RESUMES_CORPUS_PATH, "rb") as f:
            corpus_tokens = pickle.load(f)
    else:
        corpus_tokens = []
    if os.path.exists(BM25_RESUMES_META_PATH):
        with open(BM25_RESUMES_META_PATH, "rb") as f:
            meta_by_id = pickle.load(f)
    else:
        meta_by_id = {}
    if os.path.exists(BM25_RESUMES_DOCIDS_PATH):
        with open(BM25_RESUMES_DOCIDS_PATH, "rb") as f:
            bm25_doc_ids = pickle.load(f)
    else:
        bm25_doc_ids = []
    return corpus_tokens, meta_by_id, bm25_doc_ids

def save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids):
    with open(BM25_RESUMES_CORPUS_PATH, "wb") as f:
        pickle.dump(corpus_tokens, f)
    with open(BM25_RESUMES_META_PATH, "wb") as f:
        pickle.dump(meta_by_id, f)
    with open(BM25_RESUMES_DOCIDS_PATH, "wb") as f:
        pickle.dump(bm25_doc_ids, f)

# --------------------------- Core ingestion ---------------------------

def add_one_document(coll, text: str, metadata: Dict, base_id: str, corpus_tokens: List[List[str]], bm25_doc_ids: List[str]):
    # 1) Chunk
    chunks = chunk_text(text, size=int(os.getenv("RES_CHUNK_SIZE", "600")), overlap=int(os.getenv("RES_CHUNK_OVERLAP", "120")))
    if not chunks:
        return

    # 2) Embed (via Ollama)
    try:
        embedder = get_embedder()
        vecs = embedder.embed_documents(chunks)
    except Exception as e:
        st.error("Embedding failed. Ensure Ollama is running and the model is pulled (e.g., `ollama pull nomic-embed-text`).", icon="⚠️")
        raise

    # 3) IDs + per-chunk metadata
    ids = [f"{base_id}::chunk_{i}" for i in range(len(chunks))]

    base_md = sanitize_metadata(metadata)

    metas = []
    for i, ch in enumerate(chunks):
        md = dict(base_md)
        md.update({
            "parent_id": base_id,
            "resume_id": base_id,
            "chunk_id": int(i),
            "source_ext": str(metadata.get("source_ext") or ""),
            "file_path": str(metadata.get("file_path") or ""),
        })
        metas.append(sanitize_metadata(md))

    # 4) Add to Chroma
    coll.add(documents=chunks, metadatas=metas, ids=ids, embeddings=vecs)

    # 5) Update BM25 artifacts
    for ch in chunks:
        corpus_tokens.append(tokenize(ch))
    bm25_doc_ids.extend(ids)

# --------------------------- UI ---------------------------

tab_up, tab_scan, tab_inv = st.tabs(["Upload Resumes", "Scan folder", "Inventory"])

with tab_up:
    st.caption("Community & Service Profile (saved along with each uploaded resume)")
    interestedCommunityAreas = st.multiselect(
        "Interested Community Areas",
        options=[
            "health care", "education", "public safety", "environment",
            "community development", "arts & culture", "disaster response",
        ],
        default=["health care", "education"]
    )
    preferredServiceType = st.selectbox(
        "Preferred Service Type",
        options=[
            "Mentoring", "Tutoring", "Training/Workshops", "Fundraising",
            "Event Support", "Admin/Back-office", "Field Work", "Other"
        ],
        index=0
    )
    causesPassionateAbout = st.multiselect(
        "Causes You’re Passionate About",
        options=[
            "youth development", "elder care", "veterans", "homelessness",
            "food security", "STEM education", "mental health", "animal welfare"
        ],
        default=["youth development"]
    )
    communityServiceExperience = st.text_area(
        "Community Service Experience",
        value="mkjkhgxfcgvhjkll",
        placeholder="Briefly describe prior community/volunteer experience…",
        height=120
    )
    skillsForCommunityService = st.multiselect(
        "Skills for Community Service",
        options=[
            "teaching", "counseling", "project management", "public speaking",
            "data analysis", "first aid", "translation", "IT support", "outreach"
        ],
        default=["teaching"]
    )
    certificationsOrTraining = st.multiselect(
        "Certifications or Training",
        options=[
            "childcare", "first aid/CPR", "background screening",
            "teaching credential", "social work training", "youth counseling"
        ],
        default=["childcare"]
    )
    st.divider()
    
    st.subheader("Upload resume files")
    up = st.file_uploader("Drop one or many resumes", type=["pdf", "docx", "txt", "rtf", "doc"], accept_multiple_files=True)
    if up:
        coll = get_chroma()
        corpus_tokens, meta_by_id, bm25_doc_ids = load_bm25()
        details = st.empty()
        added = skipped = 0
        for f in up:
            data = f.read()
            sha256_full, short12 = stable_id_from_bytes(data)

            # Skip if already present by sha256
            already = any(md.get("sha256") == sha256_full for md in meta_by_id.values())
            if already:
                skipped += 1
                continue

            try:
                text, ext = read_text_from_bytes(data, f.name)
                base_id = f"{Path(f.name).stem}.{short12}"
                stored_name = f"{Path(f.name).stem}.{short12}{Path(f.name).suffix.lower()}"
                stored_path = str(Path(RESUMES_STORE_DIR) / stored_name)
                if not os.path.exists(stored_path):
                    with open(stored_path, "wb") as w:
                        w.write(data)

                md_core = extract_resume_metadata(text, Path(f.name).stem)
                md = sanitize_metadata({
                    **md_core,
                    "sha256": sha256_full,
                    "short_hash": short12,
                    "file_path": stored_path,
                    "source_ext": ext,
                    # ---- Community & Service Profile (from the UI above) ----
                    "interestedCommunityAreas": interestedCommunityAreas,
                    "preferredServiceType": preferredServiceType,
                    "causesPassionateAbout": causesPassionateAbout,
                    "communityServiceExperience": communityServiceExperience,
                    "skillsForCommunityService": skillsForCommunityService,
                    "certificationsOrTraining": certificationsOrTraining,
                })
                meta_by_id[base_id] = md

                add_one_document(coll, text, md, base_id, corpus_tokens, bm25_doc_ids)
                added += 1
                details.info(f"Added: {f.name} → {base_id}")
            except Exception as e:
                st.warning(f"Skip {f.name}: {e}")

        save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids)
        st.success(f"Done. Added {added}, skipped {skipped}.")



with tab_scan:
    st.subheader("Scan a folder of resume files")
    p = st.text_input("Folder path", value=str(Path.cwd()))
    go = st.button("Scan & ingest", type="primary")
    if go:
        coll = get_chroma()
        corpus_tokens, meta_by_id, bm25_doc_ids = load_bm25()
        paths = [x for x in Path(p).glob("*") if x.is_file()]
        added = skipped = 0
        for path in paths:
            try:
                data = path.read_bytes()
                sha256_full, short12 = stable_id_from_bytes(data)

                if any(md.get("sha256") == sha256_full for md in meta_by_id.values()):
                    skipped += 1
                    continue

                text, ext = read_text_from_bytes(data, path.name)
                base_id = f"{path.stem}.{short12}"
                stored_name = f"{path.stem}.{short12}{path.suffix.lower()}"
                stored_path = str(Path(RESUMES_STORE_DIR) / stored_name)
                if not os.path.exists(stored_path):
                    with open(stored_path, "wb") as w:
                        w.write(data)

                md_core = extract_resume_metadata(text, path.stem)
                md = sanitize_metadata({
                    **md_core,
                    "sha256": sha256_full,
                    "short_hash": short12,
                    "file_path": stored_path,
                    "source_ext": ext,
                })
                meta_by_id[base_id] = md

                add_one_document(coll, text, md, base_id, corpus_tokens, bm25_doc_ids)
                added += 1
            except Exception:
                skipped += 1

        save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids)
        st.success(f"Ingestion finished. Added {added}, skipped {skipped}.")

with tab_inv:
    st.subheader("Resume Inventory in Chroma (parent-level)")
    coll = get_chroma()

    # Collect all metadatas to aggregate by resume_id
    ids_all, metas_all = [], []
    offset, page = 0, 500
    while True:
        batch = coll.get(include=["metadatas"], limit=page, offset=offset)
        _ids = batch.get("ids", [])
        _metas = batch.get("metadatas", [])
        if not _ids:
            break
        ids_all.extend(_ids)
        metas_all.extend(_metas)
        offset += len(_ids)

    # group by parent_id / resume_id
    agg = {}
    for _id, md in zip(ids_all, metas_all):
        if not md:
            continue
        pid = md.get("resume_id") or md.get("parent_id") or (_id.split("::")[0] if _id else None)
        row = agg.get(pid) or {
            "resume_id": pid,
            "candidate_name": md.get("candidate_name", ""),
            "email": md.get("email", ""),
            "phone": md.get("phone", ""),
            "source_ext": md.get("source_ext", ""),
            "short_hash": md.get("short_hash", ""),
            "sha256": md.get("sha256", ""),
            "file_path": md.get("file_path", ""),
            "chunks": 0,
        }
        row["chunks"] = row.get("chunks", 0) + 1
        agg[pid] = row

    df = pd.DataFrame(list(agg.values()))
    if df.empty:
        st.info("No resumes indexed yet.")
    else:
        show = ["candidate_name", "email", "phone", "resume_id", "chunks", "short_hash", "sha256", "file_path"]
        for col in show:
            if col not in df.columns:
                df[col] = None
        st.dataframe(df[show], use_container_width=True, hide_index=True)
        with st.expander("Export as CSV"):
            csv = df[show].to_csv(index=False).encode()
            st.download_button("Download CSV", csv, "resume_inventory.csv", "text/csv")
