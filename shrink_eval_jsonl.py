#!/usr/bin/env python3
import json, re, argparse

STOP = {"and","or","with","the","a","an","in","to","for","of","on","at","by","from","as","is","are","be","this","that"}
ALIASES = {".net":"dotnet","c#":"csharp","c++":"cpp","node.js":"nodejs","react.js":"react","next.js":"nextjs","javascript":"js","typescript":"ts"}

def norm_text(t: str) -> str:
    t = t or ""
    t = t.strip()
    t = re.sub(r"\s+", " ", t)
    return t

def strip_rtf_noise(s: str) -> str:
    if not isinstance(s, str): return ""
    if s.lstrip().startswith("{\\rtf"):
        s = re.sub(r"[{}]", " ", s)
        s = re.sub(r"\\[a-zA-Z]+\d* ?", " ", s)
    return norm_text(s)

def ref_keywords(ref: str, max_k=8):
    s = (ref or "").lower()
    for a,b in ALIASES.items(): s = s.replace(a,b)
    toks = re.findall(r"[a-z0-9][\w\+\.-]{2,}", s)
    kws = [t for t in toks if t not in STOP]
    # keep unique order
    seen, out = set(), []
    for k in kws:
        if k not in seen:
            seen.add(k); out.append(k)
        if len(out) >= max_k: break
    return out

def best_snip(doc: str, kws, max_chars=600, pad=140):
    d = strip_rtf_noise(doc)
    if not d: return ""
    if not kws: return d[:max_chars]
    d_low = d.lower()
    # find first keyword occurrence
    hits = [d_low.find(k) for k in kws if d_low.find(k) != -1]
    if not hits: return d[:max_chars]
    pos = min(hits)
    start = max(0, pos - pad)
    end = min(len(d), start + max_chars)
    return d[start:end]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="eval_retrieval.jsonl")
    ap.add_argument("--out", dest="out", default="eval_retrieval_small.jsonl")
    ap.add_argument("--max_contexts", type=int, default=8)
    ap.add_argument("--max_chars", type=int, default=600)
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8") as f, open(args.out, "w", encoding="utf-8") as w:
        for line in f:
            row = json.loads(line)
            ref = row.get("reference","")
            kws = ref_keywords(ref)
            seen = set()
            small = []
            for ctx in row.get("retrieved_contexts", []):
                snip = best_snip(ctx, kws, max_chars=args.max_chars)
                s = norm_text(snip)
                if not s: continue
                if s in seen: continue
                seen.add(s)
                small.append(s)
                if len(small) >= args.max_contexts: break
            # if nothing survived, keep a tiny head from the first ctx
            if not small and row.get("retrieved_contexts"):
                small = [norm_text(row["retrieved_contexts"][0])[:args.max_chars]]
            row["retrieved_contexts"] = small
            w.write(json.dumps(row, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main()
