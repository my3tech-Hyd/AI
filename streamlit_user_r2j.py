# streamlit_user_r2j.py
import io
import os
from pathlib import Path
from typing import List, Dict, Tuple

import streamlit as st
import pandas as pd
import chromadb
import requests
from rank_bm25 import BM25Okapi
from pypdf import PdfReader
from docx import Document as Docx

# Reuse helpers
from utils_jd import clean_text, tokenize

# JD corpus config
from config_jd import (
    CHROMA_DIR, CHROMA_COLLECTION_JDS,
    JDS_INDEX_DIR, BM25_JDS_CORPUS_PATH, BM25_JDS_META_PATH, BM25_JDS_DOCIDS_PATH,
)

st.set_page_config(page_title="Resume → JD Search", page_icon="🔁", layout="wide")

# Tunables
MAX_QUERY_CHARS = int(os.getenv("R2J_MAX_QUERY_CHARS", "1200"))
OLLAMA_TIMEOUT  = float(os.getenv("OLLAMA_TIMEOUT", "45"))
QUERY_CHUNK_SIZE    = int(os.getenv("R2J_QUERY_CHUNK_SIZE", "500"))
QUERY_CHUNK_OVERLAP = int(os.getenv("R2J_QUERY_CHUNK_OVERLAP", "100"))
QUERY_MAX_CHUNKS    = int(os.getenv("R2J_QUERY_MAX_CHUNKS", "6"))
TOP_K_VECTOR = int(os.getenv("R2J_TOP_K_VECTOR", "40"))
TOP_K_FINAL  = int(os.getenv("R2J_TOP_K_FINAL", "10"))
HYBRID_ALPHA = float(os.getenv("R2J_HYBRID_ALPHA", "0.6"))  # semantic vs keyword balance
EMBED_MODEL  = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# ---------- Helpers ----------

def read_text_from_bytes(data: bytes, filename: str) -> str:
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
        text = data.decode(errors="ignore")
    return clean_text(text)

def chunk_text_query(text: str, size: int, overlap: int, max_chunks: int) -> List[str]:
    t = text[:MAX_QUERY_CHARS] if MAX_QUERY_CHARS > 0 else text
    n = len(t)
    if n == 0: return []
    size  = max(1, int(size))
    overlap = max(0, int(overlap))
    if overlap >= size: overlap = size // 4
    chunks, start = [], 0
    while start < n and len(chunks) < max_chunks:
        end = min(n, start + size)
        chunks.append(t[start:end])
        if end == n: break
        start = end - overlap
    return chunks

def embed_query(chunk: str) -> List[float]:
    # direct call to Ollama /api/embeddings to avoid heavier deps
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": chunk},
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        vec = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if not isinstance(vec, list) or not all(isinstance(x, (int, float)) for x in vec):
            raise ValueError("Invalid embedding vector")
        return vec
    except Exception as e:
        st.error(f"Embedding failed against {OLLAMA_HOST}. Is Ollama running and `{EMBED_MODEL}` pulled?", icon="⚠️")
        raise

def embed_query_pooled(text: str) -> List[float]:
    chunks = chunk_text_query(text, QUERY_CHUNK_SIZE, QUERY_CHUNK_OVERLAP, QUERY_MAX_CHUNKS)
    if not chunks:
        return []
    vecs = [embed_query(ch) for ch in chunks]
    # length-weighted mean pool
    dims = len(vecs[0])
    pooled = [0.0]*dims
    weights = [len(ch) for ch in chunks]
    W = float(sum(weights) or 1.0)
    for v, w in zip(vecs, weights):
        if len(v) != dims:  # guard
            continue
        for i in range(dims):
            pooled[i] += (w * float(v[i]))
    for i in range(dims):
        pooled[i] /= W
    return pooled

def get_chroma():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_or_create_collection(name=CHROMA_COLLECTION_JDS)

def load_bm25():
    import pickle
    if not (os.path.exists(BM25_JDS_CORPUS_PATH) and os.path.exists(BM25_JDS_DOCIDS_PATH)):
        return None, None, None
    with open(BM25_JDS_CORPUS_PATH, "rb") as f:
        corpus_tokens = pickle.load(f)
    with open(BM25_JDS_DOCIDS_PATH, "rb") as f:
        bm25_doc_ids = pickle.load(f)
    with open(BM25_JDS_META_PATH, "rb") as f:
        meta_by_id = pickle.load(f)
    return corpus_tokens, bm25_doc_ids, meta_by_id

def _normalize(xs: List[float]) -> List[float]:
    if not xs: return xs
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-9: return [0.0 for _ in xs]
    return [(x - lo) / (hi - lo) for x in xs]

# ---------- Core search: Resume → JDs ----------

def hybrid_search(resume_text: str, coll, bm25_artifacts):
    qvec = embed_query_pooled(resume_text)
    if not qvec:
        return []

    # Vector search over JD chunks
    res = coll.query(query_embeddings=[qvec], n_results=TOP_K_VECTOR, include=["documents","distances","metadatas","embeddings"])
    ids     = res.get("ids", [[]])[0]
    dists   = res.get("distances", [[]])[0]
    metas   = res.get("metadatas", [[]])[0]
    docs    = res.get("documents", [[]])[0]

    # Convert cosine distances to similarities (best-effort)
    sem = [1.0 - float(d) for d in dists]
    sem_norm = _normalize(sem)

    # BM25 over JDs (chunk-level), then map to returned chunk ids
    kw_norm_map = {}
    if bm25_artifacts and bm25_artifacts[0] is not None:
        corpus_tokens, bm25_doc_ids, meta_by_id = bm25_artifacts
        bm = BM25Okapi(corpus_tokens)
        q_tokens = tokenize(resume_text)
        scores = bm.get_scores(q_tokens)  # aligned with corpus_tokens
        scores_norm = _normalize([float(s) for s in scores])
        # Build id -> norm score map
        for doc_id, sc in zip(bm25_doc_ids, scores_norm):
            kw_norm_map[doc_id] = sc

    fused = []
    rows = []
    for i, (_id, m, doc, s) in enumerate(zip(ids, metas, docs, sem_norm)):
        kw = kw_norm_map.get(_id, 0.0)
        f = HYBRID_ALPHA * s + (1.0 - HYBRID_ALPHA) * kw
        rows.append({
            "chunk_id": _id,
            "job_id": (m or {}).get("job_id") or (m or {}).get("parent_id") or (_id.split("::")[0] if _id else None),
            "title": (m or {}).get("title"),
            "company": (m or {}).get("company"),
            "location": (m or {}).get("location"),
            "url": (m or {}).get("url"),
            "sem": float(s),
            "kw": float(kw),
            "fused": float(f),
            "preview": (doc or "")[:320].replace("\n", " "),
        })

    # Aggregate to JD (parent) level: keep best chunk as evidence
    by_parent: Dict[str, Dict] = {}
    for r in rows:
        pid = r.get("job_id")
        cur = by_parent.get(pid)
        if (not cur) or (r["fused"] > cur["fused"]):
            by_parent[pid] = r

    # Rank and compute relative Match%
    ranked = sorted(by_parent.values(), key=lambda x: x["fused"], reverse=True)[:TOP_K_FINAL]
    if not ranked: return []
    hi = max(x["fused"] for x in ranked) or 1.0
    lo = min(x["fused"] for x in ranked)
    for x in ranked:
        x["match_pct"] = round(100.0 * ((x["fused"] - lo) / (hi - lo + 1e-9)), 1)
    return ranked

# ---------- UI ----------

st.title("Resume → JD Search")
st.caption("Reverse search: upload a resume to find the most relevant Job Descriptions (JDs) from the JD corpus.")

left, right = st.columns([1,1])
with left:
    resume_file = st.file_uploader("Upload one resume (PDF/DOCX/TXT)", type=["pdf","docx","txt","rtf","doc"], accept_multiple_files=False)
    find_btn = st.button("Find matching JDs", type="primary", use_container_width=True)

with right:
    st.subheader("Settings")
    st.write(f"HYBRID_ALPHA (semantic vs keyword): {HYBRID_ALPHA}")
    st.write(f"TOP_K_VECTOR: {TOP_K_VECTOR}  |  TOP_K_FINAL: {TOP_K_FINAL}")
    st.caption("You can override these with env vars: R2J_HYBRID_ALPHA, R2J_TOP_K_VECTOR, R2J_TOP_K_FINAL.")

if find_btn:
    if not resume_file:
        st.warning("Please upload a resume first.")
    else:
        try:
            text = read_text_from_bytes(resume_file.read(), resume_file.name)
            if not text.strip():
                st.warning("This file seems empty after parsing/cleaning.")
            else:
                coll = get_chroma()
                bm25_artifacts = load_bm25()
                results = hybrid_search(text, coll, bm25_artifacts)
                if not results:
                    st.info("No results. Make sure you've ingested JDs with the JD admin tool.")
                else:
                    df = pd.DataFrame(results)
                    show = ["match_pct","title","company","location","url","job_id","sem","kw","fused","preview"]
                    st.dataframe(df[show], use_container_width=True, hide_index=True)
                    st.caption("Match% is relative within this result set. 'sem' is semantic similarity; 'kw' is BM25 score (normalized).")
        except Exception as e:
            st.error(f"Search failed: {e}")
