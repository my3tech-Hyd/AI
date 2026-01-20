# API Guide

## Base
- **Framework**: FastAPI
- **Interactive docs**: `GET /docs` (Swagger), `GET /redoc`
- **Base prefixes**:
  - Module APIs: `/api/v1/...`
  - Utility APIs: `/`, `/health`, `/api/v1/info`

---

## Utility Endpoints

### `GET /`
**Request body**: none

**Response body**
```json
{
  "message": "AI Matching System API",
  "version": "1.0.0",
  "status": "operational",
  "timestamp": "ISO-8601 string",
  "docs": "/docs",
  "modules": ["..."],
  "endpoints_per_module": {
    "admin": "Upload/ingest data",
    "search": "Search and retrieve matches",
    "analyze": "Get AI-generated analysis"
  }
}
```

### `GET /health`
**Request body**: none

**Response body**
```json
{
  "status": "healthy",
  "timestamp": "ISO-8601 string",
  "services": {
    "pinecone": "connected",
    "ollama": "connected",
    "bm25": "loaded"
  }
}
```

### `GET /api/v1/info`
**Request body**: none

**Response body** (high level)
```json
{
  "api_name": "AI Matching System",
  "version": "1.0.0",
  "description": "...",
  "total_endpoints": 18,
  "modules": { "j_to_r": { "description": "...", "endpoints": ["..."] } },
  "technology_stack": { "framework": "FastAPI", "vector_db": "Pinecone", "keyword_search": "BM25" }
}
```

---

## Shared Schemas

### Upload Response (`UploadResponse`)
```json
{
  "success": true,
  "message": "string",
  "document_id": "string",
  "vectors_created": 1,
  "pinecone_namespace": "resumes|jobs|training|assistance",
  "bm25_updated": true,
  "timestamp": "ISO-8601 string"
}
```

### Search Response (`SearchResponse`)
```json
{
  "success": true,
  "total_results": 10,
  "query_summary": "string",
  "results": [
    {
      "rank": 1,
      "score": 0.82,
      "score_percentage": "82.0%",
      "semantic_score": 0.7,
      "keyword_score": 0.9,
      "name": "optional (resumes)",
      "title": "optional (jobs)",
      "company": "optional (jobs)",
      "center_name": "optional (training/assistance)",
      "services": "optional (assistance)",
      "courses": "optional (training)",
      "text_preview": "optional",
      "metadata": {}
    }
  ],
  "search_metadata": {},
  "timestamp": "ISO-8601 string"
}
```

### Analyze Response (`analysis` object returned by all `/analyze` endpoints)
```json
{
  "fit_score": 75,
  "summary": "string",
  "strengths": ["string"],
  "gaps": ["string"],
  "recommendations": ["string"],
  "detailed_analysis": "string (markdown)"
}
```

---

## Module: Job -> Resumes (`j_to_r`)

### `POST /api/v1/j-to-r/admin/upload-jd`
**Request body** (`application/json`)
```json
{
  "title": "string",
  "company": "string (optional)",
  "location": "string (optional)",
  "description": "string",
  "required_skills": "string (optional, comma-separated)",
  "experience": "string (optional)",
  "salary": "string (optional)",
  "job_type": "string (optional)",
  "url": "string (optional)"
}
```

**Response body**: `UploadResponse`

### `POST /api/v1/j-to-r/search`
**Request body** (`application/json`)
```json
{
  "title": "string",
  "company": "string (optional)",
  "location": "string (optional)",
  "description": "string",
  "required_skills": "string (optional)",
  "top_k": 10
}
```

**Response body**: `SearchResponse` (results are resumes)

### `POST /api/v1/j-to-r/analyze`
**Request body** (`multipart/form-data`)
- `resume_file` (file, required): PDF/DOCX/TXT/RTF
- Job fields (form fields):
  - `job_title` (required)
  - `description` (required)
  - Optional (defaulted in code): `employer_id`, `job_id_external`, `company_name`, `location`, `job_type`, `min_salary`, `max_salary`, `required_skills`, `qualifications_educations`, `posted_date`, `anonymous_posting`, `is_active`, `created_at`, `updated_at`

**Response body**
```json
{
  "success": true,
  "query_id": "jd_<job_title>",
  "result_id": "resume filename",
  "analysis": { "fit_score": 75, "summary": "...", "strengths": [], "gaps": [], "recommendations": [], "detailed_analysis": "..." },
  "timestamp": "ISO-8601 string"
}
```

---

## Module: Resume (file) -> Jobs (`r_to_j`)

### `POST /api/v1/r-to-j/admin/upload-resume`
**Request body** (`multipart/form-data`)
- `files` (file[], required): multiple PDF/DOCX/TXT/RTF
- Optional form fields: `location`, `experience`, `skills`

**Response body**
```json
{
  "success": true,
  "message": "string",
  "total_files": 2,
  "success_count": 2,
  "fail_count": 0,
  "results": [
    {
      "file_name": "string",
      "success": true,
      "document_id": "string",
      "vectors_created": 3,
      "bm25_updated": true
    }
  ],
  "pinecone_namespace": "resumes",
  "timestamp": "ISO-8601 string"
}
```

### `POST /api/v1/r-to-j/search`
**Request body** (`multipart/form-data`)
- `file` (file, required): resume file
- `top_k` (text/int, optional; default `10`)

**Response body** (returns raw formatted job results)
```json
{
  "success": true,
  "total_results": 10,
  "query_summary": "Resume file: <filename>",
  "results": [
    {
      "rank": 1,
      "score": 0.82,
      "score_percentage": "82.0%",
      "semantic_score": 0.7,
      "keyword_score": 0.9,
      "title": "string",
      "company": "string",
      "location": "string",
      "required_skills": "string",
      "experience_required": "string",
      "salary": "string",
      "job_type": "string",
      "url": "string",
      "description_preview": "string"
    }
  ],
  "search_metadata": { "query_type": "resume_to_jd", "corpus": "jobs", "namespace": "jobs", "top_k": 10, "file_name": "..." },
  "timestamp": "ISO-8601 string"
}
```

### `POST /api/v1/r-to-j/analyze`
**Request body / response body**: same shape as `POST /api/v1/j-to-r/analyze` (job form + resume file)

---

## Module: Training -> Resumes (`p_to_r`)

### `POST /api/v1/p-to-r/admin/upload-training`
**Request body** (`application/json`)
```json
{
  "center_name": "string",
  "courses_offered": "string (comma-separated)",
  "course_duration": "string (optional)",
  "certification": "string (optional)",
  "description": "string (optional)",
  "capacity": 50,
  "address": "string (optional)",
  "email": "string (optional)",
  "phone": "string (optional)"
}
```

**Response body**: `UploadResponse`

### `POST /api/v1/p-to-r/search`
**Request body** (`application/json`)
```json
{
  "center_name": "string",
  "courses": "string",
  "duration": "string (optional)",
  "certification": "string (optional)",
  "description": "string (optional)",
  "top_k": 10
}
```

**Response body**: `SearchResponse` (results are resumes)

### `POST /api/v1/p-to-r/analyze`
**Request body** (`multipart/form-data`)
- `resume_file` (file, required)
- Training fields (form fields): `center_name` (required), `courses_offered` (required), `description` (required)
- Optional (defaulted in code): `capacity`, `address`, `phone`, `email`, `course_duration`, `certification`

**Response body**
```json
{
  "success": true,
  "query_id": "training_<center_name>",
  "result_id": "resume filename",
  "analysis": { "fit_score": 75, "summary": "...", "strengths": [], "gaps": [], "recommendations": [], "detailed_analysis": "..." },
  "timestamp": "ISO-8601 string"
}
```

---

## Module: Resume -> Training (`r_to_p`)

### `POST /api/v1/r-to-p/admin/upload-resume`
**Request body** (`application/json`)
```json
{
  "file_content": "string (raw text OR prefix with 'base64:' then base64 content)",
  "file_name": "string",
  "file_type": "pdf|docx|txt|rtf",
  "location": "string (optional)",
  "experience": "string (optional)",
  "skills": "string (optional, comma-separated)"
}
```

**Response body**: `UploadResponse`

### `POST /api/v1/r-to-p/search`
**Request body** (`application/json`)
```json
{
  "candidate_name": "string",
  "current_role": "string (optional)",
  "experience_years": 5,
  "skills": "string (comma-separated)",
  "summary": "string (optional)",
  "education": "string (optional)",
  "location_preference": "string (optional)",
  "top_k": 10
}
```

**Response body**: `SearchResponse` (results are training programs; only `center_name`/`courses` fields are guaranteed in `results[]`)

### `POST /api/v1/r-to-p/analyze`
**Request body / response body**: same shape as `POST /api/v1/p-to-r/analyze`

---

## Module: Assistance -> Resumes (`a_to_r`)

### `POST /api/v1/a-to-r/admin/upload-assistance`
**Request body** (`application/json`)
```json
{
  "center_name": "string",
  "services": "string (comma-separated)",
  "operating_hours": "string (optional)",
  "description": "string (optional)",
  "capacity": 30,
  "address": "string (optional)",
  "email": "string (optional)",
  "phone": "string (optional)"
}
```

**Response body**: `UploadResponse`

### `POST /api/v1/a-to-r/search`
**Request body** (`application/json`)
```json
{
  "center_name": "string",
  "services": "string",
  "operating_hours": "string (optional)",
  "description": "string (optional)",
  "top_k": 10
}
```

**Response body**: `SearchResponse` (results are resumes)

### `POST /api/v1/a-to-r/analyze`
**Request body** (`multipart/form-data`)
- `resume_file` (file, required)
- Assistance fields (form fields): `center_name` (required), `services` (required), `description` (required)
- Optional (defaulted in code): `capacity`, `address`, `phone`, `email`, `operating_hours`

**Response body**
```json
{
  "success": true,
  "query_id": "assistance_<center_name>",
  "result_id": "resume filename",
  "analysis": { "fit_score": 75, "summary": "...", "strengths": [], "gaps": [], "recommendations": [], "detailed_analysis": "..." },
  "timestamp": "ISO-8601 string"
}
```

---

## Module: Resume -> Assistance (`r_to_a`)

### `POST /api/v1/r-to-a/admin/upload-resume`
**Request body**: same as `POST /api/v1/r-to-p/admin/upload-resume` (JSON `ResumeUploadRequest`)

**Response body**: `UploadResponse`

### `POST /api/v1/r-to-a/search`
**Request body**: same as `POST /api/v1/r-to-p/search` (JSON `ResumeSearchRequest`)

**Response body**: `SearchResponse` (results are assistance centers; only `center_name`/`services` fields are guaranteed in `results[]`)

### `POST /api/v1/r-to-a/analyze`
**Request body / response body**: same shape as `POST /api/v1/a-to-r/analyze`
