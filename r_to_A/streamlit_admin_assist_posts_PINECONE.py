# streamlit_admin_assist_posts_PINECONE.py
# Admin tool for ingesting Assistance Posts into Pinecone + BM25
# ----------------------------------------------------------------------

import os
import sys
import pickle
from pathlib import Path
from typing import List, Dict

import streamlit as st
import pandas as pd
import requests
from rank_bm25 import BM25Okapi
from pinecone.grpc import PineconeGRPC as Pinecone

# Import configs
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE_ASSISTANCE,
    VECTOR_DIMENSION,
    OLLAMA_HOST,
    EMBED_MODEL,
    BM25_ASSISTANCE_CORPUS_PATH,
    BM25_ASSISTANCE_DOCIDS_PATH,
    BM25_ASSISTANCE_META_PATH,
    ASSISTANCE_STORE_DIR,
)

# ========================= Page Config =========================
st.set_page_config(
    page_title="Admin – Assistance Posts Indexer (Pinecone)",
    page_icon="🧭",
    layout="wide"
)
st.title("🧭 Admin – Assistance Posts Indexer (Pinecone + BM25)")
st.caption("Ingest assistance center postings into Pinecone (namespace: assistance) and local BM25 index")

# ========================= Helpers =========================

def clean_text(text: str) -> str:
    """Clean and sanitize text"""
    import re
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text

def tokenize(text: str) -> List[str]:
    """Simple tokenization"""
    return text.lower().split()

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

def ingest_assistance_to_pinecone_and_bm25(
    assistance_data: Dict,
    pc_index
):
    """
    Ingest one assistance post:
    1. Compose text from form fields
    2. Embed (single embedding per post)
    3. Upsert to Pinecone
    4. Tokenize → update BM25
    """
    
    # Compose assistance post text
    post_parts = []
    if assistance_data.get('center_name'):
        post_parts.append(f"Assistance Center: {assistance_data['center_name']}")
    if assistance_data.get('services'):
        post_parts.append(f"Services Offered: {assistance_data['services']}")
    if assistance_data.get('operating_hours'):
        post_parts.append(f"Operating Hours: {assistance_data['operating_hours']}")
    if assistance_data.get('description'):
        post_parts.append(f"\nDescription:\n{assistance_data['description']}")
    if assistance_data.get('address'):
        post_parts.append(f"\nAddress: {assistance_data['address']}")
    if assistance_data.get('email'):
        post_parts.append(f"Email: {assistance_data['email']}")
    if assistance_data.get('phone'):
        post_parts.append(f"Phone: {assistance_data['phone']}")
    
    post_text = "\n\n".join(post_parts)
    post_text = clean_text(post_text)
    
    if not post_text.strip():
        st.warning("⚠️ Assistance post is empty after cleaning")
        return False
    
    # Generate stable ID
    post_id = f"assistance_{hash(post_text) & 0x7FFFFFFF}"
    
    st.info(f"📄 Post ID: {post_id} | {len(post_text)} characters")
    
    # Metadata
    metadata = {
        "post_id": post_id,
        "document_id": post_id,
        "parent_id": post_id,
        "center_name": assistance_data.get('center_name', ''),
        "services": assistance_data.get('services', ''),
        "operating_hours": assistance_data.get('operating_hours', ''),
        "email": assistance_data.get('email', ''),
        "phone": assistance_data.get('phone', ''),
        "address": assistance_data.get('address', ''),
        "capacity": assistance_data.get('capacity', ''),
        "text": post_text[:1000],
    }
    
    # Embed
    with st.spinner(f"Embedding assistance post..."):
        try:
            embedding = embed_text_ollama(post_text)
        except:
            st.error(f"Failed to embed assistance post")
            return False
    
    # Upsert to Pinecone
    try:
        pc_index.upsert(
            vectors=[{
                "id": post_id,
                "values": embedding,
                "metadata": metadata
            }],
            namespace=PINECONE_NAMESPACE_ASSISTANCE
        )
        st.success(f"✅ Uploaded to Pinecone (namespace: {PINECONE_NAMESPACE_ASSISTANCE})")
    except Exception as e:
        st.error(f"❌ Pinecone upsert failed: {e}")
        return False
    
    # Update BM25 (local)
    try:
        # Load existing BM25
        if os.path.exists(BM25_ASSISTANCE_CORPUS_PATH):
            with open(BM25_ASSISTANCE_CORPUS_PATH, "rb") as f:
                corpus_tokens = pickle.load(f)
            with open(BM25_ASSISTANCE_DOCIDS_PATH, "rb") as f:
                doc_ids = pickle.load(f)
            with open(BM25_ASSISTANCE_META_PATH, "rb") as f:
                meta_by_id = pickle.load(f)
        else:
            corpus_tokens, doc_ids, meta_by_id = [], [], {}
        
        # Check if already exists
        if post_id in doc_ids:
            idx = doc_ids.index(post_id)
            corpus_tokens[idx] = tokenize(post_text)
            meta_by_id[post_id] = metadata
            st.info("🔄 Updated existing post in BM25")
        else:
            doc_ids.append(post_id)
            corpus_tokens.append(tokenize(post_text))
            meta_by_id[post_id] = metadata
        
        # Rebuild BM25
        bm25 = BM25Okapi(corpus_tokens)
        
        # Save
        Path(BM25_ASSISTANCE_CORPUS_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(BM25_ASSISTANCE_CORPUS_PATH, "wb") as f:
            pickle.dump(corpus_tokens, f)
        with open(BM25_ASSISTANCE_DOCIDS_PATH, "wb") as f:
            pickle.dump(doc_ids, f)
        with open(BM25_ASSISTANCE_META_PATH, "wb") as f:
            pickle.dump(meta_by_id, f)
        
        st.success(f"✅ Updated BM25 index (now {len(doc_ids)} assistance posts)")
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
    assistance_count = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_ASSISTANCE, {}).get('vector_count', 0)
    
    st.info(f"📊 Pinecone index: **{PINECONE_INDEX_NAME}** | Namespace: **{PINECONE_NAMESPACE_ASSISTANCE}** | Vectors: **{assistance_count}**")
except Exception as e:
    st.error(f"❌ Pinecone connection failed: {e}")
    st.stop()

# BM25 stats
if os.path.exists(BM25_ASSISTANCE_DOCIDS_PATH):
    with open(BM25_ASSISTANCE_DOCIDS_PATH, "rb") as f:
        bm25_docs = pickle.load(f)
    st.info(f"📊 BM25 index: **{len(bm25_docs)}** assistance posts")
else:
    st.info("📊 BM25 index: **0** assistance posts (will be created)")

st.markdown("---")

# Assistance Post Form
st.subheader("🧭 Add Assistance Center Posting")

with st.form("assistance_form"):
    col1, col2 = st.columns([2, 1])
    
    with col1:
        center_name = st.text_input("Assistance Center Name *", placeholder="e.g., CareerPath Assistance Center")
        services = st.text_area(
            "Services Offered (comma-separated) *",
            height=100,
            placeholder="Career Counseling, Resume Writing, Interview Preparation, Job Placement Support"
        )
        operating_hours = st.text_input("Operating Hours", placeholder="e.g., Mon–Fri 9:00 AM – 6:00 PM")
        
        description = st.text_area(
            "Description",
            height=200,
            placeholder="""Enter the assistance center description here...

Example:
CareerPath Assistance Center helps job seekers achieve their career goals
through personalized guidance, expert resume building, and intensive 
interview preparation...
"""
        )
    
    with col2:
        capacity = st.number_input("Capacity", min_value=0, value=30, step=5)
        address = st.text_area("Address", height=80, placeholder="Street, City, State, PIN")
        email = st.text_input("Email", placeholder="support@example.com")
        phone = st.text_input("Phone", placeholder="+91-9123456780")
    
    submit = st.form_submit_button("🚀 Ingest Assistance Post", type="primary", use_container_width=True)

if submit:
    if not center_name or not services:
        st.error("❌ Assistance Center Name and Services are required!")
    else:
        assistance_data = {
            'center_name': center_name,
            'services': services,
            'operating_hours': operating_hours,
            'description': description,
            'capacity': str(capacity),
            'address': address,
            'email': email,
            'phone': phone,
        }
        
        st.markdown("---")
        st.subheader("📊 Ingestion Progress")
        
        success = ingest_assistance_to_pinecone_and_bm25(assistance_data, pc_index)
        
        if success:
            st.success("🎉 **Assistance post ingested successfully!**")
            
            # Refresh stats
            try:
                stats = pc_index.describe_index_stats()
                new_count = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_ASSISTANCE, {}).get('vector_count', 0)
                st.info(f"📊 New Pinecone vector count: **{new_count}**")
            except:
                pass
        else:
            st.error("❌ Ingestion failed. Please check the errors above.")

st.markdown("---")
st.caption("💡 **Tip:** Assistance posts are stored as single vectors in Pinecone for efficient search. Each post gets one embedding in the 'assistance' namespace.")

