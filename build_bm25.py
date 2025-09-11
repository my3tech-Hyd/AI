# build_bm25.py — build BM25 artifacts from the plaintext resume store
import os, sys, pickle
from pathlib import Path
from typing import List, Dict

from config import (
    INDEX_DIR,
    RESUMES_STORE_DIR,
    BM25_CORPUS_PATH, BM25_DOCIDS_PATH, BM25_META_PATH,
)
from utils_text import read_text, clean_text, tokenize
from tqdm import tqdm

# Optional normalization/aliasing to improve recall
ALIASES = {
    ".net": "dotnet", "c#": "csharp", "c++": "cpp",
    "node.js": "nodejs", "react.js": "react", "next.js": "nextjs",
    "javascript": "js", "typescript": "ts",
}

def _normalize_for_bm25(text: str) -> str:
    s = (text or "").lower()
    for a,b in ALIASES.items():
        s = s.replace(a, b)
    return s

def rebuild_from_store(store_dir: str):
    """Walk RESUMES_STORE_DIR, build tokenized corpus and metadata/ids.
    Expects one plaintext chunk per file in store_dir (your admin pipeline).
    """
    p = Path(store_dir)
    files = [f for f in p.glob("**/*") if f.is_file()]

    corpus_tokens: List[List[str]] = []
    doc_ids: List[str] = []
    meta_by_id: Dict[str, Dict] = {}

    for f in tqdm(files, desc="bm25:scan"):
        try:
            text = read_text(str(f))  # supports pdf/docx/txt/rtf; your util handles
            text = clean_text(text)
            text = _normalize_for_bm25(text)
            toks = tokenize(text)
            if not toks:
                continue
            cid = f.stem  # use filename stem as chunk_id
            corpus_tokens.append(toks)
            doc_ids.append(cid)
            meta_by_id[cid] = {
                "file_path": str(f),
                # Optionally store parent_id if filename encodes it; else leave blank
                # "parent_id": cid.split("__")[0] if "__" in cid else cid,
            }
        except Exception as e:
            print("skip:", f, "->", e)

    Path(INDEX_DIR).mkdir(parents=True, exist_ok=True)
    with open(BM25_CORPUS_PATH, "wb") as f:
        pickle.dump(corpus_tokens, f)
    with open(BM25_DOCIDS_PATH, "wb") as f:
        pickle.dump(doc_ids, f)
    with open(BM25_META_PATH, "wb") as f:
        pickle.dump(meta_by_id, f)

if __name__ == "__main__":
    store = sys.argv[1] if len(sys.argv) > 1 else RESUMES_STORE_DIR
    rebuild_from_store(store)