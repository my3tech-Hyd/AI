#!/usr/bin/env python3
import json, argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="eval_retrieval.jsonl",
                    help="Path to the JSONL created by eval_retrieval_chunks.py")
    # Each item = plus-separated keywords that must all appear in at least one retrieved context
    ap.add_argument("--need", nargs="+", default=[
        "java+kafka+spring boot",
        "snowflake+airflow",
        "react+node+aws",
    ])
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.jsonl, encoding="utf-8")]
    need_groups = [set(s.lower().split("+")) for s in args.need]

    hits = 0
    for i, (row, req) in enumerate(zip(rows, need_groups), 1):
        ok = any(all(k in ctx.lower() for k in req) for ctx in row["retrieved_contexts"])
        print(f"row {i}: {'OK' if ok else 'MISS'}")
        hits += int(ok)
    print(f"total: {hits}/{len(rows)}")

if __name__ == "__main__":
    main()
