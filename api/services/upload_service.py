# api/services/upload_service.py
# Service for handling document uploads (resumes, jobs, training, assistance)
# ----------------------------------------------------------------------

import os
import sys
import pickle
import base64
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

import requests
from rank_bm25 import BM25Okapi
from pinecone.grpc import PineconeGRPC as Pinecone

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE_RESUMES,
    PINECONE_NAMESPACE_JOBS,
    PINECONE_NAMESPACE_TRAINING,
    PINECONE_NAMESPACE_ASSISTANCE,
    BM25_RESUMES_CORPUS_PATH,
    BM25_RESUMES_DOCIDS_PATH,
    BM25_RESUMES_META_PATH,
    BM25_JOBS_CORPUS_PATH,
    BM25_JOBS_DOCIDS_PATH,
    BM25_JOBS_META_PATH,
    BM25_TRAINING_CORPUS_PATH,
    BM25_TRAINING_DOCIDS_PATH,
    BM25_TRAINING_META_PATH,
    BM25_ASSISTANCE_CORPUS_PATH,
    BM25_ASSISTANCE_DOCIDS_PATH,
    BM25_ASSISTANCE_META_PATH,
    VECTOR_DIMENSION,
    OLLAMA_HOST,
    EMBED_MODEL,
)


class UploadService:
    """Service for uploading and indexing documents"""
    
    def __init__(self):
        self.pc = Pinecone(api_key=PINECONE_API_KEY)
        self.index = self.pc.Index(PINECONE_INDEX_NAME)
        
        # Namespace mappings
        self.namespaces = {
            "resumes": PINECONE_NAMESPACE_RESUMES,
            "jobs": PINECONE_NAMESPACE_JOBS,
            "training": PINECONE_NAMESPACE_TRAINING,
            "assistance": PINECONE_NAMESPACE_ASSISTANCE,
        }
        
        # BM25 path mappings
        self.bm25_paths = {
            "resumes": (BM25_RESUMES_CORPUS_PATH, BM25_RESUMES_DOCIDS_PATH, BM25_RESUMES_META_PATH),
            "jobs": (BM25_JOBS_CORPUS_PATH, BM25_JOBS_DOCIDS_PATH, BM25_JOBS_META_PATH),
            "training": (BM25_TRAINING_CORPUS_PATH, BM25_TRAINING_DOCIDS_PATH, BM25_TRAINING_META_PATH),
            "assistance": (BM25_ASSISTANCE_CORPUS_PATH, BM25_ASSISTANCE_DOCIDS_PATH, BM25_ASSISTANCE_META_PATH),
        }
    
    def embed_text(self, text: str) -> List[float]:
        """Generate embedding using Ollama"""
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
            raise RuntimeError(f"Embedding failed: {e}")
    
    def chunk_text(self, text: str, size: int = 600, overlap: int = 120) -> List[str]:
        """Chunk text with overlap"""
        chunks = []
        words = text.split()
        
        if len(words) <= size:
            return [text]
        
        for i in range(0, len(words), size - overlap):
            chunk = " ".join(words[i:i + size])
            chunks.append(chunk)
            
            if i + size >= len(words):
                break
        
        return chunks
    
    def tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25"""
        return text.lower().split()
    
    def upload_to_pinecone_and_bm25(
        self,
        doc_type: str,
        doc_id: str,
        text: str,
        metadata: Dict,
        chunk_docs: bool = True
    ) -> Tuple[int, bool]:
        """
        Upload document to Pinecone and BM25
        
        Args:
            doc_type: "resumes", "jobs", "training", "assistance"
            doc_id: Unique document ID
            text: Document text
            metadata: Document metadata
            chunk_docs: Whether to chunk the document (True for resumes, False for jobs/training/assistance)
        
        Returns:
            (vectors_created, bm25_updated)
        """
        namespace = self.namespaces[doc_type]
        corpus_path, docids_path, meta_path = self.bm25_paths[doc_type]
        
        vectors_created = 0
        
        # Chunk or use as single document
        if chunk_docs:
            chunks = self.chunk_text(text)
        else:
            chunks = [text]
        
        # Upload to Pinecone
        vectors_to_upsert = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}" if chunk_docs else doc_id
            
            # Generate embedding
            embedding = self.embed_text(chunk)
            
            # Prepare metadata
            chunk_metadata = {
                **metadata,
                "chunk_id": chunk_id,
                "chunk_index": i,
                "parent_id": doc_id,
                "document_id": doc_id,
                "text": chunk[:1000],  # Pinecone metadata limit
            }
            
            vectors_to_upsert.append({
                "id": chunk_id,
                "values": embedding,
                "metadata": chunk_metadata
            })
            
            vectors_created += 1
        
        # Upsert to Pinecone
        if vectors_to_upsert:
            try:
                self.index.upsert(vectors=vectors_to_upsert, namespace=namespace)
            except Exception as e:
                raise RuntimeError(f"Pinecone upsert failed: {e}")
        
        # Update BM25
        try:
            # Load existing BM25
            if os.path.exists(corpus_path):
                with open(corpus_path, "rb") as f:
                    corpus_tokens = pickle.load(f)
                with open(docids_path, "rb") as f:
                    doc_ids = pickle.load(f)
                with open(meta_path, "rb") as f:
                    meta_by_id = pickle.load(f)
            else:
                corpus_tokens, doc_ids, meta_by_id = [], [], {}
            
            # Update or insert
            if doc_id in doc_ids:
                idx = doc_ids.index(doc_id)
                corpus_tokens[idx] = self.tokenize(text)
                meta_by_id[doc_id] = metadata
            else:
                doc_ids.append(doc_id)
                corpus_tokens.append(self.tokenize(text))
                meta_by_id[doc_id] = metadata
            
            # Save
            Path(corpus_path).parent.mkdir(parents=True, exist_ok=True)
            with open(corpus_path, "wb") as f:
                pickle.dump(corpus_tokens, f)
            with open(docids_path, "wb") as f:
                pickle.dump(doc_ids, f)
            with open(meta_path, "wb") as f:
                pickle.dump(meta_by_id, f)
            
            bm25_updated = True
        except Exception as e:
            print(f"BM25 update failed: {e}")
            bm25_updated = False
        
        return vectors_created, bm25_updated
    
    @staticmethod
    def generate_doc_id(text: str, prefix: str = "doc") -> str:
        """Generate stable document ID from text"""
        hash_obj = hashlib.sha256(text.encode())
        hash_hex = hash_obj.hexdigest()[:16]
        return f"{prefix}_{hash_hex}"
    
    @staticmethod
    def decode_base64_file(file_content: str) -> str:
        """Decode base64 encoded file content"""
        try:
            decoded = base64.b64decode(file_content)
            return decoded.decode('utf-8', errors='ignore')
        except Exception as e:
            raise ValueError(f"Failed to decode file: {e}")

