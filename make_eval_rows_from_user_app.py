#!/usr/bin/env python3
# Build RAGAS-ready rows by calling your user app's retriever.
# Accepts CSV or XLSX with columns: user_input, reference

import os, sys, json, argparse
from pathlib import Path

def load_table(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {p}")
    ext = p.suffix.lower()
    rows = []
    if ext in {".xlsx", ".xls"}:
        import pandas as pd
        df = pd.read_excel(p)
        for _, r in df.iterrows():
            rows.append({
                "user_input": str(r.get("user_input", "") or "").strip(),
                "reference": str(r.get("reference", "") or "").strip(),
            })
    else:
        import csv
        with open(p, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "user_input": (r.get("user_input") or "").strip(),
                    "reference": (r.get("reference") or "").strip(),
                })
    # basic validation
    bad = [i for i, r in enumerate(rows, 1) if not r["user_input"]]
    if bad:
        raise ValueError(f"Missing user_input in rows: {bad[:8]}{'...' if len(bad)>8 else ''}")
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Path to eval_retrieval.csv or .xlsx")
    ap.add_argument("--out", dest="out", default="eval_retrieval.jsonl", help="Output JSONL")
    ap.add_argument("--k", dest="k_final", type=int, default=5, help="Top-K final contexts per row")
    ap.add_argument("--app-dir", dest="app_dir", default=".", help="Folder where streamlit_user.py lives")
    args = ap.parse_args()

    # make sure we can import streamlit_user no matter where we run from
    sys.path.insert(0, os.path.abspath(args.app_dir))
    import importlib
    su = importlib.import_module("streamlit_user")

    # warm up the retriever pieces from your app
    _, coll = su.get_chroma()                                # uses CHROMA_DIR / CHROMA_COLLECTION
    bm25, doc_ids, id2pos, meta_by_id = su.load_bm25_index() # BM25_* artifacts if present
    # (all defined in config.py) :contentReference[oaicite:3]{index=3}

    rows_in = load_table(args.inp)
    written = 0
    errors = 0
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as w:
        for i, r in enumerate(rows_in, 1):
            ui = r["user_input"]
            ref = r.get("reference", "")
            try:
                # call your app's hybrid search (same ranking as UI)
                results = su.hybrid_search(ui, coll, bm25, id2pos)  # returns resume-level results
                # Use the preview/evidence snippet per resume as retrieved contexts
                contexts = []
                for it in results[:args.k_final]:
                    # streamlit_user fills 'preview' as a trimmed chunk text; use it
                    ctx = (it.get("preview") or "").strip()
                    if ctx:
                        contexts.append(ctx)
                # minimal row for ragas retrieval metrics
                row_out = {
                    "user_input": ui,
                    "retrieved_contexts": contexts,
                    "reference": ref,   # optional but enables LLMContextRecall
                }
                w.write(json.dumps(row_out, ensure_ascii=False) + "\n")
                written += 1
            except Exception as e:
                errors += 1
                print(f"[row {i}] ERROR: {type(e).__name__}: {e}")
    print(f"Done. Wrote {written} rows to {out_path} ({errors} errors).")

if __name__ == "__main__":
    main()
