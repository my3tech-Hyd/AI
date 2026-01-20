# 🌲 Pinecone Quick Start Guide

## 🎯 Goal
Replace ChromaDB with Pinecone for **reliable, scalable, cloud-hosted vector search**.

---

## ✅ Prerequisites

1. **Python** (any version - Pinecone works with all!)
2. **Ollama** running locally (`http://localhost:11434`)
3. **nomic-embed-text** model pulled (`ollama pull nomic-embed-text`)

---

## 📝 Step-by-Step Setup (10 minutes)

### Step 1: Get Pinecone API Key (2 minutes)

1. Go to [https://www.pinecone.io/](https://www.pinecone.io/)
2. Click "Sign Up" (FREE forever tier)
3. Create account
4. Go to "API Keys" in dashboard
5. Copy your API key

**Free Tier Limits:**
- ✅ 100,000 vectors
- ✅ 1 project
- ✅ Unlimited queries
- ✅ Perfect for your use case!

---

### Step 2: Install Pinecone (1 minute)

```bash
cd "C:\WITS\Wits dev\AI Model"
.venv\Scripts\Activate.ps1
pip install pinecone-client[grpc]
```

---

### Step 3: Configure Environment (2 minutes)

Create or update your `.env` file in the project root:

```env
# Pinecone (REQUIRED)
PINECONE_API_KEY=your-api-key-here
PINECONE_ENVIRONMENT=us-east-1

# Pinecone Index Names (optional - uses defaults if not set)
PINECONE_INDEX_RESUMES=resumes
PINECONE_INDEX_JOBS=jobs
PINECONE_INDEX_TRAINING=training-posts
PINECONE_INDEX_ASSISTANCE=assistance-posts

# Ollama (unchanged)
OLLAMA_HOST=http://localhost:11434
EMBED_MODEL=nomic-embed-text

# Vector dimension for nomic-embed-text
VECTOR_DIMENSION=768
```

**Important:** Replace `your-api-key-here` with your actual Pinecone API key!

---

### Step 4: Create Pinecone Indexes (2 minutes)

Run the setup script:

```bash
python setup_pinecone_indexes.py
```

**Expected output:**
```
✅ Configuration valid
📊 Existing indexes: (none)

🔨 Creating index: resumes
   ✅ Created successfully!

🔨 Creating index: jobs
   ✅ Created successfully!

🔨 Creating index: training-posts
   ✅ Created successfully!

🔨 Creating index: assistance-posts
   ✅ Created successfully!

✅ Setup complete! Total indexes: 4
```

---

### Step 5: Test the Setup (1 minute)

```bash
python -c "from pinecone import Pinecone; from pinecone_config import PINECONE_API_KEY, PINECONE_INDEX_RESUMES; pc = Pinecone(api_key=PINECONE_API_KEY); print(f'✅ Connected to Pinecone!'); idx = pc.Index(PINECONE_INDEX_RESUMES); print(f'✅ Index stats: {idx.describe_index_stats()}')"
```

**Expected output:**
```
✅ Connected to Pinecone!
✅ Index stats: {'dimension': 768, 'index_fullness': 0.0, 'namespaces': {}, 'total_vector_count': 0}
```

---

## 🚀 What's Ready Now

### ✅ Core Components Created:
1. **`pinecone_config.py`** - Centralized configuration
2. **`pinecone_retriever.py`** - Hybrid retrieval engine
3. **`setup_pinecone_indexes.py`** - Index setup script

### ✅ Pinecone Indexes Created:
- `resumes` - For storing resume vectors
- `jobs` - For storing job description vectors
- `training-posts` - For training center postings
- `assistance-posts` - For assistance center postings

### ⏳ Next Steps:
1. Update admin ingestion tools to use Pinecone
2. Update user search modules to use Pinecone
3. Ingest your data
4. Test!

---

## 📥 Ingesting Data (Next)

You have two options:

### Option 1: Fresh Start (Recommended - 30 min)
Re-run admin tools with Pinecone integration:
- Upload resumes again
- Upload job descriptions again
- Create training posts again
- Create assistance posts again

**Benefit:** Clean slate, no corruption

### Option 2: Migrate Existing Data (Advanced - 1 hour)
Create a migration script to copy from ChromaDB to Pinecone.

**Would you like me to create:**
1. ✅ Updated admin tools for Pinecone ingestion? (RECOMMENDED)
2. ⚠️ Migration script from ChromaDB to Pinecone? (If you want to preserve existing data)

---

## 🎯 Updated Files Needed

To complete the Pinecone migration, I need to update:

### Admin Tools (for ingestion):
1. `j_to_r/streamlit_admin_resumes_PINECONE.py` - Ingest resumes to Pinecone
2. `streamlit_admin_jd_PINECONE.py` - Ingest job descriptions to Pinecone
3. `r_to_p/streamlit_admin_training_posts_PINECONE.py` - Ingest training posts
4. `r_to_A/streamlit_admin_assist_posts_PINECONE.py` - Ingest assistance posts

### User Search Modules (all 6):
1. `j_to_r/streamlit_user_jd_to_resume_PINECONE.py` - Job → Resume search
2. `p_to_r/streamlit_user_training_to_resumes_PINECONE.py` - Training → Resume search
3. `a_to_r/streamlit_user_assist_to_resumes_PINECONE.py` - Assistance → Resume search
4. `r_to_p/streamlit_user_resume_to_training_posts_PINECONE.py` - Resume → Training search
5. `r_to_A/streamlit_user_resume_to_assist_posts_PINECONE.py` - Resume → Assistance search
6. `streamlit_user_r2j_PINECONE.py` - Resume → Job search

---

## 🔑 Key Differences: ChromaDB vs Pinecone

| Feature | ChromaDB | Pinecone |
|---------|----------|----------|
| **Hosting** | Local files | Cloud ✅ |
| **Python Version** | 3.8-3.12 only | Any version ✅ |
| **Scalability** | ~100K vectors | Millions ✅ |
| **Setup** | Auto-created | Manual setup |
| **Backups** | Manual | Automatic ✅ |
| **Corruption Risk** | High (Rust panic) | None ✅ |
| **Query Speed** | Fast | Very fast ✅ |
| **Cost** | Free | Free tier (100K vectors) ✅ |

---

## 💰 Cost Estimate

For your use case (let's estimate):
- **Resumes**: ~1,000 vectors (chunked)
- **Jobs**: ~500 vectors
- **Training**: ~100 vectors
- **Assistance**: ~100 vectors
- **Total**: ~1,700 vectors

**Pinecone Free Tier:** 100,000 vectors ✅

**You're well within the free tier!** 🎉

---

## 🐛 Troubleshooting

### Issue: "PINECONE_API_KEY not set"
**Fix:** Add your API key to `.env` file:
```env
PINECONE_API_KEY=your-actual-key-here
```

### Issue: "Index already exists"
**Fix:** This is fine! The setup script skips existing indexes.

### Issue: "Unable to connect to Pinecone"
**Fix:** Check your internet connection and API key.

### Issue: "Wrong dimension"
**Fix:** Make sure `VECTOR_DIMENSION=768` for `nomic-embed-text` model.

---

## ✅ What You've Accomplished So Far

- [x] Identified ChromaDB Python 3.13 incompatibility
- [x] Decided to switch to Pinecone
- [x] Created Pinecone configuration
- [x] Created Pinecone hybrid retriever
- [x] Setup script ready

## 📋 What's Next

Choose your path:

### Path A: Fresh Start (Recommended)
```
1. I'll create updated admin ingestion tools for Pinecone
2. You run them to upload your data
3. I'll create updated user search modules
4. You test the searches
5. Done! 🎉
```

### Path B: Migrate Data (If you want to preserve existing data)
```
1. I'll create a migration script
2. You run it to copy ChromaDB → Pinecone
3. I'll create updated user search modules
4. You test the searches
5. Done! 🎉
```

---

## 🎯 Ready to Proceed?

**Tell me which path you prefer:**
- **"Fresh start"** - I'll create admin tools for Pinecone ingestion (fastest, cleanest)
- **"Migrate data"** - I'll create migration script to preserve existing data (slower)

Either way, you'll have a fully functional Pinecone-based system in **less than 1 hour**! 🚀

---

## 🌟 Benefits You'll Get

✅ **No more Python version issues**
✅ **No more database corruption**
✅ **Faster queries**
✅ **Automatic backups**
✅ **Better scalability**
✅ **Same hybrid search quality** (Pinecone + BM25 + RRF + MMR)

**Ready? Just say the word!** 🎯

