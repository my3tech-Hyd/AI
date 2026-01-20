# streamlit_user_assist_to_resumes_ENHANCED.py
# ----------------------------------------------------------------------
# Assistance Center Form → Resume HYBRID matcher (production-grade)
# - Uses UniversalHybridRetriever for robust vector + BM25 fusion
# - RRF, MMR, anti-collapse, contact recovery, deleted parent filtering
# - Query pooling for long assistance descriptions
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

from config_assist_to_resumes import (
    CHROMA_DIR_RESUMES,
    CHROMA_COLLECTION_RESUMES,
    OLLAMA_HOST,
    EMBED_MODEL,
    A2R_TOP_K_VECTOR,
    A2R_TOP_K_FINAL,
    A2R_QUERY_CHUNK_SIZE,
    A2R_QUERY_CHUNK_OVERLAP,
    A2R_QUERY_MAX_CHUNKS,
    A2R_MAX_QUERY_CHARS,
    dump_config,
)

# Import BM25 paths from j_to_r config (resumes corpus)
sys.path.append(str(Path(__file__).parent.parent / "j_to_r"))
from config_jds_resumes import (
    BM25_RESUMES_CORPUS_PATH,
    BM25_RESUMES_DOCIDS_PATH,
    BM25_RESUMES_META_PATH,
)

from utils_assist_to_resumes import (
    clean_text,
    to_csv_list,
    compose_text_from_assist_form,
)

# ---------------- Streamlit UI config ----------------
st.set_page_config(
    page_title="Assistance → Resume Search (HYBRID)",
    page_icon="🧭",
    layout="wide",
)
st.title("🧭 Assistance → Resume Search (HYBRID)")
st.caption(
    "Fill an **Assistance Center** posting form and find the most relevant **resumes** "
    "using production-grade hybrid retrieval (Vector + BM25 + RRF + MMR)."
)

# ---------------- Initialize Retriever ----------------
@st.cache_resource
def get_retriever():
    """Initialize universal hybrid retriever for resumes corpus"""
    client = chromadb.PersistentClient(path=CHROMA_DIR_RESUMES)
    coll = client.get_or_create_collection(name=CHROMA_COLLECTION_RESUMES)
    
    config = {
        "K_VEC": A2R_TOP_K_VECTOR,
        "K_BM25": A2R_TOP_K_VECTOR * 2,
        "K_CHUNKS": 20,
        "HYBRID_ALPHA": 0.6,
        "USE_RRF": True,
        "RRF_K": 60,
        "USE_MMR": True,
        "MMR_LAMBDA": 0.5,
        "QUERY_CHUNK_SIZE": A2R_QUERY_CHUNK_SIZE,
        "QUERY_CHUNK_OVERLAP": A2R_QUERY_CHUNK_OVERLAP,
        "QUERY_MAX_CHUNKS": A2R_QUERY_MAX_CHUNKS,
        "MAX_QUERY_CHARS": A2R_MAX_QUERY_CHARS,
        "TOP_K_FINAL": A2R_TOP_K_FINAL,
    }
    
    return UniversalHybridRetriever(
        chroma_client=client,
        chroma_collection=coll,
        bm25_corpus_path=BM25_RESUMES_CORPUS_PATH,
        bm25_docids_path=BM25_RESUMES_DOCIDS_PATH,
        bm25_meta_path=BM25_RESUMES_META_PATH,
        embed_model=EMBED_MODEL,
        ollama_host=OLLAMA_HOST,
        corpus_type="resumes",
        config=config,
    )

# ---------------- Core search ----------------
def hybrid_search(assist_text: str, top_k: int = None) -> List[Dict]:
    """
    Assistance form text → hybrid retrieval (vector + BM25 + RRF + MMR)
    Returns ranked resumes with match percentages.
    """
    retriever = get_retriever()
    results = retriever.retrieve(assist_text, top_k=top_k or A2R_TOP_K_FINAL)
    return results

# ---------------- UI ----------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("🏢 Assistance Center Posting (Form)")
    with st.form("assist_form_ui", clear_on_submit=False):
        center_name = st.text_input("Center Name", value="CareerPath Assistance Center")
        capacity = st.number_input("Capacity", value=80, step=5)
        address = st.text_input("Address", value="2nd Floor, Orion Towers, Ameerpet, Hyderabad, Telangana, 500016")
        phone = st.text_input("Phone", value="+91-9123456780")
        email = st.text_input("Email", value="support@careerpathcenter.com")
        operating_hours = st.text_input("Operating Hours", value="Mon–Fri 9:00 AM – 6:00 PM")
        services_text = st.text_input(
            "Services (comma-separated)",
            value="Career Counseling, Resume Writing, Interview Preparation, Job Placement Support, Personality Development",
        )
        description = st.text_area(
            "Description",
            value=(
                "CareerPath Assistance Center helps job seekers achieve their career goals through personalized guidance, "
                "expert resume building, and intensive interview preparation. With strong industry connections, we provide "
                "end-to-end job placement support for fresh graduates and experienced professionals."
            ),
            height=160,
        )
        run_btn = st.form_submit_button("🔍 Find matching resumes (HYBRID)", type="primary")

with right:
    st.subheader("⚙️ Settings & Info")
    cfg = dump_config()
    st.write(f"**Chroma dir (resumes):** `{cfg['CHROMA_DIR_RESUMES']}`")
    st.write(f"**Collection:** `{cfg['CHROMA_COLLECTION_RESUMES']}`")
    st.write(f"**Embeddings:** `{cfg['EMBED_MODEL']}` @ `{cfg['OLLAMA_HOST']}`")
    st.markdown(
        f"""
**Hybrid Retrieval Features:**
- ✅ Vector (cosine) + BM25 (keyword) fusion
- ✅ RRF (Reciprocal Rank Fusion)
- ✅ MMR (diversity)
- ✅ Anti-collapse re-scoring
- ✅ Query pooling: size `{cfg['A2R_QUERY_CHUNK_SIZE']}`, overlap `{cfg['A2R_QUERY_CHUNK_OVERLAP']}`
- ✅ Deleted parent filtering
- 📊 Retrieval: top `{cfg['A2R_TOP_K_VECTOR']}` chunks → top `{cfg['A2R_TOP_K_FINAL']}` resumes
"""
    )

# ---------------- Run search ----------------
if run_btn:
    try:
        services_list = to_csv_list(services_text)
        composed_text = compose_text_from_assist_form(
            center_name=center_name,
            capacity=int(capacity),
            address=address,
            phone=phone,
            email=email,
            operating_hours=operating_hours,
            services=services_list,
            description=description,
        )
        text = clean_text(composed_text)

        if not text.strip():
            st.warning("This form seems empty after parsing/cleaning.")
        else:
            with st.spinner("🔍 Running hybrid retrieval (Vector + BM25 + RRF + MMR)..."):
                results = hybrid_search(text)

            if not results:
                st.info("No results. Make sure you've ingested resumes in the resume collection.")
            else:
                st.success(f"✅ Found {len(results)} matching resumes!")
                
                df = pd.DataFrame(results)
                show_cols = [
                    "match_pct",
                    "candidate_name",
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
                        file_name="assist_to_resumes_results_hybrid.csv",
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

