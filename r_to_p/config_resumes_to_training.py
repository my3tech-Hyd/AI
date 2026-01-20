# config_resumes_to_training.py
# ----------------------------------------------------------------------
# Config for: Resume → Training Postings retrieval (cosine-only)
# - Uses a dedicated Chroma collection for TRAINING postings (admin-ingested)
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

# ---------------- Chroma (TRAINING postings corpus; dedicated) ----------------
CHROMA_DIR_TRAIN_POSTS: str = os.getenv("CHROMA_DIR_TRAIN_POSTS", "./chroma_training_posts")
CHROMA_COLLECTION_TRAIN_POSTS: str = os.getenv("CHROMA_COLLECTION_TRAIN_POSTS", "training_posts")

# Optional store dir if you want to persist source JSON/TXT (used by admin ingest)
TRAIN_POSTS_STORE_DIR: str = os.getenv("TRAIN_POSTS_STORE_DIR", "./training_posts_store")

# ---------------- Ollama embeddings ----------------
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")

# ---------------- Query pooling (Resume→Training) ----------------
# We pool overlapping chunks of the resume text to build a stable query vector.
R2T_QUERY_CHUNK_SIZE: int = int(os.getenv("R2T_QUERY_CHUNK_SIZE", "700"))
R2T_QUERY_CHUNK_OVERLAP: int = int(os.getenv("R2T_QUERY_CHUNK_OVERLAP", "150"))
R2T_QUERY_MAX_CHUNKS: int = int(os.getenv("R2T_QUERY_MAX_CHUNKS", "8"))

# How many chunks to fetch from Chroma (vector stage) and how many posts to keep finally.
R2T_TOP_K_VECTOR: int = int(os.getenv("R2T_TOP_K_VECTOR", "40"))
R2T_TOP_K_FINAL: int = int(os.getenv("R2T_TOP_K_FINAL", "10"))

# ---------------- Local tuning (optional) ----------------
# Safety clip for very long resumes before chunking.
R2T_MAX_QUERY_CHARS: int = int(os.getenv("R2T_MAX_QUERY_CHARS", "4000"))
# Ollama HTTP timeout (seconds)
OLLAMA_TIMEOUT: float = float(os.getenv("R2T_OLLAMA_TIMEOUT", "45"))

def dump_config() -> dict:
    """Convenience helper for debugging in Streamlit."""
    return {
        "CHROMA_DIR_TRAIN_POSTS": CHROMA_DIR_TRAIN_POSTS,
        "CHROMA_COLLECTION_TRAIN_POSTS": CHROMA_COLLECTION_TRAIN_POSTS,
        "TRAIN_POSTS_STORE_DIR": TRAIN_POSTS_STORE_DIR,
        "OLLAMA_HOST": OLLAMA_HOST,
        "EMBED_MODEL": EMBED_MODEL,
        "R2T_QUERY_CHUNK_SIZE": R2T_QUERY_CHUNK_SIZE,
        "R2T_QUERY_CHUNK_OVERLAP": R2T_QUERY_CHUNK_OVERLAP,
        "R2T_QUERY_MAX_CHUNKS": R2T_QUERY_MAX_CHUNKS,
        "R2T_TOP_K_VECTOR": R2T_TOP_K_VECTOR,
        "R2T_TOP_K_FINAL": R2T_TOP_K_FINAL,
        "R2T_MAX_QUERY_CHARS": R2T_MAX_QUERY_CHARS,
        "OLLAMA_TIMEOUT": OLLAMA_TIMEOUT,
    }
