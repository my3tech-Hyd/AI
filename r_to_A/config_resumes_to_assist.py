# config_resumes_to_assist.py
# ----------------------------------------------------------------------
# Config for: Resume → Assistance Center Postings retrieval (cosine-only)
# - Uses a dedicated Chroma collection for ASSISTANCE postings (admin-ingested)
# - Reuses Ollama + embedding settings
# - Provides pooling knobs for resume query and retrieval cutoffs
# ----------------------------------------------------------------------

from __future__ import annotations
import os

try:
    # Optional: load .env if available
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ---------------- Chroma (ASSISTANCE postings corpus; dedicated) ----------------
CHROMA_DIR_ASSIST_POSTS: str = os.getenv("CHROMA_DIR_ASSIST_POSTS", "./chroma_assist_posts")
CHROMA_COLLECTION_ASSIST_POSTS: str = os.getenv("CHROMA_COLLECTION_ASSIST_POSTS", "assistance_posts")

# Optional store dir if you want to persist source TXT/JSON (used by admin ingest)
ASSIST_POSTS_STORE_DIR: str = os.getenv("ASSIST_POSTS_STORE_DIR", "./assist_posts_store")

# ---------------- Ollama embeddings ----------------
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")

# ---------------- Query pooling (Resume→Assistance) ----------------
# We pool overlapping chunks of the resume text to build a stable query vector.
R2A_QUERY_CHUNK_SIZE: int = int(os.getenv("R2A_QUERY_CHUNK_SIZE", "700"))
R2A_QUERY_CHUNK_OVERLAP: int = int(os.getenv("R2A_QUERY_CHUNK_OVERLAP", "150"))
R2A_QUERY_MAX_CHUNKS: int = int(os.getenv("R2A_QUERY_MAX_CHUNKS", "8"))

# How many vectors to fetch from Chroma (vector stage) and how many posts to keep finally.
R2A_TOP_K_VECTOR: int = int(os.getenv("R2A_TOP_K_VECTOR", "40"))
R2A_TOP_K_FINAL: int = int(os.getenv("R2A_TOP_K_FINAL", "10"))

# ---------------- Local tuning (optional) ----------------
# Safety clip for very long resumes before chunking.
R2A_MAX_QUERY_CHARS: int = int(os.getenv("R2A_MAX_QUERY_CHARS", "4000"))
# Ollama HTTP timeout (seconds)
OLLAMA_TIMEOUT: float = float(os.getenv("R2A_OLLAMA_TIMEOUT", "45"))

def dump_config() -> dict:
    """Convenience helper for debugging in Streamlit."""
    return {
        "CHROMA_DIR_ASSIST_POSTS": CHROMA_DIR_ASSIST_POSTS,
        "CHROMA_COLLECTION_ASSIST_POSTS": CHROMA_COLLECTION_ASSIST_POSTS,
        "ASSIST_POSTS_STORE_DIR": ASSIST_POSTS_STORE_DIR,
        "OLLAMA_HOST": OLLAMA_HOST,
        "EMBED_MODEL": EMBED_MODEL,
        "R2A_QUERY_CHUNK_SIZE": R2A_QUERY_CHUNK_SIZE,
        "R2A_QUERY_CHUNK_OVERLAP": R2A_QUERY_CHUNK_OVERLAP,
        "R2A_QUERY_MAX_CHUNKS": R2A_QUERY_MAX_CHUNKS,
        "R2A_TOP_K_VECTOR": R2A_TOP_K_VECTOR,
        "R2A_TOP_K_FINAL": R2A_TOP_K_FINAL,
        "R2A_MAX_QUERY_CHARS": R2A_MAX_QUERY_CHARS,
        "OLLAMA_TIMEOUT": OLLAMA_TIMEOUT,
    }
