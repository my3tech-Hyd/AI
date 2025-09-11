#!/usr/bin/env python3
# Build JSONL for RAGAS by retrieving top fused chunks using vector ∪ BM25
# and light cleaning. No dependency on streamlit_user.tokenize.

import os, sys, json, argparse, importlib, re
os.environ.setdefault("GIT_PYTHON_REFRESH","quiet")

# --- local text helpers (mirror BM25 build behavior) ---
ALIASES = {
    ".net": "dotnet", "c#": "csharp", "c++": "cpp",
    "node.js": "nodejs", "react.js": "react", "next.js": "nextjs",
    "javascript": "js", "typescript": "ts",
}
def parse_ids(val):
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val)
    if not s.strip():
        return []
    for sep in ["|", " ", ";"]:
        s = s.replace(sep, ",")
    return [t.strip() for t in s.split(",") if t.strip()]

def parse_ref_contexts(val):
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    if not s:
        return []
    # split on " || " or newlines
    return [p.strip() for p in re.split(r"\s*\|\|\s*|\n+", s) if p.strip()]

def get_top_parent_ids(su, query, kvec, kbm25, topn=10):
    # uses your robust retriever + parent pooling from streamlit_user.py
    cands = su.retrieve_candidates_union(query, kvec, kbm25)
    parents = su.parent_pool(cands)
    return [p.get("parent_id") for p in parents[:topn] if p.get("parent_id")]
def normalize_for_bm25(text: str) -> str:
    s = (text or "").lower()
    for a,b in ALIASES.items():
        s = s.replace(a, b)
    return s

def strip_rtf_noise(t: str) -> str:
    if not isinstance(t, str):
        return ""
    if t.lstrip().startswith("{\\rtf"):
        t = re.sub(r"[{}]", " ", t)
        t = re.sub(r"\\[a-zA-Z]+\\d* ?", " ", t)  # \par \b0 \fs22 ...
    return re.sub(r"\\s+", " ", t).strip()

def norm(v):
    if not v:
        return []
    mn, mx = min(v), max(v)
    if mx - mn < 1e-9:
        return [0.0 for _ in v]
    return [(x - mn) / (mx - mn) for x in v]
def retrieve_top_chunks_union(su, jd_text, kvec=80, kbm25=80, kchunks=15):
    import os

    def read_plain(fp: str) -> str:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            try:
                with open(fp, "r", encoding="latin-1") as f:
                    return f.read()
            except Exception:
                return ""

    # 1) pooled query vector
    qvec = su.embed_query_pooled(jd_text)

    # 2) vector candidates
    client, coll = su.get_chroma()
    q = coll.query(
        query_embeddings=[qvec],
        n_results=kvec,
        include=["documents", "metadatas", "distances"],
    )
    ids_v   = q.get("ids", [[]])[0]
    docs_v  = q.get("documents", [[]])[0]
    metas_v = q.get("metadatas", [[]])[0]
    dists_v = q.get("distances", [[]])[0]
    sem_v   = [1.0 - d for d in dists_v]

    C = {}  # key -> {doc, sem, kw, meta}
    for i, cid in enumerate(ids_v):
        key = metas_v[i].get("chunk_id", cid)
        C.setdefault(key, {"doc": strip_rtf_noise(docs_v[i] or ""), "sem": 0.0, "kw": 0.0, "meta": metas_v[i]})
        C[key]["sem"] = max(C[key]["sem"], sem_v[i])

    # 3) BM25 global top-K
    bm25, doc_ids, id2pos, meta_by_id = su.load_bm25_index()
    if getattr(bm25, "corpus_size", 0) > 0 and id2pos:
        tokens = normalize_for_bm25(jd_text).split()
        scores = bm25.get_scores(tokens)
        pairs = [(cid, float(scores[pos])) for cid, pos in id2pos.items() if pos < len(scores)]
        pairs.sort(key=lambda x: x[1], reverse=True)
        top_chunk_ids = [cid for cid, _ in pairs[:kbm25]]

        # try to fetch docs from chroma by metadata
        if top_chunk_ids:
            try:
                got = coll.get(where={"chunk_id": {"$in": top_chunk_ids}},
                               include=["documents","metadatas","ids"])
                got_ids  = got.get("ids", []) or []
                got_docs = got.get("documents", []) or []
                got_meta = got.get("metadatas", []) or []
                for i in range(len(got_ids)):
                    cid = got_meta[i].get("chunk_id", got_ids[i])
                    C.setdefault(cid, {"doc": "", "sem": 0.0, "kw": 0.0, "meta": got_meta[i]})
                    C[cid]["doc"] = C[cid]["doc"] or strip_rtf_noise(got_docs[i] or "")
            except Exception:
                pass

        # attach KW scores and FILL missing docs from file_path
        kw_map = dict(pairs)
        for cid, sc in kw_map.items():
            C.setdefault(cid, {"doc": "", "sem": 0.0, "kw": 0.0, "meta": (meta_by_id.get(cid) or {"chunk_id": cid})})
            C[cid]["kw"] = max(C[cid]["kw"], sc)
            if not C[cid]["doc"]:
                fp = (meta_by_id.get(cid) or {}).get("file_path")
                if fp and os.path.exists(fp):
                    C[cid]["doc"] = strip_rtf_noise(read_plain(fp))

    # 4) normalize + fuse
    keys = list(C.keys())
    def _norm(v):
        if not v: return []
        mn, mx = min(v), max(v)
        return [0.0 if mx-mn < 1e-9 else (x-mn)/(mx-mn) for x in v]
    sem_n = _norm([C[k]["sem"] for k in keys])
    kw_n  = _norm([C[k]["kw"]  for k in keys])

    alpha = float(getattr(su, "HYBRID_ALPHA", 0.55))
    fused = {k: alpha*sem_n[i] + (1.0-alpha)*kw_n[i] for i,k in enumerate(keys)}

    # 5) rank; RETURN ONLY non-empty docs; backfill with vector docs if needed
    ordered = sorted(keys, key=lambda k: fused[k], reverse=True)
    texts = [C[k]["doc"] for k in ordered if C[k]["doc"].strip()]
    if len(texts) < kchunks:
        # ensure we always have something: take any vector docs again
        vec_texts = [strip_rtf_noise(t or "") for t in docs_v if (t or "").strip()]
        for t in vec_texts:
            if len(texts) >= kchunks: break
            texts.append(t)
    return texts[:kchunks]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", default=".", help="folder where streamlit_user.py lives")
    ap.add_argument("--in", dest="inp", required=True, help="eval_retrieval.xlsx/.csv")
    ap.add_argument("--out", dest="out", default="eval_retrieval.jsonl")
    ap.add_argument("--kvec", type=int, default=80)
    ap.add_argument("--kbm25", type=int, default=80)
    ap.add_argument("--kchunks", type=int, default=15)
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.app_dir))
    su = importlib.import_module("streamlit_user")

    # load rows
    rows = []
    # inside main(), when reading Excel
    if args.inp.lower().endswith(".xlsx"):
        import pandas as pd
        df = pd.read_excel(args.inp)
        for _, r in df.iterrows():
            rows.append({
                "user_input": str(r["user_input"]),
                "reference": str(r.get("reference", "")),
                "relevant_parent_ids": r.get("relevant_parent_ids", ""),
                "reference_contexts": r.get("reference_contexts", ""),
            })
    else:
        import csv
        with open(args.inp, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "user_input": (r.get("user_input") or ""),
                    "reference": (r.get("reference") or ""),
                    "relevant_parent_ids": (r.get("relevant_parent_ids") or ""),
                    "reference_contexts": (r.get("reference_contexts") or ""),
                })
    with open(args.out, "w", encoding="utf-8") as w:
        for r in rows:
            # contexts for RAGAS
            ctxs = retrieve_top_chunks_union(
                su, r["user_input"], kvec=args.kvec, kbm25=args.kbm25, kchunks=args.kchunks
            )
            # NEW: parent IDs for MRR@10
            retrieved_parent_ids = get_top_parent_ids(
                su, r["user_input"], args.kvec, args.kbm25, topn=10
            )

            data = {
                "user_input": r["user_input"],
                "retrieved_contexts": ctxs,
                "retrieved_parent_ids": retrieved_parent_ids,
                "reference": r.get("reference", ""),
            }
            # pass through gold labels if present in Excel
            if r.get("relevant_parent_ids"):
                data["relevant_parent_ids"] = parse_ids(r["relevant_parent_ids"])
            if r.get("reference_contexts"):
                data["reference_contexts"] = parse_ref_contexts(r["reference_contexts"])

            w.write(json.dumps(data, ensure_ascii=False) + "\n")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
