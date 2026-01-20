# streamlit_user_r2j_PINECONE.py
# Resume → Job Descriptions Search (Pinecone + BM25 Hybrid)
# ----------------------------------------------------------------------

import sys
from pathlib import Path
from typing import List, Dict

import streamlit as st
import pandas as pd

# Import Pinecone retriever
from pinecone_retriever import PineconeHybridRetriever
from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE_JOBS,
    BM25_JOBS_CORPUS_PATH,
    BM25_JOBS_DOCIDS_PATH,
    BM25_JOBS_META_PATH,
    EMBED_MODEL,
    OLLAMA_HOST,
    HYBRID_ALPHA,
    K_VEC,
    K_BM25,
    USE_RRF,
    USE_MMR,
    TOP_K_FINAL,
)

# ========================= Page Config =========================
st.set_page_config(
    page_title="Resume → Job Search (Pinecone)",
    page_icon="💼",
    layout="wide"
)
st.title("💼 Resume → Job Descriptions Search (Pinecone Hybrid)")
st.caption("Enter resume details and find the best matching job opportunities using hybrid retrieval (Pinecone + BM25)")

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
        bm25_corpus_path=BM25_JOBS_CORPUS_PATH,
        bm25_docids_path=BM25_JOBS_DOCIDS_PATH,
        bm25_meta_path=BM25_JOBS_META_PATH,
        embed_model=EMBED_MODEL,
        ollama_host=OLLAMA_HOST,
        corpus_type="jobs",
        namespace=PINECONE_NAMESPACE_JOBS,
        config=config
    )
    
    # Get initial stats
    try:
        from pinecone.grpc import PineconeGRPC as Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        idx = pc.Index(PINECONE_INDEX_NAME)
        stats = idx.describe_index_stats()
        namespace_stats = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_JOBS, {})
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
    st.markdown(f"**Namespace:** `{PINECONE_NAMESPACE_JOBS}`")
    
    if 'pinecone_vector_count' in st.session_state:
        st.markdown(f"**Vectors:** `{st.session_state['pinecone_vector_count']}`")
    
    st.markdown("---")
    st.header("⚙️ Search Settings")
    
    hybrid_alpha = st.slider(
        "Hybrid Balance (0=BM25, 1=Semantic)",
        0.0, 1.0, HYBRID_ALPHA, 0.05,
        help="Balance between keyword (BM25) and semantic (vector) search"
    )
    
    use_rrf = st.checkbox("Use RRF Fusion", value=USE_RRF,
                          help="Reciprocal Rank Fusion for better result blending")
    
    use_mmr = st.checkbox("Use MMR (diversity)", value=USE_MMR,
                          help="Maximal Marginal Relevance for diverse results")
    
    top_k = st.slider("Number of results", 5, 50, TOP_K_FINAL, 5)

# Initialize retriever
with st.spinner("🔄 Initializing retriever..."):
    retriever = get_retriever()
    
    # Override config with sidebar values
    retriever.config['HYBRID_ALPHA'] = hybrid_alpha
    retriever.config['USE_RRF'] = use_rrf
    retriever.config['USE_MMR'] = use_mmr
    retriever.config['TOP_K_FINAL'] = top_k

st.markdown("---")

# Resume Form Input
with st.form("resume_form_ui", clear_on_submit=False):
    st.subheader("📝 Enter Resume Details")
    
    candidate_name = st.text_input("Candidate Name", value="Amit Kumar")
    current_role = st.text_input("Current Role", value="Senior Python Developer")
    experience_years = st.number_input("Years of Experience", min_value=0, max_value=50, value=5)
    
    skills = st.text_area(
        "Skills (comma-separated)",
        value="Python, Django, Flask, PostgreSQL, Docker, AWS, React, REST APIs",
        height=100,
    )
    
    summary = st.text_area(
        "Professional Summary / Career Objective",
        value="Experienced Python developer with 5+ years of building scalable web applications. Proficient in Django and Flask frameworks, cloud deployment on AWS, and modern frontend technologies. Strong problem-solving skills and passion for clean code.",
        height=150,
    )
    
    education = st.text_input("Education", value="B.Tech in Computer Science")
    location_preference = st.text_input("Location Preference", value="Hyderabad, Bangalore, Remote")
    
    results_to_show = st.slider("Number of results to show", 1, 50, 10)
    run_btn = st.form_submit_button("🔍 Find Matching Jobs", type="primary")

if run_btn:
    if not candidate_name or not skills:
        st.error("❌ Candidate Name and Skills are required!")
    else:
        # Compose resume query
        query_parts = []
        if candidate_name:
            query_parts.append(f"Candidate: {candidate_name}")
        if current_role:
            query_parts.append(f"Current Role: {current_role}")
        if experience_years is not None:
            query_parts.append(f"Experience: {experience_years} years")
        if skills:
            query_parts.append(f"Skills: {skills}")
        if summary:
            query_parts.append(f"\nProfessional Summary:\n{summary}")
        if education:
            query_parts.append(f"\nEducation: {education}")
        if location_preference:
            query_parts.append(f"\nLocation Preference: {location_preference}")
        
        query_text = "\n\n".join(query_parts)
        
        st.markdown("---")
        st.subheader("🔍 Search Results")
        
        with st.spinner("🔄 Searching for matching jobs..."):
            try:
                results = retriever.retrieve(query_text, top_k=results_to_show)
                
                if not results:
                    st.warning("⚠️ No matching jobs found. Try adjusting your search criteria.")
                else:
                    st.success(f"✅ Found **{len(results)}** matching jobs!")
                    
                    # Display results
                    for idx, result in enumerate(results, 1):
                        with st.expander(f"**#{idx} – {result.get('title', 'Unknown')}** (Score: {result.get('score', 0)*100:.1f}%)"):
                            col1, col2 = st.columns([2, 1])
                            
                            with col1:
                                st.markdown(f"**Job Title:** {result.get('title', 'N/A')}")
                                
                                if result.get('company'):
                                    st.markdown(f"**Company:** {result.get('company')}")
                                
                                if result.get('location'):
                                    st.markdown(f"**Location:** {result.get('location')}")
                                
                                if result.get('required_skills'):
                                    st.markdown(f"**Required Skills:** {result.get('required_skills')}")
                                
                                if result.get('experience'):
                                    st.markdown(f"**Experience:** {result.get('experience')}")
                                
                                if result.get('salary'):
                                    st.markdown(f"**Salary:** {result.get('salary')}")
                                
                                if result.get('job_type'):
                                    st.markdown(f"**Job Type:** {result.get('job_type')}")
                                
                                if result.get('url'):
                                    st.markdown(f"**Apply:** [{result.get('url')}]({result.get('url')})")
                            
                            with col2:
                                st.metric("Match Score", f"{result.get('score', 0)*100:.1f}%")
                                
                                if result.get('semantic_score') is not None:
                                    st.metric("Semantic", f"{result.get('semantic_score')*100:.1f}%")
                                
                                if result.get('bm25_score') is not None:
                                    st.metric("Keyword", f"{result.get('bm25_score')*100:.1f}%")
                            
                            # Show text preview if available
                            if result.get('text'):
                                with st.container():
                                    st.markdown("**Job Description Preview:**")
                                    st.text_area(
                                        "Preview",
                                        result.get('text', '')[:500] + "...",
                                        height=100,
                                        key=f"preview_{idx}",
                                        disabled=True
                                    )
                    
                    # Download as CSV
                    df = pd.DataFrame(results)
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download Results as CSV",
                        data=csv,
                        file_name="resume_to_jobs_results.csv",
                        mime="text/csv",
                    )
            
            except Exception as e:
                st.error(f"❌ Search failed: {e}")
                import traceback
                with st.expander("🐛 Debug Info"):
                    st.code(traceback.format_exc())

st.markdown("---")
st.caption("💡 **Tip:** This tool searches the 'jobs' namespace to find job opportunities that match the candidate's skills and experience.")

