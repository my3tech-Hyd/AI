# 🚀 FastAPI Architecture - Complete System

## 📋 **Overview**

**Total Endpoints:** 18 (6 modules × 3 endpoints each)

**Technology Stack:**
- **FastAPI** - Web framework
- **Pinecone** - Vector database (semantic search)
- **BM25** - Keyword search (local)
- **Ollama** - Embeddings (nomic-embed-text)
- **OpenAI GPT-4o-mini** - Generative AI analysis

---

## 🏗️ **Module Structure**

### **Each Module Has 3 Endpoints:**

1. **`/admin`** - Upload/Ingest Data
   - Uploads documents (resumes, jobs, training, assistance)
   - Creates embeddings via Ollama
   - Stores in Pinecone (vector) + BM25 (keyword)
   - Returns document ID and confirmation

2. **`/search`** - Search & Retrieve Matches
   - Takes query (JD, resume, training, assistance details)
   - Performs hybrid search (Pinecone + BM25)
   - Returns ranked matches with scores
   - Same accuracy as Streamlit apps

3. **`/analyze`** - AI-Generated Analysis
   - Takes a search result
   - Uses OpenAI GPT-4o-mini for deep analysis
   - Returns fit score, strengths, gaps, recommendations
   - Detailed explanations

---

## 📊 **6 Modules**

### **1. j_to_r (Job → Resume)**
- **Upload:** Job descriptions → `jobs` namespace
- **Search:** Job description → Find matching resumes
- **Analyze:** Explain why resume matches JD

**Base Path:** `/api/v1/j-to-r/`

**Endpoints:**
- `POST /api/v1/j-to-r/admin/upload-jd`
- `POST /api/v1/j-to-r/search`
- `POST /api/v1/j-to-r/analyze`

---

### **2. r_to_j (Resume → Job)**
- **Upload:** Resumes → `resumes` namespace
- **Search:** Resume details → Find matching jobs
- **Analyze:** Explain why job matches resume

**Base Path:** `/api/v1/r-to-j/`

**Endpoints:**
- `POST /api/v1/r-to-j/admin/upload-resume`
- `POST /api/v1/r-to-j/search`
- `POST /api/v1/r-to-j/analyze`

---

### **3. p_to_r (Training → Resume)**
- **Upload:** Training programs → `training` namespace
- **Search:** Training program details → Find matching candidates
- **Analyze:** Explain why candidate fits training program

**Base Path:** `/api/v1/p-to-r/`

**Endpoints:**
- `POST /api/v1/p-to-r/admin/upload-training`
- `POST /api/v1/p-to-r/search`
- `POST /api/v1/p-to-r/analyze`

---

### **4. r_to_p (Resume → Training)**
- **Upload:** Resumes → `resumes` namespace
- **Search:** Resume details → Find matching training programs
- **Analyze:** Explain why training program matches candidate

**Base Path:** `/api/v1/r-to-p/`

**Endpoints:**
- `POST /api/v1/r-to-p/admin/upload-resume`
- `POST /api/v1/r-to-p/search`
- `POST /api/v1/r-to-p/analyze`

---

### **5. a_to_r (Assistance → Resume)**
- **Upload:** Assistance centers → `assistance` namespace
- **Search:** Assistance center details → Find matching candidates
- **Analyze:** Explain why candidate needs assistance services

**Base Path:** `/api/v1/a-to-r/`

**Endpoints:**
- `POST /api/v1/a-to-r/admin/upload-assistance`
- `POST /api/v1/a-to-r/search`
- `POST /api/v1/a-to-r/analyze`

---

### **6. r_to_a (Resume → Assistance)**
- **Upload:** Resumes → `resumes` namespace
- **Search:** Resume details → Find matching assistance centers
- **Analyze:** Explain why assistance center matches candidate

**Base Path:** `/api/v1/r-to-a/`

**Endpoints:**
- `POST /api/v1/r-to-a/admin/upload-resume`
- `POST /api/v1/r-to-a/search`
- `POST /api/v1/r-to-a/analyze`

---

## 🔄 **Data Flow**

### **Admin Endpoint (Upload):**
```
1. Client sends request with data (JSON)
   ↓
2. FastAPI validates with Pydantic models
   ↓
3. Extract/process document text
   ↓
4. Generate embeddings via Ollama
   ↓
5. Chunk text (for resumes)
   ↓
6. Store in Pinecone (with metadata)
   ↓
7. Update BM25 index (local)
   ↓
8. Return success + document ID
```

### **Search Endpoint:**
```
1. Client sends search query (JSON)
   ↓
2. FastAPI validates request
   ↓
3. Compose query text from fields
   ↓
4. Initialize PineconeHybridRetriever
   ↓
5. Perform hybrid search:
   - Semantic search (Pinecone)
   - Keyword search (BM25)
   - Score fusion (RRF)
   ↓
6. Aggregate chunks → parent documents
   ↓
7. Extract metadata
   ↓
8. Format results
   ↓
9. Return ranked matches
```

### **Analyze Endpoint:**
```
1. Client sends query + result ID
   ↓
2. Fetch match details from Pinecone
   ↓
3. Compose prompt for GPT-4o-mini
   ↓
4. Call OpenAI API
   ↓
5. Parse AI response
   ↓
6. Structure analysis:
   - Fit score (0-100)
   - Strengths
   - Gaps
   - Recommendations
   ↓
7. Return analysis
```

---

## 📁 **File Structure**

```
api/
├── __init__.py
├── main.py                    # FastAPI app + routers
├── models.py                  # Pydantic request/response models
├── utils.py                   # Shared utilities
│
├── routers/
│   ├── __init__.py
│   ├── j_to_r_router.py      # Job → Resume (3 endpoints)
│   ├── r_to_j_router.py      # Resume → Job (3 endpoints)
│   ├── p_to_r_router.py      # Training → Resume (3 endpoints)
│   ├── r_to_p_router.py      # Resume → Training (3 endpoints)
│   ├── a_to_r_router.py      # Assistance → Resume (3 endpoints)
│   └── r_to_a_router.py      # Resume → Assistance (3 endpoints)
│
└── services/
    ├── __init__.py
    ├── upload_service.py      # Document upload/processing
    ├── search_service.py      # Hybrid search logic
    └── analyze_service.py     # AI analysis logic
```

---

## 🔐 **Authentication (Future)**

Currently: Open API (no auth)

**Planned:**
- API Key authentication
- Rate limiting
- Usage tracking
- User management

---

## 📊 **Response Format**

### **Success Response:**
```json
{
  "success": true,
  "data": { ... },
  "timestamp": "2025-01-30T10:30:00Z"
}
```

### **Error Response:**
```json
{
  "error": "Error message",
  "detail": "Detailed error info",
  "timestamp": "2025-01-30T10:30:00Z"
}
```

---

## 🚀 **Running the API**

### **Development:**
```bash
cd "C:\WITS\Wits dev\AI Model"
.venv\Scripts\Activate.ps1
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### **Access:**
- **API Docs:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Health Check:** http://localhost:8000/health

---

## 📝 **Testing**

### **Postman Collection:**
Import the provided Postman collection JSON file.

### **Example cURL:**
```bash
# Health check
curl http://localhost:8000/health

# Upload JD
curl -X POST http://localhost:8000/api/v1/j-to-r/admin/upload-jd \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Python Developer",
    "description": "We need a Python expert...",
    "required_skills": "Python, Django"
  }'

# Search resumes
curl -X POST http://localhost:8000/api/v1/j-to-r/search \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Python Developer",
    "description": "We need a Python expert...",
    "top_k": 10
  }'
```

---

## ✅ **API Matches Streamlit Accuracy**

All endpoints use the **EXACT SAME** backend logic as Streamlit apps:
- Same `PineconeHybridRetriever`
- Same `pinecone_config.py`
- Same hybrid search algorithm
- Same scoring/ranking logic

**Result:** API accuracy = Streamlit accuracy! ✅

---

## 🎯 **Next Steps**

1. ✅ Create all router files
2. ✅ Create service layer files
3. ✅ Create Postman documentation
4. ✅ Test all endpoints
5. Deploy to production

---

**Total: 18 API Endpoints Ready for Production!** 🚀

