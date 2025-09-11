# config.py — merged & backward-compatible
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Load .env once, do not override existing env
load_dotenv(find_dotenv(), override=False)

# -------------------------
# Helpers
# -------------------------
def _get_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default

def _get_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default

# Old-style helper shims (safe to keep)
def env_bool(name: str, default=False) -> bool:
    v = os.getenv(name)
    if v is None:
        return bool(default)
    return str(v).strip().lower() in {"1","true","yes","y","on"}

def env_int(name: str, default: int) -> int:
    return _get_int(name, default)

def env_float(name: str, default: float) -> float:
    return _get_float(name, default)

def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)

# -------------------------
# Core paths
# -------------------------
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "resumes")

RESUMES_RAW_DIR = os.getenv("RESUMES_RAW_DIR", "./resumes_raw")
RESUMES_STORE_DIR = os.getenv("RESUMES_STORE_DIR", "./resumes_store")  # chunked/plaintext store
INDEX_DIR = os.getenv("INDEX_DIR", "./indexes")

for _d in (CHROMA_DIR, RESUMES_RAW_DIR, RESUMES_STORE_DIR, INDEX_DIR):
    Path(_d).mkdir(parents=True, exist_ok=True)

# -------------------------
# BM25 artifacts
# -------------------------
BM25_CORPUS_PATH = str(Path(INDEX_DIR) / "bm25_corpus.pkl")   # list[list[str]] tokens per chunk
BM25_DOCIDS_PATH = str(Path(INDEX_DIR) / "bm25_doc_ids.pkl")  # list[str] chunk_ids aligned to corpus
BM25_META_PATH   = str(Path(INDEX_DIR) / "bm25_meta.pkl")     # {chunk_id: {file_path, parent_id, ...}}
BM25_LANGUAGE    = os.getenv("BM25_LANGUAGE", "english")

# -------------------------
# Models / endpoints
# -------------------------
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
CHAT_MODEL  = os.getenv("CHAT_MODEL", "llama3.2:3b")

# -------------------------
# Query-side limits & chunking (query embedding)
# -------------------------
MAX_QUERY_CHARS     = int(os.getenv("MAX_QUERY_CHARS", "1200"))  # cap text sent to embedder
OLLAMA_TIMEOUT      = float(os.getenv("OLLAMA_TIMEOUT", "45"))
QUERY_CHUNK_SIZE    = int(os.getenv("QUERY_CHUNK_SIZE", "500"))
QUERY_CHUNK_OVERLAP = int(os.getenv("QUERY_CHUNK_OVERLAP", "100"))
QUERY_MAX_CHUNKS    = int(os.getenv("QUERY_MAX_CHUNKS", "6"))

# -------------------------
# Ingestion-time chunking (from OLD config; used by admin/build steps)
# -------------------------
CHUNK_SIZE    = _get_int("CHUNK_SIZE", 1200)
CHUNK_OVERLAP = _get_int("CHUNK_OVERLAP", 200)
if CHUNK_OVERLAP >= CHUNK_SIZE:
    CHUNK_OVERLAP = max(0, CHUNK_SIZE - 1)

# -------------------------
# File types (from OLD config)
# -------------------------
_raw_exts = os.getenv("ALLOWED_EXTS", "")
_raw_exts = _raw_exts.split(",") if _raw_exts else []
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".rtf", ".doc"} | {
    e.strip().lower() for e in _raw_exts if e.strip()
}

# -------------------------
# Ranking knobs (UI aggregation)
# -------------------------
TOP_K_FINAL = _get_int("TOP_K_FINAL", 10)

# Back-compat: old TOP_K_VECTOR feeds the new K_VEC by default
TOP_K_VECTOR = _get_int("TOP_K_VECTOR", 50)

# -------------------------
# Robust retrieval knobs (env-overridable)
# -------------------------
# If K_VEC is not set, default to TOP_K_VECTOR (old behavior) else 80
K_VEC        = _get_int("K_VEC", TOP_K_VECTOR if "K_VEC" not in os.environ else 80)
K_BM25       = _get_int("K_BM25", 80)     # add BM25 pool
K_CHUNKS     = _get_int("K_CHUNKS", 15)   # evidence chunks retained pre parent-pooling

HYBRID_ALPHA = _get_float("HYBRID_ALPHA", 0.55)  # 0..1 (↑semantic). Old default was 0.7
HYBRID_ALPHA = 0.0 if HYBRID_ALPHA < 0 else (1.0 if HYBRID_ALPHA > 1 else HYBRID_ALPHA)

USE_RRF    = env_bool("USE_RRF", True)
RRF_K      = _get_int("RRF_K", 60)

USE_MMR    = env_bool("USE_MMR", True)
MMR_LAMBDA = _get_float("MMR_LAMBDA", 0.6)  # 0..1 (↑diversity)

# -------------------------
# LangSmith
# -------------------------
LANGSMITH_TRACING = env_bool("LANGSMITH_TRACING", False)
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "resume-matcher")

def config_summary() -> str:
    return (
        f"CHROMA_DIR={CHROMA_DIR}, CHROMA_COLLECTION={CHROMA_COLLECTION}\n"
        f"RESUMES_RAW_DIR={RESUMES_RAW_DIR}, RESUMES_STORE_DIR={RESUMES_STORE_DIR}\n"
        f"INDEX_DIR={INDEX_DIR}\n"
        f"EMBED_MODEL={EMBED_MODEL}, CHAT_MODEL={CHAT_MODEL}, OLLAMA_HOST={OLLAMA_HOST}\n"
        f"MAX_QUERY_CHARS={MAX_QUERY_CHARS}, OLLAMA_TIMEOUT={OLLAMA_TIMEOUT}\n"
        f"QUERY_CHUNK_SIZE={QUERY_CHUNK_SIZE}, QUERY_CHUNK_OVERLAP={QUERY_CHUNK_OVERLAP}, QUERY_MAX_CHUNKS={QUERY_MAX_CHUNKS}\n"
        f"CHUNK_SIZE={CHUNK_SIZE}, CHUNK_OVERLAP={CHUNK_OVERLAP}\n"
        f"ALLOWED_EXTS={sorted(ALLOWED_EXTS)}\n"
        f"K_VEC={K_VEC}, K_BM25={K_BM25}, K_CHUNKS={K_CHUNKS}, HYBRID_ALPHA={HYBRID_ALPHA}, USE_RRF={USE_RRF}, RRF_K={RRF_K}, USE_MMR={USE_MMR}, MMR_LAMBDA={MMR_LAMBDA}\n"
        f"TOP_K_VECTOR={TOP_K_VECTOR}, TOP_K_FINAL={TOP_K_FINAL}\n"
        f"BM25_LANGUAGE={BM25_LANGUAGE}\n"
        f"LangSmith(tracing={LANGSMITH_TRACING}, project={LANGSMITH_PROJECT})"
    )

# -------------------------
# Back-compat attribute shim (old -> new names)
# -------------------------
import warnings as _warnings
_DEPRECATED_MAP = {
    # common legacy names → current names
    "CHROMA_PATH": "CHROMA_DIR",
    "BM25_CORPUS": "BM25_CORPUS_PATH",
    "BM25_DOC_IDS": "BM25_DOCIDS_PATH",
    "EMBEDDING_MODEL": "EMBED_MODEL",
    "TOP_K": "TOP_K_FINAL",
    "VECTOR_TOP_K": "K_VEC",
    "QUERY_SIZE": "QUERY_CHUNK_SIZE",
    "QUERY_OVERLAP": "QUERY_CHUNK_OVERLAP",
}

def __getattr__(name: str):
    if name in _DEPRECATED_MAP and _DEPRECATED_MAP[name] in globals():
        new = _DEPRECATED_MAP[name]
        _warnings.warn(
            f"config.{name} is deprecated; use config.{new}",
            DeprecationWarning,
            stacklevel=2,
        )
        return globals()[new]
    # allow direct access to existing names (including old ones we kept, e.g., TOP_K_VECTOR)
    if name in globals():
        return globals()[name]
    raise AttributeError(f"module 'config' has no attribute '{name}'")
