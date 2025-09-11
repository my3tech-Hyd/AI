import os, re, shutil, hashlib
from typing import Tuple, Dict
from pypdf import PdfReader
from docx import Document as Docx
from pathlib import Path

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being below
between both but by could did do does doing down during each few for from further had has have having
he her here hers herself him himself his how i if in into is it its itself just me more most my
myself no nor not of off on once only or other our ours ourselves out over own same she should so
some such than that the their theirs them themselves then there these they this those through to too
under until up very was we were what when where which while who whom why with you your yours yourself
yourselves
""".split())

def read_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == ".docx":
        doc = Docx(path)
        return "\n".join(p.text for p in doc.paragraphs)
    if ext in {".txt", ".rtf"}:
        # naive RTF strip; for robust handling use unrtf or striprtf
        with open(path, "r", errors="ignore") as f:
            txt = f.read()
        return re.sub(r"{\\rtf1.*?}", "", txt, flags=re.DOTALL) if ext==".rtf" else txt
    raise ValueError(f"Unsupported file: {path}")

def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def simple_metadata(text: str, default_name: str) -> Dict:
    email = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    phone = re.search(r"(\+?\d[\d\-\s]{7,}\d)", text)
    return {
        "candidate_name": default_name,
        "email": email.group(0) if email else None,
        "phone": phone.group(0) if phone else None,
    }

def tokenize(text: str):
    tokens = re.findall(r"[a-zA-Z][a-zA-Z\-]+", text.lower())
    return [t for t in tokens if t not in STOPWORDS]


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def stage_resume(original_path: str, store_dir: str) -> Tuple[str, str]:
    os.makedirs(store_dir, exist_ok=True)
    h = file_hash(original_path)[:12]
    ext = Path(original_path).suffix.lower()
    staged = os.path.join(store_dir, f"{Path(original_path).stem}.{h}{ext}")
    if not os.path.exists(staged):
        shutil.copy2(original_path, staged)
    return staged, h
EMAIL_RE = re.compile(
    r'(?i)(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])'
)
PHONE_CANDIDATE_RE = re.compile(
    r'''(?x)
    (?:
      (?:\+?\d{1,3}[\s\-.()]* )?     # optional country code
      (?:\(?\d{3}\)?[\s\-.()]*)      # area code, with or without ()
      \d{3}[\s\-.]*\d{4}             # local number
    )
    '''
)

def extract_email(text: str) -> str | None:
    m = EMAIL_RE.search(text or "")
    return m.group(1) if m else None

def extract_phone(text: str) -> str | None:
    txt = text or ""
    # Ignore phones that are directly part of an email token
    for m in PHONE_CANDIDATE_RE.finditer(txt):
        s, e = m.span()
        around = txt[max(0, s-2):min(len(txt), e+2)]
        if "@" in around:      # skip phones glued to an email token
            continue
        digits = re.sub(r'\D+', '', m.group(0))
        # Keep plausible 10–15 digits
        if 10 <= len(digits) <= 15:
            # Normalize to US-like 10-digit XXX-XXX-XXXX if length==10, else E.164-like
            if len(digits) == 10:
                return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
            return f"+{digits}" if not digits.startswith("+") else digits
    return None

def guess_name(text: str, fallback: str) -> str:
    # Very light heuristic: first non-empty line that isn’t an email/phone blob
    for line in (text or "").splitlines():
        ln = line.strip()
        if not ln:
            continue
        if EMAIL_RE.search(ln) or PHONE_CANDIDATE_RE.search(ln):
            continue
        # avoid ALL CAPS paragraphs and super-long lines
        if len(ln) <= 80:
            return ln
    return fallback

def simple_metadata(text: str, fallback_name: str) -> dict:
    """Return clean per-resume metadata with isolated email/phone fields."""
    email = extract_email(text)
    phone = extract_phone(text)
    name  = guess_name(text, fallback_name)
    return {
        "candidate_name": name,
        "email": email,
        "phone": phone,
    }