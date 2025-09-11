import pandas as pd, re, ast, json

SRC = "resumefinder_rag_eval.csv"
CAT = "id_catalog.csv"
DST = "resumefinder_rag_eval_ids.csv"

df = pd.read_csv(SRC)
cat = pd.read_csv(CAT)

# Build maps
id_to_name = dict(zip(cat["document_id"], cat["candidate_name"]))
# name -> list of ids (handle duplicates)
from collections import defaultdict
name_to_ids = defaultdict(list)
for did, nm in id_to_name.items():
    name_to_ids[(nm or "").strip().lower()].append(did)

def parse_listish(x):
    if isinstance(x, list): return x
    if pd.isna(x): return []
    s = str(x).strip()
    for parser in (json.loads, ast.literal_eval):
        try:
            v = parser(s); return list(v) if isinstance(v, (list, tuple)) else [str(v)]
        except Exception:
            pass
    return [t.strip() for t in s.split(",") if t.strip()]

def normalize_name(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

gold = []
if "gold_doc_ids" in df.columns and df["gold_doc_ids"].notna().any():
    # If you already have IDs but maybe missing short-hash, try to map by base-name
    pat_short = re.compile(r"-[0-9a-f]{10,16}$", re.I)
    for s in df["gold_doc_ids"].apply(parse_listish):
        ids = []
        for item in s:
            # if looks like an ID and exists, keep
            if item in id_to_name:
                ids.append(item); continue
            base = re.sub(pat_short, "", str(item))
            # try match by name
            cands = name_to_ids.get(normalize_name(base), [])
            ids.extend(cands)
        gold.append(list(dict.fromkeys(ids)))  # unique preserve order
else:
    # If your CSV has gold names in a "gold_names" column
    if "gold_names" not in df.columns:
        raise SystemExit("Add a 'gold_names' column or provide 'gold_doc_ids' to convert.")
    for s in df["gold_names"].apply(parse_listish):
        ids = []
        for nm in s:
            ids.extend(name_to_ids.get(normalize_name(nm), []))
        gold.append(list(dict.fromkeys(ids)))

out = df.copy()
out["gold_doc_ids"] = gold
out.to_csv(DST, index=False, encoding="utf-8")
print(f"Saved: {DST}")
