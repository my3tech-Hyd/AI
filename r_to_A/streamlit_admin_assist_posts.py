# streamlit_admin_assist_posts.py
# ----------------------------------------------------------------------
# Admin – Assistance Center Postings Ingestion via FORM (single-embedding)
# - Dedicated Chroma collection for ASSISTANCE postings
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

# Config for the dedicated ASSISTANCE postings corpus
from config_resumes_to_assist import (
    CHROMA_DIR_ASSIST_POSTS,
    CHROMA_COLLECTION_ASSIST_POSTS,
    ASSIST_POSTS_STORE_DIR,
    EMBED_MODEL,
)

# Reuse simple cleaners
from utils_resumes_to_assist import clean_text, to_csv_list

# ---------------- Page config ----------------
st.set_page_config(
    page_title="Admin – Assistance Posts Indexer (Form → Chroma)",
    page_icon="🗂️",
    layout="wide",
)
st.title("Admin – Assistance Posts Indexer (Form → Chroma)")
st.caption(
    "Create assistance-center postings via form and store each as a SINGLE document "
    "with a SINGLE embedding in a dedicated Chroma collection."
)

# ---------------- Helpers ----------------

def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s or "").strip("_")
    return s or "assist_post"

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
    operating_hours: str,
    services: List[str],
    description: str,
) -> str:
    txt = f"""
Center Name: {center_name}
Capacity: {capacity}
Address: {address}
Phone: {phone}
Email: {email}
Operating Hours: {operating_hours}
Services: {", ".join(services)}
Description: {description}
""".strip()
    return clean_text(txt)

def get_chroma_assist_posts():
    client = chromadb.PersistentClient(path=CHROMA_DIR_ASSIST_POSTS)
    coll = client.get_or_create_collection(
        name=CHROMA_COLLECTION_ASSIST_POSTS,
        metadata={"hnsw:space": "cosine"}
    )
    os.makedirs(ASSIST_POSTS_STORE_DIR, exist_ok=True)
    return coll

def get_embedder():
    # Lazy import so the UI still loads if Ollama isn't up yet
    from langchain_community.embeddings import OllamaEmbeddings
    return OllamaEmbeddings(model=EMBED_MODEL)

# ---------------- UI ----------------

tab_form, tab_inv = st.tabs(["➕ New Assistance Posting (Form)", "📦 Inventory"])

with tab_form:
    st.subheader("Create an Assistance Center Posting (single embedding)")

    with st.form("assist_form_admin", clear_on_submit=False):
        center_name = st.text_input("Center Name", value="CareerPath Assistance Center")
        capacity = st.number_input("Capacity", value=80, step=5)
        address = st.text_input("Address", value="2nd Floor, Orion Towers, Ameerpet, Hyderabad, Telangana, 500016")
        phone = st.text_input("Phone", value="+91-9123456780")
        email = st.text_input("Email", value="support@careerpathcenter.com")
        operating_hours = st.text_input("Operating Hours", value="Mon–Fri 9:00 AM – 6:00 PM")
        services_text = st.text_input(
            "Services (comma-separated)",
            value="Career Counseling, Resume Writing, Interview Preparation, Job Placement Support, Personality Development",
        )
        description = st.text_area(
            "Description",
            value=(
                "CareerPath Assistance Center helps job seekers achieve their career goals through personalized guidance, "
                "expert resume building, and intensive interview preparation. With strong industry connections, we "
                "provide end-to-end job placement support for fresh graduates and experienced professionals."
            ),
            height=160,
        )
        submit = st.form_submit_button("Ingest Posting", type="primary")

    if submit:
        try:
            services_list = to_csv_list(services_text)
            text = compose_text_from_form(
                center_name=center_name,
                capacity=int(capacity),
                address=address,
                phone=phone,
                email=email,
                operating_hours=operating_hours,
                services=services_list,
                description=description,
            )

            if not text.strip():
                st.warning("Form is empty after cleaning.")
                st.stop()

            coll = get_chroma_assist_posts()

            # Deduplicate by content hash
            sha256_full, short12 = stable_id_from_bytes(text.encode("utf-8"))
            # Scan existing metadatas for duplicate sha (simple paging)
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
                "operating_hours": operating_hours,
                "services": ", ".join(services_list),
                "source_ext": "form",
                "sha256": sha256_full,
                "short_hash": short12,
            })

            # Optional: persist a human-readable copy for audits
            stored_name = f"{base_id}.txt"
            stored_path = str(Path(ASSIST_POSTS_STORE_DIR) / stored_name)
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

            st.success(f"Ingested assistance posting as single embedding: {base_id}")
        except Exception as e:
            st.error(f"Failed to ingest assistance posting from form: {e}", icon="⚠️")

with tab_inv:
    st.subheader("Assistance Postings Inventory")
    coll = get_chroma_assist_posts()

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
            "operating_hours": md.get("operating_hours"),
            "services": md.get("services"),
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
        st.info("No assistance postings indexed yet.")
    else:
        show = [
            "center_name",
            "post_id",
            "capacity",
            "operating_hours",
            "services",
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
                file_name="assist_posts_inventory.csv",
                mime="text/csv",
                use_container_width=True,
            )
