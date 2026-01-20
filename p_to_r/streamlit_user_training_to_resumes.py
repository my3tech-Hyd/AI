# streamlit_user_training_to_resumes.py
# ----------------------------------------------------------------------
# Training Center Form → Resume semantic matcher (cosine only, no BM25)
# - User fills a Training Center posting form (single text composed)
# - We embed the form text (pooled across chunks) using Ollama embeddings
# - Query the existing Chroma collection that contains RESUME chunks
# - Convert distances → similarities, normalize, aggregate per resume
# - Rank resumes and show top matches with evidence preview
# ----------------------------------------------------------------------

from __future__ import annotations

from typing import Dict, List
import requests
import streamlit as st
import pandas as pd

from config_training_to_resumes import (
    CHROMA_DIR_RESUMES,
    CHROMA_COLLECTION_RESUMES,
    OLLAMA_HOST,
    EMBED_MODEL,
    T2R_TOP_K_VECTOR,
    T2R_TOP_K_FINAL,
    dump_config,
)

from utils_training_to_resumes import (
    clean_text,
    to_csv_list,
    compose_text_from_training_form,
    embed_query_pooled,
    distances_to_similarities,
    normalize,
    get_resume_collection,
)

# ---------------- Streamlit UI config ----------------
st.set_page_config(
    page_title="Training → Resume Search (Semantic Only)",
    page_icon="🎓",
    layout="wide",
)
st.title("Training → Resume Search (Semantic Only)")
st.caption(
    "Fill a **Training Center** posting form and find the most relevant **resumes** using cosine similarity over the existing resumes collection."
)

# ---------------- Core search ----------------
def _semantic_search(training_text: str) -> List[Dict]:
    """
    Training form text → (pooled) embedding → Chroma query over RESUME chunks →
    normalize similarities → aggregate to parent resume → rank.
    """
    qvec = embed_query_pooled(training_text)
    if not qvec:
        return []

    coll = get_resume_collection()
    res = coll.query(
        query_embeddings=[qvec],
        n_results=T2R_TOP_K_VECTOR,
        include=["documents", "distances", "metadatas"],
    )

    ids = res.get("ids", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    docs = res.get("documents", [[]])[0]

    sims = distances_to_similarities([float(d) for d in dists])
    sims_norm = normalize(sims)

    # Chunk-level rows
    rows: List[Dict] = []
    for _id, md, doc, s in zip(ids, metas, docs, sims_norm):
        rows.append(
            {
                "chunk_id": _id,
                "resume_id": (md or {}).get("resume_id")
                or (md or {}).get("parent_id")
                or (_id.split("::")[0] if _id else None),
                "candidate_name": (md or {}).get("candidate_name"),
                "email": (md or {}).get("email"),
                "phone": (md or {}).get("phone"),
                "sim": float(s),
                "preview": (doc or "")[:320].replace("\n", " "),
            }
        )

    # Aggregate to parent resume: keep the best chunk as the representative evidence
    by_parent: Dict[str, Dict] = {}
    for r in rows:
        pid = r.get("resume_id")
        if not pid:
            # Skip rows without a resolvable parent id
            continue
        cur = by_parent.get(pid)
        if (not cur) or (r["sim"] > cur["sim"]):
            by_parent[pid] = r

    ranked = sorted(by_parent.values(), key=lambda x: x["sim"], reverse=True)[: T2R_TOP_K_FINAL]
    if not ranked:
        return []

    # Relative Match% scaling within the top-k (for easier reading)
    hi = max(x["sim"] for x in ranked) or 1.0
    lo = min(x["sim"] for x in ranked)
    span = hi - lo if hi > lo else 1.0
    for x in ranked:
        x["match_pct"] = round(100.0 * ((x["sim"] - lo) / span), 1)

    return ranked

# ---------------- UI ----------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.subheader("🏫 Training Center Posting (Form)")
    # Unique key to avoid session_state collisions elsewhere
    with st.form("training_form_ui", clear_on_submit=False):
        center_name = st.text_input("Center Name", value="TechBridge Learning Hub")
        capacity = st.number_input("Capacity", value=120, step=10)
        address = st.text_input("Address", value="3rd Floor, Sunrise Plaza, Madhapur, Hyderabad, Telangana, 500081")
        phone = st.text_input("Phone", value="+91-9876543210")
        email = st.text_input("Email", value="contact@techbridgehub.com")
        course_duration = st.text_input("Course Duration", value="6 months")
        certification = st.text_input("Certification", value="Industry Certified by NASSCOM & Microsoft")
        courses_offered_text = st.text_input(
            "Courses Offered (comma-separated)",
            value="Web Development, Data Analytics, Cloud Computing, Digital Marketing, Cybersecurity",
        )
        description = st.text_area(
            "Description",
            value=(
                "TechBridge Learning Hub is a premier IT training institute focused on equipping students and "
                "professionals with hands-on skills in emerging technologies. With expert trainers, modern labs, "
                "and placement support, we ensure learners are ready for real-world challenges."
            ),
            height=160,
        )
        run_btn = st.form_submit_button("Find matching resumes", type="primary")

with right:
    st.subheader("Settings & Info")
    cfg = dump_config()
    st.write(f"Chroma dir (resumes): `{cfg['CHROMA_DIR_RESUMES']}`")
    st.write(f"Collection: `{cfg['CHROMA_COLLECTION_RESUMES']}`")
    st.write(f"Embeddings via Ollama: `{cfg['EMBED_MODEL']}` at `{cfg['OLLAMA_HOST']}`")
    st.markdown(
        f"""
- Query pooling: size `{cfg['T2R_QUERY_CHUNK_SIZE']}`, overlap `{cfg['T2R_QUERY_CHUNK_OVERLAP']}`, max chunks `{cfg['T2R_QUERY_MAX_CHUNKS']}`  
- Retrieval: top `{cfg['T2R_TOP_K_VECTOR']}` chunks → top `{cfg['T2R_TOP_K_FINAL']}` resumes  
- Max query chars: `{cfg['T2R_MAX_QUERY_CHARS']}`  
"""
    )

# ---------------- Run search ----------------
if run_btn:
    try:
        courses_list = to_csv_list(courses_offered_text)
        composed_text = compose_text_from_training_form(
            center_name=center_name,
            capacity=int(capacity),
            address=address,
            phone=phone,
            email=email,
            course_duration=course_duration,
            certification=certification,
            courses_offered=courses_list,
            description=description,
        )
        text = clean_text(composed_text)

        if not text.strip():
            st.warning("This form seems empty after parsing/cleaning.")
        else:
            results = _semantic_search(text)

            if not results:
                st.info("No results. Make sure you've ingested resumes in the resume collection.")
            else:
                df = pd.DataFrame(results)
                show_cols = [
                    "match_pct",
                    "candidate_name",
                    "email",
                    "phone",
                    "resume_id",
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
                        file_name="training_to_resume_results.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

                st.caption(
                    "Match% is relative within this result set. "
                    "'sim' is normalized cosine similarity (best-chunk evidence per resume)."
                )

    except requests.RequestException as e:
        st.error(
            f"Embedding call to Ollama failed. "
            f"Is Ollama running and the model `{EMBED_MODEL}` pulled at `{OLLAMA_HOST}`? Details: {e}",
            icon="⚠️",
        )
    except Exception as e:
        st.error(f"Search failed: {e}")
