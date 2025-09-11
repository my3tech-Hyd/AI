# scripts/export_parent_ids.py
import csv, os
from typing import Dict
from streamlit_chat import get_chroma  # uses your existing connection

(_, coll) = get_chroma()

def list_parents(coll) -> Dict[str, Dict]:
    page = 0
    page_size = 1000
    agg: Dict[str, Dict] = {}
    while True:
        batch = coll.get(include=["metadatas"], limit=page_size, offset=page * page_size)
        ids = batch.get("ids", []) or []
        metas = batch.get("metadatas", []) or []
        if not ids:
            break
        for _id, m in zip(ids, metas):
            m = m or {}
            parent = m.get("parent_id") or str(_id).split("::")[0]
            row = agg.get(parent)
            if not row:
                agg[parent] = {
                    "document_id": parent,
                    "candidate_name": m.get("candidate_name", ""),
                    "email": m.get("email", ""),
                    "phone": m.get("phone", ""),
                    "file_path": m.get("file_path", ""),
                    "source_ext": m.get("source_ext", ""),
                }
        page += 1
    return agg

agg = list_parents(coll)

with open("id_catalog.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["document_id","candidate_name","email","phone","file_path","source_ext"])
    w.writeheader()
    for row in agg.values():
        w.writerow(row)

print(f"Wrote {len(agg)} rows to id_catalog.csv")
