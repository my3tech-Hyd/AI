# 🚀 Quick Reference - Pinecone System

## ⚡ **Instant Commands**

### **Setup (One Time)**
```powershell
cd "C:\WITS\Wits dev\AI Model"
.venv\Scripts\Activate.ps1
```

---

## 📤 **Upload Data (Admin Tools)**

| What to Upload | Command | Namespace |
|----------------|---------|-----------|
| **Resumes** | `streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py` | `resumes` |
| **Jobs** | `streamlit run streamlit_admin_jd_PINECONE.py` | `jobs` |
| **Training** | `streamlit run r_to_p/streamlit_admin_training_posts_PINECONE.py` | `training` |
| **Assistance** | `streamlit run r_to_A/streamlit_admin_assist_posts_PINECONE.py` | `assistance` |

---

## 🔍 **Search (User Tools)**

| Search Type | Command | Reads From |
|-------------|---------|------------|
| **JD → Resume** | `streamlit run j_to_r/streamlit_user_jd_to_resume_PINECONE.py` | `resumes` |
| **Training → Resume** | `streamlit run p_to_r/streamlit_user_training_to_resumes_PINECONE.py` | `resumes` |
| **Assist → Resume** | `streamlit run a_to_r/streamlit_user_assist_to_resumes_PINECONE.py` | `resumes` |
| **Resume → Jobs** | `streamlit run streamlit_user_r2j_PINECONE.py` | `jobs` |
| **Resume → Training** | `streamlit run r_to_p/streamlit_user_resume_to_training_posts_PINECONE.py` | `training` |
| **Resume → Assist** | `streamlit run r_to_A/streamlit_user_resume_to_assist_posts_PINECONE.py` | `assistance` |

---

## 🎯 **Namespace Map**

```
📦 Pinecone Index: pbma
├── 📁 resumes     → Admin: j_to_r/streamlit_admin_resumes_PINECONE.py
│                  → Users: j_to_r, p_to_r, a_to_r (3 search tools)
├── 📁 jobs        → Admin: streamlit_admin_jd_PINECONE.py
│                  → User: streamlit_user_r2j_PINECONE.py
├── 📁 training    → Admin: r_to_p/streamlit_admin_training_posts_PINECONE.py
│                  → User: r_to_p/streamlit_user_resume_to_training_posts_PINECONE.py
└── 📁 assistance  → Admin: r_to_A/streamlit_admin_assist_posts_PINECONE.py
                   → User: r_to_A/streamlit_user_resume_to_assist_posts_PINECONE.py
```

---

## ⚙️ **Quick Config** (`pinecone_config.py`)

| Setting | Value | What It Does |
|---------|-------|--------------|
| `HYBRID_ALPHA` | 0.5 | Balance: 0=keyword, 1=semantic |
| `K_VEC` | 50 | Top semantic results to fetch |
| `K_BM25` | 50 | Top keyword results to fetch |
| `USE_RRF` | True | Use Reciprocal Rank Fusion |
| `USE_MMR` | False | Enable diversity filter |
| `TOP_K_FINAL` | 10 | Final results to show |

---

## 🧪 **Quick Test Flow**

```powershell
# 1. Upload a resume
streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py
# → Upload 1 PDF resume

# 2. Search with JD
streamlit run j_to_r/streamlit_user_jd_to_resume_PINECONE.py
# → Enter job description
# → Should see the resume you uploaded!

# 3. Upload a job
streamlit run streamlit_admin_jd_PINECONE.py
# → Fill job form

# 4. Search with resume
streamlit run streamlit_user_r2j_PINECONE.py
# → Enter resume details
# → Should see the job you added!
```

---

## 🔧 **Tuning Tips**

### **For Better Semantic Matching:**
- Increase `HYBRID_ALPHA` to 0.7-0.9
- Increase `K_VEC` to 100

### **For Better Keyword Matching:**
- Decrease `HYBRID_ALPHA` to 0.1-0.3
- Increase `K_BM25` to 100

### **For Diverse Results:**
- Enable `USE_MMR = True`
- Adjust `MMR_LAMBDA` (0.5 = balanced)

### **For Faster Search:**
- Reduce `TOP_K_FINAL` to 5
- Disable `USE_MMR`

---

## 📊 **Check Stats**

Open any admin tool to see:
- **Vector count** per namespace
- **BM25 index** size
- **Connection status**

---

## ⚠️ **Troubleshooting**

| Issue | Solution |
|-------|----------|
| "No results" | 1. Check if data uploaded to correct namespace<br>2. Try adjusting `HYBRID_ALPHA`<br>3. Check Ollama is running |
| "Pinecone error" | 1. Check API key in `pinecone_config.py`<br>2. Run `setup_pinecone_namespace.py` |
| "BM25 empty" | Run admin tool to upload data first |
| "Ollama timeout" | 1. Start Ollama: `ollama serve`<br>2. Check `OLLAMA_HOST` in config |

---

## 🎉 **You're Ready!**

**10 tools, 4 namespaces, 1 powerful system!**

Start with:
```powershell
streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py
```

Happy searching! 🚀

