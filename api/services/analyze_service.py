# api/services/analyze_service.py
# Service for AI-powered analysis using OpenAI
# ----------------------------------------------------------------------

import os
from typing import Dict, List

# Import OpenAI and httpx to create a custom http client
try:
    from openai import OpenAI
    import httpx
except ImportError:
    raise ImportError("OpenAI library not installed. Run: pip install openai==1.54.3")


class AnalyzeService:
    """Service for generating AI-powered analysis"""
    
    def __init__(self):
        # Initialize OpenAI client - only pass api_key to avoid version conflicts
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        # Initialize client with only api_key parameter
        # Workaround for httpx/OpenAI version incompatibility with proxies parameter
        # The issue is that OpenAI 1.54.3 tries to pass 'proxies' to httpx.Client
        # but httpx 0.28.1 doesn't accept it in the same way
        try:
            # Create a custom httpx client without proxy settings to avoid the issue
            # This bypasses the automatic proxy detection that causes the error
            http_client = httpx.Client(
                timeout=httpx.Timeout(60.0),
                follow_redirects=True
            )
            
            # Initialize OpenAI with the custom http_client
            self.client = OpenAI(
                api_key=api_key,
                http_client=http_client
            )
        except TypeError as e:
            error_msg = str(e)
            if "proxies" in error_msg.lower():
                # If custom http_client doesn't work, try without it
                try:
                    # Fallback: try direct initialization
                    self.client = OpenAI(api_key=api_key)
                except Exception as e2:
                    import openai
                    openai_version = getattr(openai, '__version__', 'unknown')
                    httpx_version = getattr(httpx, '__version__', 'unknown')
                    raise ValueError(
                        f"OpenAI client initialization failed: {error_msg}\n"
                        f"OpenAI version: {openai_version}\n"
                        f"httpx version: {httpx_version}\n"
                        f"This is a known compatibility issue between OpenAI 1.54.3 and httpx.\n"
                        f"Try: pip install --upgrade httpx"
                    ) from e2
            else:
                raise
        except Exception as e:
            raise ValueError(f"Failed to initialize OpenAI client: {str(e)}") from e
        
        self.model = "gpt-4o-mini"
    
    def analyze_match(
        self,
        query_type: str,
        query_json: Dict,
        resume_json: Dict,
        analysis_type: str = "detailed"
    ) -> Dict:
        """
        Generate AI analysis of a match
        
        Args:
            query_type: Type of query ("jd_to_resume", "resume_to_jd", etc.)
            query_text: Original query text
            match_text: Text of the matched document
            match_metadata: Metadata of the match
            analysis_type: "detailed", "brief", or "comparison"
        
        Returns:
            Analysis dictionary with fit_score, summary, strengths, gaps, recommendations
        """
        # Build prompt based on query type
        system_prompt, user_prompt = self._build_prompts(query_type, query_json, resume_json)
        
        # Call OpenAI
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                temperature=0.25,
                max_tokens=2000
            )
            
            analysis_text = response.choices[0].message.content or ""
            
            # Return full markdown analysis (matches Streamlit behavior)
            return {
                "fit_score": 75,  # Default - can be extracted if needed
                "summary": analysis_text[:500] + "..." if len(analysis_text) > 500 else analysis_text,
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "detailed_analysis": analysis_text  # Full markdown report
            }
            
        except Exception as e:
            # Return error as analysis
            return {
                "fit_score": 0,
                "summary": f"Analysis failed: {str(e)}",
                "strengths": [],
                "gaps": ["Analysis service unavailable"],
                "recommendations": ["Try again later"],
                "detailed_analysis": f"Error: {str(e)}"
            }
    
    def _build_prompts(
        self,
        query_type: str,
        query_json: Dict,
        resume_json: Dict
    ) -> tuple:
        """Build system and user prompts based on query type - matches Streamlit generative files"""
        import json
        
        if query_type == "jd_to_resume":
            system_prompt = """You are a senior Hiring Manager & Technical Recruiter.
Given one job posting and one candidate resume, produce an employer-ready assessment.
Be concrete, evidence-based (quote/point to phrases), and decisive. Avoid generic fluff."""
            
            user_prompt = f"""You are given two JSON payloads:

[JOB_POSTING]
{json.dumps(query_json, ensure_ascii=False, indent=2)}

[CANDIDATE_RESUME]
{json.dumps(resume_json, ensure_ascii=False, indent=2)}

GOAL:
Help an employer decide whether this candidate fits the role. If not, make it clear why—and what conditions/mentoring would change the decision.

TASKS (Markdown output):
1) Executive Fit Summary (6–10 sentences)
   - WHY this candidate is/isn't aligned with the role, stack, and level.
   - Mention obvious matches and the most critical gaps.
2) Requirements Match Matrix
   - Table-style bullets: each key requirement → (Evidence from resume | Strength / Partial / Gap).
   - Include the "Qualifications & Educations" check explicitly.
3) Concrete Evidence & Signals
   - Quote or reference 6–10 specific phrases/lines from the resume that support/contradict the fit.
4) Risks & Red Flags (5–10 bullets)
   - Tenure stability, seniority mismatch, missing production scale, version/tool gaps, compliance, etc.
5) Interview Plan
   - Technical deep-dive areas (5–8 topics) with 1–2 sample questions each.
   - Systems/Code exercise suggestion tailored to the role.
6) Calibration & Leveling
   - Suggested level (e.g., Junior/Mid/Senior) and scope of work they can own in the first quarter.
7) Offer Recommendation
   - One of: Strong Hire / Lean Hire / Neutral / Lean No / Strong No (bold the decision).
   - If not a clear hire, list "conditions to convert to hire" (mentorship, ramp plan, trial task).
8) Candidate Feedback (shareable)
   - 6–10 constructive bullets you could send to the candidate (no internal language).

CONSTRAINTS:
- Be specific & actionable. Use the provided job fields ("Required Skills", "Qualifications & Educations", etc.).
- Do NOT include raw JSON in the output. Markdown only."""
            
            return system_prompt, user_prompt
        
        elif query_type == "resume_to_jd":
            system_prompt = """You are a Career Counselor & Job Search Strategist.
Given one candidate resume and one job posting, produce a candidate-facing analysis.
Be specific, actionable, and encouraging. Help the candidate understand fit and how to improve."""
            
            user_prompt = f"""You are given two JSON payloads:

[CANDIDATE_RESUME]
{json.dumps(resume_json, ensure_ascii=False, indent=2)}

[JOB_POSTING]
{json.dumps(query_json, ensure_ascii=False, indent=2)}

GOAL:
Help the candidate understand how well they match this job and what they can do to improve their fit.

TASKS (Markdown output):
1) Fit Summary (6–10 sentences)
   - WHY you are/aren't aligned with the role, stack, and level.
   - Mention obvious matches and the most critical gaps.
2) Strengths & Highlights
   - 8–12 bullets: what makes you a strong candidate for THIS role.
3) Gaps & Deal-Breakers (8–12 bullets)
   - Clearly separate **Critical Gaps (must fix)** vs **Nice-to-Have Gaps**.
   - Call out missing stacks, insufficient depth, domain gaps, tool/version mismatches, or soft-skill signals.
4) Skills Alignment Matrix
   - **Matched skills/keywords** (group by category; include exact phrases that appear in your resume).
   - **Missing or weak skills** (group by category; note what the JD expects).
5) Education & Qualifications Check
   - Compare the JD's "Qualifications & Educations" vs your education/certifications.
   - State compliance plainly: Meets / Partially Meets / Does Not Meet, with evidence.
6) Risks / Watch-outs (short bullets)
   - E.g., tenure stability, production scale gaps, leadership vs IC mismatch, ATS risks; be specific.
7) Resume Tweaks for THIS JD (8–12 bullets)
   - Actionable, JD-targeted edits: quantification ideas, phrasing changes, ordering, portfolio/GitHub pointers.
8) Tailored Cover-Letter Hooks (4–6 bullets)
   - Short opening lines you can use that reference the company and role credibly.
9) Optional: JD-Tailored Resume Summary (3–5 sentences)
   - A concise summary you can paste at the top of your resume for this application.

FORMAT:
- Return **Markdown only** with clear section headings.
- Do **not** include raw JSON in the output.
- Use second person ("you") consistently and keep it concise but information-dense.
- When citing evidence, quote short phrases in quotes (no long excerpts)."""
            
            return system_prompt, user_prompt
        
        elif query_type == "training_to_resume":
            system_prompt = """You are a Lead Admissions Officer at a training/skill development center.
Given one training posting and one candidate resume, produce an admissions-ready assessment.
Be concrete, evidence-based, and decisive. Avoid generic fluff."""
            
            user_prompt = f"""You are given two JSON payloads:

[TRAINING_POSTING]
{json.dumps(query_json, ensure_ascii=False, indent=2)}

[CANDIDATE_RESUME]
{json.dumps(resume_json, ensure_ascii=False, indent=2)}

GOAL:
Help the training center decide if this candidate is a strong fit for its programs right now. If not, explain why—and specify what needs to change.

TASKS (Markdown output):
1) Fit Summary (6–10 sentences)
   - WHY the candidate is/isn't aligned with the center's courses, format, and goals.
   - Mention the most impactful courses for them and critical mismatches (if any).
2) Candidate Needs & Goals
   - Infer short-term and long-term goals from resume signals; call out uncertainties explicitly.
3) Courses Mapping Table
   - For each course in "Courses Offered", provide:
     - Relevance (High/Medium/Low)
     - Expected impact (what outcome the candidate should see)
     - How to measure success (KPIs: projects completed, certifications earned, etc.)
4) Evidence From Resume
   - Quote or reference 6–10 specific phrases/lines that support/contradict the fit.
5) Gaps & Coaching Plan (8–12 bullets)
   - Exact gaps (foundations, tooling, consistency), with actionable steps.
6) Engagement Plan & Timeline
   - Weekly plan aligned to "Course Duration" and center capacity; include milestones, projects, and assessments.
7) Risks & Mitigation (5–10 bullets)
   - Time availability, foundations (math/programming), tooling, consistency; give concrete mitigations.
8) Decision & Conditions
   - One of: **Strong Admit / Admit / Waitlist / Reject** (bold the decision).
   - If not a clear admit, list "conditions to admit" (bridge study, probation period, mentor check-ins).
9) 30/60/90-Day Learning Plan (bullets)
   - Weekly milestones aligned to "Course Duration"; measurable outcomes (projects, certifications).

CONSTRAINTS:
- Ground suggestions in the "Courses Offered" list and center's "Description".
- State assumptions when information is missing.
- Do NOT include raw JSON in the output. Markdown only."""
            
            return system_prompt, user_prompt
        
        elif query_type == "resume_to_training":
            system_prompt = """You are a Career Counselor & Training Advisor.
Given one candidate resume and one training posting, produce a candidate-facing analysis.
Be specific, actionable, and encouraging. Help the candidate understand if this training is right for them."""
            
            user_prompt = f"""You are given two JSON payloads:

[CANDIDATE_RESUME]
{json.dumps(resume_json, ensure_ascii=False, indent=2)}

[TRAINING_POSTING]
{json.dumps(query_json, ensure_ascii=False, indent=2)}

GOAL:
Help the candidate understand if this training program is right for them and how it will help their career.

TASKS (Markdown output):
1) Fit Summary (6–10 sentences)
   - WHY this training is/isn't aligned with your goals, background, and career path.
2) Strengths & Readiness
   - 8–12 bullets: what makes you ready for this training.
3) Gaps & Prerequisites (8–12 bullets)
   - What you need to know/do before starting.
4) Courses Alignment
   - For each course, explain how it helps your career.
5) Learning Plan
   - What you'll learn week by week.
6) Career Impact
   - How this training will advance your career.
7) Risks & Mitigation
   - Potential challenges and how to overcome them.
8) Decision Recommendation
   - One of: **Strong Fit / Good Fit / Conditional / Not Recommended** (bold the decision).

CONSTRAINTS:
- Use second person ("you") consistently.
- Be specific and actionable.
- Do NOT include raw JSON in the output. Markdown only."""
            
            return system_prompt, user_prompt
        
        elif query_type == "assistance_to_resume":
            system_prompt = """You are a Lead Career Counselor at a job assistance center.
Given one assistance center posting and one candidate resume, produce an intake decision report.
Be concrete, evidence-based, and decisive. Avoid generic fluff."""
            
            user_prompt = f"""You are given two JSON payloads:

[ASSISTANCE_CENTER_POSTING]
{json.dumps(query_json, ensure_ascii=False, indent=2)}

[CANDIDATE_RESUME]
{json.dumps(resume_json, ensure_ascii=False, indent=2)}

GOAL:
Help the assistance center decide if this candidate is a strong fit for its services right now. If not, explain why—and specify what needs to change.

TASKS (Markdown output):
1) Fit Summary (6–10 sentences)
   - WHY the candidate is/isn't aligned with the center's services, format, and goals.
   - Mention the most impactful services for them and critical mismatches (if any).
2) Candidate Needs & Goals
   - Infer short-term and long-term goals from resume signals; call out uncertainties explicitly.
3) Services Mapping Table
   - For each service in "Services", provide:
     - Relevance (High/Medium/Low)
     - Expected impact (what outcome the candidate should see)
     - How to measure success (KPIs: interviews scheduled, offers, ATS passes, etc.)
4) Evidence From Resume
   - Quote or reference 6–10 specific phrases/lines that support/contradict the fit.
5) Gaps & Coaching Plan (8–12 bullets)
   - Exact gaps (resume structure, storytelling, project depth, interviewing, soft skills), with actionable steps.
6) Engagement Plan & Timeline
   - Weekly plan aligned to "Operating Hours" and center capacity; include mock interviews, resume rewrites, and placement activities.
7) Risks & Mitigation (5–10 bullets)
   - Time constraints, skill mismatch, motivation, communication; provide concrete mitigations.
8) Decision & Conditions
   - One of: **Strong Enroll / Enroll / Conditional / Not a Fit** (bold the decision).
   - If conditional or not a fit, list "conditions to enroll" (bridge study, minimum portfolio pieces, diagnostics).
9) Candidate-Facing Feedback (shareable)
   - 6–10 constructive bullets the center can send the candidate (no internal language).

CONSTRAINTS:
- Ground suggestions in the center's "Services" and "Description".
- Be specific & actionable; avoid generic statements.
- Do NOT include the raw JSON in the output. Markdown only."""
            
            return system_prompt, user_prompt
        
        elif query_type == "resume_to_assistance":
            system_prompt = """You are a Career Counselor & Assistance Advisor.
Given one candidate resume and one assistance center posting, produce a candidate-facing analysis.
Be specific, actionable, and encouraging. Help the candidate understand if these services are right for them."""
            
            user_prompt = f"""You are given two JSON payloads:

[CANDIDATE_RESUME]
{json.dumps(resume_json, ensure_ascii=False, indent=2)}

[ASSISTANCE_CENTER_POSTING]
{json.dumps(query_json, ensure_ascii=False, indent=2)}

GOAL:
Help the candidate understand if this assistance center's services are right for them and how they will help.

TASKS (Markdown output):
1) Fit Summary (6–10 sentences)
   - WHY these services are/isn't aligned with your needs and goals.
2) Services Alignment
   - For each service, explain how it helps you.
3) Benefits & ROI
   - What you'll gain from these services.
4) Engagement Plan
   - How to work with the center.
5) Expected Outcomes
   - What you can expect to achieve.
6) Decision Recommendation
   - One of: **Strong Fit / Good Fit / Conditional / Not Recommended** (bold the decision).

CONSTRAINTS:
- Use second person ("you") consistently.
- Be specific and actionable.
- Do NOT include raw JSON in the output. Markdown only."""
            
            return system_prompt, user_prompt
        
        else:
            system_prompt = "You are an expert analyst. Provide insightful, actionable analysis."
            user_prompt = f"Analyze the match between:\n\nQuery:\n{json.dumps(query_json, indent=2)}\n\nResume:\n{json.dumps(resume_json, indent=2)}"
            return system_prompt, user_prompt
    
    def _parse_analysis(self, analysis_text: str) -> Dict:
        """Parse AI response into structured format"""
        
        result = {
            "fit_score": 75,  # Default
            "summary": "",
            "strengths": [],
            "gaps": [],
            "recommendations": [],
            "detailed_analysis": ""
        }
        
        try:
            lines = analysis_text.split('\n')
            current_section = None
            
            for line in lines:
                line = line.strip()
                
                # Extract fit score
                if line.startswith("**FIT SCORE:**"):
                    try:
                        score_str = line.split("**FIT SCORE:**")[1].strip()
                        score = int(''.join(filter(str.isdigit, score_str)))
                        result["fit_score"] = min(max(score, 0), 100)
                    except:
                        pass
                
                # Extract summary
                elif line.startswith("**SUMMARY:**"):
                    result["summary"] = line.split("**SUMMARY:**")[1].strip()
                    current_section = "summary"
                
                # Section headers
                elif line.startswith("**STRENGTHS:**"):
                    current_section = "strengths"
                elif line.startswith("**GAPS:**"):
                    current_section = "gaps"
                elif line.startswith("**RECOMMENDATIONS:**"):
                    current_section = "recommendations"
                elif line.startswith("**DETAILED ANALYSIS:**"):
                    current_section = "detailed"
                    result["detailed_analysis"] = line.split("**DETAILED ANALYSIS:**")[1].strip()
                
                # Extract list items
                elif line.startswith("- ") and current_section in ["strengths", "gaps", "recommendations"]:
                    result[current_section].append(line[2:].strip())
                
                # Continue multi-line content
                elif line and current_section == "summary" and not line.startswith("**"):
                    result["summary"] += " " + line
                elif line and current_section == "detailed" and not line.startswith("**"):
                    result["detailed_analysis"] += " " + line
            
            # Fallback: use entire text as detailed analysis if parsing failed
            if not result["summary"] and not result["detailed_analysis"]:
                result["detailed_analysis"] = analysis_text
                result["summary"] = analysis_text[:200] + "..."
            
        except Exception as e:
            result["detailed_analysis"] = analysis_text
            result["summary"] = f"Analysis provided (parsing error: {e})"
        
        return result

