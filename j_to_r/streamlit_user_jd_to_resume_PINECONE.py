# streamlit_user_jd_to_resume_PINECONE.py
# Job Description → Resume Search (Pinecone + BM25 Hybrid)
# ----------------------------------------------------------------------

import sys
from pathlib import Path
from typing import List, Dict

import streamlit as st
import pandas as pd

# Import Pinecone retriever
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pinecone_retriever import PineconeHybridRetriever
from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE_RESUMES,
    BM25_RESUMES_CORPUS_PATH,
    BM25_RESUMES_DOCIDS_PATH,
    BM25_RESUMES_META_PATH,
    EMBED_MODEL,
    OLLAMA_HOST,
    HYBRID_ALPHA,
    K_VEC,
    K_BM25,
    USE_RRF,
    USE_MMR,
    TOP_K_FINAL,
)

from utils_r import clean_text

# ========================= Page Config =========================
st.set_page_config(
    page_title="JD → Resume Search (Pinecone)",
    page_icon="🔍",
    layout="wide"
)
st.title("🔍 Job Description → Resume Search (Pinecone Hybrid)")
st.caption("Enter a JD and find the best matching resumes using hybrid retrieval (Pinecone + BM25)")

# ========================= Initialize Retriever =========================

@st.cache_resource
def get_retriever():
    """Initialize Pinecone hybrid retriever (cached)"""
    config = {
        'K_VEC': K_VEC,
        'K_BM25': K_BM25,
        'K_CHUNKS': 20,
        'HYBRID_ALPHA': HYBRID_ALPHA,
        'USE_RRF': USE_RRF,
        'RRF_K': 60,
        'USE_MMR': USE_MMR,
        'MMR_LAMBDA': 0.5,
        'QUERY_CHUNK_SIZE': 500,
        'QUERY_CHUNK_OVERLAP': 100,
        'QUERY_MAX_CHUNKS': 6,
        'MAX_QUERY_CHARS': 1200,
        'TOP_K_FINAL': TOP_K_FINAL,
    }
    
    retriever = PineconeHybridRetriever(
        pinecone_api_key=PINECONE_API_KEY,
        pinecone_index_name=PINECONE_INDEX_NAME,
        bm25_corpus_path=BM25_RESUMES_CORPUS_PATH,
        bm25_docids_path=BM25_RESUMES_DOCIDS_PATH,
        bm25_meta_path=BM25_RESUMES_META_PATH,
        embed_model=EMBED_MODEL,
        ollama_host=OLLAMA_HOST,
        corpus_type="resumes",
        namespace=PINECONE_NAMESPACE_RESUMES,
        config=config
    )
    
    # Get initial stats
    try:
        from pinecone.grpc import PineconeGRPC as Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        idx = pc.Index(PINECONE_INDEX_NAME)
        stats = idx.describe_index_stats()
        namespace_stats = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_RESUMES, {})
        vector_count = namespace_stats.get('vector_count', 0)
        st.session_state['pinecone_vector_count'] = vector_count
    except:
        st.session_state['pinecone_vector_count'] = 0
    
    return retriever

# ========================= UI =========================

# Info sidebar
with st.sidebar:
    st.header("📊 System Info")
    st.markdown(f"**Pinecone Index:** `{PINECONE_INDEX_NAME}`")
    st.markdown(f"**Namespace:** `{PINECONE_NAMESPACE_RESUMES}`")
    
    if 'pinecone_vector_count' in st.session_state:
        st.markdown(f"**Vectors:** `{st.session_state['pinecone_vector_count']}`")
    
    st.markdown("---")
    st.markdown("**Hybrid Retrieval:**")
    st.markdown(f"- Semantic weight: {HYBRID_ALPHA:.0%}")
    st.markdown(f"- Keyword weight: {(1-HYBRID_ALPHA):.0%}")
    st.markdown(f"- RRF: {'✅ Enabled' if USE_RRF else '❌ Disabled'}")
    st.markdown(f"- MMR: {'✅ Enabled' if USE_MMR else '❌ Disabled'}")
    
    st.markdown("---")
    st.caption("💡 **No more ChromaDB!**")
    st.caption("✅ Works with Python 3.13")
    st.caption("☁️ Cloud-hosted vectors")

# Job Description Form
st.subheader("📝 Enter Job Description")

jd_text = None

with st.form("jd_form"):
    col1, col2 = st.columns([3, 1])
    
    with col1:
        jd_title = st.text_input("Job Title", placeholder="e.g., Senior Python Developer")
        jd_company = st.text_input("Company (optional)", placeholder="e.g., TechCorp Inc.")
        jd_location = st.text_input("Location (optional)", placeholder="e.g., Hyderabad, India")
        
        jd_description = st.text_area(
            "Job Description",
            height=300,
            placeholder="""Paste the full job description here...

Example:
We are seeking a Senior Python Developer with 5+ years of experience...

Requirements:
- Strong Python programming skills
- Experience with Django/Flask
- Knowledge of SQL and NoSQL databases
- ...
"""
        )
        
        jd_skills = st.text_area(
            "Required Skills (one per line)",
            height=150,
            placeholder="Python\nDjango\nPostgreSQL\nDocker\nAWS"
        )
    
    with col2:
        st.markdown("### ⚙️ Options")
        top_k = st.number_input(
            "Results to show",
            min_value=1,
            max_value=50,
            value=TOP_K_FINAL,
            help="Number of top matches"
        )
    
    search_button = st.form_submit_button(
        "🔍 Find Matching Resumes",
        type="primary",
        use_container_width=True
    )

if search_button:
    # Compose JD text from form
    jd_parts = []
    
    if jd_title:
        jd_parts.append(f"Job Title: {jd_title}")
    if jd_company:
        jd_parts.append(f"Company: {jd_company}")
    if jd_location:
        jd_parts.append(f"Location: {jd_location}")
    if jd_description:
        jd_parts.append(f"\nJob Description:\n{jd_description}")
    if jd_skills:
        jd_parts.append(f"\nRequired Skills:\n{jd_skills}")
    
    jd_text = "\n\n".join(jd_parts)

# Results section (common for both input methods)
if jd_text:
    try:
        jd_text = clean_text(jd_text)
        
        if not jd_text or not jd_text.strip():
            st.error("❌ Job description is empty")
            st.stop()
        
        st.info(f"📊 Job description: {len(jd_text)} characters")
        
        # Search
        with st.spinner("🔍 Searching resumes (Pinecone + BM25 hybrid)..."):
            retriever = get_retriever()
            results = retriever.retrieve(jd_text, top_k=int(top_k))
        
        if not results:
            st.warning("⚠️ No matching resumes found. Make sure you've uploaded resumes first!")
            st.info("💡 Run the admin tool to upload resumes: `streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py`")
        else:
            st.success(f"✅ Found {len(results)} matching resumes!")
            
            # Display results
            st.markdown("---")
            st.subheader("📊 Top Matches")
            
            # Create DataFrame
            df = pd.DataFrame(results)
            
            # Select columns to display
            display_cols = [
                "match_pct",
                "candidate_name",
                "email",
                "phone",
                "score",
                "preview"
            ]
            
            # Ensure columns exist
            for col in display_cols:
                if col not in df.columns:
                    df[col] = None
            
            # Format columns
            df_display = df[display_cols].copy()
            df_display['match_pct'] = df_display['match_pct'].apply(lambda x: f"{x}%" if pd.notna(x) else "")
            df_display['score'] = df_display['score'].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "")
            
            # Rename for display
            df_display.columns = [
                "Match %",
                "Name",
                "Email",
                "Phone",
                "Score",
                "Preview"
            ]
            
            # Display table
            st.dataframe(
                df_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Match %": st.column_config.TextColumn(width="small"),
                    "Name": st.column_config.TextColumn(width="medium"),
                    "Email": st.column_config.TextColumn(width="medium"),
                    "Phone": st.column_config.TextColumn(width="small"),
                    "Score": st.column_config.TextColumn(width="small"),
                    "Preview": st.column_config.TextColumn(width="large"),
                }
            )
            
            # Download button
            with st.expander("📥 Download Results"):
                csv = df[display_cols].to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Download CSV",
                    data=csv,
                    file_name=f"jd_to_resume_results_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            
            # Stats
            st.markdown("---")
            st.caption(f"**Match %:** Relative to the best match in this result set")
            st.caption(f"**Score:** Fused hybrid score (semantic + keyword + RRF)")
            st.caption(f"**Retrieval:** Pinecone (vector) + BM25 (keyword) with {HYBRID_ALPHA:.0%}/{(1-HYBRID_ALPHA):.0%} weighting")
    
    except Exception as e:
        st.error(f"❌ Search failed: {e}")
        st.exception(e)
        st.info("💡 Make sure Ollama is running: `ollama serve`")

# Instructions
if not jd_text:
    st.markdown("---")
    st.info("""
    ### 📖 How to Use
    
    1. Fill in the **Job Description** form above
    2. Click **"Find Matching Resumes"**
    3. View results ranked by relevance
    
    ### 🎯 What's Different (vs ChromaDB)?
    
    - ✅ **No Python version issues** - Works with Python 3.13!
    - ☁️ **Cloud-hosted** - Vectors stored in Pinecone
    - 🚀 **Faster** - Optimized for performance
    - 💪 **More reliable** - No local database corruption
    
    ### 🔧 First Time?
    
    Upload resumes first:
    ```bash
    streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py
    ```
    """)

