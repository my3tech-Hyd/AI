# streamlit_analysis_resume_vs_training.py
# ----------------------------------------------------------------------
# Resume ↔︎ Training Center Analyst (GPT-4o-mini)
# - User uploads ONE resume file
# - User fills the Training Center / Skill Posting form (provided fields)
# - We convert resume → JSON (light heuristics) and collect training form → JSON
# - Both JSONs are fed to GPT-4o-mini via a robust prompt template
# - Output: a deep analysis focused on WHY the candidate needs this training,
#           how it maps to current skills, and how it can improve outcomes
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
    page_title="Resume ↔︎ Training Center Analyst (GPT-4o-mini)",
    page_icon="🎯",
    layout="wide",
)
st.title("🎯 Resume ↔︎ Skill/Training Analysis (GPT-4o-mini)")
st.caption("Upload a resume, fill the training center form, and get a tailored analysis: why this training, strengths, skill gaps, and improvement path.")

# -------------- API key handling --------------
def get_openai_client() -> OpenAI:
    """
    Priority: ENV['OPENAI_API_KEY'] > st.secrets['OPENAI_API_KEY'] > sidebar input.
    """
    api_key = os.getenv("OPENAI_API_KEY", "") or st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        with st.sidebar:
            st.subheader("🔑 OpenAI")
            api_key = st.text_input(
                "Enter your OpenAI API Key",
                type="password",
                help="Recommended: set OPENAI_API_KEY env or .streamlit/secrets.toml",
            )
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

# -------------- Prompt Template --------------
SYSTEM_PROMPT = """You are an expert Career Coach and Learning Strategist.
You analyze a single resume against a training/skills program and produce a thorough, personalized report.
Focus on: WHY this candidate needs (or doesn't need) this training now, how it maps to current skills,
what gaps it fills, and the concrete improvement path including milestones and portfolio work.
Be specific and actionable. Avoid generic fluff."""

USER_PROMPT_TEMPLATE = """You are given two JSON payloads:

[TRAINING_CENTER_POSTING]
{center_json}

[CANDIDATE_RESUME]
{resume_json}

OBJECTIVE:
Provide a tailored analysis answering:
- Why this candidate would benefit from the training at this center now.
- How the offered courses align with their current skill set and target roles.
- What gaps are present and how the training addresses them.
- What measurable outcomes (projects, certifications, portfolios, interview readiness) they should achieve.

TASKS (Markdown output):
1) Executive Summary (6–10 sentences): clear rationale for pursuing this training now.
2) Strengths (8–12 bullets): specific capabilities from the resume that will accelerate learning in these courses.
3) Skill Gaps & Learning Needs (8–12 bullets): gaps mapped to precise modules or topics from the offered courses.
4) Course Fit & Roadmap:
   - Rank top 2–3 courses from the center by impact for this candidate.
   - For each: what they’ll learn, prerequisites assumed, how it fixes gaps.
   - Timeline aligned to “Course Duration” with weekly milestones.
5) Project & Portfolio Plan:
   - 3–5 project ideas tied to the courses (with crisp acceptance criteria, datasets/tech suggestions).
   - GitHub/portfolio structure and documentation notes.
6) Certifications & Assessments:
   - How the center’s certifications (and any third-party ones) add credibility; mapping to roles.
7) Interview & Career Outcomes:
   - Expected interview topics they’ll be able to answer after training.
   - Resume bullet rewrites (4–6 lines) post-training outcome.
8) Risk & Mitigation:
   - Potential blockers (time, math background, tooling) with mitigation steps.
9) 30/60/90-Day Plan:
   - What to accomplish in the first 30/60/90 days to maximize ROI from the training.

CONSTRAINTS:
- Use the "Courses Offered" list to ground your suggestions.
- When you infer missing info, state assumptions explicitly.
- Do NOT include the raw JSON in the output. Markdown only."""

# -------------- UI: left form (training center), right upload (resume) --------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("🏫 Training Center / Skill Posting")
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
        submit_center = st.form_submit_button("Use this Training Center")

with right:
    st.subheader("📄 Resume Upload")
    resume_file = st.file_uploader(
        "Upload a resume (PDF/DOCX/TXT/RTF/DOC)",
        type=["pdf", "docx", "txt", "rtf", "doc"],
        accept_multiple_files=False,
    )
    analyze_btn = st.button("Generate Training Analysis", type="primary", use_container_width=True)

# Persist the form data on submit
if submit_center:
    st.session_state["center_form"] = {
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
    st.success("Training center form saved for analysis.")

# -------------- Run analysis --------------
if analyze_btn:
    if not resume_file:
        st.warning("Please upload a resume.")
        st.stop()
    if "center_form" not in st.session_state:
        st.warning("Please submit the Training Center form first.")
        st.stop()

    # Read resume text
    resume_text = read_text_from_bytes(resume_file.read(), resume_file.name)
    if not resume_text.strip():
        st.warning("This resume seems empty after parsing/cleaning.")
        st.stop()

    # Build JSONs
    resume_json = resume_to_json(resume_text)
    center_json = TrainingFormJSON(**st.session_state["center_form"])

    # Show parsed inputs (optional)
    with st.expander("👀 View Parsed Inputs (JSON)"):
        st.json({"training_center": asdict(center_json), "resume": asdict(resume_json)})

    # Build prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(
        center_json=json.dumps(asdict(center_json), ensure_ascii=False, indent=2),
        resume_json=json.dumps(asdict(resume_json), ensure_ascii=False, indent=2),
    )

    # Call OpenAI (GPT-4o-mini)
    try:
        with st.spinner("Analyzing profile vs training pathways..."):
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
    st.subheader("📊 Training Fit & Improvement Analysis")
    st.markdown(content)

    # Download button
    safe_center = re.sub(r"[^A-Za-z0-9_.-]+", "_", center_json.center_name or "center")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (resume_json.name_guess or "candidate"))
    fname = f"training_analysis_{safe_center}_{safe_name}.md"
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
- Make sure the **Courses Offered** list is realistic and specific.
- Prefer **PDF or DOCX** resumes for more reliable parsing.
- Use environment variables or `.streamlit/secrets.toml` to manage your API key securely.
        """.strip()
    )
