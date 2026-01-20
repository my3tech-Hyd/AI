# api/utils/analyze_utils.py
# Utility functions for analyze endpoints
# ----------------------------------------------------------------------

import io
import re
from pathlib import Path
from typing import Dict, List, Optional
from pypdf import PdfReader
from docx import Document as Docx


def read_text_from_file(file_data: bytes, filename: str) -> str:
    """
    Extract text from common file formats
    
    Supports: PDF, DOCX, TXT, RTF, MD
    """
    ext = Path(filename).suffix.lower()
    
    try:
        if ext == ".pdf":
            with io.BytesIO(file_data) as f:
                reader = PdfReader(f, strict=False)
                text = " ".join((page.extract_text() or "") for page in reader.pages)
        elif ext == ".docx":
            with io.BytesIO(file_data) as f:
                doc = Docx(f)
                text = "\n".join(p.text for p in doc.paragraphs)
        elif ext in {".txt", ".rtf", ".md"}:
            text = file_data.decode(errors="ignore")
        else:
            text = file_data.decode(errors="ignore")
    except Exception:
        text = file_data.decode(errors="ignore")
    
    return clean_text(text)


def clean_text(s: str) -> str:
    """Clean and normalize text"""
    s = re.sub(r"\s+", " ", s or "")
    return s.strip()


# Regex patterns for contact extraction
_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
_PHONE_RE = re.compile(r"(?:(?:\+?\d{1,3}[-.\s])?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3}[-.\s]?\d{4,})")

# Section headers for resume parsing
SECTION_HEADERS = [
    r"summary", r"objective", r"profile",
    r"skills", r"technical skills", r"key skills",
    r"experience", r"work experience", r"employment history", r"professional experience",
    r"projects", r"certifications", r"education", r"publications", r"achievements",
]


def _find_all(patterns: List[str], text: str) -> List[tuple]:
    """Find all section headers in text"""
    out = []
    for p in patterns:
        m = re.search(rf"(?im)^\s*{p}\s*[:\-]?\s*$", text)
        if m:
            out.append((p.lower(), m.start()))
    return sorted(out, key=lambda x: x[1])


def _slice_sections(text: str) -> Dict[str, str]:
    """Slice resume text into sections"""
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
    """Extract top N non-empty lines"""
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]
    return "\n".join(lines[:n])


def to_csv_list(s: str) -> List[str]:
    """Convert comma-separated string to list"""
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def resume_to_json(text: str) -> Dict:
    """
    Convert resume text to lightweight JSON structure
    Matches the structure used in Streamlit generative files
    """
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

    return {
        "raw_text": text,
        "name_guess": name_guess,
        "email": email,
        "phone": phone,
        "top_lines": top,
        "sections": sections,
    }


