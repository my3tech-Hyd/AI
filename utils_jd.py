# utils_jd.py
import re, hashlib
from pathlib import Path
from typing import Dict

# We will reuse clean_text and tokenize from the existing utils_text.py inside the apps.
# Here we only provide JD-specific metadata extraction helpers.
STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being below
between both but by could did do does doing down during each few for from further had has have having
he her here hers herself him himself his how i if in into is it its itself just me more most my
myself no nor not of off on once only or other our ours ourselves out over own same she should so
some such than that the their theirs them themselves then there these they this those through to too
under until up very was we were what when where which while who whom why with you your yours yourself
yourselves
""".split())

def sanitize_metadata(md: dict) -> dict:
    """Ensure all values are Bool/Int/Float/Str; drop/convert Nones and odd types."""
    clean = {}
    for k, v in (md or {}).items():
        if v is None:
            continue  # or: clean[k] = ""  (either is fine)
        if isinstance(v, (bool, int, float, str)):
            clean[k] = v
        else:
            clean[k] = str(v)
    return clean


def simple_jd_metadata(text: str, fallback_title: str) -> Dict:
    """
    Heuristic metadata extractor for Job Descriptions.
    Tries to find title, company, location, url; falls back to safe values.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = None
    company = None
    location = None
    url = None

    # Title: prefer the first short non-empty line (<= 80 chars)
    for ln in lines[:10]:
        if len(ln) <= 80:
            title = ln
            break
    title = title or fallback_title

    # Company hints
    for ln in lines[:50]:
        if re.search(r"(?i)\bcompany\b", ln):
            company = re.sub(r"(?i)\bcompany\s*[:\-]\s*", "", ln).strip()
            break
        if re.search(r"(?i)\babout us\b|\babout the company\b", ln):
            # use the previous line as company if available
            idx = lines.index(ln)
            if idx > 0 and 2 <= len(lines[idx-1]) <= 80:
                company = lines[idx-1].strip()
                break

    # Location hints
    for ln in lines[:50]:
        if re.search(r"(?i)\blocation\b", ln):
            location = re.sub(r"(?i)\blocation\s*[:\-]\s*", "", ln).strip()
            break
        if re.search(r"(?i)\b(remote|hybrid|onsite)\b", ln):
            location = (location or "") + (" " if location else "") + ln

    # URL if present
    m = re.search(r"https?://\S+", text)
    if m:
        url = m.group(0)

    return {
        "title": title or (fallback_title or ""),
        "company": company or "",
        "location": location or "",
        "url": url or "",
    }
def stable_id_from_bytes(data: bytes) -> str:
    """Return a stable 64-hex sha256 and a short prefix."""
    h = hashlib.sha256()
    h.update(data)
    sha256_full = h.hexdigest()
    short12 = sha256_full[:12]
    return sha256_full, short12
def tokenize(text: str):
    tokens = re.findall(r"[a-zA-Z][a-zA-Z\-]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS]
def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    return s.strip()