# streamlit_user_training_to_resumes_PINECONE.py
# Training Posting → Resume Search (Pinecone + BM25 Hybrid)
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

# ========================= Page Config =========================
st.set_page_config(
    page_title="Training → Resume Search (Pinecone)",
    page_icon="🎓",
    layout="wide"
)
st.title("🎓 Training Posting → Resume Search (Pinecone Hybrid)")
st.caption("Enter training center details and find the best matching candidate resumes using hybrid retrieval (Pinecone + BM25)")

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
    
    # Debug: Check BM25 status
    bm25_loaded = getattr(retriever.bm25, "corpus_size", 0) > 0
    if bm25_loaded:
        st.sidebar.success(f"✅ BM25 loaded ({retriever.bm25.corpus_size} documents)")
    else:
        st.sidebar.warning("⚠️ BM25 not loaded - only semantic search active!")
        # Show why it's not loaded
        with st.sidebar.expander("🐛 BM25 Debug Info"):
            import os
            st.caption(f"Corpus path: {BM25_RESUMES_CORPUS_PATH}")
            st.caption(f"Exists: {os.path.exists(BM25_RESUMES_CORPUS_PATH)}")
            st.caption(f"DocIDs path: {BM25_RESUMES_DOCIDS_PATH}")
            st.caption(f"Exists: {os.path.exists(BM25_RESUMES_DOCIDS_PATH)}")
            if os.path.exists(BM25_RESUMES_DOCIDS_PATH):
                import pickle
                with open(BM25_RESUMES_DOCIDS_PATH, "rb") as f:
                    doc_ids = pickle.load(f)
                st.caption(f"Docs in file: {len(doc_ids)}")
            st.caption("**Try: Press 'C' to clear cache!**")

st.markdown("---")

# Training Form Input
with st.form("training_form_ui", clear_on_submit=False):
    st.subheader("📝 Enter Training Center Details")
    
    center_name = st.text_input("Training Center Name", value="TechBridge Learning Hub")
    courses = st.text_input("Courses Offered", value="Web Development, Data Analytics, Cloud Computing")
    duration = st.text_input("Course Duration", value="6 months")
    certification = st.text_input("Certification", value="Industry Certified by NASSCOM")
    
    description = st.text_area(
        "Training Center Description",
        value="TechBridge Learning Hub is a premier IT training institute focused on equipping students with hands-on skills in emerging technologies including web development, data science, and cloud computing. Our programs include live projects, industry mentors, and 100% placement assistance.",
        height=200,
    )
    
    results_to_show = st.slider("Number of results to show", 1, 50, 10)
    run_btn = st.form_submit_button("🔍 Find Matching Resumes", type="primary")

if run_btn:
    if not center_name or not courses:
        st.error("❌ Training Center Name and Courses are required!")
    else:
        # Compose training query
        query_parts = []
        if center_name:
            query_parts.append(f"Training Center: {center_name}")
        if courses:
            query_parts.append(f"Courses: {courses}")
        if duration:
            query_parts.append(f"Duration: {duration}")
        if certification:
            query_parts.append(f"Certification: {certification}")
        if description:
            query_parts.append(f"\nDescription:\n{description}")
        
        query_text = "\n\n".join(query_parts)
        
        st.markdown("---")
        st.subheader("🔍 Search Results")
        
        # Debug: Show query being used
        with st.expander("🔍 Query Being Searched (Debug)"):
            st.text(query_text)
            st.caption(f"Query length: {len(query_text)} characters")
            
            # Test embedding to verify it's working
            try:
                import numpy as np
                test_vec = retriever.embed_query_pooled(query_text)
                st.caption(f"Embedding generated: {len(test_vec)} dims, first 5 values: {test_vec[:5]}")
                st.caption(f"Embedding sum (fingerprint): {np.sum(test_vec):.4f}")
            except Exception as e:
                st.error(f"Embedding failed: {e}")
        
        with st.spinner("🔄 Searching for matching resumes..."):
            try:
                results = retriever.retrieve(query_text, top_k=results_to_show)
                
                if not results:
                    st.warning("⚠️ No matching resumes found. Try adjusting your search criteria.")
                else:
                    st.success(f"✅ Found **{len(results)}** matching resumes!")
                    
                    # Debug: Show score distribution
                    with st.expander("📊 Score Distribution (Debug)"):
                        scores = [r.get('score', 0) for r in results]
                        sem_scores = [r.get('semantic_score', 0) for r in results]
                        kw_scores = [r.get('bm25_score', 0) for r in results]
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Avg Match", f"{sum(scores)/len(scores)*100:.1f}%")
                        with col2:
                            st.metric("Avg Semantic", f"{sum(sem_scores)/len(sem_scores)*100:.1f}%")
                        with col3:
                            st.metric("Avg Keyword", f"{sum(kw_scores)/len(kw_scores)*100:.1f}%")
                        
                        st.caption(f"Score range: {min(scores)*100:.1f}% - {max(scores)*100:.1f}%")
                    
                    # Display results
                    for idx, result in enumerate(results, 1):
                        with st.expander(f"**#{idx} – {result.get('name', 'Unknown')}** (Score: {result.get('score', 0)*100:.1f}%)"):
                            col1, col2 = st.columns([2, 1])
                            
                            with col1:
                                st.markdown(f"**Name:** {result.get('name', 'N/A')}")
                                st.markdown(f"**Email:** {result.get('email', 'N/A')}")
                                st.markdown(f"**Phone:** {result.get('phone', 'N/A')}")
                                
                                if result.get('current_role'):
                                    st.markdown(f"**Current Role:** {result.get('current_role')}")
                                
                                if result.get('experience_years'):
                                    st.markdown(f"**Experience:** {result.get('experience_years')} years")
                                
                                if result.get('skills'):
                                    st.markdown(f"**Skills:** {result.get('skills')}")
                                
                                if result.get('education'):
                                    st.markdown(f"**Education:** {result.get('education')}")
                            
                            with col2:
                                st.metric("Match Score", f"{result.get('score', 0)*100:.1f}%")
                                
                                if result.get('semantic_score') is not None:
                                    st.metric("Semantic", f"{result.get('semantic_score')*100:.1f}%")
                                
                                if result.get('bm25_score') is not None:
                                    st.metric("Keyword", f"{result.get('bm25_score')*100:.1f}%")
                            
                            # Show text preview if available
                            if result.get('text'):
                                with st.container():
                                    st.markdown("**Resume Preview:**")
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
                        file_name="training_to_resumes_results.csv",
                        mime="text/csv",
                    )
            
            except Exception as e:
                st.error(f"❌ Search failed: {e}")
                import traceback
                with st.expander("🐛 Debug Info"):
                    st.code(traceback.format_exc())

st.markdown("---")
st.caption("💡 **Tip:** This tool searches the 'resumes' namespace to find candidates whose skills and experience match your training program needs.")

