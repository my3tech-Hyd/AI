# 📤 **Multipart File Upload API - Resume Upload**

## **Updated Endpoint: Upload Multiple Resumes**

### **Endpoint:** `POST /api/v1/r-to-j/admin/upload-resume`

Now supports **multiple file uploads** with optional metadata fields, matching the Streamlit admin functionality!

---

## **✅ Features:**

- ✅ **Multiple files** in a single request
- ✅ **Supports**: PDF, DOCX, TXT, RTF, MD
- ✅ **Text extraction** from all formats
- ✅ **Automatic chunking** (600 size, 120 overlap)
- ✅ **Metadata extraction** (name, email, phone)
- ✅ **Pinecone upload** (resumes namespace)
- ✅ **BM25 indexing** for keyword search
- ✅ **Optional form fields** (location, experience, skills)

---

## **📝 Request Format:**

**Content-Type:** `multipart/form-data`

### **Form Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | File[] | ✅ Yes | One or more resume files |
| `location` | String | ❌ No | Candidate location |
| `experience` | String | ❌ No | Years of experience |
| `skills` | String | ❌ No | Key skills (comma-separated) |

---

## **🧪 Testing with cURL:**

### **Single File Upload:**
```bash
curl -X POST http://localhost:8016/api/v1/r-to-j/admin/upload-resume \
  -F "files=@C:/Users/YourName/Documents/resume1.pdf" \
  -F "location=Hyderabad" \
  -F "experience=5 years" \
  -F "skills=Python, Django, AWS"
```

### **Multiple Files Upload:**
```bash
curl -X POST http://localhost:8016/api/v1/r-to-j/admin/upload-resume \
  -F "files=@resume1.pdf" \
  -F "files=@resume2.docx" \
  -F "files=@resume3.txt" \
  -F "location=Hyderabad" \
  -F "skills=Python, Java, React"
```

### **Without Optional Fields:**
```bash
curl -X POST http://localhost:8016/api/v1/r-to-j/admin/upload-resume \
  -F "files=@resume.pdf"
```

---

## **📮 Testing with Postman:**

### **Step 1: Create New Request**
1. Open Postman
2. Create new request: `POST`
3. URL: `http://localhost:8016/api/v1/r-to-j/admin/upload-resume`

### **Step 2: Set Body Type**
1. Go to **Body** tab
2. Select **form-data** (NOT raw JSON!)

### **Step 3: Add Files**
1. Click **Add field**
2. Change type from `Text` to `File`
3. Key: `files`
4. Click **Select Files** and choose one or more resume files
5. To add more files, click **Add field** again with key `files`

### **Step 4: Add Optional Metadata (Optional)**
Add these as `Text` fields:
- Key: `location` | Value: `Hyderabad`
- Key: `experience` | Value: `5 years`
- Key: `skills` | Value: `Python, Django, PostgreSQL`

### **Step 5: Send Request**
Click **Send** button

---

## **✅ Success Response:**

```json
{
  "success": true,
  "message": "Processed 3 files: 3 succeeded, 0 failed",
  "total_files": 3,
  "success_count": 3,
  "fail_count": 0,
  "results": [
    {
      "file_name": "amit_kumar_resume.pdf",
      "success": true,
      "document_id": "resume_a7b3c9f2e1d4a5b6",
      "vectors_created": 5,
      "bm25_updated": true
    },
    {
      "file_name": "priya_sharma_resume.docx",
      "success": true,
      "document_id": "resume_b8c4d0g3f2e5b7c8",
      "vectors_created": 4,
      "bm25_updated": true
    },
    {
      "file_name": "rahul_verma_resume.txt",
      "success": true,
      "document_id": "resume_c9d5e1h4g3f6c8d9",
      "vectors_created": 3,
      "bm25_updated": true
    }
  ],
  "pinecone_namespace": "resumes",
  "timestamp": "2025-12-30T16:30:00.123456"
}
```

---

## **❌ Partial Success Response:**

If some files fail:

```json
{
  "success": true,
  "message": "Processed 3 files: 2 succeeded, 1 failed",
  "total_files": 3,
  "success_count": 2,
  "fail_count": 1,
  "results": [
    {
      "file_name": "good_resume.pdf",
      "success": true,
      "document_id": "resume_abc123",
      "vectors_created": 5,
      "bm25_updated": true
    },
    {
      "file_name": "empty_resume.pdf",
      "success": false,
      "error": "Empty file or text extraction failed"
    },
    {
      "file_name": "another_good_resume.docx",
      "success": true,
      "document_id": "resume_def456",
      "vectors_created": 4,
      "bm25_updated": true
    }
  ],
  "pinecone_namespace": "resumes",
  "timestamp": "2025-12-30T16:30:00.123456"
}
```

---

## **🔍 How It Works:**

### **1. File Processing:**
```
For each uploaded file:
├── Extract text (based on file type)
│   ├── PDF: Use pypdf
│   ├── DOCX: Use python-docx
│   └── TXT/RTF: Direct decode
├── Generate stable document ID (from content hash)
├── Extract metadata (name, email, phone)
└── Merge with form metadata
```

### **2. Chunking:**
```
Resume Text (e.g., 3000 chars)
↓
Chunk 1: [0:600]
Chunk 2: [480:1080]    (120 char overlap)
Chunk 3: [960:1560]
Chunk 4: [1440:2040]
Chunk 5: [1920:2520]
└── Result: 5 chunks
```

### **3. Embedding & Storage:**
```
For each chunk:
├── Generate embedding (Ollama nomic-embed-text)
├── Store in Pinecone (resumes namespace)
│   └── Metadata: name, email, phone, skills, chunk_id, etc.
└── Update BM25 index (for keyword search)
```

---

## **📊 Supported File Types:**

| Format | Extension | Extraction Method |
|--------|-----------|-------------------|
| PDF | `.pdf` | pypdf (PdfReader) |
| Word | `.docx` | python-docx |
| Text | `.txt` | Direct decode |
| RTF | `.rtf` | Direct decode |
| Markdown | `.md` | Direct decode |

---

## **⚠️ Important Notes:**

### **File Size Limits:**
- Default FastAPI limit: **~2MB per file**
- To increase: Add to `api/main.py`:
  ```python
  app.add_middleware(
      HTTPException,
      max_upload_size=10 * 1024 * 1024  # 10MB
  )
  ```

### **Concurrent Processing:**
- Files are processed **sequentially** (not parallel)
- Each file is fully processed before moving to next
- Progress can be tracked via individual result entries

### **Error Handling:**
- If a file fails, others continue processing
- Check `results` array for per-file status
- `success` is `true` if ANY file succeeds

---

## **🔄 Similar Endpoints:**

These endpoints also support multiple file uploads:

| Endpoint | Purpose | Namespace |
|----------|---------|-----------|
| `/api/v1/r-to-p/admin/upload-resume` | Resume → Training | resumes |
| `/api/v1/r-to-a/admin/upload-resume` | Resume → Assistance | resumes |

---

## **🎯 Next Steps:**

### **After Uploading:**
1. **Verify Upload:**
   ```bash
   curl http://localhost:8016/health
   ```
   Should show updated vector counts.

2. **Search Uploaded Resumes:**
   ```bash
   curl -X POST http://localhost:8016/api/v1/r-to-j/search \
     -H "Content-Type: application/json" \
     -d '{
       "candidate_name": "Amit Kumar",
       "skills": "Python, Django",
       "top_k": 10
     }'
   ```

3. **Test in Swagger UI:**
   - Open http://localhost:8016/docs
   - Find `/api/v1/r-to-j/admin/upload-resume`
   - Click "Try it out"
   - Upload files using the UI

---

## **💡 Tips:**

### **For Testing:**
- Start with 1-2 small files
- Verify they appear in search results
- Then upload larger batches

### **For Production:**
- Add authentication (API keys)
- Implement rate limiting
- Add file size validation
- Consider async processing for large files
- Add progress tracking endpoint

### **For Performance:**
- Group related resumes in single request
- Use same metadata for similar profiles
- Monitor Ollama embedding speed
- Check Pinecone quota limits

---

## **✅ Verification:**

After uploading, verify in Pinecone:
```python
from pinecone.grpc import PineconeGRPC as Pinecone

pc = Pinecone(api_key="your-key")
index = pc.Index("pbma")
stats = index.describe_index_stats()

print(f"Resumes namespace: {stats['namespaces']['resumes']['vector_count']} vectors")
```

---

**Your API now matches Streamlit admin functionality!** 🎉

**Test it now:** http://localhost:8016/docs


