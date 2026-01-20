# 🐛 Ranking Bug Debug Guide

## Problem Report

**User Issue:** "For any Training Posting it is giving same ranking list"

This means the search results are **identical** regardless of what training posting query is entered.

---

## 🔍 Possible Causes

### **1. BM25 Not Loaded (Most Likely)**
- **Symptom:** Keyword scores = 0.0%
- **Cause:** BM25 index doesn't exist or is empty
- **Result:** Only semantic search is used
- **Impact:** If all queries generate similar embeddings, rankings will be nearly identical

### **2. Query Not Changing**
- **Symptom:** Same query text being used every time
- **Cause:** Streamlit form not submitting properly
- **Result:** Same search every time

### **3. Embedding Not Changing**
- **Symptom:** Ollama returning same embedding for different queries
- **Cause:** Ollama connection issue or caching
- **Result:** Same semantic scores every time

### **4. Retriever Config Caching**
- **Symptom:** Config changes not applied
- **Cause:** Streamlit cache not clearing
- **Result:** Old search parameters used

---

## ✅ Debug Steps Added

### **Step 1: Check Query Text**
A new expandable section shows:
```
🔍 Query Being Searched (Debug)
- Full query text
- Query length
- Embedding vector preview
- Embedding fingerprint (sum of values)
```

**What to check:**
- Is the query text different each time?
- Is the embedding fingerprint changing?
- Are the first 5 embedding values different?

---

### **Step 2: Check BM25 Status**
Sidebar now shows:
```
✅ BM25 loaded (694 documents)
OR
⚠️ BM25 not loaded - only semantic search active!
```

**What to check:**
- Is BM25 loaded?
- Does the document count match your resume count?

---

### **Step 3: Check Score Distribution**
After search, an expandable panel shows:
```
📊 Score Distribution (Debug)
- Avg Match: 72.5%
- Avg Semantic: 68.3%
- Avg Keyword: 0.0%
- Score range: 45.2% - 95.8%
```

**What to check:**
- Is Avg Keyword = 0.0%? (BM25 not working)
- Is score range narrow? (All results similar)
- Do scores change between different queries?

---

## 🔧 Troubleshooting

### **If BM25 Not Loaded:**

**Problem:** BM25 index missing or empty

**Solution 1: Build BM25 Index**
The BM25 index should be created automatically when uploading resumes via admin tool, but might be missing.

**Check if BM25 files exist:**
```powershell
ls indexes/resumes/
```

Expected files:
- `bm25_corpus.pkl`
- `bm25_doc_ids.pkl`
- `bm25_meta.pkl`

**Solution 2: Re-upload Resumes**
```powershell
streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py
```
Re-upload a few resumes to rebuild the BM25 index.

---

### **If Embedding Not Changing:**

**Problem:** Same embedding fingerprint for different queries

**Solution 1: Check Ollama**
```powershell
# Test Ollama directly
curl http://localhost:11434/api/embeddings -d '{
  "model": "nomic-embed-text",
  "prompt": "Python developer with 5 years experience"
}'
```

**Solution 2: Restart Ollama**
```powershell
# Stop Ollama
taskkill /F /IM ollama.exe

# Start Ollama
ollama serve
```

**Solution 3: Clear Streamlit Cache**
In the app, press `C` to clear cache, then re-run the query.

---

### **If Query Not Changing:**

**Problem:** Form not submitting or using cached query

**Solution: Hard Refresh**
1. Press `Ctrl+Shift+R` (Windows) or `Cmd+Shift+R` (Mac)
2. Clear Streamlit cache (press `C` in the app)
3. Try again with a completely different query

---

## 🧪 Testing Process

### **Test 1: Different Queries Should Give Different Rankings**

**Query A:**
```
Training Center: Python Bootcamp
Courses: Python, Django, Flask
```

**Query B:**
```
Training Center: Java Academy
Courses: Java, Spring Boot, Microservices
```

**Expected:** Different top matches (Python devs vs Java devs)

**If same:** Bug confirmed - check debug panels

---

### **Test 2: Check Embedding Fingerprint**

Run Query A, note the embedding fingerprint from debug panel:
```
Embedding sum (fingerprint): 123.4567
```

Run Query B, check if fingerprint is different:
```
Embedding sum (fingerprint): 98.7654
```

**If same:** Ollama embedding issue
**If different:** BM25 or scoring issue

---

### **Test 3: Check BM25 Contribution**

Look at results:
```
Keyword: 0.0%  ← BM25 not working
Keyword: 45.3% ← BM25 working
```

**If all 0.0%:** BM25 index missing/empty
**If varying:** BM25 working, but semantic search dominant

---

## 🎯 Quick Fixes

### **Fix 1: Rebuild BM25 (Most Common)**
```powershell
cd "C:\WITS\Wits dev\AI Model"
.venv\Scripts\Activate.ps1

# Re-upload resumes to rebuild BM25
streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py
```

### **Fix 2: Increase BM25 Weight**
In sidebar, adjust "Hybrid Balance" slider:
- Move towards 0 (more keyword/BM25)
- Default is 0.5 (50/50)
- Try 0.3 for more keyword influence

### **Fix 3: Restart Everything**
```powershell
# Kill Streamlit
Ctrl+C

# Restart Ollama
taskkill /F /IM ollama.exe
ollama serve

# Restart Streamlit
streamlit run p_to_r/streamlit_user_training_to_resumes_PINECONE.py
```

---

## 📊 What Debug Output Tells You

### **Scenario 1: BM25 Not Working**
```
⚠️ BM25 not loaded - only semantic search active!
Keyword: 0.0%
Keyword: 0.0%
Keyword: 0.0%
```
**Fix:** Rebuild BM25 index by re-uploading resumes

### **Scenario 2: All Similar Results**
```
Score range: 68.2% - 72.5%  (narrow range)
Avg Semantic: 70.1%
Avg Keyword: 0.0%
```
**Fix:** BM25 needed for differentiation + more diverse resumes

### **Scenario 3: Same Embeddings**
```
Query A fingerprint: 123.4567
Query B fingerprint: 123.4567  (identical!)
```
**Fix:** Ollama issue - restart Ollama

### **Scenario 4: Working Correctly**
```
✅ BM25 loaded (694 documents)
Score range: 45.2% - 95.8%  (wide range)
Avg Semantic: 68.3%
Avg Keyword: 42.7%  (BM25 contributing!)

Query A fingerprint: 123.4567
Query B fingerprint: 98.7654  (different!)
```
**Result:** System working correctly!

---

## 📝 Next Steps

1. **Run the tool** with debug panels open
2. **Compare** embeddings between different queries
3. **Check** if BM25 is loaded
4. **Note** the keyword scores
5. **Report back** with debug panel screenshots

This will help diagnose the exact issue! 🔍

