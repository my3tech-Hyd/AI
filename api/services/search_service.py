# api/services/search_service.py
# Service for hybrid search operations
# ----------------------------------------------------------------------

import sys
from pathlib import Path
from typing import List, Dict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pinecone_retriever import PineconeHybridRetriever
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
    EMBED_MODEL,
    OLLAMA_HOST,
    HYBRID_ALPHA,
    K_VEC,
    K_BM25,
    USE_RRF,
    USE_MMR,
    TOP_K_FINAL,
)


class SearchService:
    """Service for performing hybrid searches"""
    
    # Retriever cache (reuse across requests)
    _retrievers = {}
    
    @classmethod
    def get_retriever(cls, corpus_type: str, namespace: str) -> PineconeHybridRetriever:
        """
        Get or create retriever for corpus type
        
        Args:
            corpus_type: "resumes", "jobs", "training", "assistance"
            namespace: Pinecone namespace to query
        """
        cache_key = f"{corpus_type}_{namespace}"
        
        if cache_key not in cls._retrievers:
            # BM25 paths
            bm25_paths = {
                "resumes": (BM25_RESUMES_CORPUS_PATH, BM25_RESUMES_DOCIDS_PATH, BM25_RESUMES_META_PATH),
                "jobs": (BM25_JOBS_CORPUS_PATH, BM25_JOBS_DOCIDS_PATH, BM25_JOBS_META_PATH),
                "training": (BM25_TRAINING_CORPUS_PATH, BM25_TRAINING_DOCIDS_PATH, BM25_TRAINING_META_PATH),
                "assistance": (BM25_ASSISTANCE_CORPUS_PATH, BM25_ASSISTANCE_DOCIDS_PATH, BM25_ASSISTANCE_META_PATH),
            }
            
            corpus_path, docids_path, meta_path = bm25_paths[corpus_type]
            
            # Config
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
            
            # Create retriever
            retriever = PineconeHybridRetriever(
                pinecone_api_key=PINECONE_API_KEY,
                pinecone_index_name=PINECONE_INDEX_NAME,
                bm25_corpus_path=corpus_path,
                bm25_docids_path=docids_path,
                bm25_meta_path=meta_path,
                embed_model=EMBED_MODEL,
                ollama_host=OLLAMA_HOST,
                corpus_type=corpus_type,
                namespace=namespace,
                config=config
            )
            
            cls._retrievers[cache_key] = retriever
        
        return cls._retrievers[cache_key]
    
    @classmethod
    def search(
        cls,
        corpus_type: str,
        namespace: str,
        query_text: str,
        top_k: int = 10
    ) -> List[Dict]:
        """
        Perform hybrid search
        
        Args:
            corpus_type: Type of corpus to search
            namespace: Pinecone namespace
            query_text: Query text
            top_k: Number of results
        
        Returns:
            List of search results with scores and metadata
        """
        retriever = cls.get_retriever(corpus_type, namespace)
        results = retriever.retrieve(query_text, top_k=top_k)
        
        # Format results for API response
        formatted_results = []
        for idx, result in enumerate(results, 1):
            # Base fields (always included)
            formatted_result = {
                "rank": idx,
                "score": result.get("score", 0),
                "score_percentage": f"{result.get('score', 0) * 100:.1f}%",
                "semantic_score": result.get("semantic_score"),
                "keyword_score": result.get("bm25_score"),
            }
            
            # Add corpus-specific fields ONLY (no null fields from other types)
            if corpus_type == "resumes":
                formatted_result.update({
                    "name": result.get("name"),
                    "email": result.get("email"),
                    "phone": result.get("phone"),
                    "skills": result.get("skills"),
                    "experience": result.get("experience") or result.get("experience_years"),
                    "education": result.get("education"),
                    "location": result.get("location"),
                    "text_preview": result.get("text", "")[:500] if result.get("text") else None,
                })
            elif corpus_type == "jobs":
                formatted_result.update({
                    "title": result.get("title"),
                    "company": result.get("company"),
                    "location": result.get("location"),
                    "required_skills": result.get("required_skills"),
                    "experience_required": result.get("experience"),
                    "salary": result.get("salary"),
                    "job_type": result.get("job_type"),
                    "url": result.get("url"),
                    "description_preview": result.get("text", "")[:500] if result.get("text") else None,
                })
            elif corpus_type == "training":
                formatted_result.update({
                    "center_name": result.get("center_name"),
                    "courses": result.get("courses_offered"),
                    "duration": result.get("course_duration"),
                    "certification": result.get("certification"),
                    "email": result.get("email"),
                    "phone": result.get("phone"),
                    "address": result.get("address"),
                    "description_preview": result.get("text", "")[:500] if result.get("text") else None,
                })
            elif corpus_type == "assistance":
                formatted_result.update({
                    "center_name": result.get("center_name"),
                    "services": result.get("services"),
                    "operating_hours": result.get("operating_hours"),
                    "email": result.get("email"),
                    "phone": result.get("phone"),
                    "address": result.get("address"),
                    "description_preview": result.get("text", "")[:500] if result.get("text") else None,
                })
            
            formatted_results.append(formatted_result)
        
        return formatted_results

