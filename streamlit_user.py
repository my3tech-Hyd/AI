# streamlit_user.py — User-facing JD→Resume retrieval (robust hybrid, fine-tuned + fixes)
import io
import os
import re
import json
from pathlib import Path
from typing import List, Dict, Tuple

import streamlit as st
import pandas as pd
import requests
import chromadb
from rank_bm25 import BM25Okapi
from pypdf import PdfReader
from docx import Document as Docx

from config import (
    CHROMA_DIR, CHROMA_COLLECTION,
    RESUMES_STORE_DIR,
    BM25_CORPUS_PATH, BM25_DOCIDS_PATH, BM25_META_PATH,
    EMBED_MODEL, OLLAMA_HOST,
    MAX_QUERY_CHARS, OLLAMA_TIMEOUT,
    QUERY_CHUNK_SIZE, QUERY_CHUNK_OVERLAP, QUERY_MAX_CHUNKS,
    K_VEC, K_BM25, K_CHUNKS, HYBRID_ALPHA,
    USE_RRF, RRF_K, USE_MMR, MMR_LAMBDA,
    TOP_K_FINAL,
)

EMAIL_RE = re.compile(r'(?i)(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])')
PHONE_RE = re.compile(r'''(?x)
(?:
  (?:\+?\d{1,3}[\s\-.()]*)?    # optional country code, matches +91, +1, etc.
  (?:\(?\d{3,4}\)?[\s\-.()]*)  # area/provider code (3–4 digits)
  \d{3,4}[\s\-.]*\d{4}         # local number
)
''')

# -------------------------
# Utilities
# -------------------------

@st.cache_resource(show_spinner=False)
def get_http_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def get_ollama_base() -> str:
    base = (OLLAMA_HOST or "").strip().rstrip("/")
    if not base:
        base = "http://localhost:11434"
    return base


def strip_rtf_noise(txt: str) -> str:
    if not isinstance(txt, str):
        return ""
    s = txt
    if s.lstrip().startswith("{\\rtf"):
        s = re.sub(r"[{}]", " ", s)
        s = re.sub(r"\\[a-zA-Z]+\d* ?", " ", s)  # \par, \b0, \fs22, etc.
    return re.sub(r"\s+", " ", s).strip()


ALIASES = {
    ".net": "dotnet", "c#": "csharp", "c++": "cpp",
    "node.js": "nodejs", "react.js": "react", "next.js": "nextjs",
    "javascript": "js", "typescript": "ts",
}


def normalize_for_bm25(text: str) -> str:
    s = (text or "").lower()
    for a,b in ALIASES.items():
        s = s.replace(a, b)
    return s


def chunk_text_query(text: str, size: int = QUERY_CHUNK_SIZE, overlap: int = QUERY_CHUNK_OVERLAP, max_chunks: int = QUERY_MAX_CHUNKS) -> List[str]:
    s = (text or "").strip()
    if len(s) > MAX_QUERY_CHARS:
        s = s[:MAX_QUERY_CHARS]
    if not s:
        return []
    chunks = []
    i = 0
    while i < len(s) and len(chunks) < max_chunks:
        chunks.append(s[i:i+size])
        i = i + size - overlap
        if i <= 0:
            break
    return chunks


@st.cache_resource(show_spinner=False)
def get_chroma():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        coll = client.get_collection(CHROMA_COLLECTION)
    except Exception:
        coll = client.create_collection(CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})
    return client, coll


@st.cache_resource(show_spinner=False)
def load_bm25_index():
    import pickle
    class _NullBM25:
        corpus_size = 0
        def get_scores(self, tokens):
            return []
    if not (os.path.exists(BM25_CORPUS_PATH) and os.path.exists(BM25_DOCIDS_PATH)):
        return _NullBM25(), [], {}, {}
    with open(BM25_CORPUS_PATH, "rb") as f:
        corpus_tokens = pickle.load(f)
    with open(BM25_DOCIDS_PATH, "rb") as f:
        doc_ids = pickle.load(f)
    bm25 = _NullBM25() if (not corpus_tokens or all((not d) for d in corpus_tokens)) else BM25Okapi(corpus_tokens)
    id2pos = {d: i for i, d in enumerate(doc_ids)}
    meta_by_id = {}
    if os.path.exists(BM25_META_PATH) and os.path.getsize(BM25_META_PATH) > 0:
        with open(BM25_META_PATH, "rb") as f:
            meta_by_id = pickle.load(f)
    return bm25, doc_ids, id2pos, meta_by_id


def exists_parent_in_chroma(coll, parent_id: str) -> bool:
    try:
        got = coll.get(where={"parent_id": str(parent_id)})
        return bool(got and got.get("ids"))
    except Exception:
        return False


@st.cache_data(show_spinner=False)
def _hydrate_contacts_from_store(parent_id: str) -> dict:
    """
    Recover email/phone by sampling first few chunks from Chroma (by explicit ids),
    reading metadata and text patterns.
    """
    _, coll = get_chroma()
    probe_ids = [f"{parent_id}::c{i:04d}" for i in range(40)]
    try:
        got = coll.get(ids=probe_ids, include=["documents", "metadatas"]) or {}
    except Exception:
        return {"email": None, "phone": None}

    docs  = got.get("documents")  or []
    metas = got.get("metadatas")  or []
    text  = "\n".join((d or "") for d in docs)

    email = next((m.get("email") for m in metas if isinstance(m, dict) and m.get("email")), None)
    phone = next((m.get("phone") for m in metas if isinstance(m, dict) and m.get("phone")), None)

    if not email and text:
        m = EMAIL_RE.search(text);  email = m.group(1) if m else None
    if not phone and text:
        m = PHONE_RE.search(text);  phone = m.group(0) if m else None
    return {"email": email, "phone": phone}


def filter_rows_to_existing_parents(coll, rows):
    """rows = list of pooled parent rows (after parent_pool)."""
    kept, dropped = [], 0
    for r in rows:
        pid = r.get("document_id") or r.get("parent_id")
        if pid and exists_parent_in_chroma(coll, pid):
            kept.append(r)
        else:
            dropped += 1
    return kept, dropped

def _bm25_collect_chunks(coll, top_any: list[str], kw_scores_map_any: dict[str, float]):
    """
    Robustly map BM25 ids (which might be chunk ids, or stored under metadata keys)
    to actual chunks in Chroma. We try, in order:
      - metadata.chunk_id
      - direct ids
      - metadata.parent_id
      - metadata.document_id
      - metadata.resume_id
    Returns a list of (chunk_id, doc, meta, kw_score).
    """
    top_any = [str(x) for x in top_any if x is not None]
    remaining = set(top_any)
    out = {}
    include = ["documents", "metadatas"]

    def _merge(got, score_key: str | None = None):
        if not got:
            return
        got_ids  = got.get("ids") or []
        got_docs = got.get("documents") or []
        got_meta = got.get("metadatas") or []
        for i in range(len(got_ids)):
            meta = got_meta[i] or {}
            # canonical chunk key we’ll keep in candidate dict
            cid2 = meta.get("chunk_id", got_ids[i])
            # figure which original BM25 id this result corresponds to
            if score_key:
                key_val = meta.get(score_key)
            else:
                # for direct ids / chunk_id mode, prefer chunk_id value then id
                key_val = meta.get("chunk_id", got_ids[i])
            kw_sc = kw_scores_map_any.get(str(key_val), 0.0)
            # keep max kw score if appears via multiple passes
            if cid2 in out:
                out[cid2]["kw"] = max(out[cid2]["kw"], kw_sc)
            else:
                out[cid2] = {"doc": got_docs[i], "meta": meta, "kw": kw_sc}
            # remove matched key from remaining
            if key_val in remaining:
                try:
                    remaining.remove(key_val)
                except KeyError:
                    pass

    # 1) chunk_id metadata
    if remaining:
        got = coll.get(where={"chunk_id": {"$in": list(remaining)}}, include=include)
        _merge(got, score_key="chunk_id")

    # 2) direct ids
    if remaining:
        got = coll.get(ids=list(remaining), include=include)
        _merge(got, score_key=None)

    # 3) parent_id
    if remaining:
        got = coll.get(where={"parent_id": {"$in": list(remaining)}}, include=include)
        _merge(got, score_key="parent_id")

    # 4) document_id  (this is likely your case per diagnostics)
    if remaining:
        got = coll.get(where={"document_id": {"$in": list(remaining)}}, include=include)
        _merge(got, score_key="document_id")

    # 5) resume_id  (legacy/alternate)
    if remaining:
        got = coll.get(where={"resume_id": {"$in": list(remaining)}}, include=include)
        _merge(got, score_key="resume_id")

    # materialize
    return [(cid2, v["doc"], v["meta"], v["kw"]) for cid2, v in out.items()]

# -------------------------
# Embeddings (Ollama HTTP first, then langchain_ollama fallback)
# -------------------------

@st.cache_data(show_spinner=False)
def embed_query(text: str) -> List[float]:
    session = get_http_session()
    base = get_ollama_base()
    url = base + "/api/embeddings"

    txt = (text or "").strip()
    if not txt:
        raise ValueError("Empty query text")
    if len(txt) > MAX_QUERY_CHARS:
        txt = txt[:MAX_QUERY_CHARS]

    try:
        r = session.post(url, json={"model": EMBED_MODEL, "input": txt}, timeout=OLLAMA_TIMEOUT)
        if r.status_code == 400:
            r = session.post(url, json={"model": EMBED_MODEL, "prompt": txt}, timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        vec = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if not vec:
            raise RuntimeError("No embedding returned from Ollama")
        return vec
    except Exception:
        try:
            from langchain_ollama import OllamaEmbeddings
        except Exception:
            from langchain_community.embeddings import OllamaEmbeddings  # last resort
        emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=base)
        return emb.embed_query(txt)


@st.cache_data(show_spinner=False)
def embed_query_pooled(text: str) -> List[float]:
    chunks = chunk_text_query(text)
    if not chunks:
        return embed_query(text)  # tiny queries
    vecs = [embed_query(c) for c in chunks]
    # length-weighted mean
    dims = len(vecs[0])
    acc = [0.0] * dims
    total = 0
    for c, v in zip(chunks, vecs):
        w = max(1, len(c))
        for i in range(dims):
            acc[i] += v[i] * w
        total += w
    return [x / max(1, total) for x in acc]


# -------------------------
# Retrieval: union(vector@K, bm25@K) → RRF → score fusion → MMR diversity (fine-tuned)
# -------------------------

def _norm(arr: List[float]) -> List[float]:
    if not arr:
        return []
    mn, mx = min(arr), max(arr)
    if mx - mn < 1e-9:
        return [0.0 for _ in arr]
    return [(x - mn) / (mx - mn) for x in arr]


def _rrf_fuse(rankings: Dict[str, List[str]], k: int = RRF_K) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for _, ids in rankings.items():
        for r, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + r)
    return scores


def _detect_bm25_mode(coll, doc_ids_sample: List[str]) -> str:
    """
    Decide whether BM25 doc_ids are chunk ids, chunk_id metadatas, or parent ids.
    Returns one of: 'by_ids', 'by_meta_chunk', 'by_parent'
    """
    sample = [str(x) for x in doc_ids_sample[: min(50, len(doc_ids_sample))]]
    if not sample:
        return "by_ids"

    try:
        got = coll.get(ids=sample)
        if len((got or {}).get("ids") or []) >= max(1, len(sample) // 5):
            return "by_ids"
    except Exception:
        pass

    try:
        got = coll.get(where={"chunk_id": {"$in": sample}})
        if len((got or {}).get("ids") or []) >= max(1, len(sample) // 5):
            return "by_meta_chunk"
    except Exception:
        pass

    try:
        got = coll.get(where={"parent_id": {"$in": sample}})
        if len((got or {}).get("ids") or []) >= 1:
            return "by_parent"
    except Exception:
        pass

    return "by_ids"



def retrieve_candidates_union(jd_text: str, k_vec: int, k_bm25: int):
    # ----- Vector side (fine-tuned: key by meta['chunk_id'] when present) -----
    qvec = embed_query_pooled(jd_text)

    _, coll = get_chroma()
    q = coll.query(
        query_embeddings=[qvec],
        n_results=k_vec,
        include=["documents", "metadatas", "distances", "embeddings"],
    )

    ids_v   = q.get("ids", [[]])[0]
    docs_v  = q.get("documents", [[]])[0]
    metas_v = q.get("metadatas", [[]])[0]
    dists_v = q.get("distances", [[]])[0]
    embs_v  = q.get("embeddings", [[]])[0]

    has_embs = embs_v is not None and hasattr(embs_v, "__len__") and len(embs_v) >= len(ids_v)
    sem_v = [1.0 - d for d in dists_v]

    C: Dict[str, Dict] = {}
    for i in range(len(ids_v)):
        raw_id = ids_v[i]
        meta_i = metas_v[i] or {}
        key = meta_i.get("chunk_id", raw_id)
        C.setdefault(key, {
            "doc": strip_rtf_noise(docs_v[i]),
            "sem": 0.0, "kw": 0.0,
            "meta": meta_i,
            "emb": embs_v[i] if has_embs else None
        })
        C[key]["sem"] = max(C[key]["sem"], sem_v[i])

    # ----- BM25 side (robust mapping across multiple metadata keys) -----
    bm25, doc_ids, id2pos, meta_by_id = load_bm25_index()
    if getattr(bm25, "corpus_size", 0) > 0 and id2pos:
        toks = normalize_for_bm25(jd_text).split()
        scores = bm25.get_scores(toks)

        pairs = [(cid, float(scores[pos])) for cid, pos in id2pos.items() if pos < len(scores)]
        pairs.sort(key=lambda x: x[1], reverse=True)
        top_any = [cid for cid, _ in pairs[:k_bm25]]
        kw_scores_map_any = {cid: sc for cid, sc in pairs[:k_bm25]}

        # ← this is the key change
        bm25_hits = _bm25_collect_chunks(coll, top_any, kw_scores_map_any)

        if not bm25_hits:
            # last-ditch: synthesize entries (no Chroma fetch matched)
            for any_id, sc in kw_scores_map_any.items():
                md = meta_by_id.get(any_id, {"chunk_id": any_id})
                cid2 = md.get("chunk_id", f"{any_id}::pseudo")
                C.setdefault(cid2, {"doc": "", "sem": 0.0, "kw": sc, "meta": md, "emb": None})
        else:
            for cid2, doc2, meta2, kw_sc in bm25_hits:
                if cid2 not in C:
                    C[cid2] = {"doc": strip_rtf_noise(doc2), "sem": 0.0, "kw": kw_sc, "meta": meta2, "emb": None}
                else:
                    C[cid2]["kw"] = max(C[cid2]["kw"], kw_sc)

    # ----- Fuse (semantic + keyword + optional RRF) -----
    if USE_RRF:
        sem_rank = sorted(C.keys(), key=lambda k: C[k]["sem"], reverse=True)
        kw_rank  = sorted(C.keys(), key=lambda k: C[k]["kw" ], reverse=True)
        rrf = _rrf_fuse({"semantic": sem_rank, "bm25": kw_rank}, k=RRF_K)
    else:
        rrf = {k: 0.0 for k in C.keys()}

    keys = list(C.keys())
    sem_n = _norm([C[k]["sem"] for k in keys])
    kw_n  = _norm([C[k]["kw" ] for k in keys])

    fused: Dict[str, float] = {}
    for i, k in enumerate(keys):
        s = float(HYBRID_ALPHA) * sem_n[i] + (1.0 - float(HYBRID_ALPHA)) * kw_n[i]
        fused[k] = 0.5 * s + 0.5 * rrf.get(k, 0.0) if USE_RRF else s

    ordered = sorted(keys, key=lambda k: fused[k], reverse=True)

    # ----- Anti-collapse re-scoring (if fused range ~ 0) -----
    if ordered:
        vals = [fused[k] for k in ordered]
        if (max(vals) - min(vals)) < 1e-6:
            try:
                import numpy as np
                q = np.asarray(qvec, dtype=float)
                sims = []
                for cid in ordered:
                    e = C[cid].get("emb")
                    if e is None:
                        sims.append(0.0)
                    else:
                        v = np.asarray(e, dtype=float)
                        denom = (np.linalg.norm(q) * np.linalg.norm(v))
                        sims.append(float(np.dot(q, v) / denom) if denom > 0 else 0.0)
                if any(sims):
                    mn, mx = min(sims), max(sims)
                    sims_n = [(s - mn)/(mx - mn) if mx > mn else 0.0 for s in sims]
                    for cid, s in zip(ordered, sims_n):
                        fused[cid] = 0.7 * s + 0.3 * fused[cid]
                    ordered = sorted(ordered, key=lambda k: fused[k], reverse=True)
            except Exception:
                pass

    # ----- MMR diversity (optional) -----
    if USE_MMR and ordered:
        try:
            import numpy as np
            def cos(a,b):
                na, nb = np.linalg.norm(a), np.linalg.norm(b)
                return 0.0 if na==0 or nb==0 else float(np.dot(a,b)/(na*nb))
            def emb(cid):
                e = C[cid].get("emb")
                if e is None: return None
                try: return np.asarray(e, dtype=float)
                except Exception: return None
            selected = [ordered[0]]
            remaining = ordered[1:]
            while remaining and len(selected) < min(K_CHUNKS, len(ordered)):
                best_idx, best_score = 0, -1e9
                for i, cid in enumerate(remaining):
                    redun = max((cos(emb(cid), emb(s)) for s in selected if emb(cid) is not None and emb(s) is not None), default=0.0)
                    score = float(MMR_LAMBDA) * (1.0 - redun)
                    if score > best_score:
                        best_score, best_idx = score, i
                selected.append(remaining.pop(best_idx))
            final_ids = selected
        except Exception:
            final_ids = ordered[:K_CHUNKS]
    else:
        final_ids = ordered[:K_CHUNKS]

    # ----- materialize candidates -----
    out = []
    for cid in final_ids:
        item = C[cid]
        md = dict(item.get("meta") or {})
        md.setdefault("chunk_id", cid)
        out.append({
            "chunk_id": cid,
            "doc": item.get("doc", ""),
            "meta": md,
            "sem": item.get("sem", 0.0),
            "kw": item.get("kw", 0.0),
            "score": fused.get(cid, 0.0),
        })
    return out





def parent_pool(cands: List[Dict]) -> List[Dict]:
    """Aggregate chunk-level candidates into resume-level rows (keep best evidence).
       Also recovers email/phone for display (meta → sample chunks → preview).
    """
    buckets: Dict[str, Dict] = {}
    for c in cands:
        md = c.get("meta") or {}
        parent = (
            md.get("parent_id") or
            md.get("resume_id") or
            md.get("document_id") or
            md.get("chunk_parent") or
            md.get("chunk_id") or
            c.get("chunk_id") or
            (Path(md.get("file_path","" )).stem if md.get("file_path") else "unknown")
        )
        file_path = md.get("file_path")
        email = md.get("email")
        phone = md.get("phone")
        preview = c.get("doc", "")[:800]
        score = float(c.get("score", 0.0))
        row = buckets.get(parent)
        if (row is None) or (score > row["score"]):
            buckets[parent] = {
                "parent_id": parent,
                "document_id": parent,
                "file_path": file_path,
                "email": email,
                "phone": phone,
                "score": score,
                "preview": preview,
            }
        else:
            if not row.get("email") and email:
                row["email"] = email
            if not row.get("phone") and phone:
                row["phone"] = phone

    # enrich contacts via BM25 meta and store sampling
    _, _, _, meta_by_id = load_bm25_index()
    for pid, row in buckets.items():
        if (not row.get("email")) or (not row.get("phone")):
            md = meta_by_id.get(pid) or {}
            row["email"] = row.get("email") or md.get("email")
            row["phone"] = row.get("phone") or md.get("phone")
        if (not row.get("email")) or (not row.get("phone")):
            hyd = _hydrate_contacts_from_store(pid)
            row["email"] = row.get("email") or hyd.get("email")
            row["phone"] = row.get("phone") or hyd.get("phone")
        if not row.get("email") and row.get("preview"):
            m = EMAIL_RE.search(row["preview"]); row["email"] = m.group(1) if m else None
        if not row.get("phone") and row.get("preview"):
            m = PHONE_RE.search(row["preview"]); row["phone"] = m.group(0) if m else None

    ranked = sorted(buckets.values(), key=lambda r: r["score"], reverse=True)[:TOP_K_FINAL]
    if ranked:
        vmax = max(r["score"] for r in ranked)
        if vmax <= 0:
            for r in ranked: r["match_pct"] = 0
        else:
            for r in ranked: r["match_pct"] = int(round(100 * (r["score"] / vmax)))
    return ranked


# -------------------------
# UI
# -------------------------

st.set_page_config(page_title="JD→Resume Search", page_icon="🔎", layout="wide")
st.title("JD–Resume Search")
st.caption("Paste a JD or upload a file; we’ll retrieve top-matching resumes from the secured store.")
st.caption(f"Chroma dir: **{CHROMA_DIR}** • collection: **{CHROMA_COLLECTION}**")

left, right = st.columns([2,1])
with left:
    jd_text_area = st.text_area("Job description (paste)", height=200, placeholder="Paste the JD here…")
    st.markdown("**OR**")
    jd_file = st.file_uploader("Upload JD file (PDF/DOCX/TXT/RTF)", type=["pdf","docx","txt","rtf"])

with right:
    st.subheader("Search settings")
    st.write(f"Hybrid α (semantic vs keyword): **{HYBRID_ALPHA}**")
    st.write(f"Vector@K: **{K_VEC}**, BM25@K: **{K_BM25}**, Evidence chunks: **{K_CHUNKS}**")
    st.write(f"RRF: **{USE_RRF}** (K={RRF_K}), MMR: **{USE_MMR}** (λ={MMR_LAMBDA})")
    st.write(f"Results: **Top {TOP_K_FINAL} resumes**")

# Parse JD from upload if provided
if jd_file is not None and not jd_text_area.strip():
    try:
        if jd_file.type == "application/pdf":
            reader = PdfReader(io.BytesIO(jd_file.read()))
            jd_text_area = "\n".join(p.extract_text() or "" for p in reader.pages)
        elif jd_file.type in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",):
            doc = Docx(io.BytesIO(jd_file.read()))
            jd_text_area = "\n".join(p.text or "" for p in doc.paragraphs)
        else:
            jd_text_area = jd_file.read().decode("utf-8", errors="ignore")
    except Exception as e:
        st.error(f"Failed to read JD file: {e}")

# Run search
if st.button("Search", type="primary"):
    text = (jd_text_area or "").strip()
    if not text:
        st.warning("Please paste a JD or upload a JD file.")
    else:
        try:
            _, coll = get_chroma()  # ensure same collection as Admin
            # K normalization
            k_vec  = max(1, int(K_VEC))
            k_bm25 = max(1, int(K_BM25))

            # Pass 1: fine-tuned hybrid
            cands = retrieve_candidates_union(text, k_vec, k_bm25)
            st.caption(f"debug: pass1 candidates = {len(cands)} (vec@{k_vec}, bm25@{k_bm25})")

            # Pass 2: widen once if empty
            if not cands:
                k_vec2, k_bm252 = max(20, k_vec * 2), max(20, k_bm25 * 2)
                cands = retrieve_candidates_union(text, k_vec2, k_bm252)
                st.caption(f"fallback widened → vec={k_vec2}, bm25={k_bm252}; union={len(cands)}")

            # Pass 3: last-resort vector probe (proves embeddings are visible)
            if not cands and coll.count() > 0:
                probe_txt = "software engineer resume project experience skills"
                try:
                    qvec_probe = embed_query_pooled(probe_txt)
                    q = coll.query(query_embeddings=[qvec_probe], n_results=25, include=["documents","metadatas"])
                    ids_p  = q.get("ids", [[]])[0]
                    docs_p = q.get("documents", [[]])[0]
                    metas_p= q.get("metadatas", [[]])[0]
                    cands = [
                        {"chunk_id": ids_p[i],
                         "doc": (docs_p[i] or "")[:800],
                         "meta": (metas_p[i] or {}),
                         "sem": 0.0, "kw": 0.0, "score": 0.0}
                        for i in range(min(len(ids_p), 25))
                    ]
                    st.warning("Vector-probe fallback used — JD returned nothing, but embeddings exist. Check BM25 freshness and deleted-parent filtering.")
                except Exception as e:
                    st.caption(f"probe failed: {e}")

            results = parent_pool(cands)
            # drop parents deleted in Admin
            results, dropped = filter_rows_to_existing_parents(coll, results)
            if dropped:
                st.caption(f"Note: {dropped} deleted resume(s) were removed from results.")

            st.subheader("Top matches")
            if not results:
                st.error("No matches found. Try increasing K or adjusting α.")
                # targeted diagnostics
                cnt = coll.count()
                bm25, doc_ids, id2pos, meta_by_id = load_bm25_index()
                st.caption(f"diag: chroma_count={cnt} • bm25_chunks={len(doc_ids)} • parents_in_meta={len(meta_by_id)}")
                if cnt == 0:
                    st.warning("Chroma collection is empty for this app. Verify CHROMA_DIR/CHROMA_COLLECTION match Admin.")
                elif len(doc_ids) == 0:
                    st.warning("BM25 index is empty/stale. Open Admin and run any ingest to refresh BM25.")
            else:
                # Summary table
                rows = []
                for r in results:
                    rows.append({
                        "percentage": r.get("match_pct", 0),
                        "document_id": r.get("document_id") or r.get("parent_id"),
                        "email": r.get("email"),
                        "phone": r.get("phone"),
                        "preview": (r.get("preview") or "")[:280] + ("…" if r.get("preview") and len(r.get("preview")) > 280 else ""),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Detail expanders
                for i, r in enumerate(results, 1):
                    with st.expander(f"{i}. Match {r.get('match_pct',0)}% — {r.get('parent_id')} "):
                        col1, col2, col3 = st.columns([2,2,1])
                        with col1:
                            st.markdown(f"**Document ID:** {r.get('document_id')}")
                            st.markdown(f"**Email:** {r.get('email') or '—'}")
                        with col2:
                            st.markdown(f"**Phone:** {r.get('phone') or '—'}")
                        with col3:
                            st.markdown(f"**%:** {r.get('match_pct',0)}")
                        st.write(r.get("preview") or "(no preview)")
                        fp = r.get("file_path")
                        if fp and Path(fp).exists():
                            with open(fp, "rb") as fh:
                                data = fh.read()
                            base_name = Path(fp).name
                            st.download_button("Download resume", data, file_name=base_name)
                        else:
                            st.caption("Original file not found on server.")
        except Exception as e:
            st.error(f"Search failed: {e}")

st.divider()
st.caption("User view. Read-only access to the vector DB. Uploads are disabled for users by design.")

# -------------------------
# Diagnostics
# -------------------------
with st.expander("Diagnostics"):
    try:
        _, coll = get_chroma()
        count = coll.count()
        st.write(f"Chroma count: **{count}** vectors")
        bm25, doc_ids, id2pos, meta_by_id = load_bm25_index()
        st.write(f"BM25 corpus size: **{getattr(bm25,'corpus_size',0)}** • chunks in index: **{len(doc_ids)}** • parents in meta: **{len(meta_by_id)}**")
        if doc_ids:
            sample = [str(x) for x in doc_ids[: min(100, len(doc_ids))]]
            hits = {
                "by_ids": len((coll.get(ids=sample) or {}).get("ids") or []),
                "by_meta_chunk": len((coll.get(where={"chunk_id": {"$in": sample}}) or {}).get("ids") or []),
                "by_parent": len((coll.get(where={"parent_id": {"$in": sample}}) or {}).get("ids") or []),
                "by_document_id": len((coll.get(where={"document_id": {"$in": sample}}) or {}).get("ids") or []),
                "by_resume_id": len((coll.get(where={"resume_id": {"$in": sample}}) or {}).get("ids") or []),
            }
            st.write(f"BM25 id mapping hits on sample {len(sample)} → {hits}")
        else:
            st.write("BM25 doc_ids is empty.")
    except Exception as e:
        st.warning(f"Diagnostics failed: {e}")

