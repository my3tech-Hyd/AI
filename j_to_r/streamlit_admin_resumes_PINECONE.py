# streamlit_admin_resumes_PINECONE.py
# Admin tool for ingesting resumes into Pinecone + BM25
# ----------------------------------------------------------------------

import io
import os
import re
import pickle
import uuid
from pathlib import Path
from typing import List, Dict, Tuple

import streamlit as st
import pandas as pd
import requests
from pypdf import PdfReader
from docx import Document as Docx
from rank_bm25 import BM25Okapi
from pinecone.grpc import PineconeGRPC as Pinecone

# Import configs
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE_RESUMES,
    VECTOR_DIMENSION,
    OLLAMA_HOST,
    EMBED_MODEL,
    BM25_RESUMES_CORPUS_PATH,
    BM25_RESUMES_DOCIDS_PATH,
    BM25_RESUMES_META_PATH,
    RESUMES_STORE_DIR,
)

# Utils
from utils_r import clean_text, tokenize, stable_id_from_bytes

# ========================= Page Config =========================
st.set_page_config(
    page_title="Admin – Resume Indexer (Pinecone)",
    page_icon="📄",
    layout="wide"
)
st.title("📄 Admin – Resume Indexer (Pinecone + BM25)")
st.caption("Ingest resumes into Pinecone (namespace: resumes) and local BM25 index")

# ========================= Helpers =========================

def chunk_text(text: str, size: int = 600, overlap: int = 120) -> List[str]:
    """Chunk text with overlap"""
    n = len(text)
    if n == 0:
        return []
    
    chunks, start = [], 0
    while start < n:
        end = min(n, start + size)
        chunks.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks

def read_text_from_bytes(data: bytes, filename: str) -> Tuple[str, str]:
    """Extract text from various file formats"""
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
    
    return clean_text(text), ext

def extract_resume_metadata(text: str, fallback_name: str) -> Dict:
    """Extract name, email, phone from resume text"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    
    # Name: first reasonable line
    name = None
    for ln in lines[:10]:
        if 2 <= len(ln) <= 60 and not re.search(
            r"(?i)summary|experience|education|skills|profile|contact", ln
        ):
            name = ln
            break
    candidate_name = name or fallback_name
    
    # Email
    email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    email = email_match.group(0) if email_match else ""
    
    # Phone
    phone_match = re.search(
        r"(\+\d{1,3}\s?)?(\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{4}", text
    )
    phone = phone_match.group(0) if phone_match else ""
    
    return {
        "candidate_name": candidate_name,
        "email": email,
        "phone": phone,
    }

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

def ingest_resume_to_pinecone_and_bm25(
    file_data: bytes,
    filename: str,
    pc_index,
    form_metadata: Dict
):
    """
    Ingest one resume:
    1. Extract text
    2. Chunk it
    3. Embed chunks → upsert to Pinecone
    4. Tokenize full text → update BM25
    5. Save file to storage
    """
    
    # Extract text
    text, ext = read_text_from_bytes(file_data, filename)
    if not text.strip():
        st.warning(f"⚠️ {filename}: Empty after extraction")
        return False
    
    # Generate stable parent ID
    parent_id, short_id = stable_id_from_bytes(file_data)
    
    # Extract metadata
    auto_metadata = extract_resume_metadata(text, Path(filename).stem)
    
    # Merge with form metadata
    metadata = {
        **auto_metadata,
        **form_metadata,
        "file_name": filename,
        "parent_id": parent_id,
        "resume_id": parent_id,
        "document_id": parent_id,
    }
    
    # Chunk text
    chunks = chunk_text(text, size=600, overlap=120)
    if not chunks:
        st.warning(f"⚠️ {filename}: No chunks generated")
        return False
    
    st.info(f"📄 {filename}: {len(chunks)} chunks")
    
    # Embed and upsert to Pinecone
    vectors_to_upsert = []
    
    with st.spinner(f"Embedding {len(chunks)} chunks..."):
        for i, chunk in enumerate(chunks):
            chunk_id = f"{parent_id}::chunk_{i}"
            
            try:
                embedding = embed_text_ollama(chunk)
            except:
                st.error(f"Failed to embed chunk {i} of {filename}")
                continue
            
            chunk_metadata = {
                **metadata,
                "chunk_id": chunk_id,
                "chunk_index": i,
                "text": chunk[:1000],  # Pinecone metadata limit
            }
            
            vectors_to_upsert.append({
                "id": chunk_id,
                "values": embedding,
                "metadata": chunk_metadata
            })
    
    # Upsert to Pinecone
    if vectors_to_upsert:
        try:
            pc_index.upsert(
                vectors=vectors_to_upsert,
                namespace=PINECONE_NAMESPACE_RESUMES
            )
            st.success(f"✅ Uploaded {len(vectors_to_upsert)} vectors to Pinecone")
        except Exception as e:
            st.error(f"❌ Pinecone upsert failed: {e}")
            return False
    
    # Update BM25 (local)
    try:
        # Load existing BM25
        if os.path.exists(BM25_RESUMES_CORPUS_PATH):
            with open(BM25_RESUMES_CORPUS_PATH, "rb") as f:
                corpus_tokens = pickle.load(f)
            with open(BM25_RESUMES_DOCIDS_PATH, "rb") as f:
                doc_ids = pickle.load(f)
            with open(BM25_RESUMES_META_PATH, "rb") as f:
                meta_by_id = pickle.load(f)
        else:
            corpus_tokens, doc_ids, meta_by_id = [], [], {}
        
        # Add new document
        doc_ids.append(parent_id)
        corpus_tokens.append(tokenize(text))
        meta_by_id[parent_id] = {
            **metadata,
            "text": text[:2000],  # Store sample
        }
        
        # Rebuild BM25
        bm25 = BM25Okapi(corpus_tokens)
        
        # Save
        Path(BM25_RESUMES_CORPUS_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(BM25_RESUMES_CORPUS_PATH, "wb") as f:
            pickle.dump(corpus_tokens, f)
        with open(BM25_RESUMES_DOCIDS_PATH, "wb") as f:
            pickle.dump(doc_ids, f)
        with open(BM25_RESUMES_META_PATH, "wb") as f:
            pickle.dump(meta_by_id, f)
        
        st.success(f"✅ Updated BM25 index (now {len(doc_ids)} documents)")
    except Exception as e:
        st.error(f"❌ BM25 update failed: {e}")
    
    # Save file to storage
    try:
        storage_path = Path(RESUMES_STORE_DIR) / f"{short_id}_{filename}"
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(file_data)
        st.success(f"✅ Saved to: {storage_path}")
    except Exception as e:
        st.warning(f"⚠️ File save failed: {e}")
    
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
    resume_count = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_RESUMES, {}).get('vector_count', 0)
    
    st.info(f"📊 Pinecone index: **{PINECONE_INDEX_NAME}** | Namespace: **{PINECONE_NAMESPACE_RESUMES}** | Vectors: **{resume_count}**")
except Exception as e:
    st.error(f"❌ Pinecone connection failed: {e}")
    st.stop()

# BM25 stats
if os.path.exists(BM25_RESUMES_DOCIDS_PATH):
    with open(BM25_RESUMES_DOCIDS_PATH, "rb") as f:
        bm25_docs = pickle.load(f)
    st.info(f"📊 BM25 index: **{len(bm25_docs)}** documents")
else:
    st.info("📊 BM25 index: **0** documents (will be created)")

st.markdown("---")

# Upload form
st.subheader("📤 Upload Resumes")

with st.form("upload_form"):
    uploaded_files = st.file_uploader(
        "Select resume files (PDF, DOCX, TXT, RTF)",
        type=["pdf", "docx", "txt", "rtf"],
        accept_multiple_files=True
    )
    
    st.markdown("### Optional Metadata")
    form_location = st.text_input("Location", "")
    form_experience = st.text_input("Experience Level", "")
    form_skills = st.text_area("Key Skills (comma-separated)", "")
    
    submit = st.form_submit_button("🚀 Ingest Resumes", type="primary")

if submit and uploaded_files:
    form_metadata = {
        "location": form_location,
        "experience": form_experience,
        "skills": form_skills,
    }
    
    st.markdown("---")
    st.subheader("📊 Ingestion Progress")
    
    success_count = 0
    fail_count = 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, uploaded_file in enumerate(uploaded_files):
        status_text.text(f"Processing {i+1}/{len(uploaded_files)}: {uploaded_file.name}")
        
        try:
            file_data = uploaded_file.read()
            success = ingest_resume_to_pinecone_and_bm25(
                file_data,
                uploaded_file.name,
                pc_index,
                form_metadata
            )
            
            if success:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            st.error(f"❌ {uploaded_file.name}: {e}")
            fail_count += 1
        
        progress_bar.progress((i + 1) / len(uploaded_files))
        st.markdown("---")
    
    status_text.text("✅ Ingestion complete!")
    
    st.success(f"**Summary:** {success_count} succeeded, {fail_count} failed")
    
    # Refresh stats
    try:
        stats = pc_index.describe_index_stats()
        new_resume_count = stats.get('namespaces', {}).get(PINECONE_NAMESPACE_RESUMES, {}).get('vector_count', 0)
        st.info(f"📊 New Pinecone vector count: **{new_resume_count}**")
    except:
        pass

st.markdown("---")
st.caption("💡 **Tip:** Resumes are chunked, embedded, and stored in both Pinecone (vector search) and local BM25 (keyword search) for hybrid retrieval.")

