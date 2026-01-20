# config_jd.py
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Reuse global env, do not override the main project's config.py.
load_dotenv(find_dotenv(), override=False)

# Reuse the same Chroma directory, but keep a separate collection for JDs.
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma")
CHROMA_COLLECTION_JDS = os.getenv("CHROMA_COLLECTION_JDS", "jobs")

# Store original JD files in a separate folder so we don't disturb resumes_store
JDS_STORE_DIR = os.getenv("JDS_STORE_DIR", "./jds_store")

# Keep BM25 artifacts separate and neatly namespaced
INDEX_DIR = os.getenv("INDEX_DIR", "./indexes")
JDS_INDEX_DIR = os.getenv("JDS_INDEX_DIR", str(Path(INDEX_DIR) / "jds"))
BM25_JDS_CORPUS_PATH = str(Path(JDS_INDEX_DIR) / "bm25_corpus.pkl")
BM25_JDS_META_PATH   = str(Path(JDS_INDEX_DIR) / "bm25_meta.pkl")
BM25_JDS_DOCIDS_PATH = str(Path(JDS_INDEX_DIR) / "bm25_doc_ids.pkl")

# Embeddings + Ollama (reusing the main project's env vars if present)
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Chunking for JD indexing (overrideable via env; falls back to main defaults if set)
CHUNK_SIZE    = int(os.getenv("JDS_CHUNK_SIZE", os.getenv("CHUNK_SIZE", "600")))
CHUNK_OVERLAP = int(os.getenv("JDS_CHUNK_OVERLAP", os.getenv("CHUNK_OVERLAP", "120")))

# Allowed file types
_raw_exts = os.getenv("ALLOWED_EXTS", "").split(",") if os.getenv("ALLOWED_EXTS") else []
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".rtf", ".doc"} | {e.strip().lower() for e in _raw_exts if e.strip()}

# Make sure dirs exist (harmless if already present)
for _d in (CHROMA_DIR, JDS_STORE_DIR, JDS_INDEX_DIR):
    Path(_d).mkdir(parents=True, exist_ok=True)

# Optional LangSmith tracing (kept separate so you can tag R2J runs differently)
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT_JDS", "jobs-index")
