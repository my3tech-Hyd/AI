# utils_training_to_resumes.py
# ----------------------------------------------------------------------
# Utilities for: Training Center Form → Resume Retrieval (cosine-only)
# - Text cleaning and chunking for pooled query embeddings
# - Ollama embedding client (nomic-embed-text by default)
# - Distance → similarity conversion and min–max normalization
# - Helper to open the existing RESUMES Chroma collection (read-only usage)
# - Optional: compose text from the training-center form fields
# ----------------------------------------------------------------------

from __future__ import annotations

import io
import re
import json
import requests
from typing import List, Dict, Optional

import chromadb

from config_training_to_resumes import (
    CHROMA_DIR_RESUMES,
    CHROMA_COLLECTION_RESUMES,
    OLLAMA_HOST,
    EMBED_MODEL,
    T2R_QUERY_CHUNK_SIZE,
    T2R_QUERY_CHUNK_OVERLAP,
    T2R_QUERY_MAX_CHUNKS,
    T2R_MAX_QUERY_CHARS,
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

# ---------------- Form composition (optional but convenient) ----------------

def compose_text_from_training_form(
    *,
    center_name: str,
    capacity: int,
    address: str,
    phone: str,
    email: str,
    course_duration: str,
    certification: str,
    courses_offered: List[str],
    description: str,
) -> str:
    """
    Compose a single text payload from the training-center form fields.
    This text is what we embed (with pooled-chunk strategy) to query the RESUMES collection.
    """
    txt = f"""
Center Name: {center_name}
Capacity: {capacity}
Address: {address}
Phone: {phone}
Email: {email}
Course Duration: {course_duration}
Certification: {certification}
Courses Offered: {", ".join(courses_offered)}
Description: {description}
""".strip()
    return clean_text(txt)

# ---------------- Chunking & pooling ----------------

def _chunk_query_text(
    text: str,
    size: int = T2R_QUERY_CHUNK_SIZE,
    overlap: int = T2R_QUERY_CHUNK_OVERLAP,
    max_chunks: int = T2R_QUERY_MAX_CHUNKS,
    max_chars: int = T2R_MAX_QUERY_CHARS,
) -> List[str]:
    """
    Split (possibly long) form text into overlapping chunks for robust pooling.
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

def embed_query_pooled(text: str) -> List[float]:
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

def get_resume_collection():
    """
    Open (or create if missing) the existing RESUMES collection.
    We only read/query in the user search app.
    """
    client = chromadb.PersistentClient(path=CHROMA_DIR_RESUMES)
    # Do not mutate schema; just ensure name matches.
    return client.get_or_create_collection(name=CHROMA_COLLECTION_RESUMES)

# ---------------- Convenience export ----------------

__all__ = [
    "clean_text",
    "to_csv_list",
    "compose_text_from_training_form",
    "embed_query_pooled",
    "distances_to_similarities",
    "normalize",
    "get_resume_collection",
]
