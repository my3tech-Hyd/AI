# 🏗️ Pinecone Architecture - Complete System

## 🗂️ **Namespace Isolation Strategy**

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Pinecone Index: pbma                           │
│                    (Single Index, 4 Namespaces)                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│   Namespace   │          │   Namespace   │          │   Namespace   │
│   "resumes"   │          │    "jobs"     │          │  "training"   │
└───────────────┘          └───────────────┘          └───────────────┘
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│   Namespace   │
│ "assistance"  │
└───────────────┘
```

---

## 📊 **Data Flow: Admin Tools (WRITE)**

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ADMIN TOOLS (Ingestion)                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────┐
│ streamlit_admin_           │
│ resumes_PINECONE.py        │
│                             │
│ 📄 Upload: PDF/DOCX/TXT    │
│ 🔹 Chunks: Yes (overlapping)│
│ 📍 Target: namespace=resumes│
└──────────────┬──────────────┘
               │
               ▼
     ┌─────────────────┐
     │  Pinecone Index │
     │  Namespace:     │
     │   "resumes"     │
     │                 │
     │  + BM25 Local   │
     │  .cache/bm25/   │
     │  resumes_*      │
     └─────────────────┘

┌─────────────────────────────┐
│ streamlit_admin_           │
│ jd_PINECONE.py             │
│                             │
│ 📝 Form: Job Details       │
│ 🔹 Chunks: No (single vec) │
│ 📍 Target: namespace=jobs  │
└──────────────┬──────────────┘
               │
               ▼
     ┌─────────────────┐
     │  Pinecone Index │
     │  Namespace:     │
     │     "jobs"      │
     │                 │
     │  + BM25 Local   │
     │  .cache/bm25/   │
     │  jobs_*         │
     └─────────────────┘

┌─────────────────────────────┐
│ r_to_p/streamlit_admin_    │
│ training_posts_PINECONE.py │
│                             │
│ 📝 Form: Training Details  │
│ 🔹 Chunks: No              │
│ 📍 Target: namespace=training│
└──────────────┬──────────────┘
               │
               ▼
     ┌─────────────────┐
     │  Pinecone Index │
     │  Namespace:     │
     │   "training"    │
     │                 │
     │  + BM25 Local   │
     │  .cache/bm25/   │
     │  training_*     │
     └─────────────────┘

┌─────────────────────────────┐
│ r_to_A/streamlit_admin_    │
│ assist_posts_PINECONE.py   │
│                             │
│ 📝 Form: Assistance Details│
│ 🔹 Chunks: No              │
│ 📍 Target: namespace=assistance│
└──────────────┬──────────────┘
               │
               ▼
     ┌─────────────────┐
     │  Pinecone Index │
     │  Namespace:     │
     │  "assistance"   │
     │                 │
     │  + BM25 Local   │
     │  .cache/bm25/   │
     │  assistance_*   │
     └─────────────────┘
```

---

## 🔍 **Data Flow: User Tools (READ)**

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER TOOLS (Search)                          │
└─────────────────────────────────────────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════╗
║              SEARCHING THE "resumes" NAMESPACE                   ║
╚══════════════════════════════════════════════════════════════════╝

┌────────────────────┐      ┌────────────────────┐      ┌────────────────────┐
│  JD → Resume       │      │ Training → Resume  │      │ Assist → Resume    │
│  streamlit_user_   │      │ streamlit_user_    │      │ streamlit_user_    │
│  jd_to_resume_     │      │ training_to_resumes│      │ assist_to_resumes_ │
│  PINECONE.py       │      │ _PINECONE.py       │      │ PINECONE.py        │
│                    │      │                    │      │                    │
│ Query: JD Form     │      │ Query: Training    │      │ Query: Assistance  │
└─────────┬──────────┘      └─────────┬──────────┘      └─────────┬──────────┘
          │                           │                           │
          └───────────────────────────┼───────────────────────────┘
                                      ▼
                          ┌─────────────────────┐
                          │   Pinecone Index    │
                          │   Namespace:        │
                          │    "resumes"        │
                          │                     │
                          │ Hybrid Retrieval:   │
                          │  • Semantic (Vector)│
                          │  • Keyword (BM25)   │
                          │  • Score Fusion     │
                          └─────────────────────┘
                                      │
                                      ▼
                          ┌─────────────────────┐
                          │  Top-K Resumes      │
                          │  with Scores        │
                          │  (CSV exportable)   │
                          └─────────────────────┘

╔══════════════════════════════════════════════════════════════════╗
║               SEARCHING THE "jobs" NAMESPACE                     ║
╚══════════════════════════════════════════════════════════════════╝

┌────────────────────────────┐
│  Resume → Jobs             │
│  streamlit_user_r2j_       │
│  PINECONE.py               │
│                            │
│  Query: Resume Form        │
└─────────────┬──────────────┘
              │
              ▼
  ┌─────────────────────┐
  │   Pinecone Index    │
  │   Namespace:        │
  │     "jobs"          │
  │                     │
  │ Hybrid Retrieval    │
  └─────────────────────┘
              │
              ▼
  ┌─────────────────────┐
  │  Top-K Jobs         │
  │  with Scores        │
  └─────────────────────┘

╔══════════════════════════════════════════════════════════════════╗
║             SEARCHING THE "training" NAMESPACE                   ║
╚══════════════════════════════════════════════════════════════════╝

┌────────────────────────────┐
│  Resume → Training         │
│  r_to_p/streamlit_user_    │
│  resume_to_training_posts_ │
│  PINECONE.py               │
│                            │
│  Query: Resume Form        │
└─────────────┬──────────────┘
              │
              ▼
  ┌─────────────────────┐
  │   Pinecone Index    │
  │   Namespace:        │
  │    "training"       │
  │                     │
  │ Hybrid Retrieval    │
  └─────────────────────┘
              │
              ▼
  ┌─────────────────────┐
  │  Top-K Training     │
  │  Programs           │
  └─────────────────────┘

╔══════════════════════════════════════════════════════════════════╗
║            SEARCHING THE "assistance" NAMESPACE                  ║
╚══════════════════════════════════════════════════════════════════╝

┌────────────────────────────┐
│  Resume → Assistance       │
│  r_to_A/streamlit_user_    │
│  resume_to_assist_posts_   │
│  PINECONE.py               │
│                            │
│  Query: Resume Form        │
└─────────────┬──────────────┘
              │
              ▼
  ┌─────────────────────┐
  │   Pinecone Index    │
  │   Namespace:        │
  │   "assistance"      │
  │                     │
  │ Hybrid Retrieval    │
  └─────────────────────┘
              │
              ▼
  ┌─────────────────────┐
  │  Top-K Assistance   │
  │  Centers            │
  └─────────────────────┘
```

---

## 🔄 **Hybrid Retrieval Pipeline (All User Tools)**

```
┌──────────────────────────────────────────────────────────────┐
│                    User Query (Text Input)                   │
└───────────────────────────┬──────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
    ┌─────────────────────┐  ┌─────────────────────┐
    │  Semantic Search    │  │  Keyword Search     │
    │  (Pinecone Vector)  │  │  (BM25 Local)       │
    │                     │  │                     │
    │  1. Embed query     │  │  1. Tokenize query  │
    │  2. Query Pinecone  │  │  2. BM25 score all  │
    │  3. Get top-K       │  │  3. Get top-K       │
    └──────────┬──────────┘  └──────────┬──────────┘
               │                        │
               └────────────┬───────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │   Score Fusion          │
              │                         │
              │  • RRF (Rank-based)     │
              │    OR                   │
              │  • Weighted Blend       │
              │    (HYBRID_ALPHA)       │
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │  Optional: MMR          │
              │  (Diversity Filter)     │
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │  Top-K Results          │
              │                         │
              │  • Match scores         │
              │  • Metadata             │
              │  • Text previews        │
              │  • CSV export           │
              └─────────────────────────┘
```

---

## 🔐 **Namespace Security & Isolation**

```
┌────────────────────────────────────────────────────────────┐
│                    Single Pinecone Index                   │
│                         (pbma)                             │
└────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Namespace   │    │  Namespace   │    │  Namespace   │
│  "resumes"   │    │   "jobs"     │    │  "training"  │
│              │    │              │    │              │
│ ✅ Isolated  │    │ ✅ Isolated  │    │ ✅ Isolated  │
│ ✅ No overlap│    │ ✅ No overlap│    │ ✅ No overlap│
│ ✅ Fast query│    │ ✅ Fast query│    │ ✅ Fast query│
└──────────────┘    └──────────────┘    └──────────────┘

                    ┌──────────────┐
                    │  Namespace   │
                    │ "assistance" │
                    │              │
                    │ ✅ Isolated  │
                    │ ✅ No overlap│
                    │ ✅ Fast query│
                    └──────────────┘

Benefits:
• Each admin tool WRITES to its dedicated namespace
• Each user tool READS from the appropriate namespace(s)
• No data contamination between corpus types
• Efficient filtering at the database level
• Single index = no free tier limit issues
```

---

## 📦 **File Structure Summary**

```
AI Model/
│
├── pinecone_config.py              # ✅ Central config (API keys, namespaces)
├── pinecone_retriever.py           # ✅ Hybrid search engine
├── setup_pinecone_namespace.py     # ✅ Index setup script
│
├── streamlit_admin_jd_PINECONE.py  # 👨‍💼 Admin: Jobs (namespace: jobs)
├── streamlit_user_r2j_PINECONE.py  # 👥 User: Resume→Jobs
│
├── j_to_r/
│   ├── streamlit_admin_resumes_PINECONE.py       # 👨‍💼 Admin: Resumes (namespace: resumes)
│   └── streamlit_user_jd_to_resume_PINECONE.py   # 👥 User: JD→Resume
│
├── p_to_r/
│   └── streamlit_user_training_to_resumes_PINECONE.py  # 👥 User: Training→Resume
│
├── a_to_r/
│   └── streamlit_user_assist_to_resumes_PINECONE.py    # 👥 User: Assist→Resume
│
├── r_to_p/
│   ├── streamlit_admin_training_posts_PINECONE.py      # 👨‍💼 Admin: Training (namespace: training)
│   └── streamlit_user_resume_to_training_posts_PINECONE.py  # 👥 User: Resume→Training
│
└── r_to_A/
    ├── streamlit_admin_assist_posts_PINECONE.py        # 👨‍💼 Admin: Assistance (namespace: assistance)
    └── streamlit_user_resume_to_assist_posts_PINECONE.py  # 👥 User: Resume→Assistance
```

---

## 🎯 **Key Features Implemented**

### ✅ **From Metric-Tested `streamlit_user.py`:**
1. **Hybrid Retrieval** (Semantic + Keyword)
2. **Query Pooling** (stable embeddings)
3. **RRF Fusion** (rank-based blending)
4. **MMR** (diversity filter)
5. **Anti-Collapse Re-Scoring** (tie-breaking)
6. **Robust BM25 Mapping** (multi-layer fallback)
7. **Configurable Parameters** (sidebar controls)

### ✅ **Pinecone Integration:**
1. **Namespace Isolation** (4 namespaces in 1 index)
2. **Efficient Filtering** (namespace-level queries)
3. **Scalable Storage** (100K vectors per namespace)
4. **Real-time Stats** (vector counts)
5. **Metadata Storage** (rich document info)

### ✅ **User Experience:**
1. **Form-Based Input** (no file uploads for user tools)
2. **CSV Export** (downloadable results)
3. **Score Breakdown** (semantic + keyword)
4. **Text Previews** (result snippets)
5. **Debug Panels** (error traces)

---

## 🚀 **Production Ready!**

All 10 tools are:
- ✅ **Tested architecture** (based on metric-proven code)
- ✅ **Namespace isolated** (no data conflicts)
- ✅ **Hybrid search** (semantic + keyword)
- ✅ **User-friendly** (Streamlit UI)
- ✅ **Export-ready** (CSV downloads)
- ✅ **Debug-enabled** (error panels)
- ✅ **Configurable** (sidebar controls)

**Start uploading data and searching!** 🎉

