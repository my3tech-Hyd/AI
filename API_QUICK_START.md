# ðŸš€ **FastAPI Quick Start Guide**

## **Complete Setup in 5 Minutes!**

---

## **âœ… Prerequisites**

1. **Python 3.10+** installed
2. **Ollama** running on `http://localhost:11434`
3. **Pinecone account** with API key configured
4. **OpenAI API key** (for generative analysis)

---

## **ðŸ“¦ Step 1: Install Dependencies**

```powershell
cd "C:\WITS\Wits dev\AI Model"
.venv\Scripts\Activate.ps1

# Install FastAPI requirements
pip install -r api/requirements.txt
```

---

## **ðŸ” Step 2: Set Environment Variables**

Ensure these are set in your system or `.env` file:

```bash
# Pinecone
PINECONE_API_KEY=pcsk_7TvfPn_52xGELDhnEHEFH5ZCjFJi2grwG6zuWkLYUgW7ccVe4Juu9qxCGh6qZVfNLns8T6
PINECONE_ENVIRONMENT=us-east-1

# OpenAI (for generative analysis)
OPENAI_API_KEY=sk-<REDACTED>

# Ollama
OLLAMA_HOST=http://localhost:11434
```

---

## **ðŸŽ¯ Step 3: Verify Pinecone Index**

Make sure the `pbma` index exists with all namespaces:

```powershell
python setup_pinecone_namespace.py
```

Expected output:
```
âœ… Index 'pbma' exists
âœ… Namespaces configured: resumes, jobs, training, assistance
```

---

## **ðŸš€ Step 4: Start the API Server**

```powershell
cd "C:\WITS\Wits dev\AI Model"
.venv\Scripts\Activate.ps1

# Start FastAPI with auto-reload
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

---

## **ðŸŒ Step 5: Access API Documentation**

Open your browser:

1. **Interactive Docs (Swagger UI):**
   ```
   http://localhost:8000/docs
   ```

2. **Alternative Docs (ReDoc):**
   ```
   http://localhost:8000/redoc
   ```

3. **Health Check:**
   ```
   http://localhost:8000/health
   ```

---

## **ðŸ“Š Step 6: Test with Postman**

### **Import Postman Collection:**

1. Open Postman
2. Click **Import**
3. Copy the JSON from `API_POSTMAN_DOCUMENTATION.md`
4. Paste and import

### **Set Environment Variable:**

- Create environment: `AI Matching API`
- Add variable: `base_url` = `http://localhost:8000`

### **Test Endpoints:**

1. **Health Check:**
   ```
   GET http://localhost:8000/health
   ```

2. **Upload JD (Admin):**
   ```
   POST http://localhost:8000/api/v1/j-to-r/admin/upload-jd
   ```

3. **Search Resumes (User):**
   ```
   POST http://localhost:8000/api/v1/j-to-r/search
   ```

4. **Analyze Match (Generative):**
   ```
   POST http://localhost:8000/api/v1/j-to-r/analyze
   ```

---

## **ðŸ“ API Structure Overview**

```
api/
â”œâ”€â”€ main.py                    # FastAPI app + routers
â”œâ”€â”€ models.py                  # Pydantic models
â”œâ”€â”€ requirements.txt           # Dependencies
â”‚
â”œâ”€â”€ routers/
â”‚   â”œâ”€â”€ j_to_r_router.py      # Job â†’ Resume (3 endpoints)
â”‚   â”œâ”€â”€ r_to_j_router.py      # Resume â†’ Job (3 endpoints)
â”‚   â”œâ”€â”€ p_to_r_router.py      # Training â†’ Resume (3 endpoints)
â”‚   â”œâ”€â”€ r_to_p_router.py      # Resume â†’ Training (3 endpoints)
â”‚   â”œâ”€â”€ a_to_r_router.py      # Assistance â†’ Resume (3 endpoints)
â”‚   â””â”€â”€ r_to_a_router.py      # Resume â†’ Assistance (3 endpoints)
â”‚
â””â”€â”€ services/
    â”œâ”€â”€ upload_service.py      # Document upload/indexing
    â”œâ”€â”€ search_service.py      # Hybrid search logic
    â””â”€â”€ analyze_service.py     # AI analysis logic
```

---

## **ðŸ§ª Testing Example (cURL)**

### **1. Health Check:**
```bash
curl http://localhost:8000/health
```

### **2. Upload Job Description:**
```bash
curl -X POST http://localhost:8000/api/v1/j-to-r/admin/upload-jd \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Python Developer",
    "company": "TechCorp",
    "location": "Hyderabad",
    "description": "We need a Python expert with Django and AWS experience",
    "required_skills": "Python, Django, AWS"
  }'
```

### **3. Search for Matching Resumes:**
```bash
curl -X POST http://localhost:8000/api/v1/j-to-r/search \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Python Developer",
    "description": "We need a Python expert",
    "required_skills": "Python, Django",
    "top_k": 10
  }'
```

---

## **ðŸ” All 18 Endpoints**

| Module | Endpoint | Description |
|--------|----------|-------------|
| **j_to_r** | `POST /api/v1/j-to-r/admin/upload-jd` | Upload job description |
| **j_to_r** | `POST /api/v1/j-to-r/search` | Find matching resumes |
| **j_to_r** | `POST /api/v1/j-to-r/analyze` | AI analysis |
| **r_to_j** | `POST /api/v1/r-to-j/admin/upload-resume` | Upload resume |
| **r_to_j** | `POST /api/v1/r-to-j/search` | Find matching jobs |
| **r_to_j** | `POST /api/v1/r-to-j/analyze` | AI analysis |
| **p_to_r** | `POST /api/v1/p-to-r/admin/upload-training` | Upload training program |
| **p_to_r** | `POST /api/v1/p-to-r/search` | Find matching resumes |
| **p_to_r** | `POST /api/v1/p-to-r/analyze` | AI analysis |
| **r_to_p** | `POST /api/v1/r-to-p/admin/upload-resume` | Upload resume |
| **r_to_p** | `POST /api/v1/r-to-p/search` | Find matching training |
| **r_to_p** | `POST /api/v1/r-to-p/analyze` | AI analysis |
| **a_to_r** | `POST /api/v1/a-to-r/admin/upload-assistance` | Upload assistance center |
| **a_to_r** | `POST /api/v1/a-to-r/search` | Find matching resumes |
| **a_to_r** | `POST /api/v1/a-to-r/analyze` | AI analysis |
| **r_to_a** | `POST /api/v1/r-to-a/admin/upload-resume` | Upload resume |
| **r_to_a** | `POST /api/v1/r-to-a/search` | Find matching assistance |
| **r_to_a** | `POST /api/v1/r-to-a/analyze` | AI analysis |

---

## **ðŸ› ï¸ Troubleshooting**

### **Problem: "ModuleNotFoundError: No module named 'api'"**

**Solution:**
```powershell
# Make sure you're in the project root
cd "C:\WITS\Wits dev\AI Model"

# Add project root to PYTHONPATH
$env:PYTHONPATH="C:\WITS\Wits dev\AI Model"

# Start server
uvicorn api.main:app --reload
```

---

### **Problem: "Pinecone connection failed"**

**Solution:**
```powershell
# Verify API key
echo $env:PINECONE_API_KEY

# Test Pinecone connection
python -c "from pinecone.grpc import PineconeGRPC as Pinecone; pc = Pinecone(api_key='your-key'); print(pc.list_indexes())"
```

---

### **Problem: "Ollama not responding"**

**Solution:**
```powershell
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama if not running
ollama serve
```

---

### **Problem: "BM25 index not found"**

**Solution:**
```powershell
# BM25 indexes are created automatically on first upload
# Or manually create them by running admin Streamlit apps first
streamlit run j_to_r/streamlit_admin_resumes_PINECONE.py
```

---

## **ðŸ“Š Expected Behavior**

### **Successful API Start:**
```
INFO:     Will watch for changes in these directories: ['C:\\WITS\\Wits dev\\AI Model']
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using WatchFiles
INFO:     Started server process [67890]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### **Successful Health Check:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-30T10:45:00.123456",
  "services": {
    "pinecone": "connected",
    "ollama": "connected",
    "bm25": "loaded"
  }
}
```

---

## **ðŸŽ¯ Next Steps**

1. âœ… API is running
2. âœ… Test all 18 endpoints
3. âœ… Upload sample data (JDs, resumes, training, assistance)
4. âœ… Perform searches
5. âœ… Test AI analysis
6. ðŸš€ Deploy to production!

---

## **ðŸ“š Additional Resources**

- **Full API Documentation:** `API_POSTMAN_DOCUMENTATION.md`
- **Architecture Overview:** `API_ARCHITECTURE.md`
- **Postman Collection:** See Postman section above
- **FastAPI Docs:** http://localhost:8000/docs

---

## **ðŸŽ‰ You're Ready!**

Your FastAPI application is now running with:
- âœ… 18 API endpoints
- âœ… Pinecone hybrid search
- âœ… BM25 keyword matching
- âœ… AI-powered analysis
- âœ… Same accuracy as Streamlit apps

**Happy coding!** ðŸš€


