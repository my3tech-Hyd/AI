# streamlit_user_resume_to_training_posts_PINECONE.py
# Resume → Training Posts Search (Pinecone + BM25 Hybrid)
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
    PINECONE_NAMESPACE_TRAINING,
    BM25_TRAINING_CORPUS_PATH,
    BM25_TRAINING_DOCIDS_PATH,
    BM25_TRAINING_META_PATH,
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
    page_title="Resume → Training Posts Search (Pinecone)",
    page_icon="📚",
    layout="wide"
)
st.title("📚 Resume → Training Posts Search (Pinecone Hybrid)")
st.caption("Enter resume details and find the best matching training programs using hybrid retrieval (Pinecone + BM25)")

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
        bm25_corpus_path=BM25_TRAINING_CORPUS_PATH,
        bm25_docids_path=BM25_TRAINING_DOCIDS_PATH,
        bm25_meta_path=BM25_TRAINING_META_PATH,
        embed_model=EMBED_MODEL,
        ollama_host=OLLAMA_HOST,
        corpus_type="training",
        namespace=PINECONE_NAMESPACE_TRAINING,
        config=config
    )
    
    # Get initial stats
    try:
        from pinecone.grpc import PineconeGRPC as Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        idx = pc.Index(PINECONE_INDEX_NAME)
        stats = idx.describe_index_stats()
        namespace_stats = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_TRAINING, {})
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
    st.markdown(f"**Namespace:** `{PINECONE_NAMESPACE_TRAINING}`")
    
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
    st.subheader("📝 Enter Resume/Candidate Details")
    
    candidate_name = st.text_input("Candidate Name", value="Rahul Sharma")
    current_role = st.text_input("Current Role", value="Junior Python Developer")
    experience_years = st.number_input("Years of Experience", min_value=0, max_value=50, value=2)
    
    skills = st.text_area(
        "Skills (comma-separated)",
        value="Python, JavaScript, HTML, CSS, Git",
        height=100,
    )
    
    career_goals = st.text_area(
        "Career Goals / Interests",
        value="I want to transition into full-stack web development and learn modern frameworks like React and Django. I'm also interested in cloud technologies like AWS.",
        height=150,
    )
    
    education = st.text_input("Education", value="B.Tech in Computer Science")
    
    results_to_show = st.slider("Number of results to show", 1, 50, 10)
    run_btn = st.form_submit_button("🔍 Find Matching Training Programs", type="primary")

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
        if experience_years:
            query_parts.append(f"Experience: {experience_years} years")
        if skills:
            query_parts.append(f"Skills: {skills}")
        if career_goals:
            query_parts.append(f"\nCareer Goals:\n{career_goals}")
        if education:
            query_parts.append(f"\nEducation: {education}")
        
        query_text = "\n\n".join(query_parts)
        
        st.markdown("---")
        st.subheader("🔍 Search Results")
        
        with st.spinner("🔄 Searching for matching training programs..."):
            try:
                results = retriever.retrieve(query_text, top_k=results_to_show)
                
                if not results:
                    st.warning("⚠️ No matching training programs found. Try adjusting your search criteria.")
                else:
                    st.success(f"✅ Found **{len(results)}** matching training programs!")
                    
                    # Display results
                    for idx, result in enumerate(results, 1):
                        with st.expander(f"**#{idx} – {result.get('center_name', 'Unknown')}** (Score: {result.get('score', 0)*100:.1f}%)"):
                            col1, col2 = st.columns([2, 1])
                            
                            with col1:
                                st.markdown(f"**Center Name:** {result.get('center_name', 'N/A')}")
                                
                                if result.get('courses_offered'):
                                    st.markdown(f"**Courses:** {result.get('courses_offered')}")
                                
                                if result.get('course_duration'):
                                    st.markdown(f"**Duration:** {result.get('course_duration')}")
                                
                                if result.get('certification'):
                                    st.markdown(f"**Certification:** {result.get('certification')}")
                                
                                if result.get('email'):
                                    st.markdown(f"**Email:** {result.get('email')}")
                                
                                if result.get('phone'):
                                    st.markdown(f"**Phone:** {result.get('phone')}")
                                
                                if result.get('address'):
                                    st.markdown(f"**Address:** {result.get('address')}")
                            
                            with col2:
                                st.metric("Match Score", f"{result.get('score', 0)*100:.1f}%")
                                
                                if result.get('semantic_score') is not None:
                                    st.metric("Semantic", f"{result.get('semantic_score')*100:.1f}%")
                                
                                if result.get('bm25_score') is not None:
                                    st.metric("Keyword", f"{result.get('bm25_score')*100:.1f}%")
                            
                            # Show text preview if available
                            if result.get('text'):
                                with st.container():
                                    st.markdown("**Program Description:**")
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
                        file_name="resume_to_training_results.csv",
                        mime="text/csv",
                    )
            
            except Exception as e:
                st.error(f"❌ Search failed: {e}")
                import traceback
                with st.expander("🐛 Debug Info"):
                    st.code(traceback.format_exc())

st.markdown("---")
st.caption("💡 **Tip:** This tool searches the 'training' namespace to find programs that align with the candidate's skills and career goals.")

