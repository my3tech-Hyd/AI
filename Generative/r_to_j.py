# streamlit_analysis_resume_vs_jd.py
# ----------------------------------------------------------------------
# Resume ↔︎ Job Posting Analyst (GPT-4o-mini)
# - User uploads ONE resume file
# - User fills the SAME Job Posting form (as in streamlit_user_jd_to_resume.py)
# - We convert resume → JSON (light heuristics) and collect job form → JSON
# - Both JSONs are fed to GPT-4o-mini via a robust prompt template
# - Output: a long, structured analysis with summary, strengths, gaps, improvements
# ----------------------------------------------------------------------

from __future__ import annotations

import io
import os
import re
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st
from openai import OpenAI
from pypdf import PdfReader
from docx import Document as Docx

# -------------- App config --------------
st.set_page_config(
    page_title="Resume ↔︎ JD Analyst (GPT-4o-mini)",
    page_icon="🧠",
    layout="wide",
)
st.title("🧠 Resume ↔︎ Job Posting Analyst (GPT-4o-mini)")
st.caption("Upload a resume, fill the job posting form, and get a deep-dive analysis: fit summary, strengths, gaps, and improvements.")

# -------------- API key handling --------------
def get_openai_client() -> OpenAI:
    """
    Priority: ENV['OPENAI_API_KEY'] > st.secrets['OPENAI_API_KEY'] > sidebar input.
    (We strongly recommend using ENV or Secrets. Avoid hardcoding keys.)
    """
    api_key = os.getenv("OPENAI_API_KEY", "") or st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        with st.sidebar:
            st.subheader("🔑 OpenAI")
            api_key = st.text_input("Enter your OpenAI API Key", type="password", help="It is used only to call OpenAI from your browser session.")
    if not api_key:
        st.error("OpenAI API key required. Set environment variable OPENAI_API_KEY or enter it in the sidebar.")
        st.stop()
    return OpenAI(api_key=api_key)

client = get_openai_client()

# -------------- Utilities --------------
def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "")
    return s.strip()

def read_text_from_bytes(data: bytes, filename: str) -> str:
    """
    Extract text from common formats and clean it.
    Supports: .pdf, .docx, .txt, .rtf, .md, .doc (best-effort decode)
    """
    ext = Path(filename).suffix.lower()
    try:
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
            # .doc or unknown → best-effort decode
            text = data.decode(errors="ignore")
    except Exception:
        text = data.decode(errors="ignore")
    return clean_text(text)

_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
_PHONE_RE = re.compile(r"(?:(?:\+?\d{1,3}[-.\s])?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3}[-.\s]?\d{4,})")

SECTION_HEADERS = [
    r"summary", r"objective", r"profile",
    r"skills", r"technical skills", r"key skills",
    r"experience", r"work experience", r"employment history", r"professional experience",
    r"projects", r"certifications", r"education", r"publications", r"achievements",
]

def _find_all(patterns: List[str], text: str) -> List[Tuple[str, int]]:
    out = []
    for p in patterns:
        m = re.search(rf"(?im)^\s*{p}\s*[:\-]?\s*$", text)
        if m:
            out.append((p.lower(), m.start()))
    return sorted(out, key=lambda x: x[1])

def _slice_sections(text: str) -> Dict[str, str]:
    anchors = _find_all(SECTION_HEADERS, text)
    if not anchors:
        return {"body": text}
    sections: Dict[str, str] = {}
    for i, (name, idx) in enumerate(anchors):
        start = idx
        end = anchors[i + 1][1] if i + 1 < len(anchors) else len(text)
        chunk = text[start:end].strip()
        sections[name] = chunk
    return sections

def extract_top_lines(text: str, n: int = 5) -> str:
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]
    return "\n".join(lines[:n])

def to_csv_list(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]

# -------------- Lightweight Resume JSON --------------
@dataclass
class ResumeJSON:
    raw_text: str
    name_guess: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    top_lines: str
    sections: Dict[str, str]

def resume_to_json(text: str) -> ResumeJSON:
    email = (_EMAIL_RE.search(text) or (None,))[0] if _EMAIL_RE.search(text) else None
    phone = (_PHONE_RE.search(text) or (None,))[0] if _PHONE_RE.search(text) else None

    # Name guess: first non-empty line that isn't email/phone
    first_lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]
    name_guess = None
    for ln in first_lines[:5]:
        if (email and email in ln) or (phone and phone in ln):
            continue
        # crude filter: likely a name if 2–5 words, mostly alphabetic
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z\.\-']+", ln)]
        if 1 <= len(words) <= 6:
            name_guess = ln
            break

    sections = _slice_sections(text)
    top = extract_top_lines(text, n=8)

    return ResumeJSON(
        raw_text=text,
        name_guess=name_guess,
        email=email,
        phone=phone,
        top_lines=top,
        sections=sections,
    )

# -------------- Job Posting Form JSON --------------
@dataclass
class JobFormJSON:
    employer_id: str
    job_id_external: str
    company_name: str
    job_title: str
    description: str
    location: str
    job_type: str
    min_salary: float
    max_salary: float
    required_skills: List[str]
    qualifications_educations: List[str]
    posted_date: str
    anonymous_posting: bool
    is_active: bool
    created_at: str
    updated_at: str

# -------------- Prompt Template --------------
SYSTEM_PROMPT = """You are a Career Coach speaking directly to the candidate.
Analyze one resume against one job posting and give an honest, evidence-based verdict on personal fit.
Use second person (“you”) throughout. Be specific and point to concrete phrases/skills from BOTH the job post and the resume.
Avoid boilerplate. If data is missing, infer cautiously and state assumptions explicitly. Keep a professional, supportive tone."""

USER_PROMPT_TEMPLATE = """You are given two JSON payloads:

[JOB_POSTING]
{job_json}

[RESUME]
{resume_json}

ROLE: You are advising the candidate. Speak to them as “you”.

TASKS (Markdown output):
1) Should-You-Apply? (Executive Verdict, 6–10 sentences)
   - State whether this posting is a **Strong Fit / Fit / Partial Fit / Not a Fit** for you and WHY.
   - Include a confidence score (0–100) and the 2–4 most decisive reasons.

2) Your Strengths for This JD (8–12 bullets)
   - Tie each bullet to a specific job requirement, quoting short phrases from your resume or the JD where helpful.

3) Gaps & Deal-Breakers (8–12 bullets)
   - Clearly separate **Critical Gaps (must fix)** vs **Nice-to-Have Gaps**.
   - Call out missing stacks, insufficient depth, domain gaps, tool/version mismatches, or soft-skill signals.

4) Skills Alignment Matrix
   - **Matched skills/keywords** (group by category; include exact phrases that appear in your resume).
   - **Missing or weak skills** (group by category; note what the JD expects).

5) Education & Qualifications Check
   - Compare the JD’s “Qualifications & Educations” vs your education/certifications.
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
- Use second person (“you”) consistently and keep it concise but information-dense.
- When citing evidence, quote short phrases in quotes (no long excerpts)."""


# -------------- UI: left form (job), right upload (resume) --------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("📝 Job Posting (Form)")
    with st.form("job_form_ui", clear_on_submit=False):
        employer_id = st.text_input("EmployerId", value="1")
        job_id_external = st.text_input("Job ID (External)", value="")
        company_name = st.text_input("Company Name", value="")
        job_title = st.text_input("Job title", value="Java Full Stack Developer")
        description = st.text_area("Description",
                                   value="Should have knowledge on designing and developing both front-end user …",
                                   height=200)
        location = st.text_input("Location", value="Hyderabad")
        job_type = st.selectbox("JobType", options=["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY"],
                                index=0)
        min_salary = st.number_input("MinSalary", value=30000, step=1000)
        max_salary = st.number_input("MaxSalary", value=50000, step=1000)
        required_skills_text = st.text_input("RequiredSkills (comma-separated)",
                                             value="Java, Springboot, Hibernate, Html")
        qualifications_educations_text = st.text_input("Qualifications & Educations (comma-separated)", value="")
        posted_date = st.text_input("PostedDate", value="2025-08-28T13:03:02.686+00:00")
        anonymous_posting = st.checkbox("AnonymousPosting", value=False)
        is_active = st.checkbox("IsActive", value=True)
        created_at = st.text_input("CreatedAt", value="2025-08-28T13:03:02.748+00:00")
        updated_at = st.text_input("UpdatedAt", value="2025-08-28T13:03:02.748+00:00")
        submit_job = st.form_submit_button("Use this Job Posting")

with right:
    st.subheader("📄 Resume Upload")
    resume_file = st.file_uploader(
        "Upload a resume (PDF/DOCX/TXT/RTF/DOC)",
        type=["pdf", "docx", "txt", "rtf", "doc"],
        accept_multiple_files=False,
    )
    analyze_btn = st.button("Generate Analysis", type="primary", use_container_width=True)

# Persist job form in session when submitted
if submit_job:
    st.session_state["job_form"] = {
        "employer_id": employer_id,
        "job_id_external": job_id_external,
        "company_name": company_name,
        "job_title": job_title,
        "description": description,
        "location": location,
        "job_type": job_type,
        "min_salary": float(min_salary),
        "max_salary": float(max_salary),
        "required_skills": to_csv_list(required_skills_text),
        "qualifications_educations": to_csv_list(qualifications_educations_text),
        "posted_date": posted_date,
        "anonymous_posting": bool(anonymous_posting),
        "is_active": bool(is_active),
        "created_at": created_at,
        "updated_at": updated_at,
    }
    st.success("Job form saved for analysis.")

# -------------- Run analysis --------------
if analyze_btn:
    if not resume_file:
        st.warning("Please upload a resume.")
        st.stop()
    if "job_form" not in st.session_state:
        st.warning("Please submit the Job Posting form first.")
        st.stop()

    # Read resume
    resume_text = read_text_from_bytes(resume_file.read(), resume_file.name)
    if not resume_text.strip():
        st.warning("This resume seems empty after parsing/cleaning.")
        st.stop()

    # Build JSONs
    resume_json = resume_to_json(resume_text)
    job_json = JobFormJSON(**st.session_state["job_form"])

    # Show inputs (collapsible)
    with st.expander("👀 View Parsed Inputs (JSON)"):
        st.json({"job_posting": asdict(job_json), "resume": asdict(resume_json)})

    # Build prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(
        job_json=json.dumps(asdict(job_json), ensure_ascii=False, indent=2),
        resume_json=json.dumps(asdict(resume_json), ensure_ascii=False, indent=2),
    )

    # Call OpenAI (GPT-4o-mini)
    try:
        with st.spinner("Thinking..."):
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        content = resp.choices[0].message.content or ""
    except Exception as e:
        st.error(f"OpenAI call failed: {e}")
        st.stop()

    # Render output
    st.markdown("---")
    st.subheader("📊 Analysis")
    st.markdown(content)

    # Download button
    safe_job = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_json.job_title or "job")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (resume_json.name_guess or "candidate"))
    fname = f"analysis_{safe_job}_{safe_name}.md"
    st.download_button(
        "⬇️ Download Analysis (Markdown)",
        data=content.encode("utf-8"),
        file_name=fname,
        mime="text/markdown",
        use_container_width=True,
    )

# -------------- Tips --------------
with st.sidebar:
    st.markdown("### Tips")
    st.markdown(
        """
- Use **clear job requirements** and real **tech stacks** in the form for better analysis.
- Prefer **PDF or DOCX** resumes for more reliable parsing.
- Your API key never leaves your session; use environment variables or `st.secrets` in production.
        """.strip()
    )
