# streamlit_user_jd_to_resume.py
# ----------------------------------------------------------------------
# JD → Resume semantic matcher (cosine only, no BM25)
# - Upload a JD (pdf/docx/txt/rtf/doc)
# - We embed the JD (pooled across chunks) using Ollama embeddings
# - Query a separate Chroma collection that contains RESUME chunks
# - Convert distances → similarities, normalize, aggregate per resume
# - Rank resumes and show top matches with evidence preview
# ----------------------------------------------------------------------

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pickle

import numpy as np
import requests
import streamlit as st
import pandas as pd
import chromadb
from pypdf import PdfReader
from docx import Document as Docx
from rank_bm25 import BM25Okapi

# Reuse cleaning from the shared utils
from utils_r import clean_text

# Config for the RESUMES corpus (isolated DB + env-driven knobs)
from config_jds_resumes import (
    CHROMA_DIR_RESUMES,
    CHROMA_COLLECTION_RESUMES,
    OLLAMA_HOST,
    EMBED_MODEL,
    BM25_RESUMES_CORPUS_PATH,
    BM25_RESUMES_META_PATH,
    BM25_RESUMES_DOCIDS_PATH,
    # Retrieval / pooling knobs (loaded from .env by config_jds_resumes)
    R2J_QUERY_CHUNK_SIZE,
    R2J_QUERY_CHUNK_OVERLAP,
    R2J_QUERY_MAX_CHUNKS,
    R2J_TOP_K_VECTOR,
    R2J_TOP_K_FINAL,
    R2J_HYBRID_ALPHA,
)

# Additional local tunables (okay if missing in .env)
MAX_QUERY_CHARS = int(os.getenv("R2J_MAX_QUERY_CHARS", "1200"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "45"))

# Hybrid retrieval knobs (can be overridden via env)
K_VEC = int(os.getenv("R2J_K_VEC", str(R2J_TOP_K_VECTOR)))
K_BM25 = int(os.getenv("R2J_K_BM25", "80"))
K_CHUNKS = int(os.getenv("R2J_K_CHUNKS", "20"))
HYBRID_ALPHA = float(os.getenv("R2J_HYBRID_ALPHA", str(R2J_HYBRID_ALPHA)))
USE_RRF = os.getenv("R2J_USE_RRF", "true").lower() == "true"
RRF_K = int(os.getenv("R2J_RRF_K", "60"))
USE_MMR = os.getenv("R2J_USE_MMR", "true").lower() == "true"
MMR_LAMBDA = float(os.getenv("R2J_MMR_LAMBDA", "0.5"))

# ----------------------------------------------------------------------
# Streamlit UI config
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="JD → Resume Search (Semantic Only)",
    page_icon="🔁",
    layout="wide",
)
st.title("JD → Resume Search (Semantic Only)")
st.caption(
    "Uploads a JD and finds the most relevant **resumes** using cosine similarity over a separate Chroma collection."
)

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def read_text_from_bytes(data: bytes, filename: str) -> str:
    """
    Extract text from common formats and clean it.
    Supports: .pdf, .docx, .txt, .rtf, .md, .doc (best-effort decode)
    """
    ext = Path(filename).suffix.lower()
    try:
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
            # .doc or unknown → best-effort decode
            text = data.decode(errors="ignore")
    except Exception:
        # Fallback to raw decode if any parser chokes
        text = data.decode(errors="ignore")
    return clean_text(text)


def _chunk_query_text(text: str, size: int, overlap: int, max_chunks: int) -> List[str]:
    """
    Split the (possibly long) JD text into smaller chunks so we can embed
    and pooled-average them for a more stable query vector.
    """
    t = text[:MAX_QUERY_CHARS] if MAX_QUERY_CHARS > 0 else text
    n = len(t)
    if n == 0:
        return []
    size = max(1, int(size))
    overlap = max(0, int(overlap))
    if overlap >= size:
        overlap = size // 4  # safety
    chunks: List[str] = []
    start = 0
    while start < n and len(chunks) < max_chunks:
        end = min(n, start + size)
        chunks.append(t[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks


def _embed_query_ollama(chunk: str) -> List[float]:
    """
    Call Ollama's embeddings API directly.
    Requires: ollama serve  &  ollama pull <EMBED_MODEL>
    """
    resp = requests.post(
        f"{OLLAMA_HOST}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": chunk},
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    # Ollama returns either {'embedding': [...]} or {'data': [{'embedding': [...]}]}
    vec = data.get("embedding") or (data.get("data") or [{}])[0].get("embedding")
    if not isinstance(vec, list) or not all(isinstance(x, (int, float)) for x in vec):
        raise ValueError("Invalid embedding vector from Ollama")
    return [float(x) for x in vec]


def _embed_query_pooled(text: str) -> List[float]:
    """
    Pool embeddings across several overlapping chunks of the JD text.
    Length-weighted mean pooling.
    """
    chunks = _chunk_query_text(text, R2J_QUERY_CHUNK_SIZE, R2J_QUERY_CHUNK_OVERLAP, R2J_QUERY_MAX_CHUNKS)
    if not chunks:
        return []
    vecs = [_embed_query_ollama(ch) for ch in chunks]
    dims = len(vecs[0])
    pooled = [0.0] * dims
    weights = [len(ch) for ch in chunks]
    denom = float(sum(weights) or 1.0)
    for v, w in zip(vecs, weights):
        if len(v) != dims:
            # Skip malformed vectors (defensive)
            continue
        wf = float(w)
        for i in range(dims):
            pooled[i] += wf * float(v[i])
    for i in range(dims):
        pooled[i] /= denom
    return pooled


def _normalize(xs: List[float]) -> List[float]:
    """Min–max normalize to [0,1] (stable even with equal values)."""
    if not xs:
        return xs
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-12:
        return [0.0 for _ in xs]
    scale = hi - lo
    return [(x - lo) / scale for x in xs]


def _distances_to_similarities(dists: List[float]) -> List[float]:
    """
    Convert Chroma distances to a similarity proxy.
    For cosine distance `d_cos`, a simple proxy is `sim = 1 - d`.
    """
    return [1.0 - float(d) for d in dists]


def _get_resume_collection():
    client = chromadb.PersistentClient(path=CHROMA_DIR_RESUMES)
    return client.get_or_create_collection(name=CHROMA_COLLECTION_RESUMES)

# ----------------------------------------------------------------------
# Hybrid BM25 + vector helpers
# ----------------------------------------------------------------------
def _strip_rtf_noise(txt: str) -> str:
    if not isinstance(txt, str):
        return ""
    s = txt
    if s.lstrip().startswith("{\\rtf"):
        s = re.sub(r"[{}]", " ", s)
        s = re.sub(r"\\[a-zA-Z]+\d* ?", " ", s)
    return re.sub(r"\s+", " ", s).strip()


ALIASES = {
    ".net": "dotnet",
    "c#": "csharp",
    "c++": "cpp",
    "node.js": "nodejs",
    "react.js": "react",
    "next.js": "nextjs",
    "javascript": "js",
    "typescript": "ts",
}


def _normalize_for_bm25(text: str) -> str:
    s = (text or "").lower()
    for a, b in ALIASES.items():
        s = s.replace(a, b)
    return s


def _get_bm25_mtime() -> float:
    """Get the latest modification time of BM25 index files for cache invalidation."""
    mtimes: List[float] = []
    for p in [BM25_RESUMES_CORPUS_PATH, BM25_RESUMES_DOCIDS_PATH, BM25_RESUMES_META_PATH]:
        if os.path.exists(p):
            mtimes.append(os.path.getmtime(p))
    return max(mtimes) if mtimes else 0.0


@st.cache_resource(show_spinner=False)
def _load_bm25_index(_mtime: Optional[float] = None):
    """Load BM25 index for resumes. _mtime forces cache refresh when files change."""

    class _NullBM25:
        corpus_size = 0

        def get_scores(self, tokens):
            return []

    if not (os.path.exists(BM25_RESUMES_CORPUS_PATH) and os.path.exists(BM25_RESUMES_DOCIDS_PATH)):
        return _NullBM25(), [], {}, {}

    with open(BM25_RESUMES_CORPUS_PATH, "rb") as f:
        corpus_tokens = pickle.load(f)
    with open(BM25_RESUMES_DOCIDS_PATH, "rb") as f:
        doc_ids = pickle.load(f)

    if not corpus_tokens or all((not d) for d in corpus_tokens):
        bm25 = _NullBM25()
    else:
        bm25 = BM25Okapi(corpus_tokens)

    id2pos = {d: i for i, d in enumerate(doc_ids)}
    meta_by_id: Dict[str, Dict] = {}
    if os.path.exists(BM25_RESUMES_META_PATH) and os.path.getsize(BM25_RESUMES_META_PATH) > 0:
        with open(BM25_RESUMES_META_PATH, "rb") as f:
            meta_by_id = pickle.load(f)
    return bm25, doc_ids, id2pos, meta_by_id


def _bm25_collect_chunks(coll, top_any: List[str], kw_scores_map_any: Dict[str, float]):
    """
    Robustly map BM25 ids (which might be chunk ids, or stored under metadata keys)
    to actual chunks in Chroma. We try, in order:
      - metadata.chunk_id
      - direct ids
      - metadata.parent_id
      - metadata.resume_id
    Returns a list of (chunk_id, doc, meta, kw_score).
    """
    top_any = [str(x) for x in top_any if x is not None]
    remaining = set(top_any)
    out: Dict[str, Dict] = {}
    include = ["documents", "metadatas"]

    def _merge(got, score_key: Optional[str] = None):
        if not got:
            return
        got_ids = got.get("ids") or []
        got_docs = got.get("documents") or []
        got_meta = got.get("metadatas") or []
        for i in range(len(got_ids)):
            meta = got_meta[i] or {}
            cid2 = meta.get("chunk_id", got_ids[i])
            if score_key:
                key_val = meta.get(score_key)
            else:
                key_val = meta.get("chunk_id", got_ids[i])
            kw_sc = kw_scores_map_any.get(str(key_val), 0.0)
            if cid2 in out:
                out[cid2]["kw"] = max(out[cid2]["kw"], kw_sc)
            else:
                out[cid2] = {"doc": got_docs[i], "meta": meta, "kw": kw_sc}
            if key_val in remaining:
                remaining.discard(key_val)

    if remaining:
        got = coll.get(where={"chunk_id": {"$in": list(remaining)}}, include=include)
        _merge(got, score_key="chunk_id")

    if remaining:
        got = coll.get(ids=list(remaining), include=include)
        _merge(got, score_key=None)

    if remaining:
        got = coll.get(where={"parent_id": {"$in": list(remaining)}}, include=include)
        _merge(got, score_key="parent_id")

    if remaining:
        got = coll.get(where={"resume_id": {"$in": list(remaining)}}, include=include)
        _merge(got, score_key="resume_id")

    return [(cid2, v["doc"], v["meta"], v["kw"]) for cid2, v in out.items()]


def _rrf_fuse(rankings: Dict[str, List[str]], k: int = RRF_K) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for _, ids in rankings.items():
        for rank, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


# ----------------------------------------------------------------------
# NEW: diagnostic scoring helpers (do NOT affect ranking)
# ----------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#\-.]{1,63}")

def _tok(s: str) -> List[str]:
    return _WORD_RE.findall((s or "").lower())

def _ratio(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    x = max(0.0, min(1.0, numer / float(denom)))
    return x

def _extract_years(text: str) -> Optional[float]:
    """
    Heuristic: find patterns like '7 years', '3+ yrs', '10+ years'.
    Return the maximum number found (float).
    """
    if not text:
        return None
    text_l = text.lower()
    # common patterns
    patt = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|year|yrs|yr)\b")
    vals = [float(m.group(1)) for m in patt.finditer(text_l)]
    return max(vals) if vals else None

def _calc_role_score(job_title: str, resume_chunk_text: str) -> float:
    """
    Pure keyword overlap between JD title tokens and the resume chunk text.
    """
    title_tokens = [t for t in _tok(job_title) if len(t) > 1]
    if not title_tokens:
        return 0.0
    text_tokens = set(_tok(resume_chunk_text))
    hit = sum(1 for t in title_tokens if t in text_tokens)
    return _ratio(hit, len(title_tokens))

def _calc_skill_score(skills: List[str], resume_chunk_text: str) -> float:
    """
    Keyword match rate over JD skills list (simple substring, case-insensitive).
    """
    if not skills:
        return 0.0
    txt = (resume_chunk_text or "").lower()
    total = len(skills)
    hits = 0
    for s in skills:
        s_norm = (s or "").strip().lower()
        if not s_norm:
            total -= 1
            continue
        if s_norm in txt:
            hits += 1
    return _ratio(hits, max(total, 1))

def _calc_project_score(rows_for_resume: List[Dict]) -> float:
    """
    Average normalized similarity for chunks mentioning 'project'.
    """
    vals = [r["sim"] for r in rows_for_resume if "doc_full" in r and "project" in (r["doc_full"] or "").lower()]
    if not vals:
        return 0.0
    return float(sum(vals) / len(vals))

def _calc_experience_score(jd_text_full: str, resume_text_concat: str) -> float:
    """
    Ratio of resume years-of-experience vs JD requirement; clipped to [0,1].
    If JD requirement not found → 0.0 (undefined treated as neutral-low).
    """
    req = _extract_years(jd_text_full)  # requirement from full JD text
    have = _extract_years(resume_text_concat)
    if not req or req <= 0:
        return 0.0
    if not have or have < 0:
        return 0.0
    return max(0.0, min(1.0, have / req))

# ----------------------------------------------------------------------
# Core search (with diagnostic scores but unchanged ranking)
# ----------------------------------------------------------------------
def _semantic_search(
    jd_text: str,
    coll,
    *,
    job_title_for_diag: str = "",
    skills_for_diag: Optional[List[str]] = None,
) -> List[Dict]:
    """
    JD text → (pooled) embedding → Chroma query over RESUME chunks →
    normalize similarities → aggregate to parent resume → rank (UNCHANGED).
    Additionally computes diagnostic signals that DO NOT affect ranking:
      - role_score, skill_score, project_score, experience_score
    """
    qvec = _embed_query_pooled(jd_text)
    if not qvec:
        return []

    res = coll.query(
        query_embeddings=[qvec],
        n_results=R2J_TOP_K_VECTOR,
        include=["documents", "distances", "metadatas"],
    )
    ids = res.get("ids", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    docs = res.get("documents", [[]])[0]

    sims = _distances_to_similarities([float(d) for d in dists])
    sims_norm = _normalize(sims)

    # Collect chunk-level rows
    rows: List[Dict] = []
    for _id, md, doc, s in zip(ids, metas, docs, sims_norm):
        rows.append(
            {
                "chunk_id": _id,
                "resume_id": (md or {}).get("resume_id") or (md or {}).get("parent_id") or (_id.split("::")[0] if _id else None),
                "candidate_name": (md or {}).get("candidate_name"),
                "email": (md or {}).get("email"),
                "phone": (md or {}).get("phone"),
                "sim": float(s),
                "doc_full": doc or "",
                "preview": (doc or "")[:320].replace("\n", " "),
            }
        )

    # Aggregate to parent resume: keep the best chunk as the representative evidence
    by_parent: Dict[str, Dict] = {}
    rows_by_pid: Dict[str, List[Dict]] = {}
    for r in rows:
        pid = r.get("resume_id")
        if not pid:
            continue
        rows_by_pid.setdefault(pid, []).append(r)
        cur = by_parent.get(pid)
        if (not cur) or (r["sim"] > cur["sim"]):
            by_parent[pid] = r

    # UNCHANGED ranking: sort by similarity only
    ranked = sorted(by_parent.values(), key=lambda x: x["sim"], reverse=True)[: R2J_TOP_K_FINAL]
    if not ranked:
        return []

    # Relative Match% scaling within the top-k (for easier reading)
    hi = max(x["sim"] for x in ranked) or 1.0
    lo = min(x["sim"] for x in ranked)
    span = hi - lo if hi > lo else 1.0
    for x in ranked:
        x["match_pct"] = round(100.0 * ((x["sim"] - lo) / span), 1)

    # ---- NEW: compute diagnostics per resume (do NOT affect ranking) ----
    skills_for_diag = skills_for_diag or []
    for x in ranked:
        pid = x.get("resume_id")
        best_chunk_text = x.get("doc_full", "")
        group_rows = rows_by_pid.get(pid, [])

        role_score = _calc_role_score(job_title_for_diag, best_chunk_text)
        skill_score = _calc_skill_score(skills_for_diag, best_chunk_text)
        project_score = _calc_project_score(group_rows)
        # concat a reasonable slice of texts for exp extraction
        concat_txt = " ".join((r.get("doc_full") or "")[:1500] for r in group_rows[:10])
        experience_score = _calc_experience_score(jd_text_full=jd_text, resume_text_concat=concat_txt)

        x["role_score"] = role_score
        x["skill_score"] = skill_score
        x["project_score"] = project_score
        x["experience_score"] = experience_score

    return ranked


# ----------------------------------------------------------------------
# Hybrid core search (semantic + BM25 + RRF + MMR, with diagnostics)
# ----------------------------------------------------------------------
def _semantic_search(  # type: ignore[override]
    jd_text: str,
    coll,
    *,
    job_title_for_diag: str = "",
    skills_for_diag: Optional[List[str]] = None,
) -> List[Dict]:
    """
    JD text → pooled embedding → hybrid retrieval over RESUME chunks:
      - semantic (Ollama embeddings via Chroma)
      - keyword (BM25 over resume chunks)
      - score fusion (HYBRID_ALPHA) + optional RRF + MMR
    Then aggregates to parent resume level and computes diagnostics
    (role_score, skill_score, project_score, experience_score) that do
    NOT affect ranking.
    """
    qvec = _embed_query_pooled(jd_text)
    if not qvec:
        return []

    # ----- Vector side -----
    res = coll.query(
        query_embeddings=[qvec],
        n_results=K_VEC,
        include=["documents", "metadatas", "distances", "embeddings"],
    )
    ids_v = res.get("ids", [[]])[0]
    docs_v = res.get("documents", [[]])[0]
    metas_v = res.get("metadatas", [[]])[0]
    dists_v = res.get("distances", [[]])[0]
    embs_v = res.get("embeddings", [[]])[0]

    has_embs = embs_v is not None and hasattr(embs_v, "__len__") and len(embs_v) >= len(ids_v)
    sem_v = [1.0 - float(d) for d in dists_v]

    candidates: Dict[str, Dict] = {}
    for i, raw_id in enumerate(ids_v):
        md = metas_v[i] or {}
        key = md.get("chunk_id", raw_id)
        doc = docs_v[i] or ""
        entry = candidates.get(key)
        if not entry:
            candidates[key] = {
                "doc": _strip_rtf_noise(doc),
                "sem": float(sem_v[i]),
                "kw": 0.0,
                "meta": md,
                "emb": embs_v[i] if has_embs else None,
            }
        else:
            entry["sem"] = max(entry["sem"], float(sem_v[i]))

    # ----- BM25 side -----
    bm25, doc_ids, id2pos, meta_by_id = _load_bm25_index(_mtime=_get_bm25_mtime())
    if getattr(bm25, "corpus_size", 0) > 0 and id2pos:
        toks = _normalize_for_bm25(jd_text).split()
        scores = bm25.get_scores(toks)

        pairs = [(cid, float(scores[pos])) for cid, pos in id2pos.items() if pos < len(scores)]
        pairs.sort(key=lambda x: x[1], reverse=True)
        top_any = [cid for cid, _ in pairs[:K_BM25]]
        kw_scores_map_any = {cid: sc for cid, sc in pairs[:K_BM25]}

        bm25_hits = _bm25_collect_chunks(coll, top_any, kw_scores_map_any)

        if not bm25_hits:
            # last-ditch: synthesize entries when no Chroma mapping is found
            for any_id, sc in kw_scores_map_any.items():
                md = meta_by_id.get(any_id, {"chunk_id": any_id})
                cid2 = md.get("chunk_id", f"{any_id}::pseudo")
                if cid2 not in candidates:
                    candidates[cid2] = {
                        "doc": "",
                        "sem": 0.0,
                        "kw": sc,
                        "meta": md,
                        "emb": None,
                    }
                else:
                    candidates[cid2]["kw"] = max(candidates[cid2]["kw"], sc)
        else:
            for cid2, doc2, meta2, kw_sc in bm25_hits:
                if cid2 not in candidates:
                    candidates[cid2] = {
                        "doc": _strip_rtf_noise(doc2 or ""),
                        "sem": 0.0,
                        "kw": kw_sc,
                        "meta": meta2,
                        "emb": None,
                    }
                else:
                    candidates[cid2]["kw"] = max(candidates[cid2]["kw"], kw_sc)

    if not candidates:
        return []

    # ----- Fuse semantic + keyword (+ optional RRF) -----
    keys = list(candidates.keys())
    sem_vals = [candidates[k]["sem"] for k in keys]
    kw_vals = [candidates[k]["kw"] for k in keys]

    sem_n = _normalize(sem_vals)
    kw_n = _normalize(kw_vals)

    if USE_RRF:
        sem_rank = sorted(keys, key=lambda k: candidates[k]["sem"], reverse=True)
        kw_rank = sorted(keys, key=lambda k: candidates[k]["kw"], reverse=True)
        rrf = _rrf_fuse({"semantic": sem_rank, "bm25": kw_rank}, k=RRF_K)
    else:
        rrf = {k: 0.0 for k in keys}

    fused: Dict[str, float] = {}
    for i, k in enumerate(keys):
        base = float(HYBRID_ALPHA) * sem_n[i] + (1.0 - float(HYBRID_ALPHA)) * kw_n[i]
        fused[k] = 0.5 * base + 0.5 * rrf.get(k, 0.0) if USE_RRF else base

    ordered = sorted(keys, key=lambda k: fused[k], reverse=True)

    # ----- Anti-collapse re-scoring (if fused range ~ 0) -----
    if ordered:
        vals = [fused[k] for k in ordered]
        if (max(vals) - min(vals)) < 1e-6:
            try:
                q = np.asarray(qvec, dtype=float)
                sims = []
                for cid in ordered:
                    e = candidates[cid].get("emb")
                    if e is None:
                        sims.append(0.0)
                    else:
                        v = np.asarray(e, dtype=float)
                        denom = float(np.linalg.norm(q) * np.linalg.norm(v))
                        sims.append(float(np.dot(q, v) / denom) if denom > 0 else 0.0)
                if any(sims):
                    sims_n = _normalize(sims)
                    for cid, s in zip(ordered, sims_n):
                        fused[cid] = 0.7 * s + 0.3 * fused[cid]
                    ordered = sorted(ordered, key=lambda k: fused[k], reverse=True)
            except Exception:
                pass

    # ----- MMR diversity (optional) -----
    if USE_MMR and ordered:
        try:
            def _cos(a, b):
                na, nb = np.linalg.norm(a), np.linalg.norm(b)
                return 0.0 if na == 0 or nb == 0 else float(np.dot(a, b) / (na * nb))

            def _emb(cid):
                e = candidates[cid].get("emb")
                if e is None:
                    return None
                try:
                    return np.asarray(e, dtype=float)
                except Exception:
                    return None

            selected = [ordered[0]]
            remaining = ordered[1:]
            while remaining and len(selected) < min(K_CHUNKS, len(ordered)):
                best_idx, best_score = 0, -1e9
                for i, cid in enumerate(remaining):
                    ec = _emb(cid)
                    if ec is None:
                        redun = 0.0
                    else:
                        redun = max((_cos(ec, _emb(s)) for s in selected if _emb(s) is not None), default=0.0)
                    score = float(MMR_LAMBDA) * (1.0 - redun)
                    if score > best_score:
                        best_score, best_idx = score, i
                selected.append(remaining.pop(best_idx))
            final_ids = selected
        except Exception:
            final_ids = ordered[:K_CHUNKS]
    else:
        final_ids = ordered[:K_CHUNKS]

    # ----- Materialize chunk-level rows from fused scores -----
    rows: List[Dict] = []
    for cid in final_ids:
        item = candidates[cid]
        md = dict(item.get("meta") or {})
        doc = item.get("doc") or ""
        resume_id = (
            md.get("resume_id")
            or md.get("parent_id")
            or md.get("document_id")
            or (cid.split("::")[0] if cid else None)
        )
        rows.append(
            {
                "chunk_id": cid,
                "resume_id": resume_id,
                "candidate_name": md.get("candidate_name"),
                "email": md.get("email"),
                "phone": md.get("phone"),
                "sim": float(fused.get(cid, 0.0)),
                "doc_full": doc,
                "preview": doc[:320].replace("\n", " "),
            }
        )

    # Aggregate to parent resume: keep the best chunk as the representative evidence
    by_parent: Dict[str, Dict] = {}
    rows_by_pid: Dict[str, List[Dict]] = {}
    for r in rows:
        pid = r.get("resume_id")
        if not pid:
            continue
        rows_by_pid.setdefault(pid, []).append(r)
        cur = by_parent.get(pid)
        if (not cur) or (r["sim"] > cur["sim"]):
            by_parent[pid] = r

    ranked = sorted(by_parent.values(), key=lambda x: x["sim"], reverse=True)[: R2J_TOP_K_FINAL]
    if not ranked:
        return []

    # Relative Match% scaling within the top-k (for easier reading)
    hi = max(x["sim"] for x in ranked) or 1.0
    lo = min(x["sim"] for x in ranked)
    span = hi - lo if hi > lo else 1.0
    for x in ranked:
        x["match_pct"] = round(100.0 * ((x["sim"] - lo) / span), 1)

    # Diagnostics per resume (do NOT affect ranking)
    skills_for_diag = skills_for_diag or []
    for x in ranked:
        pid = x.get("resume_id")
        best_chunk_text = x.get("doc_full", "")
        group_rows = rows_by_pid.get(pid, [])

        role_score = _calc_role_score(job_title_for_diag, best_chunk_text)
        skill_score = _calc_skill_score(skills_for_diag, best_chunk_text)
        project_score = _calc_project_score(group_rows)
        concat_txt = " ".join((r.get("doc_full") or "")[:1500] for r in group_rows[:10])
        experience_score = _calc_experience_score(jd_text_full=jd_text, resume_text_concat=concat_txt)

        x["role_score"] = role_score
        x["skill_score"] = skill_score
        x["project_score"] = project_score
        x["experience_score"] = experience_score

    return ranked


# ----------------------------------------------------------------------
# NEW: Score specific applicants (even if not in top 10)
# ----------------------------------------------------------------------
def score_applicants(
    jd_text: str,
    applicant_resume_ids: List[str],
    coll,
    *,
    job_title_for_diag: str = "",
    skills_for_diag: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Score specific applicants against a JD and return their AI match scores,
    rank, and status (Top 10, Below Top 10, or Not Matched).

    This is useful when you have a list of applicants who applied to a job
    and need to show their AI scores even if they're not in the top 10.

    Args:
        jd_text: Job description text
        applicant_resume_ids: List of resume IDs to score (e.g., from your applicant database)
        coll: ChromaDB collection
        job_title_for_diag: Job title for diagnostic scoring
        skills_for_diag: Required skills list for diagnostic scoring

    Returns:
        List of dicts with applicant scores, rank, and status
    """
    qvec = _embed_query_pooled(jd_text)
    if not qvec:
        return []

    # Retrieve MORE results to ensure we capture applicants beyond top 10
    # We'll get up to 200 chunks to have better coverage
    extended_top_k = min(200, R2J_TOP_K_VECTOR * 5)

    res = coll.query(
        query_embeddings=[qvec],
        n_results=extended_top_k,
        include=["documents", "distances", "metadatas"],
    )
    ids = res.get("ids", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    docs = res.get("documents", [[]])[0]

    sims = _distances_to_similarities([float(d) for d in dists])
    sims_norm = _normalize(sims)

    # Collect chunk-level rows
    rows: List[Dict] = []
    for _id, md, doc, s in zip(ids, metas, docs, sims_norm):
        rows.append({
            "chunk_id": _id,
            "resume_id": (md or {}).get("resume_id") or (md or {}).get("parent_id") or (_id.split("::")[0] if _id else None),
            "candidate_name": (md or {}).get("candidate_name"),
            "email": (md or {}).get("email"),
            "phone": (md or {}).get("phone"),
            "sim": float(s),
            "doc_full": doc or "",
            "preview": (doc or "")[:320].replace("\n", " "),
        })

    # Aggregate to parent resume: keep the best chunk as evidence
    by_parent: Dict[str, Dict] = {}
    rows_by_pid: Dict[str, List[Dict]] = {}
    for r in rows:
        pid = r.get("resume_id")
        if not pid:
            continue
        rows_by_pid.setdefault(pid, []).append(r)
        cur = by_parent.get(pid)
        if (not cur) or (r["sim"] > cur["sim"]):
            by_parent[pid] = r

    # Get ALL results sorted by similarity (no top-k limit here)
    all_ranked = sorted(by_parent.values(), key=lambda x: x["sim"], reverse=True)

    if not all_ranked:
        return []

    # Calculate match percentages for ALL results
    hi = max(x["sim"] for x in all_ranked) or 1.0
    lo = min(x["sim"] for x in all_ranked)
    span = hi - lo if hi > lo else 1.0

    # Add diagnostics to all results
    skills_for_diag = skills_for_diag or []
    for idx, x in enumerate(all_ranked):
        x["match_pct"] = round(100.0 * ((x["sim"] - lo) / span), 1)
        x["rank"] = idx + 1  # 1-based ranking

        # Status based on rank
        if x["rank"] <= 10:
            x["status"] = "Top 10"
        elif x["rank"] <= 50:
            x["status"] = f"Ranked #{x['rank']}"
        else:
            x["status"] = f"Ranked #{x['rank']}"

        # Compute diagnostics
        pid = x.get("resume_id")
        best_chunk_text = x.get("doc_full", "")
        group_rows = rows_by_pid.get(pid, [])

        x["role_score"] = _calc_role_score(job_title_for_diag, best_chunk_text)
        x["skill_score"] = _calc_skill_score(skills_for_diag, best_chunk_text)
        x["project_score"] = _calc_project_score(group_rows)
        concat_txt = " ".join((r.get("doc_full") or "")[:1500] for r in group_rows[:10])
        x["experience_score"] = _calc_experience_score(jd_text_full=jd_text, resume_text_concat=concat_txt)

    # Build a lookup for quick access
    results_by_id = {x["resume_id"]: x for x in all_ranked if x.get("resume_id")}

    # Now build the response for requested applicants
    applicant_results = []
    for resume_id in applicant_resume_ids:
        if resume_id in results_by_id:
            # Applicant was matched by AI
            applicant_results.append(results_by_id[resume_id])
        else:
            # Applicant not in AI results (very low similarity or not indexed)
            applicant_results.append({
                "resume_id": resume_id,
                "candidate_name": None,
                "email": None,
                "phone": None,
                "match_pct": 0.0,
                "rank": None,
                "status": "Not Matched",
                "sim": 0.0,
                "role_score": 0.0,
                "skill_score": 0.0,
                "project_score": 0.0,
                "experience_score": 0.0,
                "preview": "Resume not found in AI index or similarity too low",
            })

    return applicant_results


# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
# Add tabs to separate "Find Top 10" from "Score Applicants"
tab1, tab2 = st.tabs(["🔍 Find Top 10 Matches", "📋 Score Specific Applicants"])

# ==========================
# TAB 1: Find Top 10 Matches (original functionality)
# ==========================
with tab1:
    st.markdown("### Find the top 10 matching resumes for a job posting")
    left, right = st.columns([1, 1])

with left:
    # ---------- New Job Post Form (replaces file upload) ----------
    with st.form("new_job_post_form", clear_on_submit=False):
        employer_id = st.text_input("EmployerId", value="1")
        job_title = st.text_input("Job title", value="Java Full Stack Developer")
        description = st.text_area("Description", value="Should have knowledge on designing and developing both front-end user …", height=200)
        location = st.text_input("Location", value="Hyderabad")
        job_type = st.selectbox("JobType", options=["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY"], index=0)
        min_salary = st.number_input("MinSalary", value=30000, step=1000)
        max_salary = st.number_input("MaxSalary", value=50000, step=1000)
        required_skills_text = st.text_input("RequiredSkills (comma-separated)", value="Java, Springboot, Hibernate, Html")
        posted_date = st.text_input("PostedDate", value="2025-08-28T13:03:02.686+00:00")
        anonymous_posting = st.checkbox("AnonymousPosting", value=False)
        is_active = st.checkbox("IsActive", value=True)
        created_at = st.text_input("CreatedAt", value="2025-08-28T13:03:02.748+00:00")
        updated_at = st.text_input("UpdatedAt", value="2025-08-28T13:03:02.748+00:00")
        run_btn = st.form_submit_button("Find matching resumes")

with right:
    st.subheader("Settings & Info")
    st.write(f"Chroma dir: `{CHROMA_DIR_RESUMES}`")
    st.write(f"Collection: `{CHROMA_COLLECTION_RESUMES}`")
    st.write(f"Embeddings via Ollama: `{EMBED_MODEL}` at `{OLLAMA_HOST}`")
    st.markdown(
        f"""
- Query pooling: `{R2J_QUERY_CHUNK_SIZE}` size, `{R2J_QUERY_CHUNK_OVERLAP}` overlap, `{R2J_QUERY_MAX_CHUNKS}` chunks  
- Retrieval: top `{R2J_TOP_K_VECTOR}` chunks → top `{R2J_TOP_K_FINAL}` resumes  
- Tip: ensure you've **ingested resumes** using your *Resume Admin* tool (separate collection).
"""
    )

# ----------------------------------------------------------------------
# Run search
# ----------------------------------------------------------------------
if run_btn:
    try:
        # Compose a JD text from the form fields (then clean, chunk, embed)
        skills_list = [s.strip() for s in required_skills_text.split(",") if s.strip()]
        composed_text = f"""
EmployerId: {employer_id}
Job Title: {job_title}
Description: {description}
Location: {location}
Job Type: {job_type}
Min Salary: {min_salary}
Max Salary: {max_salary}
Required Skills: {", ".join(skills_list)}
Posted Date: {posted_date}
Anonymous Posting: {anonymous_posting}
Is Active: {is_active}
Created At: {created_at}
Updated At: {updated_at}
""".strip()
        text = clean_text(composed_text)

        if not text.strip():
            st.warning("This form seems empty after parsing/cleaning.")
        else:
            coll = _get_resume_collection()
            results = _semantic_search(
                text,
                coll,
                job_title_for_diag=job_title,
                skills_for_diag=skills_list,
            )

            if not results:
                st.info("No results. Make sure you've ingested resumes in the resume collection.")
            else:
                # Prepare DataFrame (keep original columns; add diagnostics as extra columns)
                df = pd.DataFrame(results)

                # Convert diagnostic scores to percents for display (do NOT change ranking)
                def _p(x: Optional[float]) -> Optional[float]:
                    if x is None:
                        return None
                    try:
                        return round(100.0 * max(0.0, min(1.0, float(x))), 1)
                    except Exception:
                        return None

                for k in ["role_score", "skill_score", "project_score", "experience_score"]:
                    if k in df.columns:
                        df[k] = df[k].apply(_p)

                show_cols = [
                    "match_pct",
                    "candidate_name",
                    "email",
                    "phone",
                    "resume_id",
                    "sim",
                    "role_score",        # NEW diagnostics %
                    "skill_score",       # NEW diagnostics %
                    "project_score",     # NEW diagnostics %
                    "experience_score",  # NEW diagnostics %
                    "preview",
                ]
                # Ensure all columns exist for display
                for c in show_cols:
                    if c not in df.columns:
                        df[c] = None

                # Rename headings for clarity in UI
                rename_map = {
                    "match_pct": "Match %",
                    "sim": "Norm Cosine",
                    "role_score": "Role % (title match)",
                    "skill_score": "Skills % (JD list)",
                    "project_score": "Project % (avg sim)",
                    "experience_score": "Experience % (ratio)",
                }
                df_display = df.rename(columns=rename_map)

                st.dataframe(df_display[ [rename_map.get(c, c) for c in show_cols] ],
                             use_container_width=True,
                             hide_index=True)

                with st.expander("Download results"):
                    csv = df_display[ [rename_map.get(c, c) for c in show_cols] ].to_csv(index=False).encode()
                    st.download_button(
                        "Download CSV",
                        data=csv,
                        file_name="jd_to_resume_results.csv",
                        mime="text/csv",
                    )
                st.caption(
                    "Match% is relative within this result set (based on semantic similarity only). "
                    "Additional columns (Role/Skills/Project/Experience) are diagnostics and "
                    "**do not** affect ranking."
                )
    except requests.RequestException as e:
        st.error(
            f"Embedding call to Ollama failed. "
            f"Is Ollama running and the model `{EMBED_MODEL}` pulled? Details: {e}",
            icon="⚠️",
        )
    except Exception as e:
        st.error(f"Search failed: {e}")

# ==========================
# TAB 2: Score Specific Applicants
# ==========================
with tab2:
    st.markdown("### Score specific applicants (even if not in top 10)")
    st.info("📌 **Use Case:** You have a list of applicants who applied to a job, and you want to see their AI match scores, rank, and status—even if they're not in the top 10.")

    col1, col2 = st.columns([1, 1])

    with col1:
        with st.form("applicant_scoring_form"):
            st.subheader("1️⃣ Job Details")
            job_title_app = st.text_input("Job title*", value="Java Full Stack Developer")
            description_app = st.text_area("Description*", value="Should have knowledge on designing and developing both front-end user interfaces and back-end server logic...", height=150)
            required_skills_app = st.text_input("RequiredSkills (comma-separated)*", value="Java, Springboot, Hibernate, Html")

            st.subheader("2️⃣ Applicant Resume IDs")
            st.caption("Enter the resume IDs from your applicant database (one per line)")
            applicant_ids_text = st.text_area(
                "Resume IDs*",
                value="01_Liam_Carter_Senior_Java_Full_Stack_Engineer_Public_Sector_Systems\n02_Ava_Thompson_Lead_Microservices_Engineer_Identity_Access\nalex_gupta_java_developer__entry_level\nsome_non_existent_resume_id",
                height=150,
                help="These are the IDs stored in ChromaDB metadata (usually filename without extension + hash)"
            )

            score_btn = st.form_submit_button("🎯 Score These Applicants", type="primary")

    with col2:
        st.subheader("How it works")
        st.markdown("""
        1. **Enter job details** (same as Tab 1)
        2. **Provide applicant resume IDs** (from your applicant tracking system)
        3. **Get AI scores for ALL applicants**, including:
           - ✅ **Top 10**: Applicants in the top 10 matches
           - 📊 **Ranked #11-50+**: Applicants with lower match scores
           - ❌ **Not Matched**: Applicants not found or very low similarity

        **Benefits:**
        - See match scores for applicants who applied but aren't in top 10
        - Merge AI insights with your applicant database
        - No more empty entries for low-ranked applicants
        """)

        st.info("""
        **Resume ID Format:**
        Usually `{filename_without_extension}` or `{filename}.{hash}`
        Check your ChromaDB metadata to confirm the exact format.
        """)

    # Process applicant scoring
    if score_btn:
        if not applicant_ids_text.strip():
            st.warning("Please enter at least one applicant resume ID")
            st.stop()

        if not description_app.strip():
            st.warning("Please enter job description")
            st.stop()

        try:
            # Parse applicant IDs (one per line)
            applicant_ids = [line.strip() for line in applicant_ids_text.strip().split("\n") if line.strip()]

            if not applicant_ids:
                st.warning("No valid applicant IDs found")
                st.stop()

            st.success(f"✅ Processing {len(applicant_ids)} applicant(s)...")

            # Compose JD text
            skills_list_app = [s.strip() for s in required_skills_app.split(",") if s.strip()]
            composed_jd = f"""
Job Title: {job_title_app}
Description: {description_app}
Required Skills: {', '.join(skills_list_app)}
""".strip()

            # Get ChromaDB collection
            client_app = chromadb.PersistentClient(path=CHROMA_DIR_RESUMES)
            coll_app = client_app.get_collection(name=CHROMA_COLLECTION_RESUMES)

            # Score applicants using our new function
            with st.spinner("🔄 Calculating AI match scores..."):
                applicant_results = score_applicants(
                    jd_text=composed_jd,
                    applicant_resume_ids=applicant_ids,
                    coll=coll_app,
                    job_title_for_diag=job_title_app,
                    skills_for_diag=skills_list_app,
                )

            if not applicant_results:
                st.warning("No results found")
                st.stop()

            # Display results
            st.markdown("---")
            st.subheader(f"📊 AI Match Scores for {len(applicant_results)} Applicant(s)")

            # Prepare DataFrame
            df_app = pd.DataFrame(applicant_results)

            # Select columns to display
            display_cols = [
                "resume_id", "candidate_name", "status", "rank", "match_pct",
                "role_score", "skill_score", "project_score", "experience_score",
                "email", "phone", "preview"
            ]

            # Ensure all columns exist
            for col in display_cols:
                if col not in df_app.columns:
                    df_app[col] = None

            # Rename for clarity
            rename_map_app = {
                "resume_id": "Resume ID",
                "candidate_name": "Candidate",
                "status": "Status",
                "rank": "Rank",
                "match_pct": "Match %",
                "role_score": "Role %",
                "skill_score": "Skills %",
                "project_score": "Project %",
                "experience_score": "Experience %",
                "email": "Email",
                "phone": "Phone",
                "preview": "Preview",
            }

            df_display_app = df_app.rename(columns=rename_map_app)

            # Color-code by status
            def highlight_status(row):
                if row["Status"] == "Top 10":
                    return ['background-color: #d4edda'] * len(row)  # Green
                elif row["Status"] == "Not Matched":
                    return ['background-color: #f8d7da'] * len(row)  # Red
                else:
                    return ['background-color: #fff3cd'] * len(row)  # Yellow

            styled_df = df_display_app[[rename_map_app.get(c, c) for c in display_cols]].style.apply(highlight_status, axis=1)

            st.dataframe(styled_df, use_container_width=True, hide_index=True)

            # Summary stats
            st.markdown("### 📈 Summary")
            col_a, col_b, col_c = st.columns(3)

            with col_a:
                top_10_count = len([r for r in applicant_results if r.get("status") == "Top 10"])
                st.metric("Top 10 Applicants", top_10_count)

            with col_b:
                ranked_count = len([r for r in applicant_results if r.get("rank") is not None and r.get("rank") > 10])
                st.metric("Ranked (11+)", ranked_count)

            with col_c:
                not_matched_count = len([r for r in applicant_results if r.get("status") == "Not Matched"])
                st.metric("Not Matched", not_matched_count)

            # Download option
            with st.expander("📥 Download Results"):
                csv_app = df_display_app[[rename_map_app.get(c, c) for c in display_cols]].to_csv(index=False).encode()
                st.download_button(
                    "Download CSV",
                    data=csv_app,
                    file_name="applicant_ai_scores.csv",
                    mime="text/csv",
                )

            st.caption("""
            **Legend:**
            - 🟢 **Top 10**: Applicant is in the top 10 AI matches
            - 🟡 **Ranked #11+**: Applicant matched but below top 10
            - 🔴 **Not Matched**: Applicant not found in AI index or very low similarity

            Match% is relative within the retrieved result set. Diagnostic scores (Role/Skills/Project/Experience) are for reference only.
            """)

        except requests.RequestException as e:
            st.error(f"❌ Embedding call to Ollama failed. Is Ollama running and the model `{EMBED_MODEL}` pulled? Details: {e}", icon="⚠️")
        except Exception as e:
            st.error(f"❌ Scoring failed: {e}")
            import traceback
            st.code(traceback.format_exc())
