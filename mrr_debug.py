# mrr_debug.py
import json
from eval_mrr10 import canon_list

for i, line in enumerate(open("eval_retrieval.jsonl", encoding="utf-8"), 1):
    row = json.loads(line)
    got  = canon_list(row.get("retrieved_parent_ids"))
    gold = set(canon_list(row.get("relevant_parent_ids")))
    print(f"[{i}] GOT(top10)={got[:10]}")
    print(f"     GOLD={sorted(gold)}")
    hit = next((g for g in got[:10] if g in gold), None)
    print("     ->", "HIT@" + str(got.index(hit)+1) if hit else "MISS")
