# api/routers/j_to_r_router.py
# Router for Job → Resume matching
# ----------------------------------------------------------------------
"""
Job Description → Resume Matching API

Endpoints:
1. POST /admin/upload-jd - Upload job description
2. POST /search - Search for matching resumes
3. POST /analyze - AI analysis of match
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import Dict

from api.models import (
    JobUploadRequest,
    UploadResponse,
    JobSearchRequest,
    SearchResponse,
    SearchResult,
    AnalyzeRequest,
    AnalyzeResponse,
    AnalysisResult,
)
from api.services import UploadService, SearchService, AnalyzeService

router = APIRouter()

# ============================================================================
# Admin Endpoint: Upload Job Description
# ============================================================================

@router.post("/admin/upload-jd", response_model=UploadResponse)
async def upload_job_description(request: JobUploadRequest):
    """
    Upload a job description to the system
    
    - Creates embeddings and stores in Pinecone (`jobs` namespace)
    - Updates BM25 keyword index
    - Returns document ID and confirmation
    """
    try:
        service = UploadService()
        
        # Compose job description text
        jd_text = f"""
Title: {request.title}
Company: {request.company or 'N/A'}
Location: {request.location or 'N/A'}
Type: {request.job_type or 'Full-time'}
Experience Required: {request.experience or 'N/A'}
Salary: {request.salary or 'N/A'}

Description:
{request.description}

Required Skills:
{request.required_skills or 'N/A'}
"""
        
        # Generate document ID
        doc_id = service.generate_doc_id(jd_text, prefix="jd")
        
        # Prepare metadata
        metadata = {
            "title": request.title,
            "company": request.company or "",
            "location": request.location or "",
            "required_skills": request.required_skills or "",
            "experience": request.experience or "",
            "salary": request.salary or "",
            "job_type": request.job_type or "Full-time",
            "url": request.url or "",
            "uploaded_at": datetime.now().isoformat(),
        }
        
        # Upload (jobs are NOT chunked - single document)
        vectors_created, bm25_updated = service.upload_to_pinecone_and_bm25(
            doc_type="jobs",
            doc_id=doc_id,
            text=jd_text,
            metadata=metadata,
            chunk_docs=False  # Jobs are not chunked
        )
        
        return UploadResponse(
            success=True,
            message=f"Job description '{request.title}' uploaded successfully",
            document_id=doc_id,
            vectors_created=vectors_created,
            pinecone_namespace="jobs",
            bm25_updated=bm25_updated,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ============================================================================
# User Endpoint: Search for Matching Resumes
# ============================================================================

@router.post("/search", response_model=SearchResponse)
async def search_resumes(request: JobSearchRequest):
    """
    Search for resumes that match a job description
    
    - Uses hybrid search (Pinecone semantic + BM25 keyword)
    - Returns ranked list of matching candidates
    - Same accuracy as Streamlit app
    """
    try:
        # Compose query text from JD fields
        query_text = f"""
Title: {request.title}
Company: {request.company or ''}
Location: {request.location or ''}

Job Description:
{request.description}

Required Skills:
{request.required_skills or ''}
"""
        
        # Perform search (searches RESUMES namespace)
        results = SearchService.search(
            corpus_type="resumes",
            namespace="resumes",
            query_text=query_text,
            top_k=request.top_k
        )
        
        # Format results
        search_results = [SearchResult(**r) for r in results]
        
        return SearchResponse(
            success=True,
            total_results=len(search_results),
            query_summary=f"Job: {request.title} at {request.company or 'N/A'}",
            results=search_results,
            search_metadata={
                "query_type": "jd_to_resume",
                "corpus": "resumes",
                "namespace": "resumes",
                "algorithm": "Pinecone + BM25 Hybrid",
                "top_k": request.top_k,
            },
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

# ============================================================================
# Generative Endpoint: AI Analysis of Match (Multipart: Resume File + Job Form)
# ============================================================================

from fastapi import File, Form, UploadFile
from api.utils.analyze_utils import read_text_from_file, resume_to_json, to_csv_list

@router.post("/analyze")
async def analyze_match(
    # Resume file upload
    resume_file: UploadFile = File(..., description="Resume file (PDF, DOCX, TXT, RTF)"),
    # Job posting form fields
    employer_id: str = Form("1"),
    job_id_external: str = Form(""),
    company_name: str = Form(""),
    job_title: str = Form(..., description="Job title"),
    description: str = Form(..., description="Job description"),
    location: str = Form(""),
    job_type: str = Form("FULL_TIME"),
    min_salary: float = Form(30000),
    max_salary: float = Form(50000),
    required_skills: str = Form("", description="Comma-separated skills"),
    qualifications_educations: str = Form("", description="Comma-separated qualifications"),
    posted_date: str = Form(""),
    anonymous_posting: bool = Form(False),
    is_active: bool = Form(True),
    created_at: str = Form(""),
    updated_at: str = Form(""),
):
    """
    Get AI-powered analysis of why a resume matches a job
    
    - **Upload resume file** (PDF, DOCX, TXT, RTF)
    - **Fill job posting form** (all fields)
    - Uses OpenAI GPT-4o-mini for detailed analysis
    - Returns full markdown report (matches Streamlit generative)
    
    **Example using Postman:**
    - Method: POST
    - Body: form-data
    - File: `resume_file` (File type) - Select resume
    - Fields: `job_title`, `description`, `required_skills`, etc. (Text type)
    """
    try:
        # Read resume file
        file_data = await resume_file.read()
        filename = resume_file.filename or "resume.pdf"
        resume_text = read_text_from_file(file_data, filename)
        
        if not resume_text.strip():
            raise HTTPException(status_code=400, detail="Empty resume file or text extraction failed")
        
        # Build resume JSON
        resume_json = resume_to_json(resume_text)
        
        # Build job posting JSON
        job_json = {
            "employer_id": employer_id,
            "job_id_external": job_id_external,
            "company_name": company_name,
            "job_title": job_title,
            "description": description,
            "location": location,
            "job_type": job_type,
            "min_salary": float(min_salary),
            "max_salary": float(max_salary),
            "required_skills": to_csv_list(required_skills),
            "qualifications_educations": to_csv_list(qualifications_educations),
            "posted_date": posted_date,
            "anonymous_posting": bool(anonymous_posting),
            "is_active": bool(is_active),
            "created_at": created_at,
            "updated_at": updated_at,
        }
        
        # Get analysis
        service = AnalyzeService()
        analysis = service.analyze_match(
            query_type="jd_to_resume",
            query_json=job_json,
            resume_json=resume_json
        )
        
        return {
            "success": True,
            "query_id": f"jd_{job_title.replace(' ', '_')}",
            "result_id": filename,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

