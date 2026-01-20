# api/routers/r_to_j_router.py
# Router for Resume → Job matching
# ----------------------------------------------------------------------
"""
Resume → Job Description Matching API

Endpoints:
1. POST /admin/upload-resume - Upload multiple resume files
2. POST /search - Search for matching jobs
3. POST /analyze - AI analysis of match
"""

from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from datetime import datetime
from typing import List, Optional
import io
from pathlib import Path

from pypdf import PdfReader
from docx import Document as Docx

from api.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalysisResult,
)
from api.services import UploadService, SearchService, AnalyzeService

router = APIRouter()

# ============================================================================
# Helper: Extract text from various file formats
# ============================================================================

def read_text_from_file(file_data: bytes, filename: str) -> str:
    """Extract text from PDF, DOCX, TXT, RTF files"""
    ext = Path(filename).suffix.lower()
    
    try:
        if ext == ".pdf":
            with io.BytesIO(file_data) as f:
                reader = PdfReader(f, strict=False)
                text = " ".join((page.extract_text() or "") for page in reader.pages)
        elif ext == ".docx":
            with io.BytesIO(file_data) as f:
                doc = Docx(f)
                text = "\n".join(p.text for p in doc.paragraphs)
        elif ext in {".txt", ".rtf", ".md"}:
            text = file_data.decode(errors="ignore")
        else:
            text = file_data.decode(errors="ignore")
        
        return text.strip()
    except Exception as e:
        raise ValueError(f"Failed to extract text from {filename}: {str(e)}")

# ============================================================================
# Admin Endpoint: Upload Multiple Resumes
# ============================================================================

@router.post("/admin/upload-resume")
async def upload_resumes(
    files: List[UploadFile] = File(..., description="Resume files (PDF, DOCX, TXT, RTF)"),
    location: Optional[str] = Form(None, description="Candidate location"),
    experience: Optional[str] = Form(None, description="Years of experience"),
    skills: Optional[str] = Form(None, description="Key skills (comma-separated)")
):
    """
    Upload multiple resume files to the system
    
    - Accepts multiple files: PDF, DOCX, TXT, RTF
    - Extracts text and metadata from each file
    - Creates embeddings and stores in Pinecone (`resumes` namespace)
    - Chunks resume text for better matching (600 size, 120 overlap)
    - Updates BM25 keyword index
    - Returns summary of uploaded files
    
    **Example using curl:**
    ```bash
    curl -X POST http://localhost:8016/api/v1/r-to-j/admin/upload-resume \\
      -F "files=@resume1.pdf" \\
      -F "files=@resume2.docx" \\
      -F "location=Hyderabad" \\
      -F "skills=Python, Django, AWS"
    ```
    """
    try:
        service = UploadService()
        
        results = []
        success_count = 0
        fail_count = 0
        
        for uploaded_file in files:
            try:
                # Read file data
                file_data = await uploaded_file.read()
                filename = uploaded_file.filename
                
                # Extract text
                resume_text = read_text_from_file(file_data, filename)
                
                if not resume_text:
                    results.append({
                        "file_name": filename,
                        "success": False,
                        "error": "Empty file or text extraction failed"
                    })
                    fail_count += 1
                    continue
                
                # Generate document ID from file content
                doc_id = service.generate_doc_id(resume_text, prefix="resume")
                
                # Prepare metadata
                metadata = {
                    "file_name": filename,
                    "file_type": Path(filename).suffix.lower(),
                    "location": location or "",
                    "experience": experience or "",
                    "skills": skills or "",
                    "uploaded_at": datetime.now().isoformat(),
                }
                
                # Upload (resumes ARE chunked)
                vectors_created, bm25_updated = service.upload_to_pinecone_and_bm25(
                    doc_type="resumes",
                    doc_id=doc_id,
                    text=resume_text,
                    metadata=metadata,
                    chunk_docs=True  # Resumes are chunked (600 size, 120 overlap)
                )
                
                results.append({
                    "file_name": filename,
                    "success": True,
                    "document_id": doc_id,
                    "vectors_created": vectors_created,
                    "bm25_updated": bm25_updated
                })
                success_count += 1
                
            except Exception as e:
                results.append({
                    "file_name": uploaded_file.filename,
                    "success": False,
                    "error": str(e)
                })
                fail_count += 1
        
        return {
            "success": success_count > 0,
            "message": f"Processed {len(files)} files: {success_count} succeeded, {fail_count} failed",
            "total_files": len(files),
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results,
            "pinecone_namespace": "resumes",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ============================================================================
# User Endpoint: Search for Matching Jobs (Multipart File Upload)
# ============================================================================

@router.post("/search")
async def search_jobs(
    file: UploadFile = File(..., description="Resume file (PDF, DOCX, TXT, RTF)"),
    top_k: int = Form(10, description="Number of results to return")
):
    """
    Search for jobs that match a resume file
    
    - **Upload a resume file** (PDF, DOCX, TXT, RTF)
    - Extracts text from the file
    - Uses hybrid search (Pinecone semantic + BM25 keyword)
    - Returns ranked list of matching job openings
    - Same accuracy as Streamlit app
    
    **Example using curl:**
    ```bash
    curl -X POST http://localhost:8016/api/v1/r-to-j/search \\
      -F "file=@resume.pdf" \\
      -F "top_k=10"
    ```
    
    **Example using Postman:**
    - Method: POST
    - Body: form-data
    - Key: `file` (File type), Value: Select resume file
    - Key: `top_k` (Text type), Value: 10
    """
    try:
        # Read file data
        file_data = await file.read()
        filename = file.filename
        
        # Extract text from file
        resume_text = read_text_from_file(file_data, filename)
        
        if not resume_text:
            raise HTTPException(status_code=400, detail="Empty file or text extraction failed")
        
        # Compose query text
        query_text = f"Resume Content:\n{resume_text}"
        
        # Perform search (searches JOBS namespace)
        results = SearchService.search(
            corpus_type="jobs",
            namespace="jobs",
            query_text=query_text,
            top_k=top_k
        )
        
        # Return results directly (no Pydantic model to avoid extra null fields)
        return {
            "success": True,
            "total_results": len(results),
            "query_summary": f"Resume file: {filename}",
            "results": results,  # Return dict results directly
            "search_metadata": {
                "query_type": "resume_to_jd",
                "corpus": "jobs",
                "namespace": "jobs",
                "algorithm": "Pinecone + BM25 Hybrid",
                "top_k": top_k,
                "file_name": filename
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

# ============================================================================
# Generative Endpoint: AI Analysis of Match
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
    Get AI-powered analysis of why a job matches a resume (candidate-facing)
    
    - **Upload resume file** (PDF, DOCX, TXT, RTF)
    - **Fill job posting form** (all fields)
    - Uses OpenAI GPT-4o-mini for detailed analysis
    - Returns full markdown report (matches Streamlit generative)
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
            query_type="resume_to_jd",
            query_json=job_json,
            resume_json=resume_json
        )
        
        return {
            "success": True,
            "query_id": f"resume_{filename}",
            "result_id": job_title,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

