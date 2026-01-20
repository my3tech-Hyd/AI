# 🔍 **Search with Resume File Upload**

## **Updated Endpoint: Search Jobs with Resume File**

### **Endpoint:** `POST /api/v1/r-to-j/search`

Now supports **resume file upload** for job search - just like Streamlit!

---

## **✅ How It Works:**

1. Upload your resume file (PDF, DOCX, TXT, RTF)
2. API extracts text from the file
3. Performs hybrid search (Pinecone + BM25)
4. Returns matching jobs ranked by relevance

---

## **📝 Request Format:**

**Content-Type:** `multipart/form-data`

### **Form Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | ✅ Yes | Resume file (PDF, DOCX, TXT, RTF) |
| `top_k` | Text/Number | ❌ No | Number of results (default: 10) |

---

## **📮 Postman Setup:**

### **Step 1: Create Request**
- Method: **POST**
- URL: `http://localhost:8016/api/v1/r-to-j/search`

### **Step 2: Configure Body**
1. Go to **Body** tab
2. Select **form-data**

### **Step 3: Add Fields**

```
┌──────────┬───────┬──────────────────────┐
│ KEY      │ TYPE  │ VALUE                │
├──────────┼───────┼──────────────────────┤
│ file     │ File  │ [Select Resume]      │
│ top_k    │ Text  │ 10                   │
└──────────┴───────┴──────────────────────┘
```

**Important:** 
- `file`: Change type to **File**, then click "Select Files"
- `top_k`: Keep as **Text**, enter a number (e.g., 10)

### **Step 4: Send Request**
Click **Send** button

---

## **✅ Success Response:**

```json
{
  "success": true,
  "total_results": 10,
  "query_summary": "Resume file: amit_kumar_resume.pdf",
  "results": [
    {
      "rank": 1,
      "score": 0.89,
      "score_percentage": "89.0%",
      "semantic_score": 0.85,
      "keyword_score": 0.23,
      "title": "Senior Python Developer",
      "company": "TechCorp Inc.",
      "location": "Hyderabad",
      "required_skills": "Python, Django, AWS, PostgreSQL",
      "experience": "5+ years",
      "salary": "$90K - $130K",
      "job_type": "Full-time",
      "url": "https://example.com/jobs/123",
      "text_preview": "We are seeking a Senior Python Developer..."
    },
    {
      "rank": 2,
      "score": 0.85,
      "score_percentage": "85.0%",
      "title": "Lead Backend Engineer",
      "company": "StartupXYZ",
      "location": "Remote",
      "required_skills": "Python, Flask, Docker, Kubernetes",
      "experience": "4-7 years",
      "salary": "$100K - $140K",
      "job_type": "Full-time",
      "text_preview": "Join our fast-growing startup..."
    }
  ],
  "search_metadata": {
    "query_type": "resume_to_jd",
    "corpus": "jobs",
    "namespace": "jobs",
    "algorithm": "Pinecone + BM25 Hybrid",
    "top_k": 10,
    "file_name": "amit_kumar_resume.pdf"
  },
  "timestamp": "2025-12-30T17:30:00.123456"
}
```

---

## **🧪 Testing with cURL:**

### **Basic Search:**
```bash
curl -X POST http://localhost:8016/api/v1/r-to-j/search \
  -F "file=@resume.pdf"
```

### **With Custom Result Count:**
```bash
curl -X POST http://localhost:8016/api/v1/r-to-j/search \
  -F "file=@amit_kumar_resume.pdf" \
  -F "top_k=20"
```

### **Different File Types:**
```bash
# PDF
curl -X POST http://localhost:8016/api/v1/r-to-j/search -F "file=@resume.pdf"

# DOCX
curl -X POST http://localhost:8016/api/v1/r-to-j/search -F "file=@resume.docx"

# TXT
curl -X POST http://localhost:8016/api/v1/r-to-j/search -F "file=@resume.txt"
```

---

## **📊 Supported File Types:**

| Format | Extension | Extraction |
|--------|-----------|------------|
| PDF | `.pdf` | pypdf |
| Word | `.docx` | python-docx |
| Text | `.txt` | Direct |
| RTF | `.rtf` | Direct |
| Markdown | `.md` | Direct |

---

## **🔍 Search Flow:**

```
1. User uploads resume file
   ↓
2. API extracts text from file
   ↓
3. Text is used as search query
   ↓
4. Hybrid search (Pinecone + BM25)
   ├── Semantic search: Find jobs with similar meaning
   └── Keyword search: Find jobs with matching skills
   ↓
5. Score fusion (RRF)
   ↓
6. Results ranked by relevance
   ↓
7. Return top K matches
```

---

## **⚙️ Parameters:**

### **`file` (Required)**
- **Type:** File upload
- **Formats:** PDF, DOCX, TXT, RTF, MD
- **Max size:** Default ~2MB (configurable)
- **Description:** Resume file to search with

### **`top_k` (Optional)**
- **Type:** Integer
- **Default:** 10
- **Range:** 1-100
- **Description:** Number of job results to return

---

## **🎯 Use Cases:**

### **1. Job Seeker:**
Upload your resume → Get personalized job matches

### **2. Recruiter:**
Upload candidate resume → Find suitable open positions

### **3. Career Counselor:**
Upload client resume → Explore job opportunities

### **4. Batch Processing:**
```bash
for resume in *.pdf; do
    curl -X POST http://localhost:8016/api/v1/r-to-j/search \
      -F "file=@$resume" \
      -F "top_k=5" \
      > "${resume%.pdf}_jobs.json"
done
```

---

## **🔄 Comparison: Old vs New**

### **❌ Old (JSON-based):**
```json
POST /api/v1/r-to-j/search
Content-Type: application/json

{
  "candidate_name": "Amit Kumar",
  "skills": "Python, Django",
  "summary": "...",
  "top_k": 10
}
```
**Problem:** User has to manually type resume details

### **✅ New (File-based):**
```
POST /api/v1/r-to-j/search
Content-Type: multipart/form-data

file: resume.pdf
top_k: 10
```
**Benefit:** Just upload the resume file!

---

## **💡 Pro Tips:**

### **1. File Preparation:**
- Use clean, well-formatted resumes
- Include skills, experience, education
- PDF or DOCX work best

### **2. Result Optimization:**
- Start with `top_k=10`
- Increase if you need more options
- Max `top_k=50` recommended

### **3. File Size:**
- Keep resumes under 2MB
- Multi-page resumes are fine
- Text is extracted from all pages

### **4. Testing:**
```bash
# Quick test
curl -X POST http://localhost:8016/api/v1/r-to-j/search \
  -F "file=@resume.pdf" | jq '.results[0]'
```

---

## **⚠️ Error Handling:**

### **400 Bad Request**
```json
{
  "detail": "Empty file or text extraction failed"
}
```
**Solution:** Check file is valid and not corrupted

### **500 Internal Server Error**
```json
{
  "detail": "Search failed: ..."
}
```
**Solution:** Check server logs, verify Pinecone/BM25 are working

---

## **🎨 Postman Visual Guide:**

```
┌─────────────────────────────────────────────────────┐
│ POST http://localhost:8016/api/v1/r-to-j/search    │
├─────────────────────────────────────────────────────┤
│ Body                                                 │
├─────────────────────────────────────────────────────┤
│ ○ none  ● form-data  ○ raw  ○ binary               │
├─────────────────────────────────────────────────────┤
│ KEY      TYPE    VALUE                              │
├─────────────────────────────────────────────────────┤
│ file     File ▼  [resume.pdf] ✓                     │
│ top_k    Text ▼  10                                 │
└─────────────────────────────────────────────────────┘
                    ▼
              [ Send ] Button
                    ▼
┌─────────────────────────────────────────────────────┐
│ Status: 200 OK    Time: 1.8s    Size: 8.2 KB       │
├─────────────────────────────────────────────────────┤
│ Body   Headers   Test Results                       │
├─────────────────────────────────────────────────────┤
│ {                                                    │
│   "success": true,                                   │
│   "total_results": 10,                               │
│   "results": [...]                                   │
│ }                                                    │
└─────────────────────────────────────────────────────┘
```

---

## **✅ Server Auto-Reload:**

The API server will auto-reload with the new changes!

Check terminal for:
```
WARNING:  WatchFiles detected changes in 'api\routers\r_to_j_router.py'. Reloading...
INFO:     Application startup complete.
```

---

## **🚀 Ready to Test!**

### **Option 1: Swagger UI**
http://localhost:8016/docs
- Find: `POST /api/v1/r-to-j/search`
- Click "Try it out"
- Upload resume file
- Click "Execute"

### **Option 2: Postman**
- Set method: POST
- URL: `http://localhost:8016/api/v1/r-to-j/search`
- Body → form-data
- Add `file` (File type) and `top_k` (Text type)
- Send!

### **Option 3: cURL**
```bash
curl -X POST http://localhost:8016/api/v1/r-to-j/search \
  -F "file=@your_resume.pdf" \
  -F "top_k=10"
```

---

**Your search endpoint now matches the Streamlit user experience!** 🎉

**Test at:** http://localhost:8016/docs


