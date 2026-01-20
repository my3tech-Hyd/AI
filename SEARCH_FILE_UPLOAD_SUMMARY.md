# ✅ **Search Endpoint Updated - File Upload Enabled!**

## **🎯 Updated:** `POST /api/v1/r-to-j/search`

Now accepts **resume file upload** for job search - matching Streamlit behavior!

---

## **📤 What Changed:**

### **Before (JSON):**
```json
{
  "candidate_name": "John Doe",
  "skills": "Python, Django",
  "summary": "Experienced developer...",
  "top_k": 10
}
```

### **After (Multipart File):**
```
file: resume.pdf (File)
top_k: 10 (Text)
```

---

## **📮 Postman Setup:**

### **Quick Guide:**
1. **Method:** POST
2. **URL:** `http://localhost:8016/api/v1/r-to-j/search`
3. **Body:** form-data (NOT JSON!)
4. **Add Fields:**
   - `file`: Change to **File** type, select resume
   - `top_k`: Keep as **Text**, enter `10`
5. **Send!**

---

## **🧪 Test in Postman:**

### **Minimal Request:**
```
file: [Select resume.pdf]
```

### **With Options:**
```
file: [Select resume.pdf]
top_k: 20
```

---

## **✅ Example Response:**

```json
{
  "success": true,
  "total_results": 10,
  "query_summary": "Resume file: amit_kumar_resume.pdf",
  "results": [
    {
      "rank": 1,
      "score_percentage": "89.0%",
      "title": "Senior Python Developer",
      "company": "TechCorp Inc.",
      "location": "Hyderabad",
      "required_skills": "Python, Django, AWS",
      "salary": "$90K - $130K"
    }
  ],
  "search_metadata": {
    "file_name": "amit_kumar_resume.pdf",
    "algorithm": "Pinecone + BM25 Hybrid"
  }
}
```

---

## **📊 Supported Files:**

- ✅ PDF (`.pdf`)
- ✅ Word (`.docx`)
- ✅ Text (`.txt`)
- ✅ RTF (`.rtf`)
- ✅ Markdown (`.md`)

---

## **🚀 Quick Test:**

### **cURL:**
```bash
curl -X POST http://localhost:8016/api/v1/r-to-j/search \
  -F "file=@resume.pdf" \
  -F "top_k=10"
```

### **Swagger UI:**
```
http://localhost:8016/docs
↓
Find: POST /api/v1/r-to-j/search
↓
Click "Try it out"
↓
Upload file + Set top_k
↓
Execute!
```

---

## **💡 How It Works:**

```
1. Upload resume file
   ↓
2. Extract text (PDF/DOCX/TXT)
   ↓
3. Search jobs namespace
   ↓
4. Hybrid ranking (Semantic + Keyword)
   ↓
5. Return top matches
```

---

## **✅ Server Status:**

- ✅ Server: Running on port 8016
- ✅ Health: All services connected
- ✅ Endpoint: Updated and ready
- ✅ Auto-reload: Active

---

## **📚 Full Documentation:**

See `API_SEARCH_MULTIPART.md` for:
- Complete Postman guide
- cURL examples
- Error handling
- Advanced usage

---

**Test Now:** http://localhost:8016/docs

**Look for:** `POST /api/v1/r-to-j/search` → Upload resume file! 🚀


