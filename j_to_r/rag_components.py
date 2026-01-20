# rag_components.py
# Retrieval-Augmented Generation components for enhanced ranking and explanations
# ----------------------------------------------------------------------

import re
from typing import List, Dict, Optional
from openai import OpenAI


class RAGReranker:
    """
    LLM-based re-ranking with context awareness.
    
    Benefits:
    - Context-aware ranking (understands nuances beyond keyword/vector matching)
    - Explainable rankings (provides reasoning for each candidate)
    - Better handling of implicit requirements
    
    Use when:
    - High-stakes hiring decisions
    - Complex JDs with implicit requirements
    - Need explainability for rankings
    """
    
    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o-mini"):
        self.client = openai_client
        self.model = model
    
    def rerank(
        self,
        jd_text: str,
        candidates: List[Dict],
        top_k: int = 10,
        include_reasoning: bool = True
    ) -> List[Dict]:
        """
        Re-rank candidates using LLM with context awareness.
        
        Args:
            jd_text: Job description
            candidates: Initial candidates from hybrid retrieval (top 20-30)
            top_k: Number of final results
            include_reasoning: Add 'reasoning' field to each result
        
        Returns:
            Re-ranked candidates with optional reasoning
        """
        if len(candidates) <= top_k:
            return candidates  # No need to re-rank
        
        # Build prompt
        prompt = self._build_reranking_prompt(jd_text, candidates)
        
        # Call LLM
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert technical recruiter analyzing candidate-job fit. "
                                   "Provide precise, evidence-based rankings."
                    },
                    {"role": "user", "content": prompt}
                ]
            )
            
            llm_output = response.choices[0].message.content or ""
            
            # Parse LLM rankings
            rankings = self._parse_llm_rankings(llm_output)
            
            # Apply rankings to candidates
            reranked = self._apply_rankings(candidates, rankings, include_reasoning)
            
            return reranked[:top_k]
        
        except Exception as e:
            print(f"RAG reranking failed: {e}. Returning original order.")
            return candidates[:top_k]
    
    def _build_reranking_prompt(self, jd_text: str, candidates: List[Dict]) -> str:
        """Build context-rich prompt for LLM re-ranking"""
        # Truncate JD if too long
        jd_summary = jd_text[:1500] + ("..." if len(jd_text) > 1500 else "")
        
        prompt = f"""# Job Description
{jd_summary}

# Candidates to Rank ({len(candidates)} total)

"""
        # Add candidate previews
        for i, c in enumerate(candidates, 1):
            doc_id = c.get("document_id") or c.get("parent_id") or f"candidate_{i}"
            preview = c.get("preview", "")[:400]
            preview = preview.replace("\n", " ").strip()
            
            prompt += f"[{i}] {doc_id}\n"
            prompt += f"   {preview}\n\n"
        
        prompt += """# Task
Rank these candidates from 1 (best fit) to {count} (weakest fit) for this job.

For each candidate, provide:
- **Rank**: 1 (best) to {count} (weakest)
- **Score**: 0-100 (fit percentage)
- **Reasoning**: One concise sentence explaining the ranking

Focus on:
- Technical skills match (exact tools, frameworks, versions)
- Experience level alignment (junior/mid/senior)
- Domain experience (industry, project types)
- Implicit requirements (scale, production experience, leadership)

# Output Format
Use this EXACT format (one line per candidate):

[Rank] DocumentID | Score | Reasoning

Example:
[1] resume_abc123.xyz | 95 | 8+ yrs Java/Spring Boot, microservices at scale, AWS prod exp, perfect tech stack match.
[2] resume_def456.uvw | 88 | Strong Java backend, 5 yrs exp, missing AWS but has GCP, can ramp quickly.
[3] resume_ghi789.rst | 82 | Solid fundamentals, 3 yrs exp, lacks specific frameworks but learning curve low.

Begin ranking:
""".replace("{count}", str(len(candidates)))
        
        return prompt
    
    def _parse_llm_rankings(self, llm_output: str) -> List[Dict]:
        """Parse LLM ranking output into structured data"""
        rankings = []
        
        # Pattern: [Rank] DocumentID | Score | Reasoning
        pattern = r'\[(\d+)\]\s+(\S+)\s*\|\s*(\d+)\s*\|\s*(.+?)(?=\n|$)'
        
        for match in re.finditer(pattern, llm_output, re.MULTILINE):
            rank_str, doc_id, score_str, reasoning = match.groups()
            
            try:
                rankings.append({
                    "rank": int(rank_str),
                    "doc_id": doc_id.strip(),
                    "score": int(score_str),
                    "reasoning": reasoning.strip()
                })
            except ValueError:
                continue  # Skip malformed lines
        
        # Sort by rank
        rankings.sort(key=lambda x: x["rank"])
        return rankings
    
    def _apply_rankings(
        self,
        candidates: List[Dict],
        rankings: List[Dict],
        include_reasoning: bool
    ) -> List[Dict]:
        """Apply LLM rankings to original candidates"""
        # Build lookup by document ID
        rank_by_id = {r["doc_id"]: r for r in rankings}
        
        # Map candidates
        ranked_candidates = []
        for c in candidates:
            doc_id = c.get("document_id") or c.get("parent_id")
            
            if doc_id in rank_by_id:
                r = rank_by_id[doc_id]
                # Update score and match_pct based on LLM
                c["rag_score"] = r["score"]
                c["rag_rank"] = r["rank"]
                c["match_pct"] = r["score"]  # Override with LLM score
                
                if include_reasoning:
                    c["reasoning"] = r["reasoning"]
                
                ranked_candidates.append((r["rank"], c))
            else:
                # Not ranked by LLM (fallback to original order)
                ranked_candidates.append((999, c))
        
        # Sort by LLM rank
        ranked_candidates.sort(key=lambda x: x[0])
        
        return [c for _, c in ranked_candidates]


class RAGExplainer:
    """
    Generate detailed, context-aware explanations for candidate-job fit.
    
    Uses retrieved chunks as evidence to ground explanations.
    
    Benefits:
    - Detailed fit analysis beyond simple scores
    - Evidence-based reasoning (quotes from resume)
    - Actionable insights (strengths, gaps, interview questions)
    - Explainability for hiring decisions
    """
    
    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o-mini"):
        self.client = openai_client
        self.model = model
    
    def explain_match(
        self,
        jd_text: str,
        candidate: Dict,
        top_chunks: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Generate detailed explanation for why a candidate matches a JD.
        
        Args:
            jd_text: Job description
            candidate: Candidate result dict
            top_chunks: Optional list of top matching chunks for context
        
        Returns:
            Dict with keys: fit_score, strengths, gaps, evidence, interview_questions
        """
        # Build context from chunks
        if top_chunks:
            context = self._build_context_from_chunks(top_chunks)
        else:
            context = candidate.get("preview", "")[:1500]
        
        # Generate explanation
        prompt = self._build_explanation_prompt(jd_text, context, candidate)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.3,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a technical recruiter providing detailed candidate assessments. "
                                   "Be specific and quote evidence from resumes."
                    },
                    {"role": "user", "content": prompt}
                ]
            )
            
            explanation_text = response.choices[0].message.content or ""
            
            # Parse structured output
            return self._parse_explanation(explanation_text)
        
        except Exception as e:
            print(f"RAG explanation failed: {e}")
            return {
                "fit_score": candidate.get("match_pct", 0),
                "strengths": ["Unable to generate explanation"],
                "gaps": [],
                "evidence": [],
                "interview_questions": []
            }
    
    def _build_context_from_chunks(self, chunks: List[Dict]) -> str:
        """Build context string from top matching chunks"""
        context_parts = []
        for i, chunk in enumerate(chunks[:10], 1):
            text = chunk.get("doc", "") or chunk.get("text", "")
            if text:
                context_parts.append(f"[Section {i}]\n{text[:500]}")
        return "\n\n".join(context_parts)
    
    def _build_explanation_prompt(self, jd_text: str, context: str, candidate: Dict) -> str:
        """Build prompt for detailed fit explanation"""
        jd_summary = jd_text[:1500] + ("..." if len(jd_text) > 1500 else "")
        
        prompt = f"""# Job Requirements
{jd_summary}

# Candidate Resume (Relevant Sections)
{context}

# Task
Analyze this candidate's fit for the role. Provide:

## 1. Fit Score (0-100)
One number with brief rationale.

## 2. Key Strengths (5-8 bullets)
Specific capabilities that match job requirements.
**Quote exact phrases** from resume as evidence.
Format: Strength | Evidence

Example:
- **8+ years Java/Spring Boot experience** | "Led development of microservices platform using Spring Boot 2.x for 5 years at TechCorp"
- **AWS production expertise** | "Deployed and managed 20+ services on AWS ECS, handled 10M+ requests/day"

## 3. Skill Gaps (3-5 bullets)
Missing or weak areas compared to job requirements.
Be specific about what's missing.

Example:
- **Kubernetes experience**: JD requires K8s orchestration, resume shows only Docker
- **React frontend**: JD needs full-stack, resume is backend-focused

## 4. Evidence Quotes (4-6 direct quotes)
Pull exact phrases that demonstrate key qualifications.

## 5. Interview Focus Areas (4-6 questions)
Technical questions to probe based on JD requirements and resume claims.

Example:
- "Describe your largest Spring Boot microservices deployment. How did you handle inter-service communication?"
- "Walk through your AWS architecture for a high-traffic application. What services did you use and why?"

# Output Format
Use markdown with clear section headers. Be specific and evidence-based.
"""
        return prompt
    
    def _parse_explanation(self, llm_output: str) -> Dict:
        """Parse LLM explanation into structured format"""
        result = {
            "fit_score": 0,
            "strengths": [],
            "gaps": [],
            "evidence": [],
            "interview_questions": [],
            "full_text": llm_output
        }
        
        # Extract fit score
        score_match = re.search(r'(?:fit score|score):\s*(\d+)', llm_output, re.IGNORECASE)
        if score_match:
            result["fit_score"] = int(score_match.group(1))
        
        # Extract strengths (bullets under "Strengths" section)
        strengths_section = re.search(r'#+\s*(?:key\s+)?strengths.*?\n(.*?)(?=\n#+|\Z)', llm_output, re.IGNORECASE | re.DOTALL)
        if strengths_section:
            bullets = re.findall(r'[-*]\s*(.+?)(?=\n[-*]|\n\n|\Z)', strengths_section.group(1), re.DOTALL)
            result["strengths"] = [b.strip() for b in bullets if b.strip()]
        
        # Extract gaps
        gaps_section = re.search(r'#+\s*(?:skill\s+)?gaps.*?\n(.*?)(?=\n#+|\Z)', llm_output, re.IGNORECASE | re.DOTALL)
        if gaps_section:
            bullets = re.findall(r'[-*]\s*(.+?)(?=\n[-*]|\n\n|\Z)', gaps_section.group(1), re.DOTALL)
            result["gaps"] = [b.strip() for b in bullets if b.strip()]
        
        # Extract evidence quotes
        evidence_section = re.search(r'#+\s*evidence.*?\n(.*?)(?=\n#+|\Z)', llm_output, re.IGNORECASE | re.DOTALL)
        if evidence_section:
            bullets = re.findall(r'[-*]\s*(.+?)(?=\n[-*]|\n\n|\Z)', evidence_section.group(1), re.DOTALL)
            result["evidence"] = [b.strip() for b in bullets if b.strip()]
        
        # Extract interview questions
        interview_section = re.search(r'#+\s*interview.*?\n(.*?)(?=\n#+|\Z)', llm_output, re.IGNORECASE | re.DOTALL)
        if interview_section:
            bullets = re.findall(r'[-*]\s*(.+?)(?=\n[-*]|\n\n|\Z)', interview_section.group(1), re.DOTALL)
            result["interview_questions"] = [b.strip() for b in bullets if b.strip()]
        
        return result


class RAGContextBuilder:
    """
    Build rich context for RAG operations by retrieving and organizing
    the most relevant chunks from candidates.
    """
    
    @staticmethod
    def get_top_chunks_for_candidate(
        coll,
        candidate: Dict,
        qvec: List[float],
        k: int = 10
    ) -> List[Dict]:
        """
        Retrieve top K chunks for a specific candidate (parent document).
        Useful for building context for explanations.
        """
        parent_id = candidate.get("document_id") or candidate.get("parent_id")
        if not parent_id:
            return []
        
        try:
            # Query for chunks belonging to this parent
            results = coll.query(
                query_embeddings=[qvec],
                where={"parent_id": str(parent_id)},
                n_results=k,
                include=["documents", "metadatas", "distances"]
            )
            
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            
            chunks = []
            for i in range(len(ids)):
                chunks.append({
                    "chunk_id": ids[i],
                    "doc": docs[i],
                    "meta": metas[i],
                    "similarity": 1.0 - dists[i]
                })
            
            # Sort by similarity
            chunks.sort(key=lambda x: x["similarity"], reverse=True)
            return chunks
        
        except Exception as e:
            print(f"Failed to retrieve chunks for {parent_id}: {e}")
            return []
    
    @staticmethod
    def build_candidate_summary(candidate: Dict, chunks: List[Dict]) -> str:
        """
        Build a concise summary of candidate from top chunks.
        Useful for feeding to LLM for re-ranking/explanation.
        """
        # Get contact info
        email = candidate.get("email") or "N/A"
        phone = candidate.get("phone") or "N/A"
        
        # Combine top chunk texts
        texts = [c.get("doc", "") for c in chunks[:5]]
        combined = " ".join(texts)[:1500]
        
        summary = f"""Candidate: {candidate.get('document_id')}
Email: {email}
Phone: {phone}

Key Content:
{combined}
"""
        return summary

