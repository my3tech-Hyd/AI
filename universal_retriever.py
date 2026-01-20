# universal_retriever.py
# Generic production-grade hybrid retrieval that works with ANY corpus type
# (resumes, job descriptions, training posts, assistance posts)
# ----------------------------------------------------------------------

import re
import os
import pickle
import numpy as np
from typing import List, Dict, Tuple, Optional, Callable
from pathlib import Path

import chromadb
import requests
from rank_bm25 import BM25Okapi


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


class UniversalHybridRetriever:
    """
    Generic hybrid retriever that works with any corpus type.
    
    Corpus types supported:
    - Resumes (for j_to_r, p_to_r, a_to_r)
    - Job Descriptions (for streamlit_user_r2j.py)
    - Training Posts (for r_to_p)
    - Assistance Posts (for r_to_A)
    
    Features:
    - Hybrid search (Vector + BM25)
    - RRF (Reciprocal Rank Fusion)
    - MMR (Maximal Marginal Relevance)
    - Anti-collapse re-scoring
    - Multi-strategy metadata recovery
    - RTF noise stripping
    """
    
    def __init__(
        self,
        chroma_client,
        chroma_collection,
        bm25_corpus_path: str,
        bm25_docids_path: str,
        bm25_meta_path: str,
        embed_model: str = "nomic-embed-text",
        ollama_host: str = "http://localhost:11434",
        corpus_type: str = "resumes",  # or "jobs", "training", "assistance"
        config: Optional[Dict] = None
    ):
        self.client = chroma_client
        self.coll = chroma_collection
        self.embed_model = embed_model
        self.ollama_host = ollama_host.rstrip("/")
        self.corpus_type = corpus_type
        
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
        
        # Step 2: Union retrieval (vector + BM25)
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
        """Retrieve from both vector and BM25, union results"""
        candidates: Dict[str, Dict] = {}
        
        # Vector side
        try:
            res = self.coll.query(
                query_embeddings=[qvec.tolist()],
                n_results=k_vec,
                include=["documents", "metadatas", "distances", "embeddings"]
            )
            
            ids_v = res.get("ids", [[]])[0]
            docs_v = res.get("documents", [[]])[0]
            metas_v = res.get("metadatas", [[]])[0]
            dists_v = res.get("distances", [[]])[0]
            embs_v = res.get("embeddings", [[]])[0]
            
            has_embs = embs_v is not None and hasattr(embs_v, "__len__") and len(embs_v) >= len(ids_v)
            sem_scores = [1.0 - d for d in dists_v]
            
            for i in range(len(ids_v)):
                raw_id = ids_v[i]
                meta_i = metas_v[i] or {}
                key = meta_i.get("chunk_id", raw_id)
                
                if key not in candidates:
                    candidates[key] = {
                        "chunk_id": key,
                        "doc": self._strip_rtf_noise(docs_v[i] or ""),
                        "sem": 0.0,
                        "kw": 0.0,
                        "meta": meta_i,
                        "emb": embs_v[i] if has_embs else None
                    }
                candidates[key]["sem"] = max(candidates[key]["sem"], sem_scores[i])
        except Exception as e:
            print(f"Vector search failed: {e}")
        
        # BM25 side
        if getattr(self.bm25, "corpus_size", 0) > 0 and self.id2pos:
            normalized = self._normalize_for_bm25(query_text)
            tokens = normalized.split()
            scores = self.bm25.get_scores(tokens)
            
            pairs = [(cid, float(scores[pos])) for cid, pos in self.id2pos.items() if pos < len(scores)]
            pairs.sort(key=lambda x: x[1], reverse=True)
            top_bm25_ids = [cid for cid, _ in pairs[:k_bm25]]
            kw_scores_map = {cid: sc for cid, sc in pairs[:k_bm25]}
            
            bm25_hits = self._bm25_collect_chunks(top_bm25_ids, kw_scores_map)
            
            if not bm25_hits:
                for bm25_id, sc in kw_scores_map.items():
                    md = self.meta_by_id.get(bm25_id, {"chunk_id": bm25_id})
                    cid2 = md.get("chunk_id", f"{bm25_id}::pseudo")
                    if cid2 not in candidates:
                        candidates[cid2] = {
                            "chunk_id": cid2,
                            "doc": "",
                            "sem": 0.0,
                            "kw": sc,
                            "meta": md,
                            "emb": None
                        }
            else:
                for cid2, doc2, meta2, kw_sc in bm25_hits:
                    if cid2 not in candidates:
                        candidates[cid2] = {
                            "chunk_id": cid2,
                            "doc": self._strip_rtf_noise(doc2 or ""),
                            "sem": 0.0,
                            "kw": kw_sc,
                            "meta": meta2,
                            "emb": None
                        }
                    else:
                        candidates[cid2]["kw"] = max(candidates[cid2]["kw"], kw_sc)
        
        return list(candidates.values())
    
    def _bm25_collect_chunks(self, top_bm25_ids: List[str], kw_scores_map: Dict[str, float]) -> List[Tuple]:
        """5-layer fallback for BM25 ID mapping"""
        top_bm25_ids = [str(x) for x in top_bm25_ids if x is not None]
        remaining = set(top_bm25_ids)
        out: Dict[str, Dict] = {}
        include = ["documents", "metadatas"]
        
        def _merge(got, score_key: Optional[str] = None):
            if not got:
                return
            got_ids = got.get("ids") or []
            got_docs = got.get("documents") or []
            got_meta = got.get("metadatas") or []
            
            for i in range(len(got_ids)):
                meta = got_meta[i] or {}
                cid2 = meta.get("chunk_id", got_ids[i])
                
                if score_key:
                    key_val = meta.get(score_key)
                else:
                    key_val = meta.get("chunk_id", got_ids[i])
                
                kw_sc = kw_scores_map.get(str(key_val), 0.0)
                
                if cid2 in out:
                    out[cid2]["kw"] = max(out[cid2]["kw"], kw_sc)
                else:
                    out[cid2] = {"doc": got_docs[i], "meta": meta, "kw": kw_sc}
                
                if key_val and key_val in remaining:
                    remaining.discard(key_val)
        
        # 5 layers
        if remaining:
            try:
                got = self.coll.get(where={"chunk_id": {"$in": list(remaining)}}, include=include)
                _merge(got, score_key="chunk_id")
            except: pass
        
        if remaining:
            try:
                got = self.coll.get(ids=list(remaining), include=include)
                _merge(got, score_key=None)
            except: pass
        
        if remaining:
            try:
                got = self.coll.get(where={"parent_id": {"$in": list(remaining)}}, include=include)
                _merge(got, score_key="parent_id")
            except: pass
        
        if remaining:
            try:
                got = self.coll.get(where={"document_id": {"$in": list(remaining)}}, include=include)
                _merge(got, score_key="document_id")
            except: pass
        
        if remaining:
            try:
                # For training/assistance posts
                got = self.coll.get(where={"post_id": {"$in": list(remaining)}}, include=include)
                _merge(got, score_key="post_id")
            except: pass
        
        if remaining:
            try:
                # For job descriptions
                got = self.coll.get(where={"job_id": {"$in": list(remaining)}}, include=include)
                _merge(got, score_key="job_id")
            except: pass
        
        return [(cid2, v["doc"], v["meta"], v["kw"]) for cid2, v in out.items()]
    
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
        
        # Anti-collapse re-scoring
        if max(fused_scores) - min(fused_scores) < 1e-6:
            try:
                for c in candidates:
                    if c.get("emb") is not None:
                        c["score"] = self._cosine_sim(qvec, np.array(c["emb"]))
            except Exception:
                pass
        
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
        """MMR diversity selection"""
        if len(candidates) <= k:
            return candidates
        
        selected = [candidates[0]]
        remaining = candidates[1:]
        
        while len(selected) < k and remaining:
            best_idx, best_mmr = 0, -np.inf
            
            for i, cand in enumerate(remaining):
                relevance = cand["score"]
                
                if cand.get("emb") is not None:
                    redundancy = max(
                        self._cosine_sim(np.array(cand["emb"]), np.array(sel["emb"]))
                        for sel in selected
                        if sel.get("emb") is not None
                    )
                else:
                    redundancy = 0.0
                
                mmr = self.MMR_LAMBDA * relevance - (1 - self.MMR_LAMBDA) * redundancy
                
                if mmr > best_mmr:
                    best_mmr, best_idx = mmr, i
            
            selected.append(remaining.pop(best_idx))
        
        return selected
    
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
                by_parent[parent_id] = {
                    "parent_id": parent_id,
                    "document_id": parent_id,
                    "score": c["score"],
                    "preview": c.get("doc", "")[:800],
                    "meta": md,  # Keep full metadata for later extraction
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
            return {
                "candidate_name": meta.get("candidate_name"),
                "email": meta.get("email"),
                "phone": meta.get("phone"),
                "file_path": meta.get("file_path"),
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
        kept = []
        for r in results:
            parent_id = r.get("document_id") or r.get("parent_id")
            if parent_id and self._exists_parent_in_chroma(parent_id):
                kept.append(r)
        return kept
    
    def _exists_parent_in_chroma(self, parent_id: str) -> bool:
        """Check if parent document still exists"""
        try:
            got = self.coll.get(where={"parent_id": str(parent_id)})
            return bool(got and got.get("ids"))
        except:
            return False
    
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

