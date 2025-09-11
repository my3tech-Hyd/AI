#!/usr/bin/env python3
import os, sys, json, importlib
import pandas as pd

# Gate threshold (percent)
GATE_MIN_PCT = int(os.getenv("GATE_MIN_PCT", "35"))

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", default=".", help="folder where streamlit_user.py lives")
    ap.add_argument("--in", dest="inp", required=True, help="Excel/CSV with user_input,is_irrelevant")
    ap.add_argument("--out", dest="out", default="eval_gate.jsonl")
    ap.add_argument("--kvec", type=int, default=100)
    ap.add_argument("--kbm25", type=int, default=120)
    ap.add_argument("--kchunks", type=int, default=12)
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.app_dir))
    su = importlib.import_module("streamlit_user")

    # Load rows
    if args.inp.lower().endswith(".xlsx"):
        df = pd.read_excel(args.inp)
    else:
        df = pd.read_csv(args.inp)
    df = df.fillna("")
    rows = df.to_dict("records")

    with open(args.out, "w", encoding="utf-8") as w:
        for r in rows:
            q = str(r.get("user_input", ""))
            irr = bool(int(r.get("is_irrelevant", 0)))  # 1/0 → bool

            # 1) contexts for RAGAS (optional; keeps file consistent with your other evals)
            ctxs = su.retrieve_top_chunks_union(su, q, kvec=args.kvec, kbm25=args.kbm25, kchunks=args.kchunks) \
                   if hasattr(su, "retrieve_top_chunks_union") else []

            # 2) parent IDs + match % for gating
            cands = su.retrieve_candidates_union(q, su.K_VEC, su.K_BM25)
            parents = su.parent_pool(cands)  # has match_pct and parent_id
            retrieved_parent_ids = [p["parent_id"] for p in parents[:10] if p.get("parent_id")]
            top_pct = parents[0]["match_pct"] if parents else 0
            gated = bool(top_pct >= GATE_MIN_PCT) and bool(retrieved_parent_ids)

            w.write(json.dumps({
                "user_input": q,
                "is_irrelevant": irr,
                "retrieved_parent_ids": retrieved_parent_ids,
                "top_match_pct": top_pct,
                "gated": gated,                # <-- our gating decision
                "reference": r.get("reference",""),
            }, ensure_ascii=False) + "\n")
    print(f"Wrote {args.out}")

if __name__ == "__main__":
    main()
