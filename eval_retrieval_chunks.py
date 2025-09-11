# eval_retrieval_chunks.py
import os, json, argparse, importlib, csv
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

def load_rows(path):
    rows = []
    if path.lower().endswith(".xlsx"):
        import pandas as pd
        df = pd.read_excel(path)
        for _, r in df.iterrows():
            rows.append({"user_input": str(r["user_input"]), "reference": str(r["reference"])})
    else:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                rows.append({"user_input": (r["user_input"] or ""), "reference": (r.get("reference") or "")})
    return rows

def retrieve_top_chunks(su, jd_text, k_vec=50, k_chunks=10):
    qvec = su.embed_query_pooled(jd_text)
    coll = su.get_chroma()[1]
    q = coll.query(
        query_embeddings=[qvec],
        n_results=k_vec,
        include=["documents", "metadatas", "distances"],  # ← GOOD
    )
    # ids will still be present in q["ids"][0] without listing it

    ids   = q["ids"][0]; dists = q["distances"][0]
    metas = q["metadatas"][0]; docs = q["documents"][0]

    # semantic norm
    sem = [1.0 - d for d in dists]
    def norm(v):
        if not v: return v
        mn, mx = min(v), max(v)
        return [0.0 if mx-mn<1e-9 else (x-mn)/(mx-mn) for x in v]
    sem_n = norm(sem)

    # bm25 norm (aligned to same ids)
    bm25, doc_ids, id2pos, _ = su.load_bm25_index()
    kw_all = bm25.get_scores(su.tokenize(jd_text)) if getattr(bm25, "corpus_size", 0) > 0 else []
    kw_raw = [(kw_all[id2pos[cid]] if getattr(bm25,"corpus_size",0) and cid in id2pos else 0.0) for cid in ids]
    kw_n = norm(kw_raw)

    fused = [float(su.HYBRID_ALPHA)*s + (1.0-float(su.HYBRID_ALPHA))*k for s, k in zip(sem_n, kw_n)]
    order = sorted(range(len(ids)), key=lambda i: fused[i], reverse=True)
    # return top chunks’ full text (not truncated preview)
    return [docs[i] for i in order[:k_chunks]]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-dir", default=".", help="folder where streamlit_user.py lives")
    ap.add_argument("--in", dest="inp", required=True, help="eval_retrieval.xlsx or .csv")
    ap.add_argument("--out", dest="out", default="eval_retrieval.jsonl")
    ap.add_argument("--kvec", type=int, default=50)
    ap.add_argument("--kchunks", type=int, default=10)
    args = ap.parse_args()

    import sys, os
    sys.path.insert(0, os.path.abspath(args.app_dir))
    su = importlib.import_module("streamlit_user")

    in_rows = load_rows(args.inp)
    with open(args.out, "w", encoding="utf-8") as w:
        for r in in_rows:
            ctxs = retrieve_top_chunks(su, r["user_input"], k_vec=args.kvec, k_chunks=args.kchunks)
            w.write(json.dumps({
                "user_input": r["user_input"],
                "retrieved_contexts": ctxs,
                "reference": r["reference"],
            }, ensure_ascii=False) + "\n")
    print(f"Wrote {args.out}")
