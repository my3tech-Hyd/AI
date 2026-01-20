# 🚀 Quick Start Guide

## Current Status

✅ **You already have data!**
- **727 resume vectors** in `j_to_r/chroma_resumes/`
- **99 resume files** in `j_to_r/resumes_store/`
- **BM25 indexes** in `j_to_r/indexes/resumes/`

---

## 🔧 Path Issue (Fixed!)

**Problem:** The ENHANCED file was looking in the wrong directory because of relative paths.

**Solution:** Updated `j_to_r/streamlit_user_jd_to_resume_ENHANCED.py` to use absolute paths relative to the file location.

---

## 🎯 How to Test (Right Now)

### Option 1: Test Enhanced Version (Recommended)

```bash
# From project root
cd "C:\WITS\Wits dev\AI Model"

# Activate venv if not already active
.venv\Scripts\Activate.ps1

# Run the ENHANCED version
streamlit run j_to_r/streamlit_user_jd_to_resume_ENHANCED.py
```

**Expected:** You should now see **727 vectors** in the collection!

---

### Option 2: Test Original Version (Comparison)

```bash
streamlit run j_to_r/streamlit_user_jd_to_resume.py
```

---

## 📊 What to Expect

### Enhanced Version Features:
- ✅ **Hybrid retrieval** (Vector + BM25)
- ✅ **RRF** (Reciprocal Rank Fusion)
- ✅ **MMR** (diversity)
- ✅ **Anti-collapse** re-scoring
- ✅ **Query pooling** for long JDs
- ✅ **RTF noise stripping**
- ✅ **Tech alias normalization** (`.net` → `dotnet`, etc.)
- ✅ **Deleted parent filtering**
- ✅ **5-layer BM25-to-Chroma ID mapping**

### Test Query Example:

**Job Description:**
```
Senior .NET Developer

Requirements:
- 5+ years experience in C# and .NET Framework
- Strong knowledge of ASP.NET MVC
- Experience with SQL Server
- Azure cloud experience preferred
```

**Expected Results:**
- Hybrid search will find resumes with `.NET`, `C#`, `ASP.NET` keywords
- Semantic search will also find related skills (like "dotnet", "csharp")
- Results will be diverse (MMR removes redundancy)
- Match percentages will be distributed (not all 100%)

---

## 🔍 Verify Data Exists

Run this to check your collections:

```bash
python -c "import chromadb; client = chromadb.PersistentClient(path='j_to_r/chroma_resumes'); coll = client.get_collection('resumes'); print(f'✅ Resumes: {coll.count()} vectors'); import pickle; bm25 = pickle.load(open('j_to_r/indexes/resumes/bm25_corpus.pkl', 'rb')); print(f'✅ BM25: {len(bm25)} documents')"
```

**Expected Output:**
```
✅ Resumes: 727 vectors
✅ BM25: 99 documents
```

---

## 🎮 Testing Other Modules

### For p_to_r (Training → Resume):
```bash
streamlit run p_to_r/streamlit_user_training_to_resumes_ENHANCED.py
```
**Uses same resume data** (727 vectors)

### For a_to_r (Assistance → Resume):
```bash
streamlit run a_to_r/streamlit_user_assist_to_resumes_ENHANCED.py
```
**Uses same resume data** (727 vectors)

### For r2j (Resume → Job):
```bash
streamlit run streamlit_user_r2j_ENHANCED.py
```
**Requires job descriptions to be ingested first!** See below.

### For r_to_p (Resume → Training):
```bash
streamlit run r_to_p/streamlit_user_resume_to_training_posts_ENHANCED.py
```
**Requires training posts to be ingested first!** See below.

### For r_to_A (Resume → Assistance):
```bash
streamlit run r_to_A/streamlit_user_resume_to_assist_posts_ENHANCED.py
```
**Requires assistance posts to be ingested first!** See below.

---

## 📥 Ingesting Other Data Types

### If You Need Job Descriptions:
```bash
streamlit run streamlit_admin_jd.py
```
Upload job description files or fill the form to ingest JDs.

### If You Need Training Posts:
```bash
streamlit run r_to_p/streamlit_admin_training_posts.py
```
Fill the form to ingest training center postings.

### If You Need Assistance Posts:
```bash
streamlit run r_to_A/streamlit_admin_assist_posts.py
```
Fill the form to ingest assistance center postings.

---

## 🐛 Troubleshooting

### Issue: "Chroma count: 0 vectors"
**Fix:** Check that you're using the correct path. The ENHANCED files now use absolute paths relative to their location.

### Issue: "BM25 corpus size: 0"
**Fix:** Make sure BM25 indexes exist in the `indexes/` directory. If missing, re-run the admin ingestion tool.

### Issue: "Ollama not responding"
**Fix:** 
```bash
# Check Ollama is running
curl http://localhost:11434

# Pull the embedding model if needed
ollama pull nomic-embed-text
```

### Issue: Import errors
**Fix:**
```bash
# Install missing dependencies
pip install rank-bm25 chromadb numpy requests streamlit pypdf python-docx
```

---

## 📈 Performance Tips

1. **First load is slow** (embedding query) → Expected, subsequent queries use cache
2. **Long job descriptions** (>1000 chars) → Query pooling automatically handles this
3. **Too many results** → Adjust `TOP_K_FINAL` in config
4. **Not diverse enough** → Increase `MMR_LAMBDA` (towards 1.0 for more diversity)
5. **Too keyword-heavy** → Increase `HYBRID_ALPHA` (towards 1.0 for more semantic)

---

## ✅ Success Checklist

After running the ENHANCED version, you should see:
- [ ] Collection count: **727** (or your actual resume count)
- [ ] BM25 corpus size: **99** (or your actual document count)
- [ ] Search returns results with **distributed match percentages** (not all 100%)
- [ ] Results include both semantic and keyword matches
- [ ] No RTF noise in preview text
- [ ] Tech terms are normalized (`.NET` matches work)

---

## 🎉 Next Steps

1. **Test the ENHANCED version** with a real job description
2. **Compare side-by-side** with the original version
3. **Tune parameters** if needed (see `VISUAL_ARCHITECTURE.md` for tuning guide)
4. **Deploy to production** when satisfied (see `MIGRATION_GUIDE.md`)

---

## 📞 Still Having Issues?

Check these files for detailed information:
- **`UNIVERSAL_HYBRID_INTEGRATION_SUMMARY.md`**: Complete feature overview
- **`MIGRATION_GUIDE.md`**: Deployment and troubleshooting
- **`VISUAL_ARCHITECTURE.md`**: Visual diagrams and architecture
- **`INTEGRATION_PLAN.md`**: Original integration plan

Or run the diagnostic:
```bash
python -c "
import chromadb
import pickle
from pathlib import Path

# Check Chroma
client = chromadb.PersistentClient(path='j_to_r/chroma_resumes')
try:
    coll = client.get_collection('resumes')
    print(f'✅ Chroma collection exists: {coll.count()} vectors')
except Exception as e:
    print(f'❌ Chroma issue: {e}')

# Check BM25
try:
    bm25_path = Path('j_to_r/indexes/resumes/bm25_corpus.pkl')
    if bm25_path.exists():
        with open(bm25_path, 'rb') as f:
            bm25_data = pickle.load(f)
        print(f'✅ BM25 index exists: {len(bm25_data)} documents')
    else:
        print(f'❌ BM25 index not found at: {bm25_path}')
except Exception as e:
    print(f'❌ BM25 issue: {e}')

# Check Ollama
import requests
try:
    resp = requests.get('http://localhost:11434', timeout=2)
    print(f'✅ Ollama is running')
except:
    print(f'❌ Ollama not responding at http://localhost:11434')
"
```

Happy matching! 🎯

