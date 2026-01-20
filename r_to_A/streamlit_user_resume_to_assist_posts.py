# streamlit_user_resume_to_assist_posts.py
# ----------------------------------------------------------------------
# Resume → Assistance Center Postings semantic matcher (cosine only, no BM25)
# - User uploads a RESUME (pdf/docx/txt/rtf/doc)
# - We embed the resume (pooled across chunks) using Ollama embeddings
# - Query a dedicated Chroma collection that contains ASSISTANCE postings
# - Convert distances → similarities, normalize, aggregate by post_id
# - Rank postings and show top matches with evidence preview
# ----------------------------------------------------------------------

from __future__ import annotations

from typing import Dict, List
import requests
import streamlit as st
import pandas as pd

from config_resumes_to_assist import (
    CHROMA_DIR_ASSIST_POSTS,
    CHROMA_COLLECTION_ASSIST_POSTS,
    OLLAMA_HOST,
    EMBED_MODEL,
    R2A_TOP_K_VECTOR,
    R2A_TOP_K_FINAL,
    dump_config,
)

from utils_resumes_to_assist import (
    clean_text,
    read_text_from_bytes,
    embed_resume_pooled,
    distances_to_similarities,
    normalize,
    get_assist_posts_collection,
)

# ---------------- Streamlit UI config ----------------
st.set_page_config(
    page_title="Resume → Assistance Posts (Semantic Only)",
    page_icon="🧑‍💼",
    layout="wide",
)
st.title("Resume → Assistance Posts (Semantic Only)")
st.caption(
    "Upload a **resume** and find the most relevant **assistance center postings** "
    "using cosine similarity over a dedicated assistance-posts collection."
)

# ---------------- Core search ----------------
def _semantic_search(resume_text: str) -> List[Dict]:
    """
    Resume text → (pooled) embedding → Chroma query over ASSISTANCE postings →
    normalize similarities → aggregate to parent post_id → rank.
    """
    qvec = embed_resume_pooled(resume_text)
    if not qvec:
        return []

    coll = get_assist_posts_collection()
    res = coll.query(
        query_embeddings=[qvec],
        n_results=R2A_TOP_K_VECTOR,
        include=["documents", "distances", "metadatas"],
    )

    ids = res.get("ids", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    docs = res.get("documents", [[]])[0]

    sims = distances_to_similarities([float(d) for d in dists])
    sims_norm = normalize(sims)

    # Chunk-level rows (most posts are single-embedding, but keep generic)
    rows: List[Dict] = []
    for _id, md, doc, s in zip(ids, metas, docs, sims_norm):
        rows.append(
            {
                "chunk_id": _id,
                "post_id": (md or {}).get("post_id")
                or (md or {}).get("parent_id")
                or (_id.split("::")[0] if _id else None),
                "center_name": (md or {}).get("center_name"),
                "operating_hours": (md or {}).get("operating_hours"),
                "services": (md or {}).get("services"),
                "email": (md or {}).get("email"),
                "phone": (md or {}).get("phone"),
                "address": (md or {}).get("address"),
                "sim": float(s),
                "preview": (doc or "")[:320].replace("\n", " "),
            }
        )

    # Aggregate to parent post: keep the best-scoring chunk
    by_parent: Dict[str, Dict] = {}
    for r in rows:
        pid = r.get("post_id")
        if not pid:
            continue
        cur = by_parent.get(pid)
        if (not cur) or (r["sim"] > cur["sim"]):
            by_parent[pid] = r

    ranked = sorted(by_parent.values(), key=lambda x: x["sim"], reverse=True)[: R2A_TOP_K_FINAL]
    if not ranked:
        return []

    # Relative Match% scaling within this top-k (readable score for UI)
    hi = max(x["sim"] for x in ranked) or 1.0
    lo = min(x["sim"] for x in ranked)
    span = hi - lo if hi > lo else 1.0
    for x in ranked:
        x["match_pct"] = round(100.0 * ((x["sim"] - lo) / span), 1)

    return ranked

# ---------------- UI ----------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("📄 Upload Resume")
    resume_file = st.file_uploader(
        "Upload a resume (PDF/DOCX/TXT/RTF/DOC)",
        type=["pdf", "docx", "txt", "rtf", "doc"],
        accept_multiple_files=False,
    )
    run_btn = st.button("Find matching assistance postings", type="primary", use_container_width=True)

with right:
    st.subheader("Settings & Info")
    cfg = dump_config()
    st.write(f"Chroma dir (assist posts): `{cfg['CHROMA_DIR_ASSIST_POSTS']}`")
    st.write(f"Collection: `{cfg['CHROMA_COLLECTION_ASSIST_POSTS']}`")
    st.write(f"Embeddings via Ollama: `{cfg['EMBED_MODEL']}` at `{cfg['OLLAMA_HOST']}`")
    st.markdown(
        f"""
- Query pooling (resume): size `{cfg['R2A_QUERY_CHUNK_SIZE']}`, overlap `{cfg['R2A_QUERY_CHUNK_OVERLAP']}`, max chunks `{cfg['R2A_QUERY_MAX_CHUNKS']}`  
- Retrieval: top `{cfg['R2A_TOP_K_VECTOR']}` vectors → top `{cfg['R2A_TOP_K_FINAL']}` postings  
- Max query chars: `{cfg['R2A_MAX_QUERY_CHARS']}`  
"""
    )

# ---------------- Run search ----------------
if run_btn:
    try:
        if not resume_file:
            st.warning("Please upload a resume first.")
        else:
            text = read_text_from_bytes(resume_file.read(), resume_file.name)
            if not text.strip():
                st.warning("This resume seems empty after parsing/cleaning.")
            else:
                results = _semantic_search(text)

                if not results:
                    st.info(
                        "No results. Make sure you've ingested assistance postings in the dedicated collection "
                        f"(`{CHROMA_DIR_ASSIST_POSTS}` / `{CHROMA_COLLECTION_ASSIST_POSTS}`)."
                    )
                else:
                    df = pd.DataFrame(results)
                    show_cols = [
                        "match_pct",
                        "center_name",
                        "operating_hours",
                        "services",
                        "email",
                        "phone",
                        "post_id",
                        "sim",
                        "preview",
                    ]
                    for c in show_cols:
                        if c not in df.columns:
                            df[c] = None
                    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

                    with st.expander("Download results"):
                        csv = df[show_cols].to_csv(index=False).encode()
                        st.download_button(
                            "Download CSV",
                            data=csv,
                            file_name="resume_to_assist_posts_results.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

                    st.caption(
                        "Match% is relative within this result set. "
                        "'sim' is normalized cosine similarity (best-chunk evidence per posting)."
                    )

    except requests.RequestException as e:
        st.error(
            f"Embedding call to Ollama failed. "
            f"Is Ollama running and the model `{EMBED_MODEL}` pulled at `{OLLAMA_HOST}`? Details: {e}",
            icon="⚠️",
        )
    except Exception as e:
        st.error(f"Search failed: {e}")
