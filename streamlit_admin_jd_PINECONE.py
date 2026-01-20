# streamlit_admin_jd_PINECONE.py
# Admin tool for ingesting Job Descriptions into Pinecone + BM25
# ----------------------------------------------------------------------

import os
import re
import pickle
from pathlib import Path
from typing import List, Dict

import streamlit as st
import pandas as pd
import requests
from rank_bm25 import BM25Okapi
from pinecone.grpc import PineconeGRPC as Pinecone

# Import configs
from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE_JOBS,
    VECTOR_DIMENSION,
    OLLAMA_HOST,
    EMBED_MODEL,
    BM25_JOBS_CORPUS_PATH,
    BM25_JOBS_DOCIDS_PATH,
    BM25_JOBS_META_PATH,
    JOBS_STORE_DIR,
)

# Utils
from utils_jd import clean_text, tokenize, stable_id_from_bytes

# ========================= Page Config =========================
st.set_page_config(
    page_title="Admin – Job Description Indexer (Pinecone)",
    page_icon="💼",
    layout="wide"
)
st.title("💼 Admin – Job Description Indexer (Pinecone + BM25)")
st.caption("Ingest job descriptions into Pinecone (namespace: jobs) and local BM25 index")

# ========================= Helpers =========================

def sanitize_text(text: str) -> str:
    """Clean and sanitize text"""
    return clean_text(text)

def embed_text_ollama(text: str) -> List[float]:
    """Embed text using Ollama"""
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=45
        )
        resp.raise_for_status()
        data = resp.json()
        vec = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if not vec or len(vec) != VECTOR_DIMENSION:
            raise ValueError(f"Invalid embedding dimension: {len(vec) if vec else 0}")
        return vec
    except Exception as e:
        st.error(f"Embedding failed: {e}")
        raise

# ========================= Main Ingestion =========================

def ingest_jd_to_pinecone_and_bm25(
    jd_data: Dict,
    pc_index
):
    """
    Ingest one job description:
    1. Compose text from form fields
    2. Embed (single embedding per JD)
    3. Upsert to Pinecone
    4. Tokenize → update BM25
    """
    
    # Compose JD text
    jd_parts = []
    if jd_data.get('title'):
        jd_parts.append(f"Job Title: {jd_data['title']}")
    if jd_data.get('company'):
        jd_parts.append(f"Company: {jd_data['company']}")
    if jd_data.get('location'):
        jd_parts.append(f"Location: {jd_data['location']}")
    if jd_data.get('description'):
        jd_parts.append(f"\nJob Description:\n{jd_data['description']}")
    if jd_data.get('required_skills'):
        jd_parts.append(f"\nRequired Skills:\n{jd_data['required_skills']}")
    if jd_data.get('experience'):
        jd_parts.append(f"\nExperience Required: {jd_data['experience']}")
    if jd_data.get('salary'):
        jd_parts.append(f"\nSalary: {jd_data['salary']}")
    
    jd_text = "\n\n".join(jd_parts)
    jd_text = sanitize_text(jd_text)
    
    if not jd_text.strip():
        st.warning("⚠️ Job description is empty after cleaning")
        return False
    
    # Generate stable ID
    jd_id = f"jd_{hash(jd_text) & 0x7FFFFFFF}"  # Positive hash
    
    st.info(f"📄 Job ID: {jd_id} | {len(jd_text)} characters")
    
    # Metadata
    metadata = {
        "job_id": jd_id,
        "document_id": jd_id,
        "parent_id": jd_id,
        "title": jd_data.get('title', ''),
        "company": jd_data.get('company', ''),
        "location": jd_data.get('location', ''),
        "required_skills": jd_data.get('required_skills', ''),
        "experience": jd_data.get('experience', ''),
        "salary": jd_data.get('salary', ''),
        "job_type": jd_data.get('job_type', ''),
        "url": jd_data.get('url', ''),
        "text": jd_text[:1000],  # Pinecone metadata limit
    }
    
    # Embed
    with st.spinner(f"Embedding job description..."):
        try:
            embedding = embed_text_ollama(jd_text)
        except:
            st.error(f"Failed to embed JD")
            return False
    
    # Upsert to Pinecone
    try:
        pc_index.upsert(
            vectors=[{
                "id": jd_id,
                "values": embedding,
                "metadata": metadata
            }],
            namespace=PINECONE_NAMESPACE_JOBS
        )
        st.success(f"✅ Uploaded to Pinecone (namespace: {PINECONE_NAMESPACE_JOBS})")
    except Exception as e:
        st.error(f"❌ Pinecone upsert failed: {e}")
        return False
    
    # Update BM25 (local)
    try:
        # Load existing BM25
        if os.path.exists(BM25_JOBS_CORPUS_PATH):
            with open(BM25_JOBS_CORPUS_PATH, "rb") as f:
                corpus_tokens = pickle.load(f)
            with open(BM25_JOBS_DOCIDS_PATH, "rb") as f:
                doc_ids = pickle.load(f)
            with open(BM25_JOBS_META_PATH, "rb") as f:
                meta_by_id = pickle.load(f)
        else:
            corpus_tokens, doc_ids, meta_by_id = [], [], {}
        
        # Check if already exists (update vs insert)
        if jd_id in doc_ids:
            idx = doc_ids.index(jd_id)
            corpus_tokens[idx] = tokenize(jd_text)
            meta_by_id[jd_id] = metadata
            st.info("🔄 Updated existing JD in BM25")
        else:
            # Add new
            doc_ids.append(jd_id)
            corpus_tokens.append(tokenize(jd_text))
            meta_by_id[jd_id] = metadata
        
        # Rebuild BM25
        bm25 = BM25Okapi(corpus_tokens)
        
        # Save
        Path(BM25_JOBS_CORPUS_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(BM25_JOBS_CORPUS_PATH, "wb") as f:
            pickle.dump(corpus_tokens, f)
        with open(BM25_JOBS_DOCIDS_PATH, "wb") as f:
            pickle.dump(doc_ids, f)
        with open(BM25_JOBS_META_PATH, "wb") as f:
            pickle.dump(meta_by_id, f)
        
        st.success(f"✅ Updated BM25 index (now {len(doc_ids)} jobs)")
    except Exception as e:
        st.error(f"❌ BM25 update failed: {e}")
    
    return True

# ========================= UI =========================

# Initialize Pinecone
@st.cache_resource
def get_pinecone_index():
    """Get Pinecone index"""
    pc = Pinecone(api_key=PINECONE_API_KEY)
    return pc.Index(PINECONE_INDEX_NAME)

try:
    pc_index = get_pinecone_index()
    stats = pc_index.describe_index_stats()
    job_count = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_JOBS, {}).get('vector_count', 0)
    
    st.info(f"📊 Pinecone index: **{PINECONE_INDEX_NAME}** | Namespace: **{PINECONE_NAMESPACE_JOBS}** | Vectors: **{job_count}**")
except Exception as e:
    st.error(f"❌ Pinecone connection failed: {e}")
    st.stop()

# BM25 stats
if os.path.exists(BM25_JOBS_DOCIDS_PATH):
    with open(BM25_JOBS_DOCIDS_PATH, "rb") as f:
        bm25_docs = pickle.load(f)
    st.info(f"📊 BM25 index: **{len(bm25_docs)}** jobs")
else:
    st.info("📊 BM25 index: **0** jobs (will be created)")

st.markdown("---")

# Job Description Form
st.subheader("💼 Add Job Description")

with st.form("jd_form"):
    col1, col2 = st.columns([2, 1])
    
    with col1:
        jd_title = st.text_input("Job Title *", placeholder="e.g., Senior Python Developer")
        jd_company = st.text_input("Company", placeholder="e.g., TechCorp Inc.")
        jd_location = st.text_input("Location", placeholder="e.g., Hyderabad, India")
        
        jd_description = st.text_area(
            "Job Description *",
            height=250,
            placeholder="""Enter the full job description here...

Example:
We are seeking a Senior Python Developer with 5+ years of experience...

Responsibilities:
- Design and develop scalable web applications
- Write clean, maintainable code
- Collaborate with cross-functional teams
...
"""
        )
        
        jd_required_skills = st.text_area(
            "Required Skills (one per line)",
            height=150,
            placeholder="Python\nDjango\nPostgreSQL\nDocker\nAWS"
        )
    
    with col2:
        jd_experience = st.text_input("Experience", placeholder="e.g., 5+ years")
        jd_salary = st.text_input("Salary Range", placeholder="e.g., $80K - $120K")
        jd_job_type = st.selectbox(
            "Job Type",
            ["Full-time", "Part-time", "Contract", "Internship", "Remote"]
        )
        jd_url = st.text_input("Job Posting URL", placeholder="https://...")
    
    submit = st.form_submit_button("🚀 Ingest Job Description", type="primary", use_container_width=True)

if submit:
    if not jd_title or not jd_description:
        st.error("❌ Job Title and Description are required!")
    else:
        jd_data = {
            'title': jd_title,
            'company': jd_company,
            'location': jd_location,
            'description': jd_description,
            'required_skills': jd_required_skills,
            'experience': jd_experience,
            'salary': jd_salary,
            'job_type': jd_job_type,
            'url': jd_url,
        }
        
        st.markdown("---")
        st.subheader("📊 Ingestion Progress")
        
        success = ingest_jd_to_pinecone_and_bm25(jd_data, pc_index)
        
        if success:
            st.success("🎉 **Job description ingested successfully!**")
            
            # Refresh stats
            try:
                stats = pc_index.describe_index_stats()
                new_job_count = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_JOBS, {}).get('vector_count', 0)
                st.info(f"📊 New Pinecone vector count: **{new_job_count}**")
            except:
                pass
        else:
            st.error("❌ Ingestion failed. Please check the errors above.")

st.markdown("---")
st.caption("💡 **Tip:** Job descriptions are stored as single vectors in Pinecone for efficient search. Each JD gets one embedding in the 'jobs' namespace.")

