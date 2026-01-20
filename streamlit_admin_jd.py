# streamlit_admin_jds_form.py
# ----------------------------------------------------------------------
# Admin – JD Ingestion via FORM (single-embedding per JD)
# - Does NOT touch your existing admin file
# - Uses the same JD Chroma collection from config_jd
# - Stores one embedding per JD (no chunking)
# - UPDATED: Added fields:
#   1) Job ID
#   2) Requirements and skills (comma separated)
#   3) Qualifications and educations (comma separated)
#   4) Company Name
#   5) Address Line 1, Address Line 2, State, City, Zip Code
#   6) Work Mode, Salary Range, Job Expiry Date, Experience Required (Years)
# - NEW UPDATE: Community Service fields added to the form and metadata:
#   7) interestedCommunityAreas (comma separated)
#   8) preferredServiceType (text)
#   9) causesPassionateAbout (comma separated)
#   10) communityServiceExperience (text)
#   11) skillsForCommunityService (comma separated)
#   12) certificationsOrTraining (comma separated)
# ----------------------------------------------------------------------

import os
import io
import re
import pickle
from pathlib import Path
from typing import Dict, List, Tuple

import streamlit as st
import chromadb
import pandas as pd

# Reuse project utilities
from utils_jd import clean_text, tokenize, sanitize_metadata, stable_id_from_bytes

# JD config (same collection as your file-based admin)
from config_jd import (
    CHROMA_DIR, CHROMA_COLLECTION_JDS, JDS_INDEX_DIR,
    BM25_JDS_CORPUS_PATH, BM25_JDS_META_PATH, BM25_JDS_DOCIDS_PATH,
    EMBED_MODEL,
)

# ---- page ----
st.set_page_config(page_title="Admin – JD Form Ingest (Single Embedding)", page_icon="📝", layout="wide")
st.title("Admin – JD Form Ingest (Single Embedding)")
st.caption("Create a JD via form and store it as ONE document with ONE embedding in the same JD collection.")

# ---- helpers ----
def get_chroma():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    coll = client.get_or_create_collection(
        name=CHROMA_COLLECTION_JDS,
        metadata={"hnsw:space": "cosine"}  # explicit for safety
    )
    os.makedirs(JDS_INDEX_DIR, exist_ok=True)
    return coll

def get_embedder():
    # Lazy import so UI loads even if Ollama isn't up
    from langchain_community.embeddings import OllamaEmbeddings
    return OllamaEmbeddings(model=EMBED_MODEL)

def load_bm25():
    if os.path.exists(BM25_JDS_CORPUS_PATH):
        with open(BM25_JDS_CORPUS_PATH, "rb") as f:
            corpus_tokens = pickle.load(f)
    else:
        corpus_tokens = []
    if os.path.exists(BM25_JDS_META_PATH):
        with open(BM25_JDS_META_PATH, "rb") as f:
            meta_by_id = pickle.load(f)
    else:
        meta_by_id = {}
    if os.path.exists(BM25_JDS_DOCIDS_PATH):
        with open(BM25_JDS_DOCIDS_PATH, "rb") as f:
            bm25_doc_ids = pickle.load(f)
    else:
        bm25_doc_ids = []
    return corpus_tokens, meta_by_id, bm25_doc_ids

def save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids):
    with open(BM25_JDS_CORPUS_PATH, "wb") as f:
        pickle.dump(corpus_tokens, f)
    with open(BM25_JDS_META_PATH, "wb") as f:
        pickle.dump(meta_by_id, f)
    with open(BM25_JDS_DOCIDS_PATH, "wb") as f:
        pickle.dump(bm25_doc_ids, f)

def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s or "").strip("_")
    return s or "jd"

def _split_csv(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]

def compose_text_from_form(
    employer_id: str,
    job_id_external: str,
    job_title: str,
    company_name: str,
    description: str,
    location: str,
    job_type: str,
    min_salary: float,
    max_salary: float,
    required_skills: List[str],
    requirements_skills: List[str],
    qualifications_educations: List[str],
    posted_date: str,
    anonymous_posting: bool,
    is_active: bool,
    created_at: str,
    updated_at: str,
    # NEW address/location granularity + policy fields
    address_line1: str,
    address_line2: str,
    state: str,
    city: str,
    zip_code: str,
    work_mode: str,
    salary_range: str,
    job_expiry_date: str,
    experience_required_years: float,
    # NEW COMMUNITY SERVICE fields
    interested_community_areas: List[str],
    preferred_service_type: str,
    causes_passionate_about: List[str],
    community_service_experience: str,
    skills_for_community_service: List[str],
    certifications_or_training: List[str],
) -> str:
    txt = f"""
EmployerId: {employer_id}
Job ID: {job_id_external}
Company Name: {company_name}
Job Title: {job_title}
Description: {description}
Location: {location}
Address Line 1: {address_line1}
Address Line 2: {address_line2}
State: {state}
City: {city}
Zip Code: {zip_code}
Job Type: {job_type}
Work Mode: {work_mode}
Salary Range: {salary_range}
Min Salary: {min_salary}
Max Salary: {max_salary}
Experience Required (Years): {experience_required_years}
Job Expiry Date: {job_expiry_date}
Required Skills: {", ".join(required_skills)}
Requirements & Skills: {", ".join(requirements_skills)}
Qualifications & Educations: {", ".join(qualifications_educations)}
Posted Date: {posted_date}
Anonymous Posting: {anonymous_posting}
Is Active: {is_active}
Created At: {created_at}
Updated At: {updated_at}

# Community Service Profile
Interested Community Areas: {", ".join(interested_community_areas)}
Preferred Service Type: {preferred_service_type}
Causes Passionate About: {", ".join(causes_passionate_about)}
Community Service Experience: {community_service_experience}
Skills for Community Service: {", ".join(skills_for_community_service)}
Certifications or Training: {", ".join(certifications_or_training)}
""".strip()
    return clean_text(txt)

# ---- UI: form + inventory ----
tab_form, tab_inv = st.tabs(["➕ New JD (Form)", "📦 Inventory"])

with tab_form:
    st.subheader("Create a JD via Form (single embedding)")

    with st.form("jd_form", clear_on_submit=False):
        employer_id = st.text_input("EmployerId", value="1")
        # NEW fields
        job_id_external = st.text_input("Job ID", value="")
        company_name = st.text_input("Company Name", value="")
        # Existing fields
        job_title = st.text_input("Job title", value="Java Full Stack Developer")
        description = st.text_area("Description", value="Should have knowledge on designing and developing both front-end user …", height=200)
        location = st.text_input("Location", value="Hyderabad")

        # --- New: fine-grained address/location inputs ---
        col_a1, col_a2 = st.columns(2)
        with col_a1:
            address_line1 = st.text_input("Address Line 1", value="")
            state = st.text_input("State", value="")
            job_type = st.selectbox("JobType", options=["FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY"], index=0)
        with col_a2:
            address_line2 = st.text_input("Address Line 2", value="")
            city = st.text_input("City", value="")
            work_mode = st.selectbox("Work Mode", options=["ONSITE", "HYBRID", "REMOTE"], index=0)

        col_zip, col_salrng, col_exp = st.columns([1,2,1])
        with col_zip:
            zip_code = st.text_input("Zip Code", value="")
        with col_salrng:
            salary_range = st.text_input("Salary Range", value="")
        with col_exp:
            experience_required_years = st.number_input("Experience Required (Years)", value=0.0, step=0.5)

        # Existing salary fields remain (do not remove)
        min_salary = st.number_input("MinSalary", value=30000, step=1000)
        max_salary = st.number_input("MaxSalary", value=50000, step=1000)

        # Existing skills + NEW requirements/qualifications
        required_skills_text = st.text_input("RequiredSkills (comma-separated)", value="Java, Springboot, Hibernate, Html")
        requirements_and_skills_text = st.text_input("Requirements and skills (comma separated)", value="")
        qualifications_and_educations_text = st.text_input("Qualifications and educations (comma separated)", value="")

        # New: job expiry date
        job_expiry_date = st.text_input("Job Expiry Date (dd-mm-yyyy)", value="")

        posted_date = st.text_input("PostedDate", value="2025-08-28T13:03:02.686+00:00")
        anonymous_posting = st.checkbox("AnonymousPosting", value=False)
        is_active = st.checkbox("IsActive", value=True)
        created_at = st.text_input("CreatedAt", value="2025-08-28T13:03:02.748+00:00")
        updated_at = st.text_input("UpdatedAt", value="2025-08-28T13:03:02.748+00:00")

        st.markdown("---")
        st.subheader("Community Service Profile (Optional)")

        # NEW community service inputs (lists are comma-separated; one field is a free-text area)
        interested_community_areas_text = st.text_input(
            "interestedCommunityAreas (comma separated)",
            value=""
        )
        preferred_service_type = st.text_input(
            "preferredServiceType",
            value=""
        )
        causes_passionate_about_text = st.text_input(
            "causesPassionateAbout (comma separated)",
            value=""
        )
        community_service_experience = st.text_area(
            "communityServiceExperience",
            value="",
            height=100
        )
        skills_for_community_service_text = st.text_input(
            "skillsForCommunityService (comma separated)",
            value=""
        )
        certifications_or_training_text = st.text_input(
            "certificationsOrTraining (comma separated)",
            value=""
        )

        submit = st.form_submit_button("Ingest JD")

    if submit:
        try:
            # Parse CSV-like fields
            required_skills_list = _split_csv(required_skills_text)
            requirements_skills_list = _split_csv(requirements_and_skills_text)
            qualifications_educations_list = _split_csv(qualifications_and_educations_text)

            # Parse NEW community service list fields
            interested_community_areas_list = _split_csv(interested_community_areas_text)
            causes_passionate_about_list = _split_csv(causes_passionate_about_text)
            skills_for_community_service_list = _split_csv(skills_for_community_service_text)
            certifications_or_training_list = _split_csv(certifications_or_training_text)

            text = compose_text_from_form(
                employer_id=employer_id,
                job_id_external=job_id_external,
                job_title=job_title,
                company_name=company_name,
                description=description,
                location=location,
                job_type=job_type,
                min_salary=min_salary,
                max_salary=max_salary,
                required_skills=required_skills_list,
                requirements_skills=requirements_skills_list,
                qualifications_educations=qualifications_educations_list,
                posted_date=posted_date,
                anonymous_posting=anonymous_posting,
                is_active=is_active,
                created_at=created_at,
                updated_at=updated_at,
                # NEW params
                address_line1=address_line1,
                address_line2=address_line2,
                state=state,
                city=city,
                zip_code=zip_code,
                work_mode=work_mode,
                salary_range=salary_range,
                job_expiry_date=job_expiry_date,
                experience_required_years=experience_required_years,
                # NEW community service params
                interested_community_areas=interested_community_areas_list,
                preferred_service_type=preferred_service_type,
                causes_passionate_about=causes_passionate_about_list,
                community_service_experience=community_service_experience,
                skills_for_community_service=skills_for_community_service_list,
                certifications_or_training=certifications_or_training_list,
            )

            if not text:
                st.warning("Form is empty after cleaning.")
                st.stop()

            coll = get_chroma()
            corpus_tokens, meta_by_id, bm25_doc_ids = load_bm25()

            # Use the composed text for dedupe + stable id
            sha256_full, short12 = stable_id_from_bytes(text.encode("utf-8"))
            # dedupe on content hash
            if any(md.get("sha256") == sha256_full for md in meta_by_id.values()):
                st.info("This JD content already exists (duplicate by content hash).")
                st.stop()

            base_id = f"{slugify(job_title)}.{short12}"
            chunk_id = f"{base_id}::chunk_0"  # single chunk id

            # Combine skills for a compact "required_skills" field while retaining the new fields as well
            combined_skills = list(dict.fromkeys(required_skills_list + requirements_skills_list))  # de-dup preserve order

            # Metadata (kept simple and sanitized)
            md = sanitize_metadata({
                "job_id": base_id,                        # internal parent id used by matchers
                "job_id_external": job_id_external,       # NEW: external Job ID from the form
                "title": job_title,
                "company": company_name,                  # NEW: company name
                "employer_id": str(employer_id),
                "location": location,
                "url": "",
                "source_ext": "form",
                "sha256": sha256_full,
                "short_hash": short12,
                # Optional mirrors of form fields:
                "job_type": job_type,
                "work_mode": work_mode,                   # NEW
                "min_salary": float(min_salary),
                "max_salary": float(max_salary),
                "salary_range": salary_range,             # NEW (free-form)
                "experience_required_years": float(experience_required_years),  # NEW
                "required_skills": ", ".join(combined_skills),                 # combined compact
                "requirements_skills": ", ".join(requirements_skills_list),    # NEW
                "qualifications_educations": ", ".join(qualifications_educations_list),  # NEW
                "posted_date": posted_date,
                "job_expiry_date": job_expiry_date,       # NEW
                "anonymous_posting": bool(anonymous_posting),
                "is_active": bool(is_active),
                "created_at": created_at,
                "updated_at": updated_at,
                "embed_model": EMBED_MODEL,
                # NEW granular address/location
                "address_line1": address_line1,
                "address_line2": address_line2,
                "state": state,
                "city": city,
                "zip_code": zip_code,
                # NEW community service metadata mirrors
                "interested_community_areas": ", ".join(interested_community_areas_list),
                "preferred_service_type": preferred_service_type,
                "causes_passionate_about": ", ".join(causes_passionate_about_list),
                "community_service_experience": community_service_experience,
                "skills_for_community_service": ", ".join(skills_for_community_service_list),
                "certifications_or_training": ", ".join(certifications_or_training_list),
            })

            # Embed as ONE document (no chunking)
            embedder = get_embedder()
            vec = embedder.embed_documents([text])  # returns [vector]

            # Write to Chroma (single doc)
            coll.add(
                documents=[text],
                metadatas=[md],
                ids=[chunk_id],
                embeddings=vec
            )

            # Keep BM25 artifacts consistent (optional but harmless)
            corpus_tokens.append(tokenize(text))
            bm25_doc_ids.append(chunk_id)
            meta_by_id[base_id] = md
            save_bm25(corpus_tokens, meta_by_id, bm25_doc_ids)

            st.success(f"Ingested JD as single embedding: {base_id}")
            st.caption(f"External Job ID: {job_id_external or '—'}  •  Company: {company_name or '—'}")
        except Exception as e:
            st.error(f"Failed to ingest JD from form: {e}", icon="⚠️")

with tab_inv:
    st.subheader("JD Inventory (Form + Files)")
    coll = get_chroma()

    # collect parent-level
    ids_all, metas_all = [], []
    offset, page = 0, 500
    while True:
        batch = coll.get(include=["metadatas"], limit=page, offset=offset)
        _ids = batch.get("ids", [])
        _metas = batch.get("metadatas", [])
        if not _ids:
            break
        ids_all.extend(_ids)
        metas_all.extend(_metas)
        offset += len(_ids)

    agg = {}
    for _id, md in zip(ids_all, metas_all):
        if not md:
            continue
        pid = md.get("job_id") or md.get("parent_id") or _id.split("::")[0]
        row = agg.get(pid) or {
            "job_id": pid,
            "job_id_external": md.get("job_id_external"),
            "title": md.get("title"),
            "company": md.get("company"),
            "location": md.get("location"),
            "city": md.get("city"),
            "state": md.get("state"),
            "work_mode": md.get("work_mode"),
            "job_expiry_date": md.get("job_expiry_date"),
            "experience_required_years": md.get("experience_required_years"),
            "url": md.get("url"),
            "source_ext": md.get("source_ext"),
            "short_hash": md.get("short_hash"),
            "sha256": md.get("sha256"),
            # NEW community service snapshots (compact view)
            "preferred_service_type": md.get("preferred_service_type"),
            "interested_community_areas": md.get("interested_community_areas"),
            "causes_passionate_about": md.get("causes_passionate_about"),
            "skills_for_community_service": md.get("skills_for_community_service"),
            "certifications_or_training": md.get("certifications_or_training"),
            "chunks": 0,
        }
        row["chunks"] = row.get("chunks", 0) + 1
        agg[pid] = row

    df = pd.DataFrame(list(agg.values()))
    if df.empty:
        st.info("No JDs indexed yet.")
    else:
        show = [
            "title", "company", "location", "city", "state",
            "job_id", "job_id_external", "work_mode",
            "experience_required_years", "job_expiry_date",
            # NEW community columns (helpful at-a-glance)
            "preferred_service_type", "interested_community_areas",
            "causes_passionate_about", "skills_for_community_service",
            "certifications_or_training",
            "chunks", "source_ext", "short_hash", "sha256"
        ]
        for col in show:
            if col not in df.columns:
                df[col] = None
        st.dataframe(df[show], use_container_width=True, hide_index=True)
