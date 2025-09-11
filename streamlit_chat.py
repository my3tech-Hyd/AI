# streamlit_chat.py
"""
JD–Resume Chat (RAG)

• Local-only stack: Chroma + Ollama (embeddings + chat) + LangChain memory
• Hybrid retrieval (semantic + BM25) with parent-resume aggregation
• Top 5 resumes returned per user turn with evidence + download buttons
• Chat history in sidebar + persistent memory across refreshes

Run:
  ollama serve
  ollama pull nomic-embed-text
  ollama pull llama3.2:3b
  streamlit run streamlit_chat.py
"""
from __future__ import annotations
import io
import os
import re
import json
import uuid
import glob
import heapq
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

# import ranked
import streamlit as st
import pandas as pd
import chromadb
import requests
from rank_bm25 import BM25Okapi
from pypdf import PdfReader
from docx import Document as Docx
import time
import uuid

from langsmith.wrappers import wrap_openai
from langsmith import traceable
# LangChain (for chat + memory)
# (Chat model switched to OpenAI; LangChain memory import kept for future use)
from langchain.memory import ConversationBufferMemory  # (kept available; memory is manual via summaries)

# OpenAI SDK (chat model)
from openai import OpenAI
from types import SimpleNamespace

from config import (
    CHROMA_DIR, CHROMA_COLLECTION,
    BM25_CORPUS_PATH, BM25_META_PATH, BM25_DOCIDS_PATH,
    EMBED_MODEL, HYBRID_ALPHA, TOP_K_VECTOR, TOP_K_FINAL
)
from utils_text import clean_text, tokenize
from openai import OpenAI
from types import SimpleNamespace
from pathlib import Path  # you already import Path; keep it




# ---------------- App config ----------------
st.set_page_config(page_title="JD–Resume • Chat", page_icon="💬", layout="wide")
# --- Secrets bootstrap (optional but handy on Windows) ---
try:
    if "OPENAI_API_KEY" in st.secrets and st.secrets["OPENAI_API_KEY"]:
        os.environ.setdefault("OPENAI_API_KEY", st.secrets["OPENAI_API_KEY"])
except Exception:
    pass

# Defaults & env knobs
CHAT_MODEL           = os.getenv("CHAT_MODEL", "gpt-4o-mini")  # switched default to OpenAI chat model
OLLAMA_TIMEOUT       = float(os.getenv("OLLAMA_TIMEOUT", "45"))
MAX_QUERY_CHARS      = int(os.getenv("MAX_QUERY_CHARS", "1200"))
QUERY_CHUNK_SIZE     = int(os.getenv("QUERY_CHUNK_SIZE", "500"))
QUERY_CHUNK_OVERLAP  = int(os.getenv("QUERY_CHUNK_OVERLAP", "100"))
QUERY_MAX_CHUNKS     = int(os.getenv("QUERY_MAX_CHUNKS", "6"))
TOP_K_FINAL_CHAT     = int(os.getenv("TOP_K_FINAL_CHAT", "5"))  # always show 5 resumes in chat
CHAT_STORE_DIR       = os.getenv("CHAT_STORE_DIR", "./chat_store")
HISTORY_WINDOW_TURNS = int(os.getenv("HISTORY_WINDOW_TURNS", "8"))
SUMMARY_TRIGGER      = int(os.getenv("SUMMARY_TRIGGER", "20"))  # summarize after this many messages
REWRITE_ENABLED      = os.getenv("REWRITE_ENABLED", "true").lower() != "false"
# Absolute confidence (filter + display)
# ABS_SCORE_W_SEM      = float(os.getenv("ABS_SCORE_W_SEM", "0.7"))   # weight for raw semantic similarity
# ABS_SCORE_W_LEX      = float(os.getenv("ABS_SCORE_W_LEX", "0.3"))   # weight for lexical overlap
# ABS_SCORE_FLOOR      = float(os.getenv("ABS_SCORE_FLOOR", "0.35"))  # drop anything below this absolute confidence


# Relevance gating (to handle irrelevance → “I don’t know”)
IRRELEVANCE_GATING_ON = os.getenv("IRRELEVANCE_GATING_ON", "true").lower() != "false"
MIN_SEM_RAW_SIM       = float(os.getenv("MIN_SEM_RAW_SIM", "0.28"))   # minimum raw cosine-sim (1 - distance) on best chunk
MIN_LEXICAL_OVERLAP   = float(os.getenv("MIN_LEXICAL_OVERLAP", "0.06"))  # |tokens∩| / |tokens_q| on best snippet
MIN_KW_SCORE          = float(os.getenv("MIN_KW_SCORE", "0.0"))       # allow 0 by default; BM25 passes if overlap is strong


# ---------------- Utilities ----------------

@st.cache_resource(show_spinner=False)
def get_http_session():
    s = requests.Session()
    ad = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1)
    s.mount("http://", ad); s.mount("https://", ad)
    return s

@st.cache_resource(show_spinner=False)
def get_ollama_base() -> str:
    return (os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")

@st.cache_resource(show_spinner=False)
def get_chroma():
    try:
        if hasattr(chromadb, "PersistentClient"):
            client = chromadb.PersistentClient(path=CHROMA_DIR)
        else:
            from chromadb.config import Settings
            client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory=CHROMA_DIR))
    except Exception:
        st.error("Failed to initialize Chroma client. Try `pip install -U chromadb==0.5.5`.", icon="⚠️")
        raise
    # enforce cosine space for consistent similarity math
    coll = client.get_or_create_collection(name=CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})
    return client, coll

# --- File readers (for JD upload option inside chat) ---

def read_text_from_bytes(data: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        doc = Docx(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)
    elif suffix in {".txt", ".rtf"}:
        txt = data.decode(errors="ignore")
        if suffix == ".rtf":
            return re.sub(r"{\\rtf1.*?}", "", txt, flags=re.DOTALL)
        return txt
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

# --- Query chunker ---

def chunk_text_query(text: str, size: int = QUERY_CHUNK_SIZE, overlap: int = QUERY_CHUNK_OVERLAP) -> List[str]:
    text = (text or "")
    n = len(text)
    if n == 0:
        return []
    size = max(1, int(size))
    overlap = max(0, int(overlap))
    if overlap >= size:
        overlap = size // 4
    chunks = []
    start = 0
    while start < n and len(chunks) < max(1, QUERY_MAX_CHUNKS):
        end = min(n, start + size)
        chunks.append(text[start:end])
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks

# --- BM25 index loader (safe if empty) ---

@st.cache_resource(show_spinner=False)
def load_bm25_index():
    import pickle, os
    class _NullBM25:
        corpus_size = 0
        def get_scores(self, tokens):
            return []

    if not (os.path.exists(BM25_CORPUS_PATH) and os.path.exists(BM25_DOCIDS_PATH)):
        return _NullBM25(), [], {}

    with open(BM25_CORPUS_PATH, "rb") as f:
        corpus_tokens = pickle.load(f)
    with open(BM25_DOCIDS_PATH, "rb") as f:
        doc_ids = pickle.load(f)

    corpus_size = len(corpus_tokens) if corpus_tokens else 0

    if not corpus_tokens or all((not d) for d in corpus_tokens):
        bm25 = _NullBM25()
        id2pos = {}  # no valid rows; keep empty mapping
    else:
        bm25 = BM25Okapi(corpus_tokens)
        # Only map IDs that actually have a BM25 row
        safe_n = min(len(doc_ids), corpus_size)
        id2pos = {doc_ids[i]: i for i in range(safe_n)}

    return bm25, doc_ids, id2pos


# --- Embeddings ---

@st.cache_data(show_spinner=False)
def embed_chunk(text: str) -> List[float]:
    session = get_http_session()
    base = get_ollama_base()
    url = base + "/api/embeddings"
    txt = (text or "").strip()
    if not txt:
        raise ValueError("Empty text to embed.")
    if len(txt) > MAX_QUERY_CHARS:
        txt = txt[:MAX_QUERY_CHARS]
    r = session.post(url, json={"model": EMBED_MODEL, "input": txt}, timeout=OLLAMA_TIMEOUT)
    if r.status_code == 400:
        r = session.post(url, json={"model": EMBED_MODEL, "prompt": txt}, timeout=OLLAMA_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    emb = data.get("embedding")
    if emb is None and isinstance(data, dict):
        arr = data.get("data") or []
        if arr and isinstance(arr[0], dict):
            emb = arr[0].get("embedding")
    try:
        from langchain_ollama import OllamaEmbeddings  # modern package
    except Exception:
        OllamaEmbeddings = None
    if not isinstance(emb, list) or len(emb) == 0:
        if OllamaEmbeddings is None:
            raise RuntimeError(
                "Received empty embedding and langchain-ollama not installed. "
                "Run: pip install -U langchain-ollama"
            )
        try:
            emb2 = OllamaEmbeddings(model=EMBED_MODEL, base_url=base).embed_query(txt)
            if isinstance(emb2, list) and len(emb2) > 0:
                return [float(x) for x in emb2]
        except Exception:
            pass
        raise RuntimeError("Received empty embedding from model.")
    return [float(x) for x in emb]

@st.cache_data(show_spinner=False)
def embed_query_pooled(text: str) -> List[float]:
    chunks = chunk_text_query(text)
    if not chunks:
        raise ValueError("Query produced no chunks.")
    vecs: List[List[float]] = []
    weights: List[float] = []
    for ch in chunks[:QUERY_MAX_CHUNKS]:
        v = embed_chunk(ch)
        if v:
            vecs.append(v); weights.append(float(len(ch)))
    if not vecs:
        raise RuntimeError("All chunk embeddings failed.")
    dim = len(vecs[0])
    vecs = [v for v in vecs if len(v) == dim]
    weights = weights[:len(vecs)]
    wsum = sum(weights) if sum(weights) > 0 else float(len(vecs))
    acc = [0.0] * dim
    for v, w in zip(vecs, weights if sum(weights) > 0 else [1.0]*len(vecs)):
        for i in range(dim):
            acc[i] += v[i] * (w if sum(weights) > 0 else 1.0)
    return [x / wsum for x in acc]

# --- Retrieval helpers ---

def _normalize(vals: List[float]) -> List[float]:
    if not vals: return vals
    mn, mx = min(vals), max(vals)
    if mx - mn < 1e-9: return [0.0 for _ in vals]
    return [(v - mn) / (mx - mn) for v in vals]

def _overlap_ratio(q_tokens: List[str], snippet: str) -> float:
    doc_tokens = set(t.lower() for t in tokenize(snippet))
    qset = set(t.lower() for t in q_tokens)
    if not qset:
        return 0.0
    return len(qset & doc_tokens) / float(len(qset))

# NOTE: Not cached (unhashable args and live I/O)
@traceable(name="hybrid_retrieve", run_type="retriever")

def hybrid_retrieve(query_text: str, _coll, _bm25, doc_ids: List[str], id2pos: Dict[str, int],
                    top_k_vec: int, top_k_final: int, alpha_weight: float) -> Tuple[List[Dict], List[Dict]]:

    # return ranked, ev_list

    """Return (ranked_resumes, evidence_chunks)."""
    # --- Build JD tokens once
    jd_tokens = tokenize(query_text)


    # --- Vector candidates
    qvec = embed_query_pooled(query_text)
    vq = _coll.query(query_embeddings=[qvec], n_results=top_k_vec,
                     include=["documents", "metadatas", "distances"])  # ids returned implicitly

    v_ids   = _tolist(vq.get("ids", [[]])[0])          # coerce to list
    v_docs  = _tolist(vq.get("documents", [[]])[0])    # coerce to list
    v_metas = _tolist(vq.get("metadatas", [[]])[0])    # coerce to list
    v_dists = [float(d) for d in _tolist(vq.get("distances", [[]])[0])]

    # raw cosine similarity (hnsw:space=cosine): sim = 1 - distance
    v_sem_raw  = [1.0 - d for d in v_dists] if len(v_dists) > 0 else []
    v_sem_norm = _normalize(v_sem_raw) if len(v_sem_raw) > 0 else []

    # --- BM25 top-k (true union path)
    kw_all = []
    topk_pos = []
    if getattr(_bm25, "corpus_size", 0) > 0 and len(jd_tokens) > 0:
        kw_all = _bm25.get_scores(jd_tokens)  # np.ndarray
        kw_len = len(kw_all)
        if kw_len > 0:
            topk_pos = heapq.nlargest(min(top_k_vec, kw_len), range(kw_len), key=lambda i: float(kw_all[i]))
    else:
        kw_len = 0

    b_ids = [doc_ids[p] for p in topk_pos if 0 <= p < len(doc_ids)]

    # --- Union: vector@K ∪ bm25@K
    v_set = set(v_ids)
    only_bm25_ids = [x for x in b_ids if x not in v_set]

    # fetch docs/meta for bm25-only
    b_docs = []; b_metas = []
    if len(only_bm25_ids) > 0:
        got = _coll.get(ids=only_bm25_ids, include=["documents", "metadatas"])
        b_docs  = got.get("documents") or []
        b_metas = got.get("metadatas") or []
        # Chroma sometimes returns nested lists
        b_docs  = _tolist(b_docs[0])  if (isinstance(b_docs, list)  and len(b_docs)  > 0 and isinstance(b_docs[0],  list)) else _tolist(b_docs)
        b_metas = _tolist(b_metas[0]) if (isinstance(b_metas, list) and len(b_metas) > 0 and isinstance(b_metas[0], list)) else _tolist(b_metas)

    # unified arrays
    ids   = list(v_ids) + list(only_bm25_ids)
    docs  = list(v_docs) + list(b_docs)
    metas = list(v_metas) + list(b_metas)

    # semantic raw/normalized for union (bm25-only chunks get 0 semantics)
    sem_raw  = list(v_sem_raw) + [0.0] * len(only_bm25_ids)
    sem_norm = list(v_sem_norm) + [0.0] * len(only_bm25_ids)

    # kw scores for union via id2pos mapping (fast lookup)
    kw_scores = []
    for cid in ids:
        pos = id2pos.get(cid)
        if kw_len > 0 and pos is not None and 0 <= pos < kw_len:
            kw_scores.append(float(kw_all[pos]))
        else:
            kw_scores.append(0.0)
    kw_norm = _normalize(kw_scores)

    fused = [float(alpha_weight) * s + (1.0 - float(alpha_weight)) * k for s, k in zip(sem_norm, kw_norm)]

    # --- Parent aggregation: top-3 mean; track best snippet + raw signals for gating
    by_parent: Dict[str, Dict] = {}
    for i, cid in enumerate(ids):
        md = metas[i] or {}
        parent = md.get("parent_id") or str(cid).split("::")[0]
        entry = by_parent.setdefault(parent, {
            "document_id": parent,
            "candidate_name": md.get("candidate_name") or "Candidate",
            "email": md.get("email"),
            "phone": md.get("phone"),
            "file_path": md.get("file_path"),
            "sem_list": [],
            "kw_list": [],
            "fused_list": [],
            "best_snippet": "",
            "best_fused": -1.0,
            "best_sem_raw": 0.0,
            "best_kw_raw": 0.0,
        })
        f = fused[i]
        entry["sem_list"].append(sem_norm[i])
        entry["kw_list"].append(kw_norm[i])
        entry["fused_list"].append(f)
        snippet = (docs[i] or "")[:800].replace("\n", " ")
        if f > entry["best_fused"]:
            entry["best_fused"] = f
            entry["best_snippet"] = snippet
            entry["best_sem_raw"] = sem_raw[i]
            entry["best_kw_raw"] = kw_scores[i]

    # Relevance gating (so random prompts return “I don’t know”)
    ranked = []
    q_tokens = [t for t in jd_tokens if t]
    for p in by_parent.values():
        top3 = sorted(p["fused_list"], reverse=True)[:3]
        pooled = sum(top3) / len(top3)
        item = {
            "document_id": p["document_id"],
            "candidate_name": p["candidate_name"],
            "email": p["email"],
            "phone": p["phone"],
            "file_path": p["file_path"],
            "sem": sum(sorted(p["sem_list"], reverse=True)[:3]) / max(1, len(top3)),
            "kw":  sum(sorted(p["kw_list"],  reverse=True)[:3]) / max(1, len(top3)),
            "score": pooled,
            "evidence": {"snippet": p["best_snippet"]},
            "_best_sem_raw": p["best_sem_raw"],
            "_best_kw_raw": p["best_kw_raw"],
            "_lex_overlap": _overlap_ratio(q_tokens, p["best_snippet"]),
        }
        if IRRELEVANCE_GATING_ON:
            sem_ok = (item["_best_sem_raw"] >= MIN_SEM_RAW_SIM)
            kw_ok  = (item["_best_kw_raw"] >= MIN_KW_SCORE)
            lex_ok = (item["_lex_overlap"]  >= MIN_LEXICAL_OVERLAP)
            if not (sem_ok or kw_ok or lex_ok):
                continue
        ranked.append(item)

    ranked.sort(key=lambda x: x["score"], reverse=True)
    ranked = ranked[:top_k_final]
    if len(ranked) > 0:
        svals = [r["score"] for r in ranked]
        smin, smax = min(svals), max(svals)
        for r in ranked:
            pct = 0 if smax - smin < 1e-9 else (r["score"] - smin) / (smax - smin)
            r["match_pct"] = int(round(100 * pct))

    ev_list = [{"document_id": r["document_id"], "snippet": r["evidence"]["snippet"]} for r in ranked]
    return ranked, ev_list

@traceable(name="chat_completion", run_type="llm")
def call_llm(llm, prompt: str) -> str:
    return llm.invoke(prompt).content or ""

# --- LLM setup & helpers ---

def _get_openai_base():
    # Optional override for Azure/OpenAI-compatible endpoints
    return os.getenv("OPENAI_BASE_URL")

class OpenAIChat:
    """Adapter so we can keep using llm.invoke(prompt).content."""

    def __init__(self, model: str, temperature: float = 0.2):
        api_key = _get_openai_api_key()
        base_url = os.getenv("OPENAI_BASE_URL")
        raw_client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.client = wrap_openai(raw_client)  # <<— this enables automatic LangSmith tracing
        self.model = model
        self.temperature = float(temperature)

    def invoke(self, prompt: str):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
        )
        text = resp.choices[0].message.content or ""
        return SimpleNamespace(content=text)

@st.cache_resource(show_spinner=False)
def get_chat_llm():
    # switched from ChatOllama → OpenAI
    return OpenAIChat(model=CHAT_MODEL, temperature=0.2)

def compose_system_prompt() -> str:
    return (
        "You are a recruiting copilot. Given a hiring query and retrieved resume snippets, "
        "recommend the top candidates and strictly ground every statement in the provided evidence only.\n"
        "\n"
        "Output requirements:\n"
        "- For each retrieved candidate, produce a concise, scannable evaluation.\n"
        "- Structure per candidate:\n"
        "  • Summary — one very long sentence on overall fit vs the query.\n"
        "  • Strengths — 5–10 bullets of clear matches (skills, tools, years, domains, certifications, Experiance, location). Quote short phrases when helpful.\n"
        "  • Areas to improve — 5–10 bullets for gaps/mismatches vs the query. If a requirement is not evidenced in the snippet, say “not evidenced in snippet”.\n"
        "- Do not invent details. If unknown, write “not in snippet”.\n"
        "- Keep tone neutral; avoid fluff and repetition; prefer specifics.\n"
    )


def invoke(self, prompt: str):
    resp = self.client.chat.completions.create(
        model=self.model,
        messages=[
            {"role": "system", "content": compose_system_prompt()},
            {"role": "user", "content": prompt},  # prompt should omit the sys text now
        ],
        temperature=self.temperature,
    )
    return SimpleNamespace(content=resp.choices[0].message.content or "")

def _get_openai_api_key() -> str:
    """Resolve the OpenAI API key from Streamlit secrets, env var, or a file path."""
    # 1) Streamlit secrets (preferred)
    try:
        key = st.secrets.get("OPENAI_API_KEY", None)  # type: ignore[attr-defined]
    except Exception:
        key = None

    # 2) Environment variable
    if not key:
        key = os.getenv("OPENAI_API_KEY")

    # 3) Optional: read from a file whose path is in env var
    if not key:
        key_file = os.getenv("OPENAI_API_KEY_FILE")
        if key_file and Path(key_file).exists():
            key = Path(key_file).read_text(encoding="utf-8").strip()

    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY not found. Add it to .streamlit/secrets.toml or set it as an env var."
        )
    return key

def _tolist(x):
    """Return a plain Python list (or []) from list/tuple/np.array/None."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    try:
        return list(x)
    except Exception:
        return [x]

@st.cache_resource(show_spinner=False)
def _get_llm_for_meta():
    # lightweight instance for summaries/rewrites (OpenAI)
    return OpenAIChat(model=CHAT_MODEL, temperature=0.1)

# ---- Chat store (persistent history) ----

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _ensure_store():
    os.makedirs(CHAT_STORE_DIR, exist_ok=True)

def _chat_path(cid: str) -> str:
    return os.path.join(CHAT_STORE_DIR, f"chat_{cid}.json")

def _atomic_write(path: str, data: dict):
    """
    Windows-safe atomic-ish write:
    1) write to a unique tmp file in the same directory
    2) flush + fsync
    3) retry os.replace with backoff (handles transient locks)
    4) fallback: direct write to target; always cleanup tmp
    """
    _ensure_store()
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"

    # Step 1: write tmp
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            # fsync may not be available on some filesystems; ignore
            pass

    # Step 2/3: replace with retries (deal with AV/indexers/other readers)
    last_err = None
    for i in range(20):  # ~ up to ~3s total
        try:
            os.replace(tmp, path)  # atomic when target isn't locked
            return
        except PermissionError as e:
            last_err = e
            # incremental backoff
            time.sleep(0.1 + 0.05 * i)
        except Exception as e:
            last_err = e
            time.sleep(0.1)

    # Step 4: fallback — direct write (best effort) + cleanup
    try:
        with open(path, "w", encoding="utf-8") as f2:
            json.dump(data, f2, ensure_ascii=False, indent=2)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

    # Log to console; don’t crash the app
    if last_err:
        print(f"[warn] atomic write fallback used for {path}: {last_err}")


def list_chats() -> List[Dict]:
    _ensure_store()
    items = []
    for p in glob.glob(os.path.join(CHAT_STORE_DIR, "chat_*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
            items.append({
                "id": obj.get("id"),
                "title": obj.get("title") or "New chat",
                "updated_at": obj.get("updated_at") or obj.get("created_at") or "",
                "pinned": bool(obj.get("pinned", False)),
            })
        except Exception:
            continue
    # sort: pinned first, then updated desc
    def _key(x):
        return (0 if x.get("pinned") else 1, x.get("updated_at") or "")
    items.sort(key=_key)
    items.reverse()  # newest on top within groups
    return items

def load_chat(cid: str) -> Dict:
    path = _chat_path(cid)
    if not os.path.exists(path):
        raise FileNotFoundError("Chat not found")
    with open(path, "r", encoding="utf-8") as f:
        chat = json.load(f)
    # ensure defaults
    chat.setdefault("id", cid)
    chat.setdefault("title", "New chat")
    chat.setdefault("created_at", _now_iso())
    chat.setdefault("updated_at", _now_iso())
    chat.setdefault("pinned", False)
    chat.setdefault("summary", "")
    chat.setdefault("messages", [])
    chat.setdefault("retrieval", {"alpha": float(HYBRID_ALPHA), "top_k_vec": int(TOP_K_VECTOR), "top_k_final": int(TOP_K_FINAL_CHAT)})
    chat.setdefault("meta", {})
    return chat

def save_chat(chat: Dict):
    chat["updated_at"] = _now_iso()
    _ensure_store()
    _atomic_write(_chat_path(chat["id"]), chat)

def new_chat() -> Dict:
    _ensure_store()
    cid = str(uuid.uuid4())
    chat = {
        "id": cid,
        "title": "New chat",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "pinned": False,
        "summary": "",
        "messages": [
            {"role": "assistant", "content": "Hi! Describe the role you’re hiring for (skills, years, tools, domain, location).Don't ask irrelevent questions", "ts": _now_iso()}
        ],
        "retrieval": {"alpha": float(HYBRID_ALPHA), "top_k_vec": int(TOP_K_VECTOR), "top_k_final": int(TOP_K_FINAL_CHAT)},
        "meta": {}
    }
    save_chat(chat)
    return chat

def delete_chat(cid: str):
    try:
        os.remove(_chat_path(cid))
    except Exception:
        pass

def rename_chat(cid: str, new_title: str):
    if not new_title.strip():
        return
    chat = load_chat(cid)
    chat["title"] = new_title.strip()[:80]
    save_chat(chat)

def toggle_pin(cid: str):
    chat = load_chat(cid)
    chat["pinned"] = not bool(chat.get("pinned", False))
    save_chat(chat)

# ---- URL query param helpers ----

def _get_query_params() -> Dict[str, str]:
    try:
        return dict(st.query_params)
    except Exception:
        return {k: v[0] for k, v in st.experimental_get_query_params().items() if v}

def _set_query_params(**kwargs):
    try:
        st.query_params.update(kwargs)
    except Exception:
        st.experimental_set_query_params(**kwargs)

# ---- Title & Summaries ----

STOPWORDS = set("for the and with to from in on of a an by as is are be this that those these using use based over under into across".split())

def autotitle_from_text(text: str) -> str:
    # simple heuristic: first 8 meaningful tokens
    tokens = re.findall(r"[A-Za-z0-9+.#-]+", text)[:12]
    tokens = [t for t in tokens if t.lower() not in STOPWORDS]
    title = " ".join(tokens[:8]) or "New chat"
    return title[:80]

@st.cache_resource(show_spinner=False)
def _get_llm_for_meta():
    # lightweight instance for summaries/rewrites (OpenAI)
    return OpenAIChat(model=CHAT_MODEL, temperature=0.1)

def summarize_history_if_needed(chat: Dict):
    try:
        msgs = [m for m in chat.get("messages", []) if m.get("role") in ("user","assistant")]
        if len(msgs) < SUMMARY_TRIGGER:
            return
        llm = _get_llm_for_meta()
        # keep only last ~4000 chars context to avoid long prompts
        transcript = []
        for m in msgs[-(SUMMARY_TRIGGER+10):]:
            prefix = "User:" if m["role"] == "user" else "Assistant:"
            transcript.append(f"{prefix} {m.get('content','')}")
        txt = "\n".join(transcript)[-4000:]
        prompt = (
            "Summarize the key hiring criteria, preferences, and constraints from this conversation in 8-12 bullet points. "
            "Be concise and neutral.\n\n" + txt
        )
        summary = llm.invoke(prompt).content or ""
        chat["summary"] = summary.strip()[:2000]
        save_chat(chat)
    except Exception:
        # non-fatal
        pass

def maybe_autotitle(chat: Dict, first_user_text: str, after_reply: bool = False):
    if chat.get("title") and chat["title"] != "New chat":
        return
    if not first_user_text:
        return
    title = autotitle_from_text(first_user_text)
    chat["title"] = title
    save_chat(chat)

# ---- Query rewriting ----

def rewrite_query(query_text: str, chat: Dict) -> str:
    if not REWRITE_ENABLED:
        return query_text
    try:
        llm = _get_llm_for_meta()
        brief = chat.get("summary", "")
        tail = chat.get("messages", [])[-(2*HISTORY_WINDOW_TURNS):]
        tail_txt = []
        for m in tail:
            prefix = "User:" if m["role"] == "user" else "Assistant:"
            tail_txt.append(f"{prefix} {m.get('content','')}")
        tail_str = "\n".join(tail_txt)[-1500:]
        prompt = (
            "Given the hiring conversation (summary + recent turns) and the user's latest request, rewrite a single, explicit search query for candidate retrieval. "
            "Keep to one line, include must-have skills, years, tools, seniority, and location if present.\n\n"
            f"Summary:\n{brief}\n\nRecent:\n{tail_str}\n\nLatest user request:\n{query_text}\n\nRewritten query:"
        )
        out = llm.invoke(prompt).content or ""
        out = out.strip().splitlines()[0]
        return out if len(out) > 10 else query_text
    except Exception:
        return query_text

# --- Rendering helpers ---

def render_results_table(results: List[Dict], key_prefix: str = "res"):
    if not results:
        return

    rows = []
    for r in results:
        rows.append({
            "Candidate": r.get("candidate_name"),
            "Match %": r.get("match_pct", 0),
            "Email": r.get("email"),
            "Phone": r.get("phone"),
            "Document ID": r.get("document_id"),
        })
    df = pd.DataFrame(rows)
    # <- give the table a unique key too (prevents re-run collisions)
    st.dataframe(df, use_container_width=True, hide_index=True, key=f"{key_prefix}_table")

    # enumerate so each download button key is unique
    for i, r in enumerate(results):
        with st.expander(f"Preview — {r['candidate_name']}  ({r.get('match_pct',0)}%)"):
            st.write(
                r.get("evidence", {}).get("snippet", "(no preview)")
                if isinstance(r.get("evidence"), dict)
                else r.get("evidence", "(no preview)")
            )
            fp = r.get("file_path")
            if fp and Path(fp).exists():
                with open(fp, "rb") as fh:
                    data = fh.read()
                base_name = Path(fp).name
                # <- UNIQUE KEY per button per row and per turn
                st.download_button(
                    "Download resume",
                    data,
                    file_name=base_name,
                    key=f"{key_prefix}_dl_{i}_{r.get('document_id','')}_{base_name}"
                )
            else:
                st.caption("Original file not found on server; contact admin.")


# ---------------- UI Layout ----------------

# Prepare services
(_, coll) = get_chroma()
bm25, doc_ids, id2pos = load_bm25_index()

# Sidebar
with st.sidebar:
    st.markdown("### Chats")
    # New chat & search
    cols = st.columns([1,1])
    if cols[0].button("➕ New", use_container_width=True):
        chat = new_chat()
        st.session_state["active_chat_id"] = chat["id"]
        _set_query_params(cid=chat["id"])  # deep link
        st.rerun()
    search_q = cols[1].text_input("Search", value="", placeholder="search…")

    # List chats
    items = list_chats()
    if search_q:
        ql = search_q.lower()
        items = [c for c in items if ql in (c.get("title","" ).lower())]

    # Determine active
    qp = _get_query_params()
    active_id = st.session_state.get("active_chat_id") or qp.get("cid")

    # render rows
    for it in items:
        row = st.container()
        c1, c2, c3 = row.columns([6, 1, 1])
        label = ("📌 " if it.get("pinned") else "") + (it.get("title") or "New chat")
        if c1.button(label, key=f"open_{it['id']}", use_container_width=True):
            st.session_state["active_chat_id"] = it["id"]
            _set_query_params(cid=it["id"])  # update URL
            st.rerun()
        pin_label = "Unpin" if it.get("pinned") else "Pin"
        if c2.button("📌" if it.get("pinned") else "📍", key=f"pin_{it['id']}"):
            toggle_pin(it["id"])
            st.rerun()
        if c3.button("🗑", key=f"del_{it['id']}"):
            delete_chat(it["id"])
            if active_id == it["id"]:
                chat = new_chat()
                st.session_state["active_chat_id"] = chat["id"]
                _set_query_params(cid=chat["id"])  # deep link
            st.rerun()

    try:
        active_chat = load_chat(active_id)
    except Exception:
        active_chat = new_chat()
        st.session_state["active_chat_id"] = active_chat["id"]
        _set_query_params(cid=active_chat["id"])
    new_title = st.text_input("Title", value=active_chat.get("title","New chat"))
    if st.button("Rename", use_container_width=True):
        rename_chat(active_chat["id"], new_title)
        st.rerun()
    if st.button("Delete chat", use_container_width=True):
        delete_chat(active_chat["id"])
        chat = new_chat()
        st.session_state["active_chat_id"] = chat["id"]
        _set_query_params(cid=chat["id"])  # deep link
        st.rerun()

    st.divider()
    st.markdown("### Retrieval settings")
    alpha = st.slider("Hybrid α (semantic vs keyword)", 0.0, 1.0, float(active_chat.get("retrieval",{}).get("alpha", HYBRID_ALPHA)), 0.05)
    topk_vec = st.slider("Vector top-K", 10, 100, int(active_chat.get("retrieval",{}).get("top_k_vec", TOP_K_VECTOR)), 5)
    rewrite_on = st.toggle("Rewrite follow-ups (query rewrite)", value=REWRITE_ENABLED, help="Uses the conversation summary to rewrite your latest query more explicitly before retrieval.")

    st.caption("Top-5 resumes are shown per turn.")
    st.divider()
    st.caption("Open the dedicated JD/Hybrid search app:")
    open_user = st.button("🔎 Open JD/Hybrid Search", use_container_width=True)
    if open_user:
        try:
            st.switch_page("streamlit_user.py")
        except Exception:
            try:
                st.switch_page("pages/streamlit_user.py")
            except Exception:
                user_url = os.getenv("USER_APP_URL", "http://localhost:8502")
                st.markdown(f"[Open JD/Hybrid Search]({user_url})")
                st.info("If it doesn't open, start it separately: `streamlit run streamlit_user.py` (usually http://localhost:8502).")
    try:
        st.page_link("pages/streamlit_user.py", label="Open JD/Hybrid Search (same process)", icon="🔎")
    except Exception:
        st.markdown("[Open JD/Hybrid Search (external)](http://localhost:8502)")

# Load the active chat for main pane rendering
active_id = st.session_state.get("active_chat_id") or _get_query_params().get("cid")
if not active_id:
    chat = new_chat()
    st.session_state["active_chat_id"] = chat["id"]
    _set_query_params(cid=chat["id"])  # deep link
    active_id = chat["id"]

try:
    chat = load_chat(active_id)
except Exception:
    chat = new_chat()
    st.session_state["active_chat_id"] = chat["id"]
    _set_query_params(cid=chat["id"])

# Persist retrieval settings selected in sidebar
chat["retrieval"]["alpha"] = float(alpha)
chat["retrieval"]["top_k_vec"] = int(topk_vec)
chat["retrieval"]["top_k_final"] = int(TOP_K_FINAL_CHAT)
save_chat(chat)

# Page title & caption
st.title("💬 Chat with your resume corpus")
st.caption("Ask for an ideal profile. We’ll retrieve the top 5 matching resumes and explain why.")

# Render chat history
for idx, m in enumerate(chat.get("messages", [])):
    with st.chat_message(m.get("role","assistant")):
        st.markdown(m.get("content",""))
        if m.get("role") == "assistant" and m.get("results"):
            st.markdown("\n**Top matches**")
            try:
                render_results_table(m.get("results", []), key_prefix=f"turn{idx}")
            except Exception:
                pass

# Chat input
user_msg = st.chat_input("e.g., Senior Python developer, 5+ yrs, FastAPI, Docker, AWS, Bangalore")

if user_msg:
    first_user_text = None
    if sum(1 for x in chat["messages"] if x.get("role") == "user") == 0:
        first_user_text = user_msg

    # optional text normalization
    user_msg_norm = user_msg  # or: clean_text(user_msg)

    # append and persist user message
    chat["messages"].append({"role": "user", "content": user_msg_norm, "ts": _now_iso()})
    save_chat(chat)

    # Maybe rewrite query from memory
    query_text = rewrite_on and rewrite_query(user_msg_norm, chat) or user_msg_norm

    # Retrieval
    try:
        with st.spinner("Retrieving resumes…"):
            results, evidence = hybrid_retrieve(
                query_text, coll, bm25, doc_ids, id2pos,
                chat["retrieval"]["top_k_vec"], TOP_K_FINAL_CHAT, chat["retrieval"]["alpha"]
            )
    except Exception as e:
        with st.chat_message("assistant"):
            st.error(f"Chat failed during retrieval: {e}")
        # record error reply
        chat["messages"].append({"role": "assistant", "content": f"(Retrieval error) {e}", "ts": _now_iso()})
        save_chat(chat)
        st.stop()

    # Compose answer
    llm = get_chat_llm()
    sys_prompt = compose_system_prompt()
    if not results:
        reply = "I don't know for this request. I couldn’t find any relevant resumes. Try broadening the skills, reducing constraints, or check that the admin has ingested resumes."
        with st.chat_message("assistant"):
            st.info(reply)
        chat["messages"].append({"role": "assistant", "content": reply, "ts": _now_iso()})
        save_chat(chat)
        st.rerun()

    snippets_md = "\n\n".join([
        f"**{i+1}. {r.get('candidate_name','Candidate')}** — match {r.get('match_pct',0)}%\n> {evidence[i]['snippet']}" for i, r in enumerate(results) if i < len(evidence)
    ])
    prompt = (
        f"{sys_prompt}\n\n"
        f"User query: {query_text}\n\n"
        f"Evidence snippets (use these only):\n{snippets_md}\n\n"
        f"Write a brief recommendation of the top {len(results)} candidates. Cite skills/tools/years that appear in the snippets."
    )
    try:
        reply = call_llm(llm, prompt)

    except Exception as e:
        reply = f"Here are the top matches based on retrieval (LLM response unavailable):\n\n" + "\n".join([
            f"- {r.get('candidate_name','Candidate')} — {r.get('match_pct',0)}%" for r in results
        ])

    with st.chat_message("assistant"):
        st.markdown(reply)
        st.markdown("\n**Top matches**")
        render_results_table(results, key_prefix=f"live_{len(chat.get('messages', []))}")

    # persist reply + a compact snapshot of results for history re-render
    results_brief = []
    for r in results:
        results_brief.append({
            "candidate_name": r.get("candidate_name"),
            "match_pct": r.get("match_pct"),
            "email": r.get("email"),
            "phone": r.get("phone"),
            "document_id": r.get("document_id"),
            "file_path": r.get("file_path"),
            "evidence": {"snippet": (r.get("evidence", {}) or {}).get("snippet", "")},
        })
    chat["messages"].append({"role": "assistant", "content": reply, "ts": _now_iso(), "results": results_brief})

    # auto-title after first turn
    if first_user_text:
        maybe_autotitle(chat, first_user_text, after_reply=True)

    # maybe summarize for memory compression
    summarize_history_if_needed(chat)

    # Save final state and rerun to show updated history
    save_chat(chat)
    st.rerun()

st.divider()
st.caption("Local RAG • Read-only access to vector DB • Download originals from server copies")
