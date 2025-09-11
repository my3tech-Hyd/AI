# eval_mrr10.py — robust MRR@10 with ID and token fallback
import json, os, re
from statistics import mean

HEX_TAIL = re.compile(r"([a-f0-9]{10,16})$")  # 12-ish hex tail in your IDs

def canon_id(s: str) -> str:
    if s is None: return ""
    s = str(s).strip().lower()
    s = os.path.basename(s)
    s = re.sub(r"\.[a-z0-9]{2,4}$", "", s)       # strip .pdf/.rtf
    s = s.split("::", 1)[0]                      # drop ::ch7
    s = re.sub(r"(__|[-_])?ch(unk)?\d+$", "", s) # drop __ch12
    s = re.sub(r"[^\w\-]+", "_", s).strip("_-")
    return s

def tail_hash(s: str) -> str:
    m = HEX_TAIL.search(s or "")
    return m.group(1) if m else ""

def toks(s: str):
    return [t for t in re.split(r"[_\-\s]+", s) if t]

def canon_list(x):
    if x is None: return []
    if isinstance(x, list): items = x
    else:
        s = str(x)
        for sep in ["|",";"," "]: s = s.replace(sep, ",")
        items = [t for t in s.split(",") if t.strip()]
    out = []
    for i in items:
        c = canon_id(i)
        if c: out.append(c)
    return out

def match_any(got_id: str, gold_list):
    """Return True if got_id matches any gold entry under strict or lenient rules."""
    g_canon = got_id
    g_tail  = tail_hash(g_canon)
    g_tok   = set(toks(g_canon))

    for raw in gold_list:
        c = canon_id(raw)
        if not c:
            # token-only gold like 'java' / 'krishna'
            token = str(raw).strip().lower()
            if token and token in g_tok:
                return True
            continue

        # strict equality
        if c == g_canon:
            return True

        # tail hash equality
        c_tail = tail_hash(c)
        if c_tail and g_tail and c_tail == g_tail:
            return True

        # substring (handles things like 'developer_7fc6ed4432aa')
        if c in g_canon:
            return True

        # token containment: all gold tokens found in got tokens
        c_tok = set(toks(c))
        if c_tok and c_tok.issubset(g_tok):
            return True

    return False

def first_rel_rank(row, k=10):
    got  = canon_list(row.get("retrieved_parent_ids"))
    gold = canon_list(row.get("relevant_parent_ids"))
    # also add raw gold tokens (non-empty strings) for the token fallback
    raw_gold = row.get("relevant_parent_ids") or []
    if not isinstance(raw_gold, list):
        raw_gold = [g for g in re.split(r"[,\|;]+", str(raw_gold)) if g.strip()]
    if got and (gold or raw_gold):
        for i, gid in enumerate(got[:k]):
            if match_any(gid, gold or raw_gold):
                return i + 1
    return None

def main(path="eval_retrieval.jsonl"):
    ranks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            rr = first_rel_rank(row, k=10)
            ranks.append(0.0 if rr is None else 1.0/rr)
    mrr10 = round(mean(ranks), 4) if ranks else 0.0
    print({"mrr@10": mrr10})

if __name__ == "__main__":
    main()
