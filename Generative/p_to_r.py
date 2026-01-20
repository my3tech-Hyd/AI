# streamlit_analysis_training_vs_resume.py
# ----------------------------------------------------------------------
# Institution-Facing Analyst: Skill/Training Posting ↔︎ Candidate Resume (GPT-4o-mini)
# - Institution fills the Training/Skill Posting form (center/program info)
# - Institution uploads ONE candidate resume file
# - We convert resume → JSON (light heuristics) and training form → JSON
# - Both JSONs go to GPT-4o-mini via an admissions-focused prompt
# - Output: Why this candidate is (or isn’t) right for the program, with evidence,
#           risks, assessment plan, bridge recommendations, and Admit/Waitlist/Reject.
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
    page_title="Institution Analysis: Training Posting ↔︎ Candidate Resume (GPT-4o-mini)",
    page_icon="🏫",
    layout="wide",
)
st.title("🏫 Institution Analysis: Training/Skill Posting ↔︎ Candidate Resume (GPT-4o-mini)")
st.caption("Upload a candidate’s resume, fill the training/skill posting form, and get an admissions-ready assessment: fit, gaps, risks, assessment plan, and decision.")

# -------------- API key handling --------------
def get_openai_client() -> OpenAI:
    """
    Priority: ENV['OPENAI_API_KEY'] > st.secrets['OPENAI_API_KEY'] > sidebar input.
    (Recommended: set OPENAI_API_KEY in your environment or .streamlit/secrets.toml)
    """
    api_key = os.getenv("OPENAI_API_KEY", "") or st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        with st.sidebar:
            st.subheader("🔑 OpenAI")
            api_key = st.text_input("Enter your OpenAI API Key", type="password")
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

def extract_top_lines(text: str, n: int = 6) -> str:
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

# -------------- Training Center Form JSON --------------
@dataclass
class TrainingFormJSON:
    center_name: str
    capacity: int
    address: str
    phone: str
    email: str
    course_duration: str
    certification: str
    courses_offered: List[str]
    description: str

# -------------- Prompt Template (Admissions-centric) --------------
SYSTEM_PROMPT = """You are an Admissions Lead for a technical training institute.
Given one training/skill posting and one candidate resume, produce an admissions-ready assessment.
Be concrete, evidence-based (quote/point to phrases), and decisive. Avoid generic fluff."""

USER_PROMPT_TEMPLATE = """You are given two JSON payloads:

[TRAINING_CENTER_POSTING]
{center_json}

[CANDIDATE_RESUME]
{resume_json}

GOAL:
Help the institution decide whether this candidate should be admitted to the training program(s). If not, make it clear why—and what bridge work would change the decision.

TASKS (Markdown output):
1) Fit Summary (6–10 sentences)
   - WHY this candidate is/isn't aligned with the center’s offerings, prerequisites, and outcomes.
   - Mention obvious matches and the most critical gaps.
2) Prerequisites & Readiness Check
   - Map current skills/education vs. assumed prerequisites for the top relevant course(s).
3) Course Fit Ranking
   - Rank the top 2–3 courses from the “Courses Offered” list for this candidate with brief justification.
4) Evidence From Resume
   - Quote or reference 6–10 specific phrases/lines that support/contradict fit.
5) Skill Gaps & Bridge Plan (8–12 bullets)
   - Exact gaps, with bridge modules/resources the candidate should complete before/during the course.
6) Assessment & Interview Plan
   - Short diagnostic test topics (5–8) + 1–2 sample questions each; include a small take-home project outline.
7) Risks & Mitigation (5–10 bullets)
   - Time availability, foundations (math/programming), tooling, consistency; give concrete mitigations.
8) Decision & Conditions
   - One of: **Strong Admit / Admit / Waitlist / Reject** (bold the decision).
   - If not a clear admit, list “conditions to admit” (bridge study, probation period, mentor check-ins).
9) 30/60/90-Day Learning Plan (bullets)
   - Weekly milestones aligned to “Course Duration”; measurable outcomes (projects, certifications).

CONSTRAINTS:
- Ground suggestions in the “Courses Offered” list and center’s “Description”.
- State assumptions when information is missing.
- Do NOT include raw JSON in the output. Markdown only."""

# -------------- UI: left = Training form, right = Resume upload --------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("🏫 Training/Skill Posting (Institution Form)")
    # Use a unique form key to avoid session_state key collisions
    with st.form("center_form_ui", clear_on_submit=False):
        center_name = st.text_input("Center Name", value="TechBridge Learning Hub")
        capacity = st.number_input("Capacity", value=120, step=10)
        address = st.text_input("Address", value="3rd Floor, Sunrise Plaza, Madhapur, Hyderabad, Telangana, 500081")
        phone = st.text_input("Phone", value="+91-9876543210")
        email = st.text_input("Email", value="contact@techbridgehub.com")
        course_duration = st.text_input("Course Duration", value="6 months")
        certification = st.text_input("Certification", value="Industry Certified by NASSCOM & Microsoft")
        courses_offered_text = st.text_input(
            "Courses Offered (comma-separated)",
            value="Web Development, Data Analytics, Cloud Computing, Digital Marketing, Cybersecurity",
        )
        description = st.text_area(
            "Description",
            value=(
                "TechBridge Learning Hub is a premier IT training institute focused on equipping students and "
                "professionals with hands-on skills in emerging technologies. With expert trainers, modern labs, "
                "and placement support, we ensure learners are ready for real-world challenges."
            ),
            height=160,
        )
        submit_center = st.form_submit_button("Use this Training Posting")

with right:
    st.subheader("📄 Candidate Resume")
    resume_file = st.file_uploader(
        "Upload a resume (PDF/DOCX/TXT/RTF/DOC)",
        type=["pdf", "docx", "txt", "rtf", "doc"],
        accept_multiple_files=False,
    )
    analyze_btn = st.button("Generate Institution Analysis", type="primary", use_container_width=True)

# Persist training form in session when submitted
if submit_center:
    st.session_state["center_form_payload"] = {
        "center_name": center_name,
        "capacity": int(capacity),
        "address": address,
        "phone": phone,
        "email": email,
        "course_duration": course_duration,
        "certification": certification,
        "courses_offered": to_csv_list(courses_offered_text),
        "description": description,
    }
    st.success("Training/Skill posting saved for analysis.")

# -------------- Run analysis --------------
if analyze_btn:
    if not resume_file:
        st.warning("Please upload a candidate resume.")
        st.stop()
    if "center_form_payload" not in st.session_state:
        st.warning("Please submit the Training/Skill posting form first.")
        st.stop()

    # Read resume
    resume_text = read_text_from_bytes(resume_file.read(), resume_file.name)
    if not resume_text.strip():
        st.warning("This resume seems empty after parsing/cleaning.")
        st.stop()

    # Build JSONs
    resume_json = resume_to_json(resume_text)
    center_json = TrainingFormJSON(**st.session_state["center_form_payload"])

    # Show inputs (optional)
    with st.expander("👀 View Parsed Inputs (JSON)"):
        st.json({"training_posting": asdict(center_json), "resume": asdict(resume_json)})

    # Build prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(
        center_json=json.dumps(asdict(center_json), ensure_ascii=False, indent=2),
        resume_json=json.dumps(asdict(resume_json), ensure_ascii=False, indent=2),
    )

    # Call OpenAI (GPT-4o-mini)
    try:
        with st.spinner("Evaluating candidate fit for the training posting…"):
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.25,
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
    st.subheader("📊 Institution-Facing Assessment")
    st.markdown(content)

    # Download button
    safe_center = re.sub(r"[^A-Za-z0-9_.-]+", "_", (center_json.center_name or "center"))
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (resume_json.name_guess or "candidate"))
    fname = f"institution_assessment_{safe_center}_{safe_name}.md"
    st.download_button(
        "⬇️ Download Assessment (Markdown)",
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
- Make “Courses Offered” concrete (e.g., “Full-Stack Web (JS/React/Node), Data Analytics (Python/SQL), Cloud (AWS)”).
- Prefer **PDF or DOCX** resumes for reliable parsing.
- Manage your API key via environment or `.streamlit/secrets.toml`.
        """.strip()
    )
