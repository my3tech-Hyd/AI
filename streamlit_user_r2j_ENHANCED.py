# streamlit_user_r2j_ENHANCED.py
# ----------------------------------------------------------------------
# Resume → Job Description HYBRID matcher (production-grade)
# - Uses UniversalHybridRetriever for robust vector + BM25 fusion
# - RRF, MMR, anti-collapse, deleted parent filtering
# - Query pooling for long resumes
# ----------------------------------------------------------------------

from __future__ import annotations

import sys
import io
from pathlib import Path
from typing import Dict, List

import streamlit as st
import pandas as pd
import chromadb
from pypdf import PdfReader
from docx import Document as Docx

# Import universal retriever
from universal_retriever import UniversalHybridRetriever

# JD corpus config
from config_jd import (
    CHROMA_DIR,
    CHROMA_COLLECTION_JDS,
    JDS_INDEX_DIR,
    BM25_JDS_CORPUS_PATH,
    BM25_JDS_META_PATH,
    BM25_JDS_DOCIDS_PATH,
    EMBED_MODEL,
    OLLAMA_HOST,
)

# Reuse helpers
from utils_jd import clean_text

# ---------------- Config ----------------
MAX_QUERY_CHARS = 4000
QUERY_CHUNK_SIZE = 700
QUERY_CHUNK_OVERLAP = 150
QUERY_MAX_CHUNKS = 8
TOP_K_VECTOR = 40
TOP_K_FINAL = 10

# ---------------- Streamlit UI config ----------------
st.set_page_config(
    page_title="Resume → JD Search (HYBRID)",
    page_icon="🔁",
    layout="wide",
)
st.title("🔁 Resume → JD Search (HYBRID)")
st.caption(
    "Upload a **resume** and find the most relevant **job descriptions** "
    "using production-grade hybrid retrieval (Vector + BM25 + RRF + MMR)."
)

# ---------------- Helpers ----------------

def read_text_from_bytes(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
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
        text = data.decode(errors="ignore")
    return clean_text(text)

# ---------------- Initialize Retriever ----------------
@st.cache_resource
def get_retriever():
    """Initialize universal hybrid retriever for job descriptions corpus"""
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    coll = client.get_or_create_collection(name=CHROMA_COLLECTION_JDS)
    
    config = {
        "K_VEC": TOP_K_VECTOR,
        "K_BM25": TOP_K_VECTOR * 2,
        "K_CHUNKS": 20,
        "HYBRID_ALPHA": 0.6,
        "USE_RRF": True,
        "RRF_K": 60,
        "USE_MMR": True,
        "MMR_LAMBDA": 0.5,
        "QUERY_CHUNK_SIZE": QUERY_CHUNK_SIZE,
        "QUERY_CHUNK_OVERLAP": QUERY_CHUNK_OVERLAP,
        "QUERY_MAX_CHUNKS": QUERY_MAX_CHUNKS,
        "MAX_QUERY_CHARS": MAX_QUERY_CHARS,
        "TOP_K_FINAL": TOP_K_FINAL,
    }
    
    return UniversalHybridRetriever(
        chroma_client=client,
        chroma_collection=coll,
        bm25_corpus_path=BM25_JDS_CORPUS_PATH,
        bm25_docids_path=BM25_JDS_DOCIDS_PATH,
        bm25_meta_path=BM25_JDS_META_PATH,
        embed_model=EMBED_MODEL,
        ollama_host=OLLAMA_HOST,
        corpus_type="jobs",
        config=config,
    )

# ---------------- Core search ----------------
def hybrid_search(resume_text: str, top_k: int = None) -> List[Dict]:
    """
    Resume text → hybrid retrieval (vector + BM25 + RRF + MMR)
    Returns ranked job descriptions with match percentages.
    """
    retriever = get_retriever()
    results = retriever.retrieve(resume_text, top_k=top_k or TOP_K_FINAL)
    return results

# ---------------- UI ----------------
st.markdown("### 📄 Upload Your Resume")
resume_file = st.file_uploader(
    "Select a resume file (PDF, DOCX, TXT, RTF, DOC)",
    type=["pdf", "docx", "txt", "rtf", "doc"],
    accept_multiple_files=False,
)

col1, col2 = st.columns([1, 3])
with col1:
    run_btn = st.button("🔍 Find matching jobs (HYBRID)", type="primary", use_container_width=True)

# Settings expander
with st.expander("⚙️ Settings & Info"):
    st.write(f"**Chroma dir (jobs):** `{CHROMA_DIR}`")
    st.write(f"**Collection:** `{CHROMA_COLLECTION_JDS}`")
    st.write(f"**Embeddings:** `{EMBED_MODEL}` @ `{OLLAMA_HOST}`")
    st.markdown(
        f"""
**Hybrid Retrieval Features:**
- ✅ Vector (cosine) + BM25 (keyword) fusion
- ✅ RRF (Reciprocal Rank Fusion)
- ✅ MMR (diversity)
- ✅ Anti-collapse re-scoring
- ✅ Query pooling: size `{QUERY_CHUNK_SIZE}`, overlap `{QUERY_CHUNK_OVERLAP}`
- ✅ Deleted parent filtering
- 📊 Retrieval: top `{TOP_K_VECTOR}` chunks → top `{TOP_K_FINAL}` jobs
"""
    )

# ---------------- Run search ----------------
if run_btn:
    try:
        if not resume_file:
            st.warning("⚠️ Please upload a resume first.")
        else:
            with st.spinner("📖 Reading resume..."):
                text = read_text_from_bytes(resume_file.read(), resume_file.name)
            
            if not text.strip():
                st.warning("⚠️ This resume seems empty after parsing/cleaning.")
            else:
                with st.spinner("🔍 Running hybrid retrieval (Vector + BM25 + RRF + MMR)..."):
                    results = hybrid_search(text)

                if not results:
                    st.info(
                        "No results. Make sure you've ingested job descriptions in the collection "
                        f"(`{CHROMA_DIR}` / `{CHROMA_COLLECTION_JDS}`)."
                    )
                else:
                    st.success(f"✅ Found {len(results)} matching job descriptions!")
                    
                    df = pd.DataFrame(results)
                    show_cols = [
                        "match_pct",
                        "title",
                        "company",
                        "location",
                        "job_type",
                        "required_skills",
                        "url",
                        "document_id",
                        "score",
                        "preview",
                    ]
                    
                    # Ensure all columns exist
                    for c in show_cols:
                        if c not in df.columns:
                            df[c] = None
                    
                    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

                    with st.expander("📥 Download results"):
                        csv = df[show_cols].to_csv(index=False).encode()
                        st.download_button(
                            "Download CSV",
                            data=csv,
                            file_name="resume_to_jd_results_hybrid.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

                    st.caption(
                        "**Match%** is relative to the best result in this set. "
                        "**Score** is the fused hybrid score (semantic + keyword + RRF)."
                    )

    except Exception as e:
        st.error(f"❌ Search failed: {e}")
        st.exception(e)

