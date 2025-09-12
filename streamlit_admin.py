# streamlit_admin.py
import io
import os
import time
import math
import pickle
import zipfile
from pathlib import Path
from typing import List, Dict, Tuple

import coll
import streamlit as st
import pandas as pd
import chromadb
import requests
from pypdf import PdfReader
from docx import Document as Docx
import traceback as tb
from urllib.parse import unquote
from config import (
    CHROMA_DIR, CHROMA_COLLECTION, INDEX_DIR,
    BM25_CORPUS_PATH, BM25_META_PATH, EMBED_MODEL,
    RESUMES_STORE_DIR, ALLOWED_EXTS, BM25_DOCIDS_PATH,
    CHUNK_SIZE, CHUNK_OVERLAP
)
from utils_text import clean_text, tokenize, simple_metadata
from langsmith import Client, traceable
import hashlib
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json as pyjson
import re, hashlib
from pathlib import Path
import json as pyjson
import time
import hashlib
import mimetypes
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import pandas as pd
import requests
from pathlib import Path

from utils_text import clean_text
st.set_page_config(page_title="JD–Resume Admin", page_icon="🗂️", layout="wide")
def get_ceipal_secrets():
    # reads from Streamlit secrets first, then env
    def _secret(name: str, default: str = ""):
        try:
            return st.secrets.get(name, default)
        except Exception:
            return os.getenv(name, default)
    return (
        _secret("CEIPAL_USERNAME", ""),
        _secret("CEIPAL_PASSWORD", ""),
        _secret("CEIPAL_API_KEY", ""),
        _secret("CEIPAL_ENDPOINT_URL", "")
    )
CEIPAL_AUTH_URL = "https://api.ceipal.com/getCustomApplicantDetails/UGtpQkJSTEZ3Z0xBaDdsN1QwOXBIUT09/3d5824dff94ff8d084ed97f34efe67cc"



def ceipal_session():
    s = requests.Session()
    retry = Retry(total=5, connect=3, read=3, backoff_factor=0.6,
                  status_forcelist=[429, 502, 503, 504], allowed_methods=["GET","POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    proxy = _secret("HTTPS_PROXY", "")
    if proxy:
        s.proxies.update({"https": proxy, "http": proxy})
    s.headers.update({"Accept": "application/json", "User-Agent": "ResumeFinder/1.0"})
    return s

# replace your ceipal_auth with this version
def ceipal_auth(email: str, password: str, api_key: str, base_url: str) -> str:
    base = (base_url or "https://api.ceipal.com").rstrip("/")
    url  = f"{base}/v1/createAuthtoken/"
    payload = {
        "email": (email or "").strip(),
        "password": password or "",
        "api_key": (api_key or "").strip(),
        "json": 1,
    }
    s = ceipal_session()
    r = s.post(url, data=payload, timeout=(5, 60))
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"Auth HTTP {r.status_code}: {e} | Server said: {r.text[:400]}")
    data = r.json()

    # accept all common CEIPAL variants
    token = (
        data.get("token")
        or data.get("authtoken")
        or (data.get("data") or {}).get("token")
        or data.get("access_token")              # <- your tenant returns this
    )
    if not token:
        raise RuntimeError(f"Auth OK but token missing in body: {pyjson.dumps(data)[:400]}")
    return str(token)


def ceipal_iter_applicants(endpoint_url: str, token: str | None, auth_style: str = "bearer",
                           paging_length: int = 30, max_pages: int | None = None):
    """
    Supports two styles:
      - bearer: Authorization header with Bearer <token>, plain endpoint URL
      - path:   endpoint already encodes auth in the path; do NOT send Authorization
    """
    s = ceipal_session()
    page = 1
    while True:
        params = {"paging_length": paging_length, "page": page}
        headers = {}
        if auth_style == "bearer" and token:
            headers["Authorization"] = f"Bearer {token}"
        r = s.get(endpoint_url, params=params, headers=headers, timeout=(5, 60))
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            raise RuntimeError(f"Fetch HTTP {r.status_code}: {e} | Server said: {r.text[:400]}")
        obj = r.json()
        rows = obj if isinstance(obj, list) else (obj.get("data") or obj.get("results") or [])
        if not rows:
            break
        for row in rows:
            yield row
        page += 1
        if max_pages and page > max_pages:
            break
# --- secrets helper (reads Streamlit secrets first, then env) ---
def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)  # Streamlit secrets.toml
    except Exception:
        return os.getenv(name, default)       # fallback to OS env

def _mask(v: str) -> str:
    if not v: return "(missing)"
    if len(v) <= 4: return "****"
    return v[:2] + ("*" * max(0, len(v) - 4)) + v[-2:]

# --- step 3/7: CEIPAL → safe text + dedupe helpers ---

SENSITIVE = {"ssn", "date_of_birth", "gpa"}  # never embed/store
SAFE_KEYS = [
    "email_address","alternate_email_address",
    "home_phone_number","mobile_number","work_phone_number","other_phone",
    "job_title","experience","skills","primary_skills","technology",
    "work_authorization","clearance",
    "city","state","country","zip_code",
    "linkedin_profile_url","expected_pay","relocation","tax_terms",
    "source","referred_by","applicant_status","ownership"
]

def _canon_dict(d: dict) -> dict:
    drop = {"updated_at","created_at","last_modified","last_login","last_modified_by"}
    return {k: ("" if d.get(k) is None else d[k]) for k in sorted(d) if k not in drop}

def applicant_sha(app: dict) -> str:
    blob = pyjson.dumps(_canon_dict(app), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

def sanitize_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+","-", (s or "").lower()).strip("-") or "applicant"

def applicant_to_text(a: dict) -> str:
    # build a search-friendly, PII-safe “virtual resume” string
    name = " ".join([a.get("first_name",""), a.get("middle_name",""), a.get("last_name","")]).strip()
    parts = []
    if name: parts.append(f"Name: {name}")
    def add(k, label=None):
        if k in SENSITIVE: return
        v = (a.get(k) or "")
        if isinstance(v, (list, tuple)): v = ", ".join([str(x) for x in v if x])
        v = str(v).strip()
        if v:
            parts.append(f"{(label or k).replace('_',' ').title()}: {v}")
    for k in SAFE_KEYS: add(k)
    return " | ".join(parts)

def build_meta_from_app(a: dict, sha_full: str) -> dict:
    name = " ".join([a.get("first_name",""), a.get("middle_name",""), a.get("last_name","")]).strip()
    ceipal_id = str(a.get("id") or a.get("applicant_id") or a.get("candidate_id") or "")
    resume_path = (a.get("resume_path") or a.get("resume_url") or "").strip()
    return {
        "candidate_name": name or (a.get("email_address") or a.get("alternate_email_address") or f"CEIPAL {sha_full[:12]}"),
        "email": a.get("email_address") or a.get("alternate_email_address"),
        "phone": a.get("mobile_number") or a.get("work_phone_number") or a.get("home_phone_number"),
        "source_ext": "ceipal",
        "sha256": sha_full,
        "short_hash": sha_full[:12],
        "linkedin": a.get("linkedin_profile_url") or "",
        "city": a.get("city") or "", "state": a.get("state") or "", "country": a.get("country") or "",
        "work_auth": a.get("work_authorization") or "", "clearance": a.get("clearance") or "",
        "file_path": "",  # no local file for API-sourced profiles
        "ceipal_id": ceipal_id,
        "resume_path": resume_path,
    }
    return {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in md.items() if v is not None}
# stable parent id for CEIPAL records
def make_base_id(a: dict, md: dict) -> str:
    """
    Prefer CEIPAL candidate id; fall back to email, then name.
    Keeps document_id stable across re-syncs (prevents dupes).
    """
    cid = (md.get("ceipal_id") or a.get("id") or a.get("candidate_id") or a.get("applicant_id"))
    if cid:
        return f"ceipal-{str(cid)}"
    key = md.get("email") or md.get("candidate_name") or "applicant"
    return f"ceipal-{sanitize_slug(key)}"

def exists_by_ceipal_id(coll, ceipal_id):
    if not ceipal_id:
        return False
    got = coll.get(where={"ceipal_id": str(ceipal_id)})
    return bool(got and got.get("ids"))

def exists_by_document_id(coll, doc_id):
    """doc_id in the UI == parent_id in chunk metadata"""
    got = coll.get(where={"parent_id": str(doc_id)})
    return bool(got and got.get("ids"))

def delete_by_document_id(coll, doc_id) -> int:
    """Delete all chunk vectors for one parent (parent_id)."""
    got = coll.get(where={"parent_id": str(doc_id)})
    ids = (got or {}).get("ids") or []
    if ids:
        coll.delete(ids=ids)
    return len(ids)


def already_exists_by_sha(collection, sha: str) -> bool:
    try:
        got = collection.get(where={"sha256": sha}, include=[])
        return bool(got and got.get("ids"))
    except Exception:
        return False


# --- step 2/7: CEIPAL auth + fetch test (tenant-aware) ---
def _http_debug(resp):
    try:
        body_txt = resp.text[:1200]
    except Exception:
        body_txt = "<no text>"
    return {
        "status": getattr(resp, "status_code", None),
        "url": getattr(resp, "url", None),
        "headers_sample": dict(list(getattr(resp, "headers", {}).items())[:10]),
        "body_preview": body_txt,
    }

def show_exception(e):
    st.exception(e)
    resp = getattr(e, "response", None)
    if resp is not None:
        st.code(pyjson.dumps(_http_debug(resp), indent=2), language="json")

with st.expander("Step 2 of 7 – CEIPAL auth + fetch (diagnostics)", expanded=False):
    base = _secret("CEIPAL_BASE_URL", "https://api.ceipal.com")
    url  = _secret("CEIPAL_ENDPOINT_URL", "")
    style = (_secret("CEIPAL_AUTH_STYLE", "bearer") or "bearer").lower().strip()
    u = _secret("CEIPAL_USERNAME", "")
    p = _secret("CEIPAL_PASSWORD", "")
    k = _secret("CEIPAL_API_KEY", "")

    st.caption(f"base={base} | endpoint={url or '(missing)'} | style={style}")

    c1, c2, c3, c4 = st.columns(4)

    if c1.button("Connectivity check"):
        try:
            s = ceipal_session()
            r = s.get(base, timeout=(5, 10))
            st.success(f"HTTPS OK → {r.status_code}")
        except Exception as e:
            st.error("Connectivity failed")
            show_exception(e)

    if c2.button("Test auth (bearer)"):
        if style == "path":
            st.info("Skipped (style=path).")
        else:
            try:
                tok = ceipal_auth(u.strip(), p, k.strip(), base.strip())
                st.success("Auth OK")
                st.code(tok[:6] + "..." + tok[-6:], language="text")
            except Exception as e:
                st.error("Auth failed")
                show_exception(e)

    if c3.button("Preview (path style)"):
        try:
            s = ceipal_session()
            params = {"paging_length": 5, "page": 1}
            r = s.get(url, params=params, timeout=(5, 60))
            r.raise_for_status()
            st.write("final URL", r.url)
            try:
                data = r.json()
            except Exception:
                st.warning("Response is not JSON, showing text preview")
                st.code(r.text[:1200])
                data = []
            rows = data if isinstance(data, list) else (data.get("data") or data.get("results") or [])
            st.dataframe(pd.DataFrame(rows[:5]), use_container_width=True, hide_index=True) if rows else st.warning("No rows returned.")
            st.success("Path call OK")
        except Exception as e:
            st.error("Path preview failed")
            show_exception(e)

    if c4.button("Preview (bearer style)"):
        try:
            tok = ceipal_auth(u.strip(), p, k.strip(), base.strip())
            sample = []
            for i, row in enumerate(ceipal_iter_applicants(url, tok, auth_style="bearer", paging_length=30, max_pages=1)):
                if i >= 5: break
                sample.append(row)
            st.dataframe(pd.DataFrame(sample), use_container_width=True, hide_index=True) if sample else st.warning("No rows.")
            st.success("Bearer preview OK")
        except Exception as e:
            st.error("Bearer preview failed")
            show_exception(e)

# --- step 3/7: CEIPAL safe text + dedupe preview (no ingest) ---
with st.expander("Step 3 of 7 – CEIPAL safe text + dedupe preview", expanded=False):
    base = _secret("CEIPAL_BASE_URL", "https://api.ceipal.com")
    url  = _secret("CEIPAL_ENDPOINT_URL", "")
    style = (_secret("CEIPAL_AUTH_STYLE", "bearer") or "bearer").lower().strip()
    u = _secret("CEIPAL_USERNAME", "")
    p = _secret("CEIPAL_PASSWORD", "")
    k = _secret("CEIPAL_API_KEY", "")

    colA, colB = st.columns([1,1])
    paging_len = colA.number_input("paging_length", 1, 100, 5, 1)
    page_one   = colB.checkbox("Only first page", value=True)

    if st.button("Build preview (first few applicants)"):
        try:
            tok = None
            if style == "bearer":
                tok = ceipal_auth(u.strip(), p, k.strip(), base.strip())

            preview_rows = []
            count = 0
            for row in ceipal_iter_applicants(url, tok, auth_style=style, paging_length=int(paging_len), max_pages=(1 if page_one else None)):
                sha = applicant_sha(row)
                text = clean_text(applicant_to_text(row))
                meta = build_meta_from_app(row, sha)
                slug = sanitize_slug(meta.get("email") or meta.get("candidate_name"))
                base_id = f"ceipal-{slug}-{sha[:12]}"
                preview_rows.append({
                    "candidate_name": meta["candidate_name"],
                    "email": meta.get("email"),
                    "phone": meta.get("phone"),
                    "sha12": sha[:12],
                    "dup_in_chroma": already_exists_by_sha(coll, sha),
                    "base_id": base_id,
                    "text_preview": (text[:160] + "…") if len(text) > 160 else text,
                    "ceipal_id": meta.get("ceipal_id", ""),
                    "resume_path": (meta.get("resume_path", "")[:60] + "…") if (
                                meta.get("resume_path") and len(meta["resume_path"]) > 60) else (
                                meta.get("resume_path") or ""),
                    "text_preview": (text[:160] + "…") if len(text) > 160 else text,
                })
                count += 1
                if count >= paging_len: break

            if preview_rows:
                st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
                st.success("Preview ready. If dup_in_chroma is True, that applicant will be skipped during ingest.")
                st.info("Next: Step 4 will wire ingestion into Chroma + BM25 using add_one_document().")
            else:
                st.warning("Endpoint returned no rows.")
        except Exception as e:
            st.error(f"Preview failed: {e}")


# ---------- Helpers ----------

def chunk_text(text: str, size: int, overlap: int) -> List[str]:
    """Simple character-level chunker with overlap. No external deps."""
    text = text or ""
    n = len(text)
    if n == 0:
        return []
    size = max(1, int(size))
    overlap = max(0, int(overlap))
    if overlap >= size:
        overlap = size // 4  # guard
    chunks = []
    start = 0
    while start < n:
        end = min(n, start + size)
        chunks.append(text[start:end])
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks

@st.cache_resource(show_spinner=False)
def get_chroma():
    # Compatible with ChromaDB v0.3–0.5+
    try:
        if hasattr(chromadb, "PersistentClient"):
            client = chromadb.PersistentClient(path=CHROMA_DIR)
        else:
            # older API
            from chromadb.config import Settings
            client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory=CHROMA_DIR))
    except Exception:
        st.error(
            "Failed to initialize Chroma client. Upgrade chromadb with `pip install -U chromadb==0.5.5` or ensure the older Settings-based API is available.",
            icon="⚠️",
        )
        raise
    coll = client.get_or_create_collection(name=CHROMA_COLLECTION)
    os.makedirs(INDEX_DIR, exist_ok=True)
    os.makedirs(RESUMES_STORE_DIR, exist_ok=True)
    return client, coll

def _chunk_stats(chunks: List[str], text_len: int, size: int, overlap: int) -> Dict:
    """Compute detailed chunk statistics for LangSmith logging."""
    stats = {
        "chunk_count": 0,
        "chunk_length_mean": 0,
        "chunk_length_median": 0,
        "chunk_length_p95": 0,
        "chunk_length_min": 0,
        "chunk_length_max": 0,
        "chunk_size_cfg": size,
        "chunk_overlap_cfg": overlap,
        "chunk_lengths_sample": [],
        "chunk_lengths_sampled_n": 0,
        "empty_chunk_count": 0,
        "last_chunk_len": 0,
        "expected_chunk_count": 0,
        "chunk_count_deviation": 0,
        "percent_within_band": 0.0,
        "tail_shrink_ratio": 0.0,
        "coverage_chars_unique_approx": 0,
        "coverage_ratio": 1.0,
        "text_len": int(text_len or 0),
    }
    if not chunks:
        return stats

    lens = [len(c) for c in chunks]
    n = len(lens)
    stats["chunk_count"] = n
    stats["empty_chunk_count"] = sum(1 for L in lens if L == 0)
    stats["last_chunk_len"] = lens[-1] if n else 0
    stats["chunk_length_min"] = min(lens)
    stats["chunk_length_max"] = max(lens)
    stats["chunk_length_mean"] = sum(lens) / n
    lens_sorted = sorted(lens)
    # median
    if n % 2 == 1:
        stats["chunk_length_median"] = lens_sorted[n // 2]
    else:
        stats["chunk_length_median"] = (lens_sorted[n // 2 - 1] + lens_sorted[n // 2]) / 2
    # p95
    p95_idx = max(0, int(0.95 * (n - 1)))
    stats["chunk_length_p95"] = lens_sorted[p95_idx]
    # sample of lengths to avoid huge payloads
    stats["chunk_lengths_sample"] = lens[:200]
    stats["chunk_lengths_sampled_n"] = min(n, 200)

    # metrics vs config
    size = max(1, int(size))
    overlap = max(0, int(overlap))
    expected = math.ceil(text_len / size) if size > 0 else n
    stats["expected_chunk_count"] = expected
    stats["chunk_count_deviation"] = n - expected

    # within-band %: [0.6 * size, 1.0 * size]
    lo = int(0.6 * size)
    hi = size
    within = sum(1 for L in lens if lo <= L <= hi)
    stats["percent_within_band"] = (within / n) if n else 0.0

    # tail shrink ratio
    stats["tail_shrink_ratio"] = (stats["last_chunk_len"] / size) if size else 0.0

    # coverage (approx): sum(lens) / (text_len + (n - 1) * overlap)
    denom = (text_len + max(0, n - 1) * overlap)
    stats["coverage_chars_unique_approx"] = denom
    stats["coverage_ratio"] = (sum(lens) / denom) if denom > 0 else 1.0

    return stats

@st.cache_resource(show_spinner=False)
def get_embedder():
    # Lazy-init so the UI can load even if Ollama isn't up yet.
    from langchain_community.embeddings import OllamaEmbeddings
    return OllamaEmbeddings(model=EMBED_MODEL)

def ollama_healthcheck():
    base = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434"
    try:
        r = requests.get(base.rstrip("/") + "/api/tags", timeout=2.5)
        ok = r.ok
        tags = r.json() if ok else None
        return ok, base, tags
    except Exception:
        return False, base, None

def read_text_from_doc_bytes(data: bytes, filename: str = "file.doc") -> str:
    """
    Extract text from legacy .doc files.
    Tries: MS Word (pywin32) → LibreOffice headless → fallback latin-1.
    """
    from datetime import datetime
    import subprocess, shutil

    tmp_dir = Path.cwd() / "_doc_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem) or "doc"
    src = tmp_dir / f"{stem}-{datetime.now().timestamp():.0f}.doc"
    with open(src, "wb") as f:
        f.write(data)

    # 1) Microsoft Word via COM (Windows + Word installed)
    try:
        import win32com.client  # pip install pywin32
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(str(src))
        out_txt = str(src.with_suffix(".txt"))
        wdFormatText = 2
        doc.SaveAs(out_txt, FileFormat=wdFormatText)
        doc.Close(False)
        word.Quit()
        return Path(out_txt).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass

    # 2) LibreOffice headless (cross-platform)
    try:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "txt:Text", "--outdir", str(tmp_dir), str(src)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            out_txt = src.with_suffix(".txt")
            if out_txt.exists():
                return out_txt.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass

    # 3) Best-effort fallback
    return data.decode("latin1", errors="ignore")



def read_text_from_bytes(data: bytes, filename: str) -> str:
    """
    Robust text extraction for PDF/DOCX/DOC/RTF/TXT regardless of filename extension.
    We first sniff the content; if that fails, we fall back to the filename suffix.
    """
    # Primary: sniff kind from bytes
    kind = _sniff_ext_from_bytes(data, filename)

    # Fallback to suffix if sniffing could not decide
    if not kind:
        kind = Path(filename).suffix.lower()

    try:
        if kind == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "".join(page.extract_text() or "" for page in reader.pages)

        if kind == ".docx":
            from docx import Document as Docx
            doc = Docx(io.BytesIO(data))
            return "\n".join(p.text or "" for p in doc.paragraphs)

        if kind == ".doc":
            return read_text_from_doc_bytes(data, filename)

        if kind == ".rtf":
            # quick-and-clean RTF text pass
            txt = data.decode(errors="ignore")
            # strip basic RTF control words/braces
            txt = re.sub(r"[{}]", " ", txt)
            txt = re.sub(r"\\[a-zA-Z]+\d* ?", " ", txt)
            return re.sub(r"\s+", " ", txt).strip()

        # default: treat as text
        return data.decode("utf-8", errors="ignore")

    except Exception:
        # One more try: if kind looks wrong, re-sniff and attempt DOC fallback
        alt = _sniff_ext_from_bytes(data, filename)
        if alt == ".doc":
            try:
                return read_text_from_doc_bytes(data, filename)
            except Exception:
                pass
        # Final fallback
        return data.decode("latin1", errors="ignore")


def save_bytes_to_store(data: bytes, filename: str) -> Tuple[str, str, str]:
    """
    Save a canonical copy to RESUMES_STORE_DIR.
    Returns (stored_path, sha256_full, short_hash12)
    """
    import hashlib
    h = hashlib.sha256()
    h.update(data)
    sha256_full = h.hexdigest()
    short12 = sha256_full[:12]
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem
    stored_name = f"{stem}.{short12}{ext}"
    stored_path = os.path.join(RESUMES_STORE_DIR, stored_name)
    if not os.path.exists(stored_path):
        with open(stored_path, "wb") as f:
            f.write(data)
    return stored_path, sha256_full, short12

def load_bm25():
    if os.path.exists(BM25_CORPUS_PATH):
        with open(BM25_CORPUS_PATH, "rb") as f:
            corpus_tokens = pickle.load(f)
    else:
        corpus_tokens = []
    if os.path.exists(BM25_META_PATH):
        with open(BM25_META_PATH, "rb") as f:
            meta_by_id = pickle.load(f)
    else:
        meta_by_id = {}
    if os.path.exists(BM25_DOCIDS_PATH):
        with open(BM25_DOCIDS_PATH, "rb") as f:
            doc_ids = pickle.load(f)
    else:
        doc_ids = []
    return corpus_tokens, meta_by_id, doc_ids

def save_bm25(corpus_tokens, meta_by_id, doc_ids):
    with open(BM25_CORPUS_PATH, "wb") as f:
        pickle.dump(corpus_tokens, f)
    with open(BM25_META_PATH, "wb") as f:
        pickle.dump(meta_by_id, f)
    with open(BM25_DOCIDS_PATH, "wb") as f:
        pickle.dump(doc_ids, f)

def already_exists(coll, sha256: str, local_meta_by_id: dict | None = None) -> bool:
    """Robust duplicate check that works across Chroma versions.
    First checks local metadata cache, then attempts a metadata-filtered get.
    """
    if local_meta_by_id:
        for md in local_meta_by_id.values():
            if md.get("sha256") == sha256:
                return True
    try:
        res = coll.get(where={"sha256": sha256}, include=[], limit=1)
        return bool(res.get("ids"))
    except Exception:
        return False

def normalize_ext(filename: str) -> str:
    return Path(filename).suffix.lower()

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".rtf", ".DOC"}

def validate_ext(filename: str) -> bool:
    ext = normalize_ext(filename)
    return ext in SUPPORTED_EXTS

def _ext_from_content_type(ct: str) -> str:
    ct = (ct or "").split(";")[0].strip().lower()
    mapping = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/rtf": ".rtf",
        "text/plain": ".txt",
    }
    return mapping.get(ct, "")

def _filename_from_content_disposition(cd: str | None) -> str | None:
    if not cd:
        return None
    m = re.search(r"filename\*=.*?''([^;]+)", cd)  # RFC 5987
    if m:
        return unquote(m.group(1))
    m = re.search(r'filename="?([^";]+)"?', cd)     # basic
    if m:
        return m.group(1)
    return None

def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:180]

def _decide_save_path(cid: str, url: str, resp, dest_dir: str, default_docx: bool = True) -> Path:
    """
    Choose filename/extension using, in order:
      1) Content-Disposition filename (authoritative)
      2) Final response URL path (after redirects)
      3) Content-Type mapping
      4) Fallback: .docx if default_docx else .bin
    """
    # 1) filename from headers
    fn = _filename_from_content_disposition(resp.headers.get("content-disposition"))
    # 2) else final URL path
    if not fn:
        final_url = getattr(resp, "url", None) or url
        fn = Path(urlparse(final_url).path).name or ""
    # extension from filename if present
    ext = "".join(Path(fn).suffixes).lower()

    # 3) if still missing, try Content-Type
    if not ext:
        ext = _ext_from_content_type(resp.headers.get("content-type"))
    # 4) final fallback — default to Word
    if not ext:
        ext = ".docx" if default_docx else ".bin"

    # base name (prefer header/url stem, else generic)
    base = _safe_name(Path(fn).stem) if fn else f"ceipal-{cid}"
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    filename = f"{base}-{h}{ext}"
    return Path(dest_dir) / filename


def _extract_candidate_id(row: dict) -> str:
    return str(
        row.get("candidate_id")
        or row.get("id")
        or row.get("ceipal_id")
        or row.get("applicant_id")
        or ""
    ).strip()

def _extract_resume_url(row: dict) -> str | None:
    return (
        row.get("resume_path")
        or row.get("resume")
        or row.get("resumeUrl")
        or row.get("resume_url")
        or row.get("resume_file")
        or row.get("file_url")
        or None
    )

def _extract_creation_dt(row: dict) -> datetime | None:
    # Try several possible CEIPAL field names
    candidates = [
        row.get("created_at"), row.get("creation_date"),
        row.get("createdDate"), row.get("date_created"),
        row.get("created_on"), row.get("created"),
        row.get("dateAdded")
    ]
    for v in candidates:
        if v is None or v == "":
            continue
        try:
            if isinstance(v, (int, float)):
                return datetime.fromtimestamp(float(v), tz=timezone.utc)
            dt = pd.to_datetime(v, utc=True, errors="coerce")
            if isinstance(dt, pd.Timestamp) and not pd.isna(dt):
                return dt.to_pydatetime()
            if isinstance(dt, datetime):
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None

def _is_within(dt: datetime | None, since: datetime, until: datetime) -> bool:
    if dt is None:
        return False
    # normalize to UTC bounds
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (since <= dt <= until)

def _suggest_filename(candidate_id: str, resume_url: str) -> str:
    parsed = urlparse(resume_url)
    name = Path(parsed.path).name or "resume"
    ext = "".join(Path(name).suffixes)
    if not ext:
        # best-effort extension from MIME
        guess = mimetypes.guess_extension(mimetypes.guess_type(resume_url)[0] or "")
        ext = guess or ".pdf"
    h = hashlib.sha1(resume_url.encode("utf-8")).hexdigest()[:8]
    base = f"ceipal-{candidate_id}-{h}"
    return base + ext

def _existing_candidate_ids(coll, meta_by_id: dict) -> set[str]:
    ids = set()
    # from BM25 parent meta
    for md in (meta_by_id or {}).values():
        cid = str(md.get("candidate_id") or md.get("ceipal_id") or md.get("id") or "").strip()
        if cid: ids.add(cid)
    # from Chroma (source=ceipal)
    try:
        got = coll.get(where={"source": "ceipal"}, include=["metadatas"])
        for md in (got or {}).get("metadatas") or []:
            if not isinstance(md, dict): continue
            cid = str(md.get("candidate_id") or md.get("ceipal_id") or md.get("id") or "").strip()
            if cid: ids.add(cid)
    except Exception:
        pass
    return ids

try:
    import olefile  # optional but nice for .doc detection
    _HAVE_OLE = True
except Exception:
    _HAVE_OLE = False

def _sniff_ext_from_bytes(data: bytes, filename: str = "") -> str:
    """
    Guess a stable extension from the file signature, ignoring the filename.
    Returns one of: .pdf, .docx, .doc, .rtf, .txt, .zip, or '' (unknown).
    """
    if not data:
        ext = Path(filename).suffix.lower()
        return ext or ""
    sig8 = data[:8]
    head = data[:4096].lstrip()

    # PDF
    if data[:5] == b"%PDF-":
        return ".pdf"

    # RTF
    if head.startswith(b"{\\rtf"):
        return ".rtf"

    # OOXML (zip); check inner structure
    if sig8.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
            if any(n.startswith("word/") for n in names): return ".docx"
            if any(n.startswith("ppt/")  for n in names): return ".pptx"
            if any(n.startswith("xl/")   for n in names): return ".xlsx"
        except Exception:
            pass
        return ".zip"

    # OLE/CFBF (97–2003)
    if sig8 == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1":
        if _HAVE_OLE:
            try:
                with olefile.OleFileIO(io.BytesIO(data)) as ole:
                    streams = {"/".join(s) for s in ole.listdir()}
                if any("WordDocument" in s for s in streams): return ".doc"
                if any("Workbook" in s for s in streams): return ".xls"
                if any("PowerPoint Document" in s for s in streams): return ".ppt"
            except Exception:
                pass
        return ".doc"  # best guess for OLE
    # Plain-ish text fallback
    try:
        sample = head[:512]
        sample.decode("utf-8")
        return ".txt"
    except Exception:
        return ""

# --- Delete helpers (Chroma + BM25) ---
def chroma_delete_by_document_ids(coll, parent_ids) -> int:
    """Bulk delete: remove all chunk vectors for the given parent_ids."""
    pid_list = [str(p) for p in parent_ids if p]
    if not pid_list:
        return 0
    got = coll.get(where={"parent_id": {"$in": pid_list}})
    ids = (got or {}).get("ids") or []
    if ids:
        coll.delete(ids=ids)
    return len(ids)

def bm25_prune_after_delete(corpus_tokens, bm25_doc_ids, meta_by_id, parent_ids):
    """Remove deleted parents from BM25 artifacts + metadata (in place)."""
    drop = {str(p) for p in parent_ids if p}
    keep = [(t, d) for (t, d) in zip(corpus_tokens, bm25_doc_ids) if str(d) not in drop]
    if keep:
        new_tokens, new_ids = zip(*keep)
        corpus_tokens[:] = list(new_tokens)
        bm25_doc_ids[:]  = list(new_ids)
    else:
        corpus_tokens[:] = []
        bm25_doc_ids[:]  = []
    for pid in drop:
        meta_by_id.pop(pid, None)

# ---------- LangSmith helpers (tracing + dataset export) ----------

@st.cache_resource(show_spinner=False)
def get_langsmith_client():
    try:
        return Client()
    except Exception as e:
        st.warning(f"LangSmith client not available: {e}")
        return None

@traceable(name="admin.embed_chunks", run_type="embedding")
def _embed_chunks(embedder, chunks: List[str]):
    return embedder.embed_documents(chunks)

@traceable(name="admin.add_one_document", run_type="chain")
def add_one_document(
    coll,
    text: str,
    metadata: Dict,
    base_doc_id: str,
    corpus_tokens: List[List[str]],
    bm25_doc_ids: List[str]
):
    # embedder
    try:
        embedder = get_embedder()
    except Exception:
        st.error(
            "Cannot initialize Ollama embeddings. Make sure Ollama is running and the model is pulled.",
            icon="⚠️",
        )
        raise

    # chunking
    chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
    if not chunks:
        raise ValueError("No text chunks produced from document")

    # embed in a batch (traced)
    try:
        vecs = _embed_chunks(embedder, chunks)
    except Exception:
        st.error("Embedding request failed. Is the Ollama server reachable and responsive?", icon="⚠️")
        raise

    # per-chunk metadata & ids
    metas = []
    ids = []
    for i, ch in enumerate(chunks):
        cid = f"{base_doc_id}::c{i:04d}"
        m = dict(metadata or {})
        m.update({
            "parent_id": base_doc_id,
            "chunk_index": i,
            "chunk_total": len(chunks),
            "text_len": len(ch),
        })
        m = {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in m.items() if v is not None}
        metas.append(m)
        ids.append(cid)
        corpus_tokens.append(tokenize(ch))
        bm25_doc_ids.append(cid)

    coll.add(documents=chunks, metadatas=metas, ids=ids, embeddings=vecs)

    # return detailed chunk stats
    stats = _chunk_stats(chunks, len(text), CHUNK_SIZE, CHUNK_OVERLAP)
    stats.update({
        "base_doc_id": base_doc_id,
    })
    # propagate a few file-level fields for convenience if present
    for k in ("sha256", "short_hash", "source_ext", "source_filename", "file_size_bytes"):
        if k in metadata:
            # promote to top-level names that match earlier UI
            if k == "sha256":
                stats["file_sha256"] = metadata.get(k)
            elif k == "short_hash":
                stats["short_hash"] = metadata.get(k)
            else:
                stats[k] = metadata.get(k)
    return stats

@traceable(name="admin.ingest_file", run_type="chain")
def ingest_file(
    coll,
    file_bytes: bytes,
    filename: str,
    alpha_secs: float,
    local_meta_by_id: Dict[str, Dict],
    corpus_tokens: List[List[str]],
    bm25_doc_ids: List[str],
):
    t0 = time.perf_counter()
    stored_path, sha256_full, short12 = save_bytes_to_store(file_bytes, filename)

    # duplicate check timing
    t_dup0 = time.perf_counter()
    is_dup = already_exists(coll, sha256_full, local_meta_by_id)
    dup_check_ms = (time.perf_counter() - t_dup0) * 1000.0

    result = {
        "source_filename": filename,
        "source_ext": normalize_ext(filename),
        "file_size_bytes": len(file_bytes),
        "file_sha256": sha256_full,
        "short_hash": short12,
        "already_exists_checked": True,
        "duplicate_check_latency_ms": dup_check_ms,
        "is_duplicate_blocked": bool(is_dup),
        "duplicate_reason": "sha256" if is_dup else "none",
        "ingested": False,
        "duration_ms_total": None,
        "error": None,
    }

    if is_dup:
        result["duration_ms_total"] = (time.perf_counter() - t0) * 1000.0
        return result  # early exit; duplicate was blocked

    # extract and clean text
    try:
        text_raw = read_text_from_bytes(file_bytes, filename)
        text = clean_text(text_raw)
        if not text.strip():
            result["duplicate_reason"] = "no_text"
            result["duration_ms_total"] = (time.perf_counter() - t0) * 1000.0
            return result
    except Exception as e:
        result["error"] = f"text_extract_error: {e}"
        result["duration_ms_total"] = (time.perf_counter() - t0) * 1000.0
        return result

    # metadata + id
    md = simple_metadata(text, Path(filename).stem)
    md.update({
        "file_path": stored_path,
        "short_hash": short12,
        "sha256": sha256_full,
        "source_ext": normalize_ext(filename),
        "source_filename": filename,
        "file_size_bytes": len(file_bytes),
    })
    base_id = f"{Path(filename).stem}-{short12}"

    # add to Chroma (also traced), and collect chunk stats
    try:
        stats = add_one_document(coll, text, md, base_id, corpus_tokens, bm25_doc_ids) or {}
        local_meta_by_id[base_id] = md
        result.update(stats)
        result["ingested"] = True
    except Exception as e:
        result["error"] = f"add_error: {e}"

    if alpha_secs and alpha_secs > 0:
        time.sleep(alpha_secs)

    result["duration_ms_total"] = (time.perf_counter() - t0) * 1000.0
    return result

def list_collection(coll) -> pd.DataFrame:
    """Aggregate by parent resume so the table shows one row per resume, not per chunk."""
    page_size = 1000
    ids_all, metas_all = [], []
    offset = 0
    while True:
        batch = coll.get(include=["metadatas"], limit=page_size, offset=offset)
        ids = batch.get("ids", [])
        metas = batch.get("metadatas", [])
        if not ids:
            break
        ids_all.extend(ids)
        metas_all.extend(metas)
        offset += len(ids)

    # aggregate by parent_id
    agg: Dict[str, Dict] = {}
    for _id, m in zip(ids_all, metas_all):
        pid = (m or {}).get("parent_id") or _id.split("::")[0]
        row = agg.get(pid)
        if not row:
            agg[pid] = {
                "document_id": pid,
                "candidate_name": m.get("candidate_name"),
                "email": m.get("email"),
                "phone": m.get("phone"),
                "source_ext": m.get("source_ext"),
                "short_hash": m.get("short_hash"),
                "sha256": m.get("sha256"),
                "file_path": m.get("file_path"),
                "chunks": 1,
            }
        else:
            row["chunks"] = row.get("chunks", 0) + 1

    df = pd.DataFrame(list(agg.values()))
    if not df.empty:
        df = df.sort_values("candidate_name", na_position="last").reset_index(drop=True)
    return df

def export_contacts_dataset_to_langsmith(df: pd.DataFrame, dataset_name: str):
    """Push current inventory to a LangSmith dataset for contact parsing validation."""
    client = get_langsmith_client()
    if client is None:
        st.error("LangSmith client not available. Set LANGSMITH_API_KEY and LANGSMITH_TRACING=true.")
        return
    # create or reuse dataset
    try:
        ds = client.create_dataset(dataset_name, description="Resume parsing/contacts verification examples")
    except Exception:
        # if exists, fetch by name
        ds = None
        try:
            for d in client.list_datasets():
                if getattr(d, "name", None) == dataset_name:
                    ds = d
                    break
        except Exception:
            pass
        if ds is None:
            raise

    # build examples from inventory
    examples = []
    for _, row in df.iterrows():
        fp = row.get("file_path")
        snippet = ""
        try:
            if fp and Path(fp).exists():
                with open(fp, "rb") as fh:
                    data = fh.read()
                snippet = (read_text_from_bytes(data, Path(fp).name) or "")[:2000]
        except Exception:
            snippet = ""

        inputs = {
            "document_id": row.get("document_id"),
            "file_path": fp,
            "text_snippet": snippet,
        }
        reference_outputs = {
            "candidate_name": row.get("candidate_name"),
            "email": row.get("email"),
            "phone": row.get("phone"),
            "source_ext": row.get("source_ext"),
        }
        examples.append({"inputs": inputs, "outputs": reference_outputs})

    # chunk insert
    BATCH = 50
    for i in range(0, len(examples), BATCH):
        client.create_examples(dataset_id=ds.id, examples=examples[i:i+BATCH])

    st.success(f"Pushed {len(examples)} examples to LangSmith dataset: {dataset_name}")

def export_dedup_dataset_to_langsmith(folder: str, dataset_name: str):
    """
    Build a LangSmith dataset for duplicate filtering.
    Each example = one file with its group_id and variant_type.
    Reference outputs:
      - is_strict_duplicate_expected (bool) relative to canonical sha256 per group
      - canonical_file_sha256 (str)
    """
    client = get_langsmith_client()
    if client is None:
        st.error("LangSmith client not available. Set LANGSMITH_API_KEY and LANGSMITH_TRACING=true.")
        return

    root = Path(folder)
    if not root.exists():
        st.error("Folder not found.")
        return

    # scan files grouped by immediate parent folder name
    items = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            group_id = p.parent.name
            variant_type = "unknown"
            if "_" in group_id:
                variant_type = group_id.split("_", 1)[0]
            with open(p, "rb") as fh:
                data = fh.read()
            sha = hashlib.sha256(data).hexdigest()
            items.append({
                "file_path": str(p.resolve()),
                "group_id": group_id,
                "variant_type": variant_type,
                "sha256": sha,
                "filename": p.name,
            })

    if not items:
        st.warning("No supported files found in the folder.")
        return

    # compute canonical per group (first by filename sort)
    examples = []
    from collections import defaultdict
    groups = defaultdict(list)
    for it in items:
        groups[it["group_id"]].append(it)
    for gid, arr in groups.items():
        arr_sorted = sorted(arr, key=lambda x: x["filename"])
        canonical_sha = arr_sorted[0]["sha256"]
        for it in arr_sorted:
            is_strict_dup_expected = (it["sha256"] == canonical_sha and it["filename"] != arr_sorted[0]["filename"])
            inputs = {
                "file_path": it["file_path"],
                "group_id": gid,
                "variant_type": it["variant_type"],
                "filename": it["filename"],
            }
            outputs = {
                "is_strict_duplicate_expected": bool(is_strict_dup_expected),
                "canonical_file_sha256": canonical_sha,
                "sha256": it["sha256"],
            }
            examples.append({"inputs": inputs, "outputs": outputs})

    # create or reuse dataset
    try:
        ds = client.create_dataset(dataset_name, description="Duplicate filtering test suite for ResumeFinder Admin")
    except Exception:
        ds = None
        try:
            for d in client.list_datasets():
                if getattr(d, "name", None) == dataset_name:
                    ds = d
                    break
        except Exception:
            pass
        if ds is None:
            raise

    BATCH = 50
    for i in range(0, len(examples), BATCH):
        client.create_examples(dataset_id=ds.id, examples=examples[i:i+BATCH])

    st.success(f"Pushed {len(examples)} examples to LangSmith dataset: {dataset_name}")

def export_chunking_dataset_to_langsmith(folder: str, dataset_name: str, size: int, overlap: int):
    """
    Build a LangSmith dataset for chunking quality.
    inputs: file_path, size, overlap
    reference outputs: expected_min_chunks, expected_max_chunks, text_len
    """
    client = get_langsmith_client()
    if client is None:
        st.error("LangSmith client not available. Set LANGSMITH_API_KEY and LANGSMITH_TRACING=true.")
        return

    root = Path(folder)
    if not root.exists():
        st.error("Folder not found.")
        return

    items = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".txt", ".pdf", ".docx", ".rtf"}:
            try:
                with open(p, "rb") as fh:
                    data = fh.read()
                txt = read_text_from_bytes(data, p.name)
                cleaned = clean_text(txt or "")
                tlen = len(cleaned)
                exp = math.ceil(tlen / max(1, int(size)))
                inputs = {
                    "file_path": str(p.resolve()),
                    "size": int(size),
                    "overlap": int(overlap),
                    "filename": p.name,
                }
                outputs = {
                    "expected_min_chunks": max(1, exp - 1),
                    "expected_max_chunks": exp + 1,
                    "text_len": tlen,
                }
                items.append({"inputs": inputs, "outputs": outputs})
            except Exception:
                continue

    if not items:
        st.warning("No supported files found in the folder.")
        return

    # create or reuse dataset
    try:
        ds = client.create_dataset(dataset_name, description="Chunking quality test suite for ResumeFinder Admin")
    except Exception:
        ds = None
        try:
            for d in client.list_datasets():
                if getattr(d, "name", None) == dataset_name:
                    ds = d
                    break
        except Exception:
            pass
        if ds is None:
            raise

    BATCH = 50
    for i in range(0, len(items), BATCH):
        client.create_examples(dataset_id=ds.id, examples=items[i:i+BATCH])

    st.success(f"Pushed {len(items)} examples to LangSmith dataset: {dataset_name}")

# ---------- UI ----------
# --- step 1/7: CEIPAL secrets sanity check ---
ce_user = _secret("CEIPAL_USERNAME", "")
ce_pass = _secret("CEIPAL_PASSWORD", "")
ce_key  = _secret("CEIPAL_API_KEY", "")
ce_url  = _secret("CEIPAL_ENDPOINT_URL", "")

with st.expander("Step 1 of 7 – CEIPAL secrets", expanded=False):
    st.write(f"CEIPAL_USERNAME:       {_mask(ce_user)}")
    st.write(f"CEIPAL_PASSWORD:       {_mask(ce_pass)}")
    st.write(f"CEIPAL_API_KEY:        {_mask(ce_key)}")
    st.write(f"CEIPAL_ENDPOINT_URL:   {_mask(ce_url)}")

all_set = bool(ce_user and ce_pass and ce_key and ce_url)
if all_set:
    st.success("CEIPAL secrets detected. Ready for Step 2 (auth + fetch helpers).")
else:
    st.warning("One or more CEIPAL secrets are missing. Fill .streamlit/secrets.toml and refresh.")

st.title("JD–Resume Admin")
st.caption("Admins can ingest resumes (bulk or single), avoid duplicates, and view everything stored in the vector DB.")

(client, coll) = get_chroma()
corpus_tokens, meta_by_id, bm25_doc_ids = load_bm25()

# === Step 3 of 7 – Download CEIPAL resumes (no date filter, dedupe by candidate_id) ===
with st.expander("Step 3 of 7 – Download CEIPAL resumes (no date filter, dedupe by candidate_id)", expanded=False):
    # Ensure Chroma + BM25 are available
    try:
        _coll = coll
        _corpus_tokens = corpus_tokens
        _meta_by_id = meta_by_id
        _bm25_doc_ids = bm25_doc_ids
    except NameError:
        (client, _coll) = get_chroma()
        _corpus_tokens, _meta_by_id, _bm25_doc_ids = load_bm25()

    # ---- Helpers (safe to keep even if defined earlier) ----
    import hashlib, mimetypes
    from urllib.parse import urlparse
    from pathlib import Path
    import requests
    import pandas as pd
    from datetime import datetime, timezone

    def _extract_candidate_id(row: dict) -> str:
        return str(
            row.get("candidate_id")
            or row.get("id")
            or row.get("ceipal_id")
            or row.get("applicant_id")
            or ""
        ).strip()

    def _extract_resume_url(row: dict) -> str | None:
        return (
            row.get("resume_path")
            or row.get("resume")
            or row.get("resumeUrl")
            or row.get("resume_url")
            or row.get("resume_file")
            or row.get("file_url")
            or None
        )

    def _suggest_filename(candidate_id: str, resume_url: str) -> str:
        parsed = urlparse(resume_url)
        name = Path(parsed.path).name or "resume"
        ext = "".join(Path(name).suffixes)
        if not ext:
            guess = mimetypes.guess_extension(mimetypes.guess_type(resume_url)[0] or "")
            ext = guess or ".pdf"
        h = hashlib.sha1(resume_url.encode("utf-8")).hexdigest()[:8]
        base = f"ceipal-{candidate_id}-{h}"
        return base + ext

    def _existing_candidate_ids(coll, meta_by_id: dict) -> set[str]:
        ids = set()
        for md in (meta_by_id or {}).values():
            cid = str(md.get("candidate_id") or md.get("ceipal_id") or md.get("id") or "").strip()
            if cid: ids.add(cid)
        try:
            got = coll.get(where={"source": "ceipal"}, include=["metadatas"])
            for md in (got or {}).get("metadatas") or []:
                if not isinstance(md, dict): continue
                cid = str(md.get("candidate_id") or md.get("ceipal_id") or md.get("id") or "").strip()
                if cid: ids.add(cid)
        except Exception:
            pass
        return ids

    # ---- CEIPAL creds ----
    base  = _secret("CEIPAL_BASE_URL", "https://api.ceipal.com")
    url   = _secret("CEIPAL_ENDPOINT_URL", "")
    style = (_secret("CEIPAL_AUTH_STYLE", "bearer") or "bearer").lower().strip()
    u     = _secret("CEIPAL_USERNAME", "")
    p     = _secret("CEIPAL_PASSWORD", "")
    k     = _secret("CEIPAL_API_KEY", "")

    # ---- Download options ----
    default_dir = str(Path(RESUMES_STORE_DIR).resolve()) if "RESUMES_STORE_DIR" in globals() else str(Path.cwd() / "resumes_store")
    dest_dir = st.text_input("Local folder to save resumes", value=default_dir, key="s3_dest_dir",
                             help="All downloaded resumes will be saved here.")
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    c1, c2, c3 = st.columns([1,1,1])
    paging_len = c1.number_input("paging_length", 1, 100, 30, 1, key="s3_paging_length")
    max_pages  = c2.number_input("max_pages (0 = all)", 0, 9999, 0, 1, key="s3_max_pages")
    test_only  = c3.checkbox("Dry run (don't download)", value=False, key="s3_dry_run")

    c4, c5 = st.columns([1,1])
    skip_existing = c4.checkbox("Skip if file exists", value=True, key="s3_skip_existing")
    throttle_s    = c5.slider("Throttle between downloads (seconds)", 0.0, 1.0, 0.0, 0.1, key="s3_throttle")

    urls_text = st.text_area("Optional: paste resume_path URLs (one per line) to force-download",
                             height=120, key="s3_urls",
                             placeholder="https://.../resume1.pdf\nhttps://.../resume2.docx")

    go = st.button("Download & stage", type="primary", use_container_width=True, key="s3_go")

    if go:
        try:
            tok = None
            if style == "bearer":
                tok = ceipal_auth(u.strip(), p, k.strip(), base.strip())

            headers = {"Authorization": f"Bearer {tok}"} if (tok and style == "bearer") else {}

            existing_ids = _existing_candidate_ids(_coll, _meta_by_id)
            seen_ids: set[str] = set()
            staged_rows: list[dict] = []

            kept = skipped_dupe = skipped_no_url = skipped_exists = dl_errors = 0
            total_seen = 0
            total_cap = int(paging_len) * (int(max_pages) if max_pages > 0 else 1000)
            pbar = st.progress(0.0, text="Starting downloads…")
            details = st.empty()

            # ---- 1) Manual URL list (optional) ----
            manual_urls = [u.strip() for u in (urls_text or "").splitlines() if u.strip()]
            for uurl in manual_urls:
                total_seen += 1
                cid = "manual-" + hashlib.sha1(uurl.encode("utf-8")).hexdigest()[:8]
                fname = _suggest_filename(cid, uurl)
                out_path = Path(dest_dir) / fname

                if skip_existing and out_path.exists():
                    skipped_exists += 1
                    staged_rows.append({
                        "row": {"candidate_id": cid, "resume_path": uurl, "source": "manual"},
                        "file_path": str(out_path),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    details.info(f"exists: {out_path.name}")
                else:
                    if not test_only:
                        try:
                            with requests.get(uurl, headers=headers, stream=True, timeout=60,
                                              allow_redirects=True) as r:
                                r.raise_for_status()
                                out_path = _decide_save_path(cid, uurl, r, dest_dir, default_docx=True)

                                if skip_existing and out_path.exists():
                                    skipped_exists += 1
                                    staged_rows.append({
                                        "row": {"candidate_id": cid, "resume_path": uurl, "source": "manual"},
                                        "file_path": str(out_path),
                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                    })
                                else:
                                    with open(out_path, "wb") as fh:
                                        for chunk in r.iter_content(chunk_size=8192):
                                            if chunk: fh.write(chunk)
                                    kept += 1
                                    staged_rows.append({
                                        "row": {"candidate_id": cid, "resume_path": uurl, "source": "manual"},
                                        "file_path": str(out_path),
                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                    })

                        except Exception as e:
                            dl_errors += 1
                            details.warning(f"manual download failed: {uurl} — {e}")
                            pbar.progress(min(0.99, total_seen / max(1, total_cap)))
                            continue
                    kept += 1
                    staged_rows.append({
                        "row": {"candidate_id": cid, "resume_path": uurl, "source": "manual"},
                        "file_path": str(out_path),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    if throttle_s > 0: time.sleep(throttle_s)

                pbar.progress(min(0.99, total_seen / max(1, total_cap)),
                              text=f"manual: kept={kept} exists={skipped_exists} dupes={skipped_dupe} no_url={skipped_no_url} errors={dl_errors}")

            # ---- 2) CEIPAL iterator (no date filter) ----
            page_cap = (int(max_pages) if max_pages > 0 else None)
            for row in ceipal_iter_applicants(
                url, tok, auth_style=style,
                paging_length=int(paging_len),
                max_pages=page_cap
            ):
                total_seen += 1
                cid = _extract_candidate_id(row)
                if not cid:
                    details.info("skip: missing candidate_id")
                    pbar.progress(min(0.99, total_seen / max(1, total_cap))); continue

                if cid in existing_ids or cid in seen_ids:
                    skipped_dupe += 1
                    details.info(f"skip duplicate candidate_id={cid}")
                    pbar.progress(min(0.99, total_seen / max(1, total_cap))); continue

                rurl = _extract_resume_url(row)
                if not rurl:
                    skipped_no_url += 1
                    details.info(f"skip: no resume_path for candidate_id={cid}")
                    pbar.progress(min(0.99, total_seen / max(1, total_cap))); continue

                fname = _suggest_filename(cid, rurl)
                out_path = Path(dest_dir) / fname

                if skip_existing and out_path.exists():
                    skipped_exists += 1
                    staged_rows.append({
                        "row": row,
                        "file_path": str(out_path),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                else:
                    if not test_only:
                        try:
                            with requests.get(rurl, headers=headers, stream=True, timeout=60,
                                              allow_redirects=True) as rr:
                                rr.raise_for_status()
                                out_path = _decide_save_path(cid, rurl, rr, dest_dir, default_docx=True)

                                if skip_existing and out_path.exists():
                                    skipped_exists += 1
                                    staged_rows.append({
                                        "row": row,
                                        "file_path": str(out_path),
                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                    })
                                else:
                                    with open(out_path, "wb") as fh:
                                        for chunk in rr.iter_content(chunk_size=8192):
                                            if chunk: fh.write(chunk)
                                    kept += 1
                                    staged_rows.append({
                                        "row": row,
                                        "file_path": str(out_path),
                                        "created_at": datetime.now(timezone.utc).isoformat(),
                                    })
                                    seen_ids.add(cid)

                        except Exception as e:
                            dl_errors += 1
                            details.warning(f"download failed for candidate_id={cid}: {e}")
                            pbar.progress(min(0.99, total_seen / max(1, total_cap))); continue

                    kept += 1
                    staged_rows.append({
                        "row": row,
                        "file_path": str(out_path),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    seen_ids.add(cid)
                    if throttle_s > 0: time.sleep(throttle_s)

                pbar.progress(min(0.99, total_seen / max(1, total_cap)),
                              text=f"seen={total_seen} kept={kept} exists={skipped_exists} dupes={skipped_dupe} no_url={skipped_no_url} errors={dl_errors}")

            pbar.progress(1.0, text=f"done • kept={kept} exists={skipped_exists} dupes={skipped_dupe} no_url={skipped_no_url} errors={dl_errors}")
            st.success(f"Staged {kept} new download(s). Skipped existing={skipped_exists}, dupes={skipped_dupe}, no-url={skipped_no_url}, errors={dl_errors}.")

            # Persist manifest for Step 4 (ingestion will consume this)
            st.session_state["ceipal_stage_rows"] = staged_rows

            # Show a compact table
            if staged_rows:
                df = pd.DataFrame([{
                    "candidate_id": _extract_candidate_id(it["row"]),
                    "resume_path": _extract_resume_url(it["row"]) or "",
                    "file_path": it["file_path"],
                    "created_at": it["created_at"],
                } for it in staged_rows])
                st.dataframe(df, use_container_width=True, hide_index=True)

        except Exception as e:
            st.error(f"Staging failed: {e}")


# --- step 4/7: CEIPAL → ingest to Chroma + BM25 ---
with st.expander("Step 4 of 7 – CEIPAL ingest to Chroma + BM25", expanded=False):
    # ensure Chroma + BM25 artifacts exist in this scope
    try:
        _coll = coll
        _corpus_tokens = corpus_tokens
        _meta_by_id = meta_by_id
        _bm25_doc_ids = bm25_doc_ids
    except NameError:
        (client, _coll) = get_chroma()
        _corpus_tokens, _meta_by_id, _bm25_doc_ids = load_bm25()

    base = _secret("CEIPAL_BASE_URL", "https://api.ceipal.com")
    url  = _secret("CEIPAL_ENDPOINT_URL", "")
    style = (_secret("CEIPAL_AUTH_STYLE", "bearer") or "bearer").lower().strip()
    u = _secret("CEIPAL_USERNAME", "")
    p = _secret("CEIPAL_PASSWORD", "")
    k = _secret("CEIPAL_API_KEY", "")

    left, right = st.columns([1, 1])
    paging_len = st.number_input("paging_length", 1, 100, 30, 1, key="s4_paging_length")
    max_pages = st.number_input("max_pages (0 = all)", 0, 9999, 0, 1, key="s4_max_pages")
    throttle_s = st.slider("throttle between adds (seconds)", 0.0, 1.0, 0.0, 0.1, key="s4_throttle")

    # Choose source of rows: staged rows from Step 3 (preferred), else live iterator
    rows_source = st.session_state.get("ceipal_stage_rows")

    ingest = st.button("Ingest CEIPAL applicants", type="primary", use_container_width=True)

    if ingest:
        try:
            tok = None
            if style == "bearer":
                tok = ceipal_auth(u.strip(), p, k.strip(), base.strip())

            added = skipped = errors = 0
            seen  = 0
            # rough cap just for progress bar visuals
            total = int(paging_len) * (int(max_pages) if max_pages > 0 else 1000)
            pbar  = st.progress(0.0, text="Starting CEIPAL ingestion…")
            details = st.empty()

            if rows_source:
                iterator = rows_source  # list of {"row": ..., "file_path": ..., "created_at": ...}
            else:
                iterator = ceipal_iter_applicants(
                    url, tok, auth_style=style,
                    paging_length=int(paging_len),
                    max_pages=(int(max_pages) if max_pages > 0 else None)
                )

            for item in iterator:
                # Unpack row + (optional) local file path
                if rows_source:
                    row = dict(item.get("row") or {})
                    local_fp = item.get("file_path")
                else:
                    row = item
                    local_fp = None

                seen += 1

                # --- candidate_id-based dedupe (in addition to sha) ---
                cand_id = _extract_candidate_id(row)
                if cand_id:
                    # Build once outside the loop if you prefer performance (left inline for clarity)
                    existing_ids = _existing_candidate_ids(_coll, _meta_by_id)
                    if cand_id in existing_ids:
                        skipped += 1
                        pbar.progress(min(0.99, seen / max(1, total)), text=f"skip duplicate candidate_id={cand_id}")
                        continue

                # dedupe by sha of canonical JSON (your existing logic)
                sha = applicant_sha(row)
                if already_exists(_coll, sha, _meta_by_id):
                    skipped += 1
                    pbar.progress(min(0.99, seen / max(1, total)), text=f"skip duplicate sha={sha[:12]}")
                    continue

                # build safe text + metadata
                text_blob = clean_text(applicant_to_text(row))
                if not text_blob.strip():
                    skipped += 1
                    continue

                md = build_meta_from_app(row, sha)

                # carry file paths into metadata when available (from Step 3)
                if local_fp:
                    md["file_path"] = local_fp
                # keep the remote path too, when present
                rurl = _extract_resume_url(row)
                if rurl and "resume_path" not in md:
                    md["resume_path"] = rurl

                base_id = make_base_id(row, md)
                slug = sanitize_slug(md.get("email") or md.get("candidate_name") or md.get("ceipal_id") or cand_id)
                base_id = f"ceipal-{slug}-{sha[:12]}"

                try:
                    add_one_document(_coll, text_blob, md, base_id, _corpus_tokens, _bm25_doc_ids)
                    _meta_by_id[base_id] = md  # parent-level meta
                    added += 1
                    details.info(f"added {md.get('candidate_name') or cand_id}  →  id={base_id}")
                    if throttle_s > 0:
                        time.sleep(throttle_s)
                except Exception as e:
                    errors += 1
                    details.warning(f"error on {base_id}: {e}")

                pbar.progress(min(0.99, seen / max(1, total)),
                              text=f"seen={seen} added={added} skipped={skipped} errors={errors}")

            save_bm25(_corpus_tokens, _meta_by_id, _bm25_doc_ids)
            pbar.progress(1.0, text=f"done • added={added} skipped={skipped} errors={errors}")
            st.success(f"CEIPAL ingest complete. added={added}, skipped={skipped}, errors={errors}")
            st.rerun()

        except Exception as e:
            st.error(f"Ingest failed: {e}")


# Health check panel for Ollama
ok, base_url, tags = ollama_healthcheck()
health_col1, health_col2 = st.columns([2,3])
with health_col1:
    st.write("**Ollama server**:")
    if ok:
        st.success(f"reachable at {base_url}")
    else:
        st.warning(f"not reachable at {base_url}. Start it with `ollama serve` or ensure the Windows service 'Ollama' is running.")
with health_col2:
    if ok:
        names = [t.get("name", "") for t in (tags or {}).get("models", tags or [])]
        names = names or [m.get("name", "") for m in tags] if isinstance(tags, list) else names
        has_model = any(EMBED_MODEL in (n or "") for n in names)
        if has_model:
            st.info(f"model present: {EMBED_MODEL}")
        else:
            st.warning(f"model NOT found. Run: `ollama pull {EMBED_MODEL}`")

tab_upload, tab_folder, tab_list, tab_langsmith = st.tabs(["Upload files", "Ingest from folder", "Vector DB contents", "LangSmith datasets"])

with tab_upload:
    st.subheader("Upload Word/PDF resumes")
    st.write("Upload one or many .pdf, .docx, .txt, or .rtf files. Duplicates are automatically detected by SHA-256.")

    files = st.file_uploader(
        "Drop files here",
        accept_multiple_files=True,
        type=["pdf", "docx", "txt", "rtf", "doc"],
        help="Supported: PDF, DOCX, TXT, RTF, DOC"
    )
    colA, colB, _ = st.columns([1,1,2])
    with colA:
        alpha = st.slider("Embedding batch delay (s)", 0.0, 0.5, 0.0, 0.05,
                          help="Optional tiny delay between embeddings if your Ollama box is resource-constrained.")
    with colB:
        do_ingest = st.button("Save to Chroma", type="primary", use_container_width=True)

    if do_ingest and files:
        pbar = st.progress(0.0, text="Starting ingestion…")
        done = 0
        added, skipped = 0, 0
        details = st.empty()
        for f in files:
            try:
                if not validate_ext(f.name):
                    st.warning(f"Unsupported file type: {f.name}. Skipped.")
                    skipped += 1
                    done += 1
                    pbar.progress(done / len(files))
                    continue

                data = f.read()
                result = ingest_file(
                    coll=coll,
                    file_bytes=data,
                    filename=f.name,
                    alpha_secs=alpha,
                    local_meta_by_id=meta_by_id,
                    corpus_tokens=corpus_tokens,
                    bm25_doc_ids=bm25_doc_ids,
                )

                if result.get("is_duplicate_blocked"):
                    st.warning(f"Duplicate detected (SHA-256={result['file_sha256'][:12]}…) → {f.name} skipped.")
                    skipped += 1
                elif result.get("error"):
                    st.error(f"Failed on {f.name}: {result.get('error')}")
                    skipped += 1
                elif result.get("ingested"):
                    added += 1
                    details.info(
                        f"Added: {f.name} → id={result.get('base_doc_id')} "
                        f"(chunks {result.get('chunk_count')}, p95={result.get('chunk_length_p95')})"
                    )
                else:
                    st.warning(f"Skipped {f.name}: {result.get('duplicate_reason','unknown')}")
                    skipped += 1

                done += 1
                pbar.progress(done / len(files))

            except Exception as e:
                skipped += 1
                done += 1
                st.error(f"Failed on {f.name}: {e}")
                pbar.progress(done / len(files))

        save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids)
        pbar.empty()
        st.success(f"Done. Added {added}, skipped {skipped}.")
        st.rerun()

with tab_folder:
    st.subheader("Bulk ingest from a server folder")
    st.write("Point to a folder on this server. All supported files will be parsed, deduped by SHA-256, embedded, and saved.")
    folder = st.text_input("Absolute or relative folder path", value="./resumes_raw")
    run = st.button("Scan & ingest folder", use_container_width=True)
    if run:
        root = Path(folder)
        if not root.exists():
            st.error("Folder not found.")
        else:
            paths: List[Path] = []
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                    paths.append(p)
            if not paths:
                st.warning("No supported files found.")
            else:
                pbar = st.progress(0.0, text=f"Found {len(paths)} files. Ingesting…")
                added = skipped = 0
                for i, p in enumerate(paths, 1):
                    try:
                        with open(p, "rb") as fh:
                            data = fh.read()
                        result = ingest_file(
                            coll=coll,
                            file_bytes=data,
                            filename=p.name,
                            alpha_secs=0.0,
                            local_meta_by_id=meta_by_id,
                            corpus_tokens=corpus_tokens,
                            bm25_doc_ids=bm25_doc_ids,
                        )
                        if result.get("is_duplicate_blocked"):
                            skipped += 1
                            pbar.progress(i / len(paths), text=f"Skip duplicate: {p.name}")
                        elif result.get("error"):
                            skipped += 1
                            pbar.progress(i / len(paths), text=f"Error on {p.name}: {result.get('error')}")
                        elif result.get("ingested"):
                            added += 1
                            pbar.progress(i / len(paths), text=f"Added: {p.name} (chunks {result.get('chunk_count')})")
                        else:
                            skipped += 1
                            pbar.progress(i / len(paths), text=f"Skipped {p.name}: {result.get('duplicate_reason','unknown')}")

                    except Exception as e:
                        skipped += 1
                        pbar.progress(i / len(paths), text=f"Error on {p.name}: {e}")

                save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids)
                pbar.empty()
                st.success(f"Ingestion finished. Added {added}, skipped {skipped}.")
                st.rerun()

with tab_list:
    st.subheader("Vector database contents")
    st.write("Full inventory of resumes currently stored in Chroma. Grouped by resume (parent), not chunks.")
    df = list_collection(coll)

    # --- inventory filters (step 5) ---
    left, right = st.columns([1,3])
    with left:
        st.metric("Total resumes", len(df))

    with right:
        # ensure we have the source column in a consistent string form
        if not df.empty and "source_ext" in df.columns:
            _srcs = sorted({str(x).lower() for x in df["source_ext"].dropna().astype(str)})
            # build choices → "All sources", "ceipal", ".pdf", ".docx", ...
            choices = ["All sources"] + [("CEIPAL" if s == "ceipal" else s) for s in _srcs]
            sel = st.selectbox("Filter by source", choices, index=0, help="Show only CEIPAL profiles or a specific file type.")
            if sel != "All sources":
                key = "ceipal" if sel.upper() == "CEIPAL" else sel
                df = df[df["source_ext"].astype(str).str.lower() == key]
        else:
            st.caption("No source metadata yet; ingest something first.")

    if df.empty:
        st.info("No resumes found.")
    else:
        # IMPORTANT: make sure we show the correct column name 'source_ext'
        show_cols = ["candidate_name", "email", "phone", "source_ext", "document_id", "chunks", "short_hash", "sha256", "file_path",]
        missing = [c for c in show_cols if c not in df.columns]
        if missing:
            # fall back gracefully if older runs missed some columns
            show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

        with st.expander("Export list as CSV"):
            csv = df.to_csv(index=False).encode()
            st.download_button("Download CSV", csv, "chroma_inventory.csv", "text/csv")

    # expose the (filtered) inventory for dataset export in the next tab
    st.session_state["__inventory_df"] = df

with st.expander("Delete selected from Vector DB (Chroma + BM25)", expanded=False):
    # use the filtered inventory if you set it earlier
    inv = st.session_state.get("__inventory_df", df.copy() if 'df' in locals() else None)

    if inv is None or inv.empty:
        st.info("No rows to delete.")
    else:
        # minimal view for selection
        view_cols = [c for c in ["document_id","candidate_name","email","source_ext","chunks"] if c in inv.columns]
        view = inv[view_cols].copy()
        view.insert(0, "select", False)

        edited = st.data_editor(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "select": st.column_config.CheckboxColumn("select", help="Mark rows to delete"),
                "document_id": st.column_config.TextColumn("document_id", disabled=True),
                "candidate_name": st.column_config.TextColumn("candidate_name", disabled=True),
                "email": st.column_config.TextColumn("email", disabled=True),
                "source_ext": st.column_config.TextColumn("source", disabled=True),
                "chunks": st.column_config.NumberColumn("chunks", disabled=True),
            },
            disabled=["document_id","candidate_name","email","source_ext","chunks"],  # only the checkbox is editable
            key="__del_editor",
        )

        to_delete = edited.loc[edited["select"], "document_id"].dropna().astype(str).unique().tolist()
        st.caption(f"Selected parents: {len(to_delete)}")

        # simple confirmation
        c1, c2 = st.columns([1,2])
        confirm_text = c2.text_input("Type DELETE to confirm", value="", key="__del_confirm")
        can_delete = len(to_delete) > 0 and confirm_text.strip().upper() == "DELETE"

        if c1.button("Delete selected", type="primary", disabled=not can_delete):
            try:
                # make sure the shared objects exist in this scope
                try:
                    _coll = coll; _corpus = corpus_tokens; _bm25ids = bm25_doc_ids; _meta = meta_by_id
                except NameError:
                    (_, _coll) = get_chroma()
                    _corpus, _meta, _bm25ids = load_bm25()

                # 1) delete from Chroma
                vecs_removed = chroma_delete_by_document_ids(_coll, to_delete)

                # 2) prune BM25 + metadata
                bm25_prune_after_delete(_corpus, _bm25ids, _meta, to_delete)
                save_bm25(_corpus, _meta, _bm25ids)

                st.success(f"Deleted {len(to_delete)} parent(s) and {vecs_removed} vector(s). BM25 artifacts updated.")
                st.rerun()
            except Exception as e:
                st.error(f"Delete failed: {e}")
        elif len(to_delete) > 0:
            st.warning("Type DELETE to enable the button.")

with tab_langsmith:
    st.subheader("Export inventory as a LangSmith dataset")
    st.write("Creates a dataset of resume entries with text snippets and extracted contacts for human review.")
    default_name = f"rf_parsing_contacts_{int(time.time())}"
    ds_name = st.text_input("Dataset name", value=default_name)
    push = st.button("Create/append dataset in LangSmith", type="primary", use_container_width=True)
    if push:
        inv = st.session_state.get("__inventory_df")
        if inv is None or inv.empty:
            st.warning("Inventory is empty. Ingest resumes first in the other tabs.")
        else:
            export_contacts_dataset_to_langsmith(inv, ds_name)

    st.divider()
    st.subheader("Build duplicate filtering dataset (rf_admin_dedup_suite)")
    st.write("Point to a folder that contains grouped files, e.g.: exact_set_01/, text_identical_01/, near_dup_01/, singleton_01/")
    dedup_folder = st.text_input("Folder path for duplicate dataset", value="./dedup_suite")
    dedup_ds_name = st.text_input("Target dataset name", value="rf_admin_dedup_suite")
    make_dedup = st.button("Create/append duplicate dataset in LangSmith", use_container_width=True)
    if make_dedup:
        export_dedup_dataset_to_langsmith(dedup_folder, dedup_ds_name)

    st.divider()
    st.subheader("Build chunking quality dataset (rf_admin_chunking_suite)")
    st.write("Provide a folder with ~20 texts across lengths/languages. We'll compute expected chunk count bands.")
    chunk_folder = st.text_input("Folder path for chunking dataset", value="./chunking_suite")
    col1, col2 = st.columns(2)
    with col1:
        chunk_ds_name = st.text_input("Target dataset name", value="rf_admin_chunking_suite")
    with col2:
        size = st.number_input("Chunk size", min_value=100, max_value=4000, value=int(CHUNK_SIZE), step=50)
        overlap = st.number_input("Chunk overlap", min_value=0, max_value=2000, value=int(CHUNK_OVERLAP), step=10)
    make_chunk = st.button("Create/append chunking dataset in LangSmith", use_container_width=True)
    if make_chunk:
        export_chunking_dataset_to_langsmith(chunk_folder, chunk_ds_name, int(size), int(overlap))

st.divider()
st.caption("Admin-only interface. Users will not see ingestion or write paths in the end-user app.")
