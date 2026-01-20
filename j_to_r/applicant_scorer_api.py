"""
applicant_scorer_api.py
----------------------
Standalone API module for scoring job applicants using AI matching.

This module provides a simple Python API that can be integrated with
external applicant tracking systems (ATS) or HR management platforms.

Usage Example:
    from j_to_r.applicant_scorer_api import ApplicantScorer

    # Initialize
    scorer = ApplicantScorer()

    # Define job
    job_description = {
        "title": "Java Full Stack Developer",
        "description": "We need experienced developers...",
        "required_skills": ["Java", "Spring Boot", "React", "AWS"]
    }

    # List of applicants (from your ATS database)
    applicant_resume_ids = [
        "resume_001",
        "resume_002",
        "resume_003"
    ]

    # Get scores
    results = scorer.score_applicants(job_description, applicant_resume_ids)

    # Process results
    for result in results:
        print(f"{result['candidate_name']}: {result['status']} (Rank: {result['rank']})")
"""

from __future__ import annotations
from typing import Dict, List, Optional
import chromadb
import requests

# Import from local modules
from config_jds_resumes import (
    CHROMA_DIR_RESUMES,
    CHROMA_COLLECTION_RESUMES,
    OLLAMA_HOST,
    EMBED_MODEL,
    R2J_QUERY_CHUNK_SIZE,
    R2J_QUERY_CHUNK_OVERLAP,
    R2J_QUERY_MAX_CHUNKS,
)


class ApplicantScorer:
    """
    Score job applicants using AI-powered semantic matching.
    """

    def __init__(self, chroma_dir: Optional[str] = None, collection_name: Optional[str] = None):
        """
        Initialize the applicant scorer.

        Args:
            chroma_dir: Path to ChromaDB directory (defaults to config)
            collection_name: Name of resume collection (defaults to config)
        """
        self.chroma_dir = chroma_dir or CHROMA_DIR_RESUMES
        self.collection_name = collection_name or CHROMA_COLLECTION_RESUMES
        self.client = chromadb.PersistentClient(path=self.chroma_dir)
        self.collection = self.client.get_collection(name=self.collection_name)

    def score_applicants(
        self,
        job_description: Dict[str, any],
        applicant_resume_ids: List[str],
        extended_results: bool = False
    ) -> List[Dict]:
        """
        Score a list of applicants against a job description.

        Args:
            job_description: Dict with keys 'title', 'description', 'required_skills' (list)
            applicant_resume_ids: List of resume IDs to score
            extended_results: If True, include full diagnostic scores

        Returns:
            List of dicts with applicant scores and ranks
        """
        # Compose JD text
        jd_text = self._compose_jd_text(job_description)

        # Embed the JD
        query_vector = self._embed_text(jd_text)
        if not query_vector:
            raise ValueError("Failed to generate embedding for job description")

        # Retrieve candidates (get more than top 10 to ensure coverage)
        extended_top_k = 200
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=extended_top_k,
            include=["documents", "distances", "metadatas"],
        )

        # Process results
        ids = results.get("ids", [[]])[0]
        dists = results.get("distances", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        docs = results.get("documents", [[]])[0]

        # Convert distances to similarities
        sims = self._distances_to_similarities([float(d) for d in dists])
        sims_norm = self._normalize(sims)

        # Aggregate by resume ID
        by_resume = {}
        for _id, md, doc, sim in zip(ids, metas, docs, sims_norm):
            resume_id = (md or {}).get("resume_id") or (md or {}).get("parent_id") or _id.split("::")[0]
            if not resume_id:
                continue

            if resume_id not in by_resume or sim > by_resume[resume_id]["sim"]:
                by_resume[resume_id] = {
                    "resume_id": resume_id,
                    "candidate_name": (md or {}).get("candidate_name"),
                    "email": (md or {}).get("email"),
                    "phone": (md or {}).get("phone"),
                    "sim": float(sim),
                    "preview": (doc or "")[:200].replace("\n", " "),
                }

        # Rank ALL results
        all_ranked = sorted(by_resume.values(), key=lambda x: x["sim"], reverse=True)

        if not all_ranked:
            return []

        # Calculate match percentages
        hi = max(x["sim"] for x in all_ranked) or 1.0
        lo = min(x["sim"] for x in all_ranked)
        span = hi - lo if hi > lo else 1.0

        for idx, x in enumerate(all_ranked):
            x["match_pct"] = round(100.0 * ((x["sim"] - lo) / span), 1)
            x["rank"] = idx + 1

            # Assign status
            if x["rank"] <= 10:
                x["status"] = "Top 10"
            else:
                x["status"] = f"Ranked #{x['rank']}"

        # Build lookup
        results_by_id = {x["resume_id"]: x for x in all_ranked}

        # Prepare response for requested applicants
        applicant_results = []
        for resume_id in applicant_resume_ids:
            if resume_id in results_by_id:
                applicant_results.append(results_by_id[resume_id])
            else:
                # Not found
                applicant_results.append({
                    "resume_id": resume_id,
                    "candidate_name": None,
                    "email": None,
                    "phone": None,
                    "match_pct": 0.0,
                    "rank": None,
                    "status": "Not Matched",
                    "sim": 0.0,
                    "preview": "Resume not found in AI index or similarity too low",
                })

        return applicant_results

    def get_top_matches(self, job_description: Dict[str, any], top_k: int = 10) -> List[Dict]:
        """
        Get the top K matching resumes for a job description.

        Args:
            job_description: Dict with keys 'title', 'description', 'required_skills' (list)
            top_k: Number of top matches to return (default: 10)

        Returns:
            List of top matching candidates
        """
        jd_text = self._compose_jd_text(job_description)
        query_vector = self._embed_text(jd_text)

        if not query_vector:
            raise ValueError("Failed to generate embedding")

        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=40,
            include=["documents", "distances", "metadatas"],
        )

        # Process and aggregate
        by_resume = {}
        for _id, md, doc, dist in zip(
            results["ids"][0],
            results["metadatas"][0],
            results["documents"][0],
            results["distances"][0]
        ):
            resume_id = (md or {}).get("resume_id") or _id.split("::")[0]
            sim = 1.0 - float(dist)  # Convert distance to similarity

            if resume_id not in by_resume or sim > by_resume[resume_id]["sim"]:
                by_resume[resume_id] = {
                    "resume_id": resume_id,
                    "candidate_name": (md or {}).get("candidate_name"),
                    "email": (md or {}).get("email"),
                    "phone": (md or {}).get("phone"),
                    "sim": sim,
                    "preview": (doc or "")[:200],
                }

        # Sort and return top K
        ranked = sorted(by_resume.values(), key=lambda x: x["sim"], reverse=True)[:top_k]
        return ranked

    # ---- Helper methods ----

    def _compose_jd_text(self, job_description: Dict) -> str:
        """Compose job description text from dict."""
        title = job_description.get("title", "")
        desc = job_description.get("description", "")
        skills = job_description.get("required_skills", [])

        if isinstance(skills, list):
            skills_str = ", ".join(skills)
        else:
            skills_str = str(skills)

        return f"""
Job Title: {title}
Description: {desc}
Required Skills: {skills_str}
""".strip()

    def _embed_text(self, text: str) -> List[float]:
        """Embed text using Ollama with chunking and pooling."""
        chunks = self._chunk_text(text)
        if not chunks:
            return []

        # Embed each chunk
        vecs = []
        for chunk in chunks:
            resp = requests.post(
                f"{OLLAMA_HOST}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": chunk},
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            vec = data.get("embedding")
            if vec is None:
                items = data.get("data") or []
                if items and isinstance(items[0], dict):
                    vec = items[0].get("embedding")
            if vec:
                vecs.append(vec)

        if not vecs:
            return []

        # Pool with length-weighted mean
        dims = len(vecs[0])
        pooled = [0.0] * dims
        weights = [len(ch) for ch in chunks]
        total_weight = float(sum(weights) or 1.0)

        for vec, w in zip(vecs, weights):
            for i in range(dims):
                pooled[i] += float(w) * float(vec[i])

        for i in range(dims):
            pooled[i] /= total_weight

        return pooled

    def _chunk_text(self, text: str, size: int = R2J_QUERY_CHUNK_SIZE,
                    overlap: int = R2J_QUERY_CHUNK_OVERLAP) -> List[str]:
        """Split text into overlapping chunks."""
        n = len(text)
        if n == 0:
            return []
        chunks = []
        start = 0
        while start < n:
            end = min(n, start + size)
            chunks.append(text[start:end])
            if end == n:
                break
            start = end - overlap
        return chunks[:R2J_QUERY_MAX_CHUNKS]

    def _distances_to_similarities(self, dists: List[float]) -> List[float]:
        """Convert cosine distances to similarities."""
        return [1.0 - float(d) for d in dists]

    def _normalize(self, values: List[float]) -> List[float]:
        """Min-max normalize to [0, 1]."""
        if not values:
            return values
        lo, hi = min(values), max(values)
        span = hi - lo
        if span <= 1e-12:
            return [0.0 for _ in values]
        return [(x - lo) / span for x in values]


# ---- Convenience functions for quick use ----

def score_applicants_simple(
    job_title: str,
    job_description: str,
    required_skills: List[str],
    applicant_resume_ids: List[str]
) -> List[Dict]:
    """
    Simplified function to score applicants.

    Args:
        job_title: Job title
        job_description: Job description text
        required_skills: List of required skills
        applicant_resume_ids: List of resume IDs to score

    Returns:
        List of scored applicants with rank and status
    """
    scorer = ApplicantScorer()
    job_desc = {
        "title": job_title,
        "description": job_description,
        "required_skills": required_skills
    }
    return scorer.score_applicants(job_desc, applicant_resume_ids)


if __name__ == "__main__":
    # Example usage
    print("ApplicantScorer API - Example Usage")
    print("=" * 50)

    # Initialize
    scorer = ApplicantScorer()

    # Sample job
    job = {
        "title": "Java Full Stack Developer",
        "description": "We need an experienced Java developer with Spring Boot and React experience",
        "required_skills": ["Java", "Spring Boot", "React", "AWS"]
    }

    # Sample applicants (replace with actual resume IDs from your system)
    applicants = [
        "01_Liam_Carter_Senior_Java_Full_Stack_Engineer_Public_Sector_Systems",
        "02_Ava_Thompson_Lead_Microservices_Engineer_Identity_Access",
        "alex_gupta_java_developer__entry_level",
        "non_existent_resume"
    ]

    print(f"\nScoring {len(applicants)} applicants for: {job['title']}")
    print("-" * 50)

    try:
        results = scorer.score_applicants(job, applicants)

        for result in results:
            status = result.get("status", "Unknown")
            rank = result.get("rank", "N/A")
            match_pct = result.get("match_pct", 0.0)
            name = result.get("candidate_name") or result.get("resume_id")

            print(f"✓ {name}")
            print(f"  Status: {status} | Rank: {rank} | Match: {match_pct}%")
            print()

    except Exception as e:
        print(f"Error: {e}")
