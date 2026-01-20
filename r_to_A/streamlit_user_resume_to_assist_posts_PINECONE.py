# streamlit_user_resume_to_assist_posts_PINECONE.py
# Resume → Assistance Posts Search (Pinecone + BM25 Hybrid)
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
    PINECONE_NAMESPACE_ASSISTANCE,
    BM25_ASSISTANCE_CORPUS_PATH,
    BM25_ASSISTANCE_DOCIDS_PATH,
    BM25_ASSISTANCE_META_PATH,
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
    page_title="Resume → Assistance Posts Search (Pinecone)",
    page_icon="🤝",
    layout="wide"
)
st.title("🤝 Resume → Assistance Posts Search (Pinecone Hybrid)")
st.caption("Enter resume details and find the best matching assistance centers using hybrid retrieval (Pinecone + BM25)")

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
        bm25_corpus_path=BM25_ASSISTANCE_CORPUS_PATH,
        bm25_docids_path=BM25_ASSISTANCE_DOCIDS_PATH,
        bm25_meta_path=BM25_ASSISTANCE_META_PATH,
        embed_model=EMBED_MODEL,
        ollama_host=OLLAMA_HOST,
        corpus_type="assistance",
        namespace=PINECONE_NAMESPACE_ASSISTANCE,
        config=config
    )
    
    # Get initial stats
    try:
        from pinecone.grpc import PineconeGRPC as Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        idx = pc.Index(PINECONE_INDEX_NAME)
        stats = idx.describe_index_stats()
        namespace_stats = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_ASSISTANCE, {})
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
    st.markdown(f"**Namespace:** `{PINECONE_NAMESPACE_ASSISTANCE}`")
    
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
    
    candidate_name = st.text_input("Candidate Name", value="Priya Patel")
    current_situation = st.text_input("Current Situation", value="Recent graduate looking for first job")
    experience_years = st.number_input("Years of Experience", min_value=0, max_value=50, value=0)
    
    skills = st.text_area(
        "Skills (comma-separated)",
        value="Java, SQL, Problem Solving",
        height=100,
    )
    
    assistance_needed = st.text_area(
        "Assistance Needed / Career Support Required",
        value="I need help with resume building, interview preparation, and job search strategies. I'm a fresher and looking for guidance to land my first IT job.",
        height=150,
    )
    
    education = st.text_input("Education", value="B.Sc in Computer Science")
    
    results_to_show = st.slider("Number of results to show", 1, 50, 10)
    run_btn = st.form_submit_button("🔍 Find Matching Assistance Centers", type="primary")

if run_btn:
    if not candidate_name or not assistance_needed:
        st.error("❌ Candidate Name and Assistance Needed are required!")
    else:
        # Compose resume query
        query_parts = []
        if candidate_name:
            query_parts.append(f"Candidate: {candidate_name}")
        if current_situation:
            query_parts.append(f"Situation: {current_situation}")
        if experience_years is not None:
            query_parts.append(f"Experience: {experience_years} years")
        if skills:
            query_parts.append(f"Skills: {skills}")
        if assistance_needed:
            query_parts.append(f"\nAssistance Needed:\n{assistance_needed}")
        if education:
            query_parts.append(f"\nEducation: {education}")
        
        query_text = "\n\n".join(query_parts)
        
        st.markdown("---")
        st.subheader("🔍 Search Results")
        
        with st.spinner("🔄 Searching for matching assistance centers..."):
            try:
                results = retriever.retrieve(query_text, top_k=results_to_show)
                
                if not results:
                    st.warning("⚠️ No matching assistance centers found. Try adjusting your search criteria.")
                else:
                    st.success(f"✅ Found **{len(results)}** matching assistance centers!")
                    
                    # Display results
                    for idx, result in enumerate(results, 1):
                        with st.expander(f"**#{idx} – {result.get('center_name', 'Unknown')}** (Score: {result.get('score', 0)*100:.1f}%)"):
                            col1, col2 = st.columns([2, 1])
                            
                            with col1:
                                st.markdown(f"**Center Name:** {result.get('center_name', 'N/A')}")
                                
                                if result.get('services'):
                                    st.markdown(f"**Services:** {result.get('services')}")
                                
                                if result.get('operating_hours'):
                                    st.markdown(f"**Hours:** {result.get('operating_hours')}")
                                
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
                                    st.markdown("**Center Description:**")
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
                        file_name="resume_to_assistance_results.csv",
                        mime="text/csv",
                    )
            
            except Exception as e:
                st.error(f"❌ Search failed: {e}")
                import traceback
                with st.expander("🐛 Debug Info"):
                    st.code(traceback.format_exc())

st.markdown("---")
st.caption("💡 **Tip:** This tool searches the 'assistance' namespace to find centers that can help with the candidate's specific career needs.")

