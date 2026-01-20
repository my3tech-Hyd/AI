# streamlit_admin_training_posts.py
# ----------------------------------------------------------------------
# Admin – Training Postings Ingestion via FORM (single-embedding per post)
# - Dedicated Chroma collection for TRAINING postings
# - Stores ONE embedding per posting (no chunking)
# - Cosine space to match your other apps
# ----------------------------------------------------------------------

from __future__ import annotations

import os
import re
import json
import hashlib
from pathlib import Path
from typing import Dict, List

import streamlit as st
import pandas as pd
import chromadb

# Config for the dedicated TRAINING postings corpus
from config_resumes_to_training import (
    CHROMA_DIR_TRAIN_POSTS,
    CHROMA_COLLECTION_TRAIN_POSTS,
    TRAIN_POSTS_STORE_DIR,
    EMBED_MODEL,
)

# Reuse simple cleaners
from utils_resumes_to_training import clean_text, to_csv_list

# ---------------- Page config ----------------
st.set_page_config(
    page_title="Admin – Training Posts Indexer (Form → Chroma)",
    page_icon="🗂️",
    layout="wide",
)
st.title("Admin – Training Posts Indexer (Form → Chroma)")
st.caption(
    "Create training/skill postings via form and store each as a SINGLE document with a SINGLE embedding in a dedicated Chroma collection."
)

# ---------------- Helpers ----------------

def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s or "").strip("_")
    return s or "training_post"

def sanitize_metadata(md: dict) -> dict:
    """Ensure all metadata values are Bool/Int/Float/Str; drop/convert Nones or odd types."""
    out = {}
    for k, v in (md or {}).items():
        if v is None:
            continue
        if isinstance(v, (bool, int, float, str)):
            out[k] = v
        else:
            out[k] = json.dumps(v, ensure_ascii=False)
    return out

def stable_id_from_bytes(data: bytes) -> tuple[str, str]:
    """Return (full_sha256_hex, short12_hex)."""
    h = hashlib.sha256()
    h.update(data)
    sha256_full = h.hexdigest()
    short12 = sha256_full[:12]
    return sha256_full, short12

def compose_text_from_form(
    *,
    center_name: str,
    capacity: int,
    address: str,
    phone: str,
    email: str,
    course_duration: str,
    certification: str,
    courses_offered: List[str],
    description: str,
) -> str:
    txt = f"""
Center Name: {center_name}
Capacity: {capacity}
Address: {address}
Phone: {phone}
Email: {email}
Course Duration: {course_duration}
Certification: {certification}
Courses Offered: {", ".join(courses_offered)}
Description: {description}
""".strip()
    return clean_text(txt)

def get_chroma_training_posts():
    client = chromadb.PersistentClient(path=CHROMA_DIR_TRAIN_POSTS)
    coll = client.get_or_create_collection(
        name=CHROMA_COLLECTION_TRAIN_POSTS,
        metadata={"hnsw:space": "cosine"}
    )
    os.makedirs(TRAIN_POSTS_STORE_DIR, exist_ok=True)
    return coll

def get_embedder():
    # Lazy import so the UI still loads if Ollama isn't up yet
    from langchain_community.embeddings import OllamaEmbeddings
    return OllamaEmbeddings(model=EMBED_MODEL)

# ---------------- UI ----------------

tab_form, tab_inv = st.tabs(["➕ New Training Posting (Form)", "📦 Inventory"])

with tab_form:
    st.subheader("Create a Training/Skill Posting (single embedding)")

    with st.form("training_form_admin", clear_on_submit=False):
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
                "TechBridge Learning Hub is a premier IT training institute focused on equipping students and professionals "
                "with hands-on skills in emerging technologies. With expert trainers, modern labs, and placement support, "
                "we ensure learners are ready for real-world challenges."
            ),
            height=160,
        )
        submit = st.form_submit_button("Ingest Posting", type="primary")

    if submit:
        try:
            courses_list = to_csv_list(courses_offered_text)
            text = compose_text_from_form(
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

            if not text.strip():
                st.warning("Form is empty after cleaning.")
                st.stop()

            coll = get_chroma_training_posts()

            # Deduplicate by content hash
            sha256_full, short12 = stable_id_from_bytes(text.encode("utf-8"))
            # Scan existing metadatas for duplicate sha (simple but effective for this scale)
            # NOTE: Chroma doesn't have a native 'where' across all docs in python client; we fetch in pages.
            offset, page = 0, 1000
            duplicate = False
            while True:
                batch = coll.get(include=["metadatas"], limit=page, offset=offset)
                _ids = batch.get("ids", [])
                _metas = batch.get("metadatas", [])
                if not _ids:
                    break
                if any((md or {}).get("sha256") == sha256_full for md in _metas):
                    duplicate = True
                    break
                offset += len(_ids)

            if duplicate:
                st.info("A posting with identical content already exists (duplicate by content hash).")
                st.stop()

            base_id = f"{slugify(center_name)}.{short12}"
            doc_id = f"{base_id}::chunk_0"  # single vector per posting

            # Metadata (simple & sanitized)
            md = sanitize_metadata({
                "post_id": base_id,
                "center_name": center_name,
                "capacity": int(capacity),
                "address": address,
                "phone": phone,
                "email": email,
                "course_duration": course_duration,
                "certification": certification,
                "courses_offered": ", ".join(courses_list),
                "source_ext": "form",
                "sha256": sha256_full,
                "short_hash": short12,
            })

            # Optional: persist a human-readable copy for audits
            stored_name = f"{base_id}.txt"
            stored_path = str(Path(TRAIN_POSTS_STORE_DIR) / stored_name)
            if not os.path.exists(stored_path):
                Path(stored_path).write_text(text, encoding="utf-8")

            # Embed once (no chunking)
            embedder = get_embedder()
            vec = embedder.embed_documents([text])  # -> [vector]

            coll.add(
                documents=[text],
                metadatas=[md],
                ids=[doc_id],
                embeddings=vec,
            )

            st.success(f"Ingested training posting as single embedding: {base_id}")
        except Exception as e:
            st.error(f"Failed to ingest training posting from form: {e}", icon="⚠️")

with tab_inv:
    st.subheader("Training Postings Inventory")
    coll = get_chroma_training_posts()

    # Collect all metadatas
    ids_all, metas_all = [], []
    offset, page = 0, 1000
    while True:
        batch = coll.get(include=["metadatas"], limit=page, offset=offset)
        _ids = batch.get("ids", [])
        _metas = batch.get("metadatas", [])
        if not _ids:
            break
        ids_all.extend(_ids)
        metas_all.extend(_metas)
        offset += len(_ids)

    # Aggregate by parent post_id
    agg: Dict[str, Dict] = {}
    for _id, md in zip(ids_all, metas_all):
        if not md:
            continue
        pid = md.get("post_id") or md.get("parent_id") or _id.split("::")[0]
        row = agg.get(pid) or {
            "post_id": pid,
            "center_name": md.get("center_name"),
            "capacity": md.get("capacity"),
            "course_duration": md.get("course_duration"),
            "certification": md.get("certification"),
            "courses_offered": md.get("courses_offered"),
            "email": md.get("email"),
            "phone": md.get("phone"),
            "address": md.get("address"),
            "short_hash": md.get("short_hash"),
            "sha256": md.get("sha256"),
            "chunks": 0,
        }
        row["chunks"] = row.get("chunks", 0) + 1
        agg[pid] = row

    df = pd.DataFrame(list(agg.values()))
    if df.empty:
        st.info("No training postings indexed yet.")
    else:
        show = [
            "center_name",
            "post_id",
            "capacity",
            "course_duration",
            "certification",
            "courses_offered",
            "email",
            "phone",
            "address",
            "short_hash",
            "sha256",
            "chunks",
        ]
        for c in show:
            if c not in df.columns:
                df[c] = None
        st.dataframe(df[show], use_container_width=True, hide_index=True)
        with st.expander("Export as CSV"):
            csv = df[show].to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV",
                data=csv,
                file_name="training_posts_inventory.csv",
                mime="text/csv",
                use_container_width=True,
            )
