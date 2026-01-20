# pinecone_config.py
# Centralized Pinecone configuration for all modules
# ----------------------------------------------------------------------

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base directory (where this config file is located)
_CONFIG_DIR = Path(__file__).resolve().parent

# ============================================================================
# PINECONE SETTINGS
# ============================================================================

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "us-east-1")

# Pinecone index name (ONE index for all corpora)
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "pbma")

# Pinecone namespaces (logical partitions within the index)
PINECONE_NAMESPACE_RESUMES = os.getenv("PINECONE_NAMESPACE_RESUMES", "resumes")
PINECONE_NAMESPACE_JOBS = os.getenv("PINECONE_NAMESPACE_JOBS", "jobs")
PINECONE_NAMESPACE_TRAINING = os.getenv("PINECONE_NAMESPACE_TRAINING", "training")
PINECONE_NAMESPACE_ASSISTANCE = os.getenv("PINECONE_NAMESPACE_ASSISTANCE", "assistance")

# Vector dimension (nomic-embed-text = 768)
VECTOR_DIMENSION = int(os.getenv("VECTOR_DIMENSION", "768"))

# Pinecone settings
PINECONE_METRIC = os.getenv("PINECONE_METRIC", "cosine")
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")

# ============================================================================
# OLLAMA SETTINGS (unchanged)
# ============================================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# ============================================================================
# BM25 PATHS (unchanged - still local files)
# ============================================================================

# Base directories (absolute paths from config file location)
INDEX_DIR = _CONFIG_DIR / Path(os.getenv("INDEX_DIR", "indexes"))

# Resume BM25 indexes
RESUMES_INDEX_DIR = INDEX_DIR / "resumes"
BM25_RESUMES_CORPUS_PATH = str(RESUMES_INDEX_DIR / "bm25_corpus.pkl")
BM25_RESUMES_DOCIDS_PATH = str(RESUMES_INDEX_DIR / "bm25_doc_ids.pkl")
BM25_RESUMES_META_PATH = str(RESUMES_INDEX_DIR / "bm25_meta.pkl")

# Job BM25 indexes
JOBS_INDEX_DIR = INDEX_DIR / "jds"
BM25_JOBS_CORPUS_PATH = str(JOBS_INDEX_DIR / "bm25_corpus.pkl")
BM25_JOBS_DOCIDS_PATH = str(JOBS_INDEX_DIR / "bm25_doc_ids.pkl")
BM25_JOBS_META_PATH = str(JOBS_INDEX_DIR / "bm25_meta.pkl")

# Training BM25 indexes
TRAINING_INDEX_DIR = INDEX_DIR / "training_posts"
BM25_TRAINING_CORPUS_PATH = str(TRAINING_INDEX_DIR / "bm25_corpus.pkl")
BM25_TRAINING_DOCIDS_PATH = str(TRAINING_INDEX_DIR / "bm25_doc_ids.pkl")
BM25_TRAINING_META_PATH = str(TRAINING_INDEX_DIR / "bm25_meta.pkl")

# Assistance BM25 indexes
ASSISTANCE_INDEX_DIR = INDEX_DIR / "assist_posts"
BM25_ASSISTANCE_CORPUS_PATH = str(ASSISTANCE_INDEX_DIR / "bm25_corpus.pkl")
BM25_ASSISTANCE_DOCIDS_PATH = str(ASSISTANCE_INDEX_DIR / "bm25_doc_ids.pkl")
BM25_ASSISTANCE_META_PATH = str(ASSISTANCE_INDEX_DIR / "bm25_meta.pkl")

# ============================================================================
# STORAGE PATHS
# ============================================================================

RESUMES_STORE_DIR = _CONFIG_DIR / Path(os.getenv("RESUMES_STORE_DIR", "resumes_store"))
JOBS_STORE_DIR = _CONFIG_DIR / Path(os.getenv("JOBS_STORE_DIR", "jds_store"))
TRAINING_STORE_DIR = _CONFIG_DIR / Path(os.getenv("TRAINING_STORE_DIR", "training_posts_store"))
ASSISTANCE_STORE_DIR = _CONFIG_DIR / Path(os.getenv("ASSISTANCE_STORE_DIR", "assist_posts_store"))

# Create directories if they don't exist
for dir_path in [
    INDEX_DIR,
    RESUMES_INDEX_DIR,
    JOBS_INDEX_DIR,
    TRAINING_INDEX_DIR,
    ASSISTANCE_INDEX_DIR,
    RESUMES_STORE_DIR,
    JOBS_STORE_DIR,
    TRAINING_STORE_DIR,
    ASSISTANCE_STORE_DIR,
]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ============================================================================
# RETRIEVAL SETTINGS
# ============================================================================

# Hybrid search parameters
HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", "0.6"))  # 60% semantic, 40% keyword
K_VEC = int(os.getenv("K_VEC", "40"))  # Vector candidates
K_BM25 = int(os.getenv("K_BM25", "80"))  # Keyword candidates
K_CHUNKS = int(os.getenv("K_CHUNKS", "20"))  # Final chunks before parent pooling
TOP_K_FINAL = int(os.getenv("TOP_K_FINAL", "10"))  # Final results

# RRF (Reciprocal Rank Fusion)
USE_RRF = os.getenv("USE_RRF", "true").lower() == "true"
RRF_K = int(os.getenv("RRF_K", "60"))

# MMR (Maximal Marginal Relevance)
USE_MMR = os.getenv("USE_MMR", "true").lower() == "true"
MMR_LAMBDA = float(os.getenv("MMR_LAMBDA", "0.5"))

# Query pooling
QUERY_CHUNK_SIZE = int(os.getenv("QUERY_CHUNK_SIZE", "500"))
QUERY_CHUNK_OVERLAP = int(os.getenv("QUERY_CHUNK_OVERLAP", "100"))
QUERY_MAX_CHUNKS = int(os.getenv("QUERY_MAX_CHUNKS", "6"))
MAX_QUERY_CHARS = int(os.getenv("MAX_QUERY_CHARS", "1200"))

# ============================================================================
# VALIDATION
# ============================================================================

def validate_config():
    """Validate configuration and return any errors"""
    errors = []
    
    if not PINECONE_API_KEY:
        errors.append("PINECONE_API_KEY not set. Get one from https://www.pinecone.io/")
    
    if VECTOR_DIMENSION not in [384, 768, 1024, 1536]:
        errors.append(f"VECTOR_DIMENSION {VECTOR_DIMENSION} may be incorrect. Common values: 384, 768, 1024, 1536")
    
    return errors

def get_pinecone_namespace(corpus_type: str) -> str:
    """Get Pinecone namespace for a corpus type"""
    mapping = {
        "resumes": PINECONE_NAMESPACE_RESUMES,
        "jobs": PINECONE_NAMESPACE_JOBS,
        "training": PINECONE_NAMESPACE_TRAINING,
        "assistance": PINECONE_NAMESPACE_ASSISTANCE,
    }
    return mapping.get(corpus_type, corpus_type)

def get_bm25_paths(corpus_type: str) -> tuple:
    """Get BM25 paths for a corpus type"""
    mapping = {
        "resumes": (BM25_RESUMES_CORPUS_PATH, BM25_RESUMES_DOCIDS_PATH, BM25_RESUMES_META_PATH),
        "jobs": (BM25_JOBS_CORPUS_PATH, BM25_JOBS_DOCIDS_PATH, BM25_JOBS_META_PATH),
        "training": (BM25_TRAINING_CORPUS_PATH, BM25_TRAINING_DOCIDS_PATH, BM25_TRAINING_META_PATH),
        "assistance": (BM25_ASSISTANCE_CORPUS_PATH, BM25_ASSISTANCE_DOCIDS_PATH, BM25_ASSISTANCE_META_PATH),
    }
    return mapping.get(corpus_type, (None, None, None))

def dump_config() -> dict:
    """Return all config as a dict for debugging"""
    return {
        "PINECONE_API_KEY": "***" + PINECONE_API_KEY[-4:] if PINECONE_API_KEY else "NOT SET",
        "PINECONE_ENVIRONMENT": PINECONE_ENVIRONMENT,
        "PINECONE_INDEX_NAME": PINECONE_INDEX_NAME,
        "PINECONE_NAMESPACE_RESUMES": PINECONE_NAMESPACE_RESUMES,
        "PINECONE_NAMESPACE_JOBS": PINECONE_NAMESPACE_JOBS,
        "PINECONE_NAMESPACE_TRAINING": PINECONE_NAMESPACE_TRAINING,
        "PINECONE_NAMESPACE_ASSISTANCE": PINECONE_NAMESPACE_ASSISTANCE,
        "VECTOR_DIMENSION": VECTOR_DIMENSION,
        "OLLAMA_HOST": OLLAMA_HOST,
        "EMBED_MODEL": EMBED_MODEL,
        "HYBRID_ALPHA": HYBRID_ALPHA,
        "K_VEC": K_VEC,
        "K_BM25": K_BM25,
        "USE_RRF": USE_RRF,
        "USE_MMR": USE_MMR,
        "TOP_K_FINAL": TOP_K_FINAL,
    }

