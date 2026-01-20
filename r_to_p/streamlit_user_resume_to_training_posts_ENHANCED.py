# streamlit_user_resume_to_training_posts_ENHANCED.py
# ----------------------------------------------------------------------
# Resume → Training Postings HYBRID matcher (production-grade)
# - Uses UniversalHybridRetriever for robust vector + BM25 fusion
# - RRF, MMR, anti-collapse, deleted parent filtering
# - Query pooling for long resumes
# NOTE: Requires BM25 indexes for training posts to be created by admin ingestion
# ----------------------------------------------------------------------

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import streamlit as st
import pandas as pd
import chromadb

# Import universal retriever
sys.path.append(str(Path(__file__).parent.parent))
from universal_retriever import UniversalHybridRetriever

from config_resumes_to_training import (
    CHROMA_DIR_TRAIN_POSTS,
    CHROMA_COLLECTION_TRAIN_POSTS,
    OLLAMA_HOST,
    EMBED_MODEL,
    R2T_TOP_K_VECTOR,
    R2T_TOP_K_FINAL,
    R2T_QUERY_CHUNK_SIZE,
    R2T_QUERY_CHUNK_OVERLAP,
    R2T_QUERY_MAX_CHUNKS,
    R2T_MAX_QUERY_CHARS,
    dump_config,
)

from utils_resumes_to_training import (
    clean_text,
    read_text_from_bytes,
)

# BM25 paths for training posts (to be created by admin ingestion)
TRAINING_INDEX_DIR = Path(__file__).parent / "indexes" / "training_posts"
BM25_TRAINING_CORPUS_PATH = str(TRAINING_INDEX_DIR / "bm25_corpus.pkl")
BM25_TRAINING_DOCIDS_PATH = str(TRAINING_INDEX_DIR / "bm25_doc_ids.pkl")
BM25_TRAINING_META_PATH = str(TRAINING_INDEX_DIR / "bm25_meta.pkl")

# Ensure index dir exists
TRAINING_INDEX_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Streamlit UI config ----------------
st.set_page_config(
    page_title="Resume → Training Posts (HYBRID)",
    page_icon="🧑‍🎓",
    layout="wide",
)
st.title("🧑‍🎓 Resume → Training Posts (HYBRID)")
st.caption(
    "Upload a **resume** and find the most relevant **training/skill postings** "
    "using production-grade hybrid retrieval (Vector + BM25 + RRF + MMR)."
)

# ---------------- Initialize Retriever ----------------
@st.cache_resource
def get_retriever():
    """Initialize universal hybrid retriever for training posts corpus"""
    client = chromadb.PersistentClient(path=CHROMA_DIR_TRAIN_POSTS)
    coll = client.get_or_create_collection(name=CHROMA_COLLECTION_TRAIN_POSTS)
    
    config = {
        "K_VEC": R2T_TOP_K_VECTOR,
        "K_BM25": R2T_TOP_K_VECTOR * 2,
        "K_CHUNKS": 20,
        "HYBRID_ALPHA": 0.6,
        "USE_RRF": True,
        "RRF_K": 60,
        "USE_MMR": True,
        "MMR_LAMBDA": 0.5,
        "QUERY_CHUNK_SIZE": R2T_QUERY_CHUNK_SIZE,
        "QUERY_CHUNK_OVERLAP": R2T_QUERY_CHUNK_OVERLAP,
        "QUERY_MAX_CHUNKS": R2T_QUERY_MAX_CHUNKS,
        "MAX_QUERY_CHARS": R2T_MAX_QUERY_CHARS,
        "TOP_K_FINAL": R2T_TOP_K_FINAL,
    }
    
    return UniversalHybridRetriever(
        chroma_client=client,
        chroma_collection=coll,
        bm25_corpus_path=BM25_TRAINING_CORPUS_PATH,
        bm25_docids_path=BM25_TRAINING_DOCIDS_PATH,
        bm25_meta_path=BM25_TRAINING_META_PATH,
        embed_model=EMBED_MODEL,
        ollama_host=OLLAMA_HOST,
        corpus_type="training",
        config=config,
    )

# ---------------- Core search ----------------
def hybrid_search(resume_text: str, top_k: int = None) -> List[Dict]:
    """
    Resume text → hybrid retrieval (vector + BM25 + RRF + MMR)
    Returns ranked training posts with match percentages.
    """
    retriever = get_retriever()
    results = retriever.retrieve(resume_text, top_k=top_k or R2T_TOP_K_FINAL)
    return results

# ---------------- UI ----------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("📄 Upload Resume")
    resume_file = st.file_uploader(
        "Upload a resume (PDF/DOCX/TXT/RTF/DOC)",
        type=["pdf", "docx", "txt", "rtf", "doc"],
        accept_multiple_files=False,
    )
    run_btn = st.button("🔍 Find matching training postings (HYBRID)", type="primary", use_container_width=True)

with right:
    st.subheader("⚙️ Settings & Info")
    cfg = dump_config()
    st.write(f"**Chroma dir (training posts):** `{cfg['CHROMA_DIR_TRAIN_POSTS']}`")
    st.write(f"**Collection:** `{cfg['CHROMA_COLLECTION_TRAIN_POSTS']}`")
    st.write(f"**Embeddings:** `{cfg['EMBED_MODEL']}` @ `{cfg['OLLAMA_HOST']}`")
    st.markdown(
        f"""
**Hybrid Retrieval Features:**
- ✅ Vector (cosine) + BM25 (keyword) fusion
- ✅ RRF (Reciprocal Rank Fusion)
- ✅ MMR (diversity)
- ✅ Anti-collapse re-scoring
- ✅ Query pooling: size `{cfg['R2T_QUERY_CHUNK_SIZE']}`, overlap `{cfg['R2T_QUERY_CHUNK_OVERLAP']}`
- ✅ Deleted parent filtering
- 📊 Retrieval: top `{cfg['R2T_TOP_K_VECTOR']}` chunks → top `{cfg['R2T_TOP_K_FINAL']}` posts
"""
    )

# ---------------- Run search ----------------
if run_btn:
    try:
        if not resume_file:
            st.warning("Please upload a resume first.")
        else:
            text = read_text_from_bytes(resume_file.read(), resume_file.name)
            if not text.strip():
                st.warning("This resume seems empty after parsing/cleaning.")
            else:
                with st.spinner("🔍 Running hybrid retrieval (Vector + BM25 + RRF + MMR)..."):
                    results = hybrid_search(text)

                if not results:
                    st.info(
                        "No results. Make sure you've ingested training postings in the dedicated collection "
                        f"(`{CHROMA_DIR_TRAIN_POSTS}` / `{CHROMA_COLLECTION_TRAIN_POSTS}`)."
                    )
                else:
                    st.success(f"✅ Found {len(results)} matching training postings!")
                    
                    df = pd.DataFrame(results)
                    show_cols = [
                        "match_pct",
                        "center_name",
                        "courses_offered",
                        "course_duration",
                        "certification",
                        "email",
                        "phone",
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
                            file_name="resume_to_training_posts_results_hybrid.csv",
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

