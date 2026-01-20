# streamlit_analysis_resume_vs_assistance_candidate.py
# ----------------------------------------------------------------------
# Candidate-Facing Analysis: Candidate Resume ↔︎ Assistance Center Posting (GPT-4o-mini)
# - Candidate uploads ONE resume
# - Candidate (or counselor) fills the Assistance Center posting form
# - We parse resume → lightweight JSON; form → JSON
# - Both go to GPT-4o-mini with a candidate-focused prompt
# - Output: WHY this posting fits the candidate now, benefits, gaps, ROI,
#           service mapping, timeline, and concrete next steps.
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
    page_title="Candidate View: Resume ↔ Assistance Center (GPT-4o-mini)",
    page_icon="🧑‍🎓",
    layout="wide",
)
st.title("🧑‍🎓 Candidate View — Why this Assistance Center fits you (GPT-4o-mini)")
st.caption("Upload your resume, fill the assistance center details, and get a personalized analysis: fit, benefits, gaps, ROI, and a week-by-week plan.")

# -------------- OpenAI key handling --------------
def get_openai_client() -> OpenAI:
    """
    Priority: ENV['OPENAI_API_KEY'] > st.secrets['OPENAI_API_KEY'] > sidebar input.
    """
    api_key = os.getenv("OPENAI_API_KEY", "") or st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        with st.sidebar:
            st.subheader("🔑 OpenAI")
            api_key = st.text_input("Enter your OpenAI API Key", type="password")
    if not api_key:
        st.error("OpenAI API key required. Set environment variable OPENAI_API_KEY or add it to `.streamlit/secrets.toml`.")
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
        sections[name] = text[start:end].strip()
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

# -------------- Assistance Center Form JSON --------------
@dataclass
class AssistanceFormJSON:
    center_name: str
    capacity: int
    address: str
    phone: str
    email: str
    operating_hours: str
    services: List[str]
    description: str

# -------------- Candidate-Focused Prompt --------------
SYSTEM_PROMPT = """You are a Career Coach advising a specific candidate.
Given their resume and an assistance center’s offering, produce a personalized plan focused on WHY this posting fits the candidate now, expected benefits, gaps to close, ROI, and concrete next steps.
Be specific, evidence-based, and motivational without fluff."""

USER_PROMPT_TEMPLATE = """You are given two JSON payloads:

[ASSISTANCE_CENTER_POSTING]
{center_json}

[CANDIDATE_RESUME]
{resume_json}

ROLE: You are speaking to the candidate directly.

TASKS (Markdown output):
1) Why this Posting Fits You (8–12 sentences)
   - Tie the center’s “Services” and “Description” to your current background and goals. Cite concrete overlaps.
2) Immediate Strengths You Bring (8–12 bullets)
   - Specific resume evidence (skills, projects, achievements) that will help you benefit faster from the services.
3) Gaps to Close for Maximum ROI (8–12 bullets)
   - Clear, actionable gaps (ATS readiness, phrasing, projects depth, behavioral/communication, mock interviews).
4) Service-to-Outcome Mapping (table-like bullets)
   - For each service: what you’ll do, expected outcome, how we measure success (interviews, callbacks, offers).
5) Personalized Timeline (4–8 bullets)
   - Weekly plan aligned to “Operating Hours” (e.g., which days to book sessions, practice time, deadlines).
6) Portfolio & Proof Plan
   - What artifacts to create (resume versions, project writeups, GitHub repos, case logs) and how to present them.
7) Interview Readiness
   - Topics you’ll master, sample answers to practice, behavioral stories to craft (STAR).
8) Risks & How You’ll Handle Them
   - Time, energy, prerequisites; give practical mitigations and accountability ideas.
9) Success Milestones & KPIs
   - 30/60/90-day checkpoints: what “good” looks like (numbers if possible).
10) Next 7 Days — Concrete Actions
   - A short, numbered checklist to get started immediately.

CONSTRAINTS:
- Speak directly to the candidate (use “you”).
- Use the center’s “Services” and “Operating Hours” to make the plan realistic.
- Do NOT include the raw JSON in the output. Markdown only.
"""

# -------------- UI: left = Assistance form, right = Resume upload --------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("🏢 Assistance Center Posting (for this candidate)")
    # Unique key to avoid session_state collisions
    with st.form("assist_form_ui_candidate_view", clear_on_submit=False):
        center_name = st.text_input("Center Name", value="CareerPath Assistance Center")
        capacity = st.number_input("Capacity", value=80, step=5)
        address = st.text_input("Address", value="2nd Floor, Orion Towers, Ameerpet, Hyderabad, Telangana, 500016")
        phone = st.text_input("Phone", value="+91-9123456780")
        email = st.text_input("Email", value="support@careerpathcenter.com")
        operating_hours = st.text_input("Operating Hours", value="Mon–Fri 9:00 AM – 6:00 PM")
        services_text = st.text_input(
            "Services (comma-separated)",
            value="Career Counseling, Resume Writing, Interview Preparation, Job Placement Support, Personality Development",
        )
        description = st.text_area(
            "Description",
            value=(
                "CareerPath Assistance Center helps job seekers achieve their career goals through personalized guidance, "
                "expert resume building, and intensive interview preparation. With strong industry connections, we provide "
                "end-to-end job placement support for fresh graduates and experienced professionals."
            ),
            height=160,
        )
        submit_center = st.form_submit_button("Use this Posting")

with right:
    st.subheader("📄 Your Resume")
    resume_file = st.file_uploader(
        "Upload your resume (PDF/DOCX/TXT/RTF/DOC)",
        type=["pdf", "docx", "txt", "rtf", "doc"],
        accept_multiple_files=False,
    )
    analyze_btn = st.button("Generate Candidate-Centric Analysis", type="primary", use_container_width=True)

# Persist form data
if submit_center:
    st.session_state["assist_form_candidate_payload"] = {
        "center_name": center_name,
        "capacity": int(capacity),
        "address": address,
        "phone": phone,
        "email": email,
        "operating_hours": operating_hours,
        "services": to_csv_list(services_text),
        "description": description,
    }
    st.success("Assistance center details saved for analysis.")

# -------------- Run analysis --------------
if analyze_btn:
    if not resume_file:
        st.warning("Please upload your resume.")
        st.stop()
    if "assist_form_candidate_payload" not in st.session_state:
        st.warning("Please submit the Assistance Center form first.")
        st.stop()

    # Read resume text
    resume_text = read_text_from_bytes(resume_file.read(), resume_file.name)
    if not resume_text.strip():
        st.warning("Your resume seems empty after parsing/cleaning.")
        st.stop()

    # Build JSONs
    resume_json = resume_to_json(resume_text)
    center_json = AssistanceFormJSON(**st.session_state["assist_form_candidate_payload"])

    # Show parsed inputs (optional)
    with st.expander("👀 View Parsed Inputs (JSON)"):
        st.json({"assistance_center": asdict(center_json), "resume": asdict(resume_json)})

    # Build prompt
    user_prompt = USER_PROMPT_TEMPLATE.format(
        center_json=json.dumps(asdict(center_json), ensure_ascii=False, indent=2),
        resume_json=json.dumps(asdict(resume_json), ensure_ascii=False, indent=2),
    )

    # Call OpenAI
    try:
        with st.spinner("Preparing your personalized plan…"):
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
    st.subheader("📊 Your Assistant-Centered Fit & Action Plan")
    st.markdown(content)

    # Download button
    safe_center = re.sub(r"[^A-Za-z0-9_.-]+", "_", center_json.center_name or "center")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (resume_json.name_guess or "candidate"))
    fname = f"candidate_view_assistance_fit_{safe_center}_{safe_name}.md"
    st.download_button(
        "⬇️ Download Your Plan (Markdown)",
        data=content.encode("utf-8"),
        file_name=fname,
        mime="text/markdown",
        use_container_width=True,
    )

# -------------- Sidebar tips --------------
with st.sidebar:
    st.markdown("### Tips")
    st.markdown(
        """
- Be specific in the **Services** you want; the plan maps directly to them.
- Prefer **PDF or DOCX** for accurate resume parsing.
- Keep your API key in environment variables or `.streamlit/secrets.toml`.
        """.strip()
    )
