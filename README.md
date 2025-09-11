ResumeFinder

Local-first, hybrid RAG system for JD→Resume matching that fuses semantic vector search (ChromaDB) with keyword scoring (BM25). Runs entirely on your machine using Ollama for both embeddings and chat, with Streamlit UIs for ingestion and retrieval.

Overview

ResumeFinder ingests resumes, chunks and embeds them with nomic-embed-text, stores vectors in ChromaDB (DuckDB + Parquet persistence), and builds a BM25 index over tokenized chunks. Recruiters can search via a dedicated JD→Resume UI or a conversational chat UI; both return grounded, evidence-based matches with downloadable originals.

Architecture

Admin ingestion flow: upload → dedupe by SHA-256 → text extraction → chunking with overlap → embeddings via Ollama → ChromaDB upserts → BM25 artifact build.

Recruiter retrieval flow: JD/query pooling → Chroma vector search ∪ BM25 top-K → late fusion (RRF or α-fusion) → parent-resume pooling (Top-3 mean) → gating → ranked Top-N with evidence and downloads.

Separation of concerns: Admin app writes; user/chat apps are read-only to the vector store and filesystem.

Technical stack

Python 3.11 on Windows 11, Streamlit apps

Vector DB: ChromaDB (DuckDB + Parquet persistence)

Local model server: Ollama (embeddings + chat)

Embedding model: nomic-embed-text

Chat LLM: llama3.2:3b (via Ollama) or OpenAI (configurable in chat app)

Keyword retriever: BM25 (rank_bm25)

Key libs: streamlit, chromadb, rank_bm25, langchain_community, pandas, requests, pypdf, python-docx

Apps

Admin (streamlit_admin.py): file ingestion, dedupe, chunking, embeddings, Chroma upserts, BM25 index build, inventory export.

JD→Resume UI (streamlit_user.py): pooled JD embedding, union of Chroma@K and BM25@K, optional RRF/MMR, parent pooling, Top-N with previews and downloads.

Chat UI (streamlit_chat.py): memory-aware chat over the same hybrid retriever, strict gating, grounded rationales, persistent chat store with pin/rename/delete.

Storage layout

Resume originals: RESUMES_STORE_DIR/

Vector store persistence: CHROMA_DIR/ (DuckDB + Parquet)

BM25 artifacts: BM25_CORPUS_PATH, BM25_DOCIDS_PATH, BM25_META_PATH

Chat history: chat_store/chat_<uuid>.json

Key configuration

Set via environment variables and config.py:

Core paths: CHROMA_DIR, CHROMA_COLLECTION, RESUMES_RAW_DIR, RESUMES_STORE_DIR, INDEX_DIR

BM25 artifacts/locale: BM25_CORPUS_PATH, BM25_META_PATH, BM25_DOCIDS_PATH, BM25_LANGUAGE

Models/backends: EMBED_MODEL, OLLAMA_HOST, optional CHAT_MODEL

Ranking knobs: TOP_K_VECTOR, TOP_K_FINAL, HYBRID_ALPHA

Chunking: CHUNK_SIZE, CHUNK_OVERLAP (auto-guarded so overlap < size)

Allowed file types: ALLOWED_EXTS

Optional LangSmith tracing: LANGSMITH_*

Gating and additional retrieval toggles are exposed in streamlit_chat.py (e.g., IRRELEVANCE_GATING_ON, MIN_SEM_RAW_SIM, STRICT_KW_GATING, MIN_STRICT_HITS, coverage bonus).

Data ingestion

Supported formats: PDF, DOCX, TXT, RTF

Text readers and utilities: parsing, cleaning, tokenization, email/phone extraction, name guessing, file hashing, staging to the store.

BM25 build script: build_bm25.py can rebuild the tokenized corpus and meta from the resume store.

Retrieval

Query chunking and pooled embedding for long JDs (length-weighted mean of chunk embeddings).

Vector side: Chroma cosine distance → similarity → normalization.

Keyword side: BM25 over tokenized chunks → normalization.

Late fusion: α-fusion or RRF-weighted fusion; optional MMR for diversity (user app).

Parent pooling: keep best snippet and compute Top-3 mean per resume; compute relative Match%.

Strict gating: semantic/lexical/BM25 thresholds and high-signal term hits before showing results (chat app).

How to run

Install Python 3.11 and dependencies (pip install the libs listed above).

Install and start Ollama; pull models:

ollama serve
ollama pull nomic-embed-text
ollama pull llama3.2:3b


Create required directories (RESUMES_STORE_DIR, CHROMA_DIR, INDEX_DIR, chat_store).

Start the apps:

Chat UI: streamlit run streamlit_chat.py

JD→Resume UI: streamlit run streamlit_user.py
Use the sidebar link inside the chat app to open the JD UI if they run in the same process.

Testing and quality

A focused test plan covers parsing, chunking, embeddings, retrieval (union + fusion + pooling), persistence, LLM grounding, and UI correctness. Suggested metrics: Precision@5, Recall@10, MRR@10, gate FPR/FNR, coverage score, strict-hits compliance, fusion sensitivity, Match-% calibration, rewrite delta, and latency breakdowns. Acceptance targets and component→metric mapping are provided to guide regression checks and LangSmith runs.

Troubleshooting

Empty or flat scores: verify BM25 artifacts exist and align with chunk IDs; the system falls back to semantic-only if BM25 is absent.

Embedding failures: ensure Ollama is running and the EMBED_MODEL is pulled; the code can fall back to langchain_ollama where available.

Missing downloads: confirm original file paths under RESUMES_STORE_DIR/.

Project structure (key files)

config.py – central paths, chunking and ranking knobs, env handling.

utils_text.py – readers, cleaners, tokenization, PII extraction, hashing/staging.

build_bm25.py – rebuild BM25 corpus and meta from stored resumes.

streamlit_user.py – JD→Resume hybrid search UI.

streamlit_chat.py – conversational hybrid search with persistence and gating.

Docs – Technical Stack, Architecture, Product Demo & Playbooks, and Test Components/Metrics.

License

Internal use for My3Tech demo and evaluation purposes unless otherwise specified.
