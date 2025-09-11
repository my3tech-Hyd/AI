#!/usr/bin/env python3
import json, sys

def main(path="eval_gate.jsonl"):
    n_irr = 0
    fp = 0
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        if row.get("is_irrelevant"):
            n_irr += 1
            if row.get("gated"):
                fp += 1
    fpr = (fp / n_irr) if n_irr else 0.0
    print({"gate_fpr": round(fpr, 4), "negatives": n_irr, "false_positives": fp})

if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "eval_gate.jsonl"
    main(p)
