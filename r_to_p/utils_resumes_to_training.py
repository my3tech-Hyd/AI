# utils_resumes_to_training.py
# ----------------------------------------------------------------------
# Utilities for: Resume → Training Postings retrieval (cosine-only)
# - Resume text extraction (pdf/docx/txt/rtf/md/doc best-effort)
# - Text cleaning, chunking, and pooled embedding via Ollama
# - Distance → similarity conversion and min–max normalization
# - Helper to open the TRAINING POSTS Chroma collection (admin-ingested)
# ----------------------------------------------------------------------

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import List

import requests
import chromadb
from pypdf import PdfReader
from docx import Document as Docx

from config_resumes_to_training import (
    CHROMA_DIR_TRAIN_POSTS,
    CHROMA_COLLECTION_TRAIN_POSTS,
    OLLAMA_HOST,
    EMBED_MODEL,
    R2T_QUERY_CHUNK_SIZE,
    R2T_QUERY_CHUNK_OVERLAP,
    R2T_QUERY_MAX_CHUNKS,
    R2T_MAX_QUERY_CHARS,
    OLLAMA_TIMEOUT,
)

# ---------------- Text utils ----------------

def clean_text(s: str) -> str:
    """Basic whitespace normalization."""
    if not s:
        return ""
    s = re.sub(r"\s+", " ", str(s))
    return s.strip()

def to_csv_list(s: str) -> List[str]:
    """Split a comma-separated string into clean tokens."""
    return [x.strip() for x in (s or "").split(",") if x.strip()]

# ---------------- Resume text extraction ----------------

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
        text = data.decode(errors="ignore")
    return clean_text(text)

# ---------------- Chunking & pooling for resume queries ----------------

def _chunk_query_text(
    text: str,
    size: int = R2T_QUERY_CHUNK_SIZE,
    overlap: int = R2T_QUERY_CHUNK_OVERLAP,
    max_chunks: int = R2T_QUERY_MAX_CHUNKS,
    max_chars: int = R2T_MAX_QUERY_CHARS,
) -> List[str]:
    """
    Split (possibly long) resume text into overlapping chunks for robust pooled embeddings.
    """
    t = text[:max_chars] if max_chars and max_chars > 0 else text
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

# ---------------- Ollama embeddings ----------------

def _embed_query_ollama(chunk: str) -> List[float]:
    """
    Call Ollama embeddings API directly.
    Requires: `ollama serve` running and `ollama pull <EMBED_MODEL>` done.
    """
    resp = requests.post(
        f"{OLLAMA_HOST}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": chunk},
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    # Accept both shapes:
    #  - {"embedding": [...]}
    #  - {"data": [{"embedding": [...]}]}
    vec = data.get("embedding")
    if vec is None:
        items = data.get("data") or []
        if items and isinstance(items[0], dict):
            vec = items[0].get("embedding")
    if not isinstance(vec, list) or not all(isinstance(x, (int, float)) for x in vec):
        raise ValueError("Invalid embedding vector received from Ollama.")
    return [float(x) for x in vec]

def embed_resume_pooled(text: str) -> List[float]:
    """
    Pool embeddings across overlapping chunks (length-weighted mean).
    """
    chunks = _chunk_query_text(text)
    if not chunks:
        return []
    vecs = [_embed_query_ollama(ch) for ch in chunks]
    dims = len(vecs[0])
    pooled = [0.0] * dims
    weights = [len(ch) for ch in chunks]
    denom = float(sum(weights) or 1.0)
    for v, w in zip(vecs, weights):
        if len(v) != dims:
            # Skip malformed vectors (defensive coding)
            continue
        wf = float(w)
        for i in range(dims):
            pooled[i] += wf * float(v[i])
    for i in range(dims):
        pooled[i] /= denom
    return pooled

# ---------------- Similarity helpers ----------------

def distances_to_similarities(dists: List[float]) -> List[float]:
    """
    Convert Chroma distances (cosine distance) to similarity proxy.
    For cosine distance d ∈ [0,2], a simple proxy is sim = 1 - d (works if Chroma returns [0,1]).
    """
    return [1.0 - float(d) for d in dists]

def normalize(xs: List[float]) -> List[float]:
    """
    Min–max normalize to [0,1]. If all values equal → all zeros.
    """
    if not xs:
        return xs
    lo, hi = min(xs), max(xs)
    span = hi - lo
    if span <= 1e-12:
        return [0.0 for _ in xs]
    return [(x - lo) / span for x in xs]

# ---------------- Chroma collection helper ----------------

def get_training_posts_collection():
    """
    Open (or create if missing) the dedicated TRAINING postings collection.
    Admin scripts should ingest one embedding per posting document.
    """
    client = chromadb.PersistentClient(path=CHROMA_DIR_TRAIN_POSTS)
    return client.get_or_create_collection(name=CHROMA_COLLECTION_TRAIN_POSTS)

# ---------------- Convenience export ----------------

__all__ = [
    "clean_text",
    "to_csv_list",
    "read_text_from_bytes",
    "embed_resume_pooled",
    "distances_to_similarities",
    "normalize",
    "get_training_posts_collection",
]
