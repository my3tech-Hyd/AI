# doc_id.py — export parent resume document_ids from Chroma
import os
import chromadb
import pandas as pd
from pathlib import Path

# Try to read your app's config; otherwise fall back to env/defaults
try:
    from config import CHROMA_DIR, CHROMA_COLLECTION  # type: ignore
except Exception:
    CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma")
    CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "resumes")

# Connect to Chroma
if hasattr(chromadb, "PersistentClient"):
    client = chromadb.PersistentClient(path=CHROMA_DIR)
else:
    from chromadb.config import Settings
    client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory=CHROMA_DIR))

coll = client.get_or_create_collection(name=CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})

def parent_from(id_str, md):
    """Match the app logic: use metadata.parent_id, else the prefix before '::'."""
    return (md or {}).get("parent_id") or str(id_str).split("::")[0]

# Page through the collection to avoid memory spikes on large corpora
total = coll.count()
batch = 5000
offset = 0
seen = set()
rows = []

while offset < total:
    n = min(batch, total - offset)
    # ✅ Do NOT include "ids" in include; Chroma returns "ids" key automatically
    data = coll.get(include=["metadatas", "documents"], limit=n, offset=offset)
    ids = data.get("ids", []) or []
    metas = data.get("metadatas", []) or []

    for i, md in zip(ids, metas):
        pid = parent_from(i, md)
        if pid in seen:
            continue
        seen.add(pid)
        rows.append({
            "document_id": pid,
            "candidate_name": (md or {}).get("candidate_name"),
            "file_path": (md or {}).get("file_path"),
            "email": (md or {}).get("email"),
            "phone": (md or {}).get("phone"),
        })
    offset += len(ids)

# Save CSV
out_path = Path("parent_document_ids.csv")
pd.DataFrame(rows).sort_values("document_id").to_csv(out_path, index=False, encoding="utf-8")
print(f"Exported {len(rows)} parent IDs to {out_path.resolve()}")
