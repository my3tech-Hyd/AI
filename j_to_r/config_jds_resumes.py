# config_jds_resumes.py
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Load env without overriding any existing values
load_dotenv(find_dotenv(), override=False)

# Chroma directory and collection for resumes (isolated project)
CHROMA_DIR_RESUMES = os.getenv("CHROMA_DIR_RESUMES", "./chroma_resumes")
CHROMA_COLLECTION_RESUMES = os.getenv("CHROMA_COLLECTION_RESUMES", "resumes")

# Resume storage and indexes (paths will be created if missing)
RESUMES_STORE_DIR = os.getenv("RESUMES_STORE_DIR", "./resumes_store")
INDEX_DIR = os.getenv("INDEX_DIR", "./indexes")
RESUMES_INDEX_DIR = os.getenv("RESUMES_INDEX_DIR", str(Path(INDEX_DIR) / "resumes"))

BM25_RESUMES_CORPUS_PATH = str(Path(RESUMES_INDEX_DIR) / "bm25_corpus.pkl")
BM25_RESUMES_META_PATH   = str(Path(RESUMES_INDEX_DIR) / "bm25_meta.pkl")
BM25_RESUMES_DOCIDS_PATH = str(Path(RESUMES_INDEX_DIR) / "bm25_doc_ids.pkl")

# Ollama for embeddings
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Optional tuning for query pooling
R2J_QUERY_CHUNK_SIZE = int(os.getenv("R2J_QUERY_CHUNK_SIZE", "500"))
R2J_QUERY_CHUNK_OVERLAP = int(os.getenv("R2J_QUERY_CHUNK_OVERLAP", "100"))
R2J_QUERY_MAX_CHUNKS = int(os.getenv("R2J_QUERY_MAX_CHUNKS", "6"))
R2J_TOP_K_VECTOR = int(os.getenv("R2J_TOP_K_VECTOR", "40"))
R2J_TOP_K_FINAL = int(os.getenv("R2J_TOP_K_FINAL", "10"))
R2J_HYBRID_ALPHA = float(os.getenv("R2J_HYBRID_ALPHA", "0.6"))

# Ensure dirs exist (isolated project for resumes)
for _d in (CHROMA_DIR_RESUMES, RESUMES_STORE_DIR, RESUMES_INDEX_DIR):
    Path(_d).mkdir(parents=True, exist_ok=True)

# Optional LangSmith tracing for this project
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT_RESUMES = os.getenv("LANGSMITH_PROJECT_RESUMES", "resumes-index")
