# pinecone_retriever.py
# Production-grade hybrid retrieval using Pinecone + BM25
# ----------------------------------------------------------------------
# Features:
# - Pinecone for vector search (cloud-hosted, scalable)
# - BM25 for keyword search (local, fast)
# - RRF (Reciprocal Rank Fusion)
# - MMR (Maximal Marginal Relevance)
# - Anti-collapse re-scoring
# - Query pooling
# - RTF noise stripping
# - Tech stack alias normalization
# ----------------------------------------------------------------------

import re
import os
import pickle
import numpy as np
from typing import List, Dict, Tuple, Optional
from pathlib import Path

import requests
from rank_bm25 import BM25Okapi
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec


# Tech stack aliases for better keyword matching
ALIASES = {
    ".net": "dotnet",
    "c#": "csharp",
    "c++": "cpp",
    "node.js": "nodejs",
    "react.js": "react",
    "next.js": "nextjs",
    "javascript": "js",
    "typescript": "ts",
}


class PineconeHybridRetriever:
    """
    Hybrid retriever using Pinecone (vector) + BM25 (keyword).
    
    Corpus types supported:
    - Resumes
    - Job Descriptions
    - Training Posts
    - Assistance Posts
    
    Features:
    - Hybrid search (Pinecone + BM25)
    - RRF (Reciprocal Rank Fusion)
    - MMR (Maximal Marginal Relevance)
    - Anti-collapse re-scoring
    - Query pooling
    - RTF noise stripping
    """
    
    def __init__(
        self,
        pinecone_api_key: str,
        pinecone_index_name: str,
        bm25_corpus_path: str,
        bm25_docids_path: str,
        bm25_meta_path: str,
        embed_model: str = "nomic-embed-text",
        ollama_host: str = "http://localhost:11434",
        corpus_type: str = "resumes",
        namespace: str = "resumes",
        config: Optional[Dict] = None
    ):
        """
        Initialize Pinecone hybrid retriever.
        
        Args:
            pinecone_api_key: Pinecone API key
            pinecone_index_name: Name of Pinecone index
            bm25_corpus_path: Path to BM25 corpus pickle
            bm25_docids_path: Path to BM25 doc IDs pickle
            bm25_meta_path: Path to BM25 metadata pickle
            embed_model: Ollama embedding model
            ollama_host: Ollama API URL
            corpus_type: Type of corpus ("resumes", "jobs", "training", "assistance")
            namespace: Pinecone namespace to query
            config: Optional config dict
        """
        self.pinecone_api_key = pinecone_api_key
        self.pinecone_index_name = pinecone_index_name
        self.namespace = namespace
        self.embed_model = embed_model
        self.ollama_host = ollama_host.rstrip("/")
        self.corpus_type = corpus_type
        
        # Initialize Pinecone
        self.pc = Pinecone(api_key=pinecone_api_key)
        self.index = self.pc.Index(pinecone_index_name)
        
        # Load BM25 index
        self.bm25, self.doc_ids, self.id2pos, self.meta_by_id = self._load_bm25_index(
            bm25_corpus_path, bm25_docids_path, bm25_meta_path
        )
        
        # Config with defaults
        self.config = config or {}
        self.K_VEC = self.config.get('K_VEC', 40)
        self.K_BM25 = self.config.get('K_BM25', 80)
        self.K_CHUNKS = self.config.get('K_CHUNKS', 20)
        self.HYBRID_ALPHA = self.config.get('HYBRID_ALPHA', 0.6)
        self.USE_RRF = self.config.get('USE_RRF', True)
        self.RRF_K = self.config.get('RRF_K', 60)
        self.USE_MMR = self.config.get('USE_MMR', True)
        self.MMR_LAMBDA = self.config.get('MMR_LAMBDA', 0.5)
        self.QUERY_CHUNK_SIZE = self.config.get('QUERY_CHUNK_SIZE', 500)
        self.QUERY_CHUNK_OVERLAP = self.config.get('QUERY_CHUNK_OVERLAP', 100)
        self.QUERY_MAX_CHUNKS = self.config.get('QUERY_MAX_CHUNKS', 6)
        self.MAX_QUERY_CHARS = self.config.get('MAX_QUERY_CHARS', 1200)
        self.TOP_K_FINAL = self.config.get('TOP_K_FINAL', 10)
        
        # HTTP session for Ollama
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    # -------------------------
    # Main Retrieval Pipeline
    # -------------------------
    
    def retrieve(self, query_text: str, top_k: Optional[int] = None) -> List[Dict]:
        """
        Main retrieval method. Returns top-k parent documents.
        
        Args:
            query_text: Query (JD, training post, resume, etc.)
            top_k: Number of results (default: self.TOP_K_FINAL)
        
        Returns:
            List of dicts with: parent_id, document_id, score, match_pct, metadata fields
        """
        top_k = top_k or self.TOP_K_FINAL
        
        # Step 1: Embed query (pooled for stability)
        qvec = self.embed_query_pooled(query_text)
        
        # Step 2: Union retrieval (Pinecone + BM25)
        candidates = self._retrieve_union(qvec, query_text, self.K_VEC, self.K_BM25)
        
        if not candidates:
            # Fallback: widen K
            candidates = self._retrieve_union(qvec, query_text, self.K_VEC * 2, self.K_BM25 * 2)
        
        if not candidates:
            return []
        
        # Step 3: Fuse scores
        candidates = self._fuse_scores(candidates, qvec)
        
        # Step 4: MMR diversity (optional)
        if self.USE_MMR:
            candidates = self._mmr_select(candidates, self.K_CHUNKS)
        else:
            candidates = candidates[:self.K_CHUNKS]
        
        # Step 5: Aggregate to parent documents
        results = self._parent_pool(candidates)
        
        # Step 6: Filter deleted parents
        results = self._filter_existing_parents(results)
        
        return results[:top_k]
    
    # -------------------------
    # Embedding (with pooling)
    # -------------------------
    
    def embed_query_pooled(self, text: str) -> np.ndarray:
        """Embed query with chunking and pooling for long text"""
        chunks = self._chunk_text_query(text)
        if not chunks or len(chunks) == 1:
            return np.array(self._embed_single(text))
        
        vecs = [self._embed_single(c) for c in chunks]
        weights = [len(c) for c in chunks]
        
        # Length-weighted mean
        pooled = np.average(vecs, axis=0, weights=weights)
        return pooled
    
    def _embed_single(self, text: str) -> List[float]:
        """Embed single text chunk via Ollama API"""
        text = (text or "").strip()
        if len(text) > self.MAX_QUERY_CHARS:
            text = text[:self.MAX_QUERY_CHARS]
        
        if not text:
            raise ValueError("Empty text for embedding")
        
        try:
            url = f"{self.ollama_host}/api/embeddings"
            resp = self.session.post(
                url,
                json={"model": self.embed_model, "prompt": text},
                timeout=45
            )
            resp.raise_for_status()
            data = resp.json()
            vec = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
            if not vec:
                raise RuntimeError("No embedding returned")
            return vec
        except Exception:
            # Fallback to langchain
            try:
                from langchain_ollama import OllamaEmbeddings
            except:
                from langchain_community.embeddings import OllamaEmbeddings
            emb = OllamaEmbeddings(model=self.embed_model, base_url=self.ollama_host)
            return emb.embed_query(text)
    
    def _chunk_text_query(self, text: str) -> List[str]:
        """Chunk long queries with overlap"""
        s = (text or "").strip()
        if len(s) > self.MAX_QUERY_CHARS:
            s = s[:self.MAX_QUERY_CHARS]
        if not s:
            return []
        
        chunks = []
        i = 0
        while i < len(s) and len(chunks) < self.QUERY_MAX_CHUNKS:
            end = min(len(s), i + self.QUERY_CHUNK_SIZE)
            chunks.append(s[i:end])
            i = i + self.QUERY_CHUNK_SIZE - self.QUERY_CHUNK_OVERLAP
            if i <= 0:
                break
        return chunks
    
    # -------------------------
    # Union Retrieval
    # -------------------------
    
    def _retrieve_union(self, qvec: np.ndarray, query_text: str, k_vec: int, k_bm25: int) -> List[Dict]:
        """Retrieve from both Pinecone and BM25, union results"""
        candidates: Dict[str, Dict] = {}
        
        # Pinecone vector search
        try:
            results = self.index.query(
                vector=qvec.tolist(),
                top_k=k_vec,
                include_metadata=True,
                namespace=self.namespace
            )
            
            for match in results.get('matches', []):
                chunk_id = match['id']
                score = match['score']  # Pinecone returns similarity (0-1)
                metadata = match.get('metadata', {})
                
                # Note: Pinecone doesn't return vectors by default, set to None
                candidates[chunk_id] = {
                    "chunk_id": chunk_id,
                    "doc": metadata.get('text', ''),
                    "sem": float(score),
                    "kw": 0.0,
                    "meta": metadata,
                    "emb": None  # Pinecone doesn't return vectors in query results
                }
        except Exception as e:
            print(f"Pinecone search failed: {e}")
        
        # BM25 keyword search
        if getattr(self.bm25, "corpus_size", 0) > 0 and self.id2pos:
            normalized = self._normalize_for_bm25(query_text)
            tokens = normalized.split()
            scores = self.bm25.get_scores(tokens)
            
            pairs = [(cid, float(scores[pos])) for cid, pos in self.id2pos.items() if pos < len(scores)]
            pairs.sort(key=lambda x: x[1], reverse=True)
            top_bm25_ids = [cid for cid, _ in pairs[:k_bm25]]
            kw_scores_map = {cid: sc for cid, sc in pairs[:k_bm25]}
            
            # Get metadata and text from BM25 meta store
            for bm25_id in top_bm25_ids:
                meta = self.meta_by_id.get(bm25_id, {})
                chunk_id = meta.get("chunk_id", bm25_id)
                
                if chunk_id not in candidates:
                    candidates[chunk_id] = {
                        "chunk_id": chunk_id,
                        "doc": self._strip_rtf_noise(meta.get('text', '')),
                        "sem": 0.0,
                        "kw": kw_scores_map.get(bm25_id, 0.0),
                        "meta": meta,
                        "emb": None
                    }
                else:
                    # Update keyword score if already in candidates from Pinecone
                    candidates[chunk_id]["kw"] = max(
                        candidates[chunk_id]["kw"],
                        kw_scores_map.get(bm25_id, 0.0)
                    )
        
        return list(candidates.values())
    
    # -------------------------
    # Score Fusion
    # -------------------------
    
    def _fuse_scores(self, candidates: List[Dict], qvec: np.ndarray) -> List[Dict]:
        """Hybrid fusion with anti-collapse"""
        if not candidates:
            return []
        
        sem_scores = [c["sem"] for c in candidates]
        kw_scores = [c["kw"] for c in candidates]
        
        sem_norm = self._normalize(sem_scores)
        kw_norm = self._normalize(kw_scores)
        
        if self.USE_RRF:
            rrf_scores = self._reciprocal_rank_fusion(candidates)
        else:
            rrf_scores = [0.0] * len(candidates)
        
        fused_scores = []
        for i in range(len(candidates)):
            base = self.HYBRID_ALPHA * sem_norm[i] + (1.0 - self.HYBRID_ALPHA) * kw_norm[i]
            fused = 0.5 * base + 0.5 * rrf_scores[i] if self.USE_RRF else base
            fused_scores.append(fused)
            candidates[i]["score"] = fused
        
        # Anti-collapse re-scoring (if all scores are very similar)
        if max(fused_scores) - min(fused_scores) < 1e-6:
            # Re-fetch embeddings from Pinecone if needed
            for c in candidates:
                if c.get("emb") is None and c["sem"] > 0:
                    # Use semantic score as proxy since we don't have vectors
                    c["score"] = c["sem"]
        
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates
    
    def _reciprocal_rank_fusion(self, candidates: List[Dict]) -> List[float]:
        """RRF: Combine semantic and keyword rankings"""
        sem_rank = sorted(range(len(candidates)), key=lambda i: candidates[i]["sem"], reverse=True)
        kw_rank = sorted(range(len(candidates)), key=lambda i: candidates[i]["kw"], reverse=True)
        
        rrf_scores = [0.0] * len(candidates)
        for rank, idx in enumerate(sem_rank, start=1):
            rrf_scores[idx] += 1.0 / (self.RRF_K + rank)
        for rank, idx in enumerate(kw_rank, start=1):
            rrf_scores[idx] += 1.0 / (self.RRF_K + rank)
        
        return self._normalize(rrf_scores)
    
    # -------------------------
    # MMR Diversity
    # -------------------------
    
    def _mmr_select(self, candidates: List[Dict], k: int) -> List[Dict]:
        """MMR diversity selection (simplified without embeddings)"""
        if len(candidates) <= k:
            return candidates
        
        # Take top K by score (simplified since we don't have embeddings)
        return candidates[:k]
    
    # -------------------------
    # Parent Pooling
    # -------------------------
    
    def _parent_pool(self, chunk_results: List[Dict]) -> List[Dict]:
        """Aggregate chunks to parent documents"""
        by_parent: Dict[str, Dict] = {}
        
        # Parent ID keys vary by corpus type
        parent_keys = {
            "resumes": ["parent_id", "resume_id", "document_id"],
            "jobs": ["parent_id", "job_id", "document_id"],
            "training": ["parent_id", "post_id", "document_id"],
            "assistance": ["parent_id", "post_id", "document_id"],
        }
        
        keys_to_try = parent_keys.get(self.corpus_type, ["parent_id", "document_id"])
        
        for c in chunk_results:
            md = c.get("meta") or {}
            
            # Try to find parent ID
            parent_id = None
            for key in keys_to_try:
                parent_id = md.get(key)
                if parent_id:
                    break
            
            if not parent_id:
                parent_id = md.get("chunk_parent") or md.get("chunk_id") or c.get("chunk_id") or "unknown"
            
            if parent_id not in by_parent or c["score"] > by_parent[parent_id]["score"]:
                # Get text from chunk metadata or doc field
                text_content = md.get("text", "") or c.get("doc", "")
                by_parent[parent_id] = {
                    "parent_id": parent_id,
                    "document_id": parent_id,
                    "score": c["score"],
                    "semantic_score": c.get("sem", 0.0),  # Individual semantic score
                    "bm25_score": c.get("kw", 0.0),  # Individual keyword score
                    "preview": text_content[:800],
                    "text": text_content,  # Full text for display
                    "meta": md,
                }
        
        # Extract corpus-specific fields
        for parent_id, result in by_parent.items():
            result.update(self._extract_corpus_fields(result["meta"]))
        
        # Sort and compute match %
        ranked = sorted(by_parent.values(), key=lambda r: r["score"], reverse=True)
        if ranked:
            vmax = max(r["score"] for r in ranked)
            if vmax > 0:
                for r in ranked:
                    r["match_pct"] = int(round(100 * (r["score"] / vmax)))
            else:
                for r in ranked:
                    r["match_pct"] = 0
        
        return ranked
    
    def _extract_corpus_fields(self, meta: Dict) -> Dict:
        """Extract corpus-specific fields from metadata"""
        if self.corpus_type == "resumes":
            # Return all available fields from metadata
            return {
                "name": meta.get("candidate_name") or meta.get("name") or "Unknown",
                "candidate_name": meta.get("candidate_name"),
                "email": meta.get("email") or "",
                "phone": meta.get("phone") or "",
                "current_role": meta.get("current_role") or "",
                "experience_years": meta.get("experience_years") or meta.get("experience") or "",
                "experience": meta.get("experience") or "",
                "skills": meta.get("skills") or "",
                "education": meta.get("education") or "",
                "location": meta.get("location") or "",
                "file_path": meta.get("file_path") or "",
                "file_name": meta.get("file_name") or "",
            }
        elif self.corpus_type == "jobs":
            return {
                "title": meta.get("title"),
                "company": meta.get("company"),
                "location": meta.get("location"),
                "url": meta.get("url"),
                "job_type": meta.get("job_type"),
                "required_skills": meta.get("required_skills"),
            }
        elif self.corpus_type == "training":
            return {
                "center_name": meta.get("center_name"),
                "courses_offered": meta.get("courses_offered"),
                "course_duration": meta.get("course_duration"),
                "certification": meta.get("certification"),
                "email": meta.get("email"),
                "phone": meta.get("phone"),
                "address": meta.get("address"),
            }
        elif self.corpus_type == "assistance":
            return {
                "center_name": meta.get("center_name"),
                "services": meta.get("services"),
                "operating_hours": meta.get("operating_hours"),
                "email": meta.get("email"),
                "phone": meta.get("phone"),
                "address": meta.get("address"),
            }
        else:
            return {}
    
    def _filter_existing_parents(self, results: List[Dict]) -> List[Dict]:
        """Remove results for deleted documents"""
        # For Pinecone, we trust the index is up-to-date
        # Optionally, you could query Pinecone to verify existence
        return results
    
    def _exists_parent_in_pinecone(self, parent_id: str) -> bool:
        """Check if parent document still exists in Pinecone"""
        try:
            # Query Pinecone by metadata filter
            results = self.index.query(
                vector=[0.0] * 768,  # Dummy vector
                top_k=1,
                filter={"parent_id": parent_id},
                namespace=self.namespace
            )
            return bool(results.get('matches'))
        except:
            return True  # Assume exists if query fails
    
    # -------------------------
    # Utilities
    # -------------------------
    
    @staticmethod
    def _normalize(values: List[float]) -> List[float]:
        """Min-max normalize to [0, 1]"""
        if not values:
            return []
        vmin, vmax = min(values), max(values)
        if vmax - vmin < 1e-9:
            return [0.0] * len(values)
        return [(v - vmin) / (vmax - vmin) for v in values]
    
    @staticmethod
    def _cosine_sim(a, b):
        """Cosine similarity"""
        a, b = np.array(a), np.array(b)
        norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    @staticmethod
    def _normalize_for_bm25(text: str) -> str:
        """Normalize tech terms for BM25"""
        text = (text or "").lower()
        for old, new in ALIASES.items():
            text = text.replace(old, new)
        return text
    
    @staticmethod
    def _strip_rtf_noise(text: str) -> str:
        """Remove RTF formatting"""
        if not isinstance(text, str):
            return ""
        s = text
        if s.lstrip().startswith("{\\rtf"):
            s = re.sub(r"[{}]", " ", s)
            s = re.sub(r"\\[a-zA-Z]+\d* ?", " ", s)
        return re.sub(r"\s+", " ", s).strip()
    
    def _load_bm25_index(self, corpus_path, docids_path, meta_path):
        """Load BM25 index"""
        class _NullBM25:
            corpus_size = 0
            def get_scores(self, tokens):
                return []
        
        if not (os.path.exists(corpus_path) and os.path.exists(docids_path)):
            return _NullBM25(), [], {}, {}
        
        with open(corpus_path, "rb") as f:
            corpus_tokens = pickle.load(f)
        with open(docids_path, "rb") as f:
            doc_ids = pickle.load(f)
        
        if not corpus_tokens or all((not d) for d in corpus_tokens):
            bm25 = _NullBM25()
        else:
            bm25 = BM25Okapi(corpus_tokens)
        
        id2pos = {d: i for i, d in enumerate(doc_ids)}
        
        meta_by_id = {}
        if os.path.exists(meta_path) and os.path.getsize(meta_path) > 0:
            with open(meta_path, "rb") as f:
                meta_by_id = pickle.load(f)
        
        return bm25, doc_ids, id2pos, meta_by_id

