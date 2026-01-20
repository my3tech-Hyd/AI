# Assistance analysis to the resume

# ----------------------------------------------------------------------
# Assistance Center ↔︎ Candidate Resume (GPT-4o-mini)
# - Assistance center fills the posting form (center details + services)
# - Upload ONE candidate resume
# - We parse resume → lightweight JSON; form → JSON
# - Both go to GPT-4o-mini with an admissions/counseling-focused prompt
# - Output: WHY this candidate is (or isn’t) a fit, service mapping, plan,
#           risks, and a clear decision (Strong Enroll / Enroll / Conditional / Not a Fit)
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

# ---------------- App config ----------------
st.set_page_config(
    page_title="Assistance Center ↔︎ Candidate Resume (GPT-4o-mini)",
    page_icon="🧭",
    layout="wide",
)
st.title("🧭 Assistance Center Analysis: Posting ↔︎ Candidate Resume (GPT-4o-mini)")
st.caption("Fill the assistance center form, upload a candidate’s resume, and get a decisive, evidence-based fit analysis.")

# ---------------- OpenAI client ----------------
@st.cache_resource
def get_openai_client() -> OpenAI:
    """
    Priority: ENV['OPENAI_API_KEY'] > st.secrets['OPENAI_API_KEY'] > sidebar input.
    Lazy initialization - only called when needed, not at module import.
    """
    api_key = os.getenv("OPENAI_API_KEY", "") or st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        with st.sidebar:
            st.subheader("🔑 OpenAI")
            api_key = st.text_input("Enter your OpenAI API Key", type="password", key="openai_key_input")
    if not api_key:
        st.error("OpenAI API key required. Set OPENAI_API_KEY env or add it to `.streamlit/secrets.toml`.")
        st.stop()
    # Only pass api_key - no other parameters to avoid version conflicts
    return OpenAI(api_key=api_key)

# ---------------- Utilities ----------------
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

# ---------------- Lightweight Resume JSON ----------------
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

# ---------------- Assistance Center Form JSON ----------------
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

# ---------------- Prompt Template (Assistance-centric) ----------------
SYSTEM_PROMPT = """You are a Lead Career Counselor at a job assistance center.
Given one assistance center posting and one candidate resume, produce an intake decision report.
Be concrete, evidence-based, and decisive. Avoid generic fluff."""

USER_PROMPT_TEMPLATE = """You are given two JSON payloads:

[ASSISTANCE_CENTER_POSTING]
{center_json}

[CANDIDATE_RESUME]
{resume_json}

GOAL:
Help the assistance center decide if this candidate is a strong fit for its services right now. If not, explain why—and specify what needs to change.

TASKS (Markdown output):
1) Fit Summary (6–10 sentences)
   - WHY the candidate is/isn’t aligned with the center’s services, format, and goals.
   - Mention the most impactful services for them and critical mismatches (if any).
2) Candidate Needs & Goals
   - Infer short-term and long-term goals from resume signals; call out uncertainties explicitly.
3) Services Mapping Table
   - For each service in “Services”, provide:
     - Relevance (High/Medium/Low)
     - Expected impact (what outcome the candidate should see)
     - How to measure success (KPIs: interviews scheduled, offers, ATS passes, etc.)
4) Evidence From Resume
   - Quote or reference 6–10 specific phrases/lines that support/contradict the fit.
5) Gaps & Coaching Plan (8–12 bullets)
   - Exact gaps (resume structure, storytelling, project depth, interviewing, soft skills), with actionable steps.
6) Engagement Plan & Timeline
   - Weekly plan aligned to “Operating Hours” and center capacity; include mock interviews, resume rewrites, and placement activities.
7) Risks & Mitigation (5–10 bullets)
   - Time constraints, skill mismatch, motivation, communication; provide concrete mitigations.
8) Decision & Conditions
   - One of: **Strong Enroll / Enroll / Conditional / Not a Fit** (bold the decision).
   - If conditional or not a fit, list “conditions to enroll” (bridge study, minimum portfolio pieces, diagnostics).
9) Candidate-Facing Feedback (shareable)
   - 6–10 constructive bullets the center can send the candidate (no internal language).

CONSTRAINTS:
- Ground suggestions in the center’s “Services” and “Description”.
- Be specific & actionable; avoid generic statements.
- Do NOT include the raw JSON in the output. Markdown only."""

# ---------------- UI ----------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("🏢 Assistance Center Posting (Form)")
    # Use a unique key to avoid session_state collisions
    with st.form("assist_form_ui", clear_on_submit=False):
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
        submit_center = st.form_submit_button("Use this Assistance Posting")

with right:
    st.subheader("📄 Candidate Resume")
    resume_file = st.file_uploader(
        "Upload a resume (PDF/DOCX/TXT/RTF/DOC)",
        type=["pdf", "docx", "txt", "rtf", "doc"],
        accept_multiple_files=False,
    )
    analyze_btn = st.button("Generate Assistance Analysis", type="primary", use_container_width=True)

# Persist form
if submit_center:
    st.session_state["assist_form_payload"] = {
        "center_name": center_name,
        "capacity": int(capacity),
        "address": address,
        "phone": phone,
        "email": email,
        "operating_hours": operating_hours,
        "services": to_csv_list(services_text),
        "description": description,
    }
    st.success("Assistance center posting saved for analysis.")

# ---------------- Run analysis ----------------
if analyze_btn:
    if not resume_file:
        st.warning("Please upload a candidate resume.")
        st.stop()
    if "assist_form_payload" not in st.session_state:
        st.warning("Please submit the Assistance Center form first.")
        st.stop()

    # Read resume text
    resume_text = read_text_from_bytes(resume_file.read(), resume_file.name)
    if not resume_text.strip():
        st.warning("This resume seems empty after parsing/cleaning.")
        st.stop()

    # Build JSONs
    resume_json = resume_to_json(resume_text)
    center_json = AssistanceFormJSON(**st.session_state["assist_form_payload"])

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
        client = get_openai_client()  # Get client when needed
        with st.spinner("Evaluating candidate fit for assistance services…"):
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
    st.subheader("📊 Assistance Center Fit Report")
    st.markdown(content)

    # Download
    safe_center = re.sub(r"[^A-Za-z0-9_.-]+", "_", center_json.center_name or "center")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (resume_json.name_guess or "candidate"))
    fname = f"assistance_fit_{safe_center}_{safe_name}.md"
    st.download_button(
        "⬇️ Download Report (Markdown)",
        data=content.encode("utf-8"),
        file_name=fname,
        mime="text/markdown",
        use_container_width=True,
    )

# ---------------- Sidebar tips ----------------
with st.sidebar:
    st.markdown("### Tips")
    st.markdown(
        """
- Keep **Services** specific (e.g., “ATS-optimized Resume Writing, DSA Mock Interviews, Behavioral Coaching”).
- Prefer **PDF or DOCX** resumes for reliable parsing.
- Manage your API key via environment variables or `.streamlit/secrets.toml`.
        """.strip()
    )
