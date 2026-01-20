# config_training_to_resumes.py
# ----------------------------------------------------------------------
# Config for: Training Center Form → Resume Retrieval (cosine-only)
# - Reuses the existing RESUMES Chroma collection (read-only)
# - Provides Ollama + embedding settings and query-pooling knobs
# - Values are read from environment with safe defaults
# ----------------------------------------------------------------------

from __future__ import annotations
import os

try:
    # Optional: load .env if present (won't fail if python-dotenv is missing)
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ---------------- Chroma (RESUMES corpus you already have) ----------------
CHROMA_DIR_RESUMES: str = os.getenv("CHROMA_DIR_RESUMES", "C:/WITS/Wits dev/AI Model/j_to_r/chroma_resumes")
CHROMA_COLLECTION_RESUMES: str = os.getenv("CHROMA_COLLECTION_RESUMES", "resumes")

# ---------------- Ollama embeddings ----------------
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")

# ---------------- Query pooling (Training→Resume) ----------------
# We pool several overlapping chunks of the training-center form text before querying.
T2R_QUERY_CHUNK_SIZE: int = int(os.getenv("T2R_QUERY_CHUNK_SIZE", "500"))
T2R_QUERY_CHUNK_OVERLAP: int = int(os.getenv("T2R_QUERY_CHUNK_OVERLAP", "100"))
T2R_QUERY_MAX_CHUNKS: int = int(os.getenv("T2R_QUERY_MAX_CHUNKS", "6"))

# How many chunks to fetch from Chroma (vector stage) and how many resumes to keep finally.
T2R_TOP_K_VECTOR: int = int(os.getenv("T2R_TOP_K_VECTOR", "40"))
T2R_TOP_K_FINAL: int = int(os.getenv("T2R_TOP_K_FINAL", "10"))

# ---------------- Local tuning (optional) ----------------
# Extra safety for very long descriptions in the form.
T2R_MAX_QUERY_CHARS: int = int(os.getenv("T2R_MAX_QUERY_CHARS", "1200"))
# Ollama HTTP timeout (seconds)
OLLAMA_TIMEOUT: float = float(os.getenv("T2R_OLLAMA_TIMEOUT", "45"))

def dump_config() -> dict:
    """Convenience helper for debugging in Streamlit."""
    return {
        "CHROMA_DIR_RESUMES": CHROMA_DIR_RESUMES,
        "CHROMA_COLLECTION_RESUMES": CHROMA_COLLECTION_RESUMES,
        "OLLAMA_HOST": OLLAMA_HOST,
        "EMBED_MODEL": EMBED_MODEL,
        "T2R_QUERY_CHUNK_SIZE": T2R_QUERY_CHUNK_SIZE,
        "T2R_QUERY_CHUNK_OVERLAP": T2R_QUERY_CHUNK_OVERLAP,
        "T2R_QUERY_MAX_CHUNKS": T2R_QUERY_MAX_CHUNKS,
        "T2R_TOP_K_VECTOR": T2R_TOP_K_VECTOR,
        "T2R_TOP_K_FINAL": T2R_TOP_K_FINAL,
        "T2R_MAX_QUERY_CHARS": T2R_MAX_QUERY_CHARS,
        "OLLAMA_TIMEOUT": OLLAMA_TIMEOUT,
    }
