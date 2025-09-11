# check_mrr_inputs.py
import json, sys
p = "eval_retrieval.jsonl" if len(sys.argv)<2 else sys.argv[1]
n, gold, have_ids = 0, 0, 0
for line in open(p, encoding="utf-8"):
    n += 1
    row = json.loads(line)
    if row.get("relevant_parent_ids"): gold += 1
    if row.get("retrieved_parent_ids"): have_ids += 1
print({"rows": n, "rows_with_gold_ids": gold, "rows_with_retrieved_parent_ids": have_ids})
