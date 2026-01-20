# api/routers/r_to_a_router.py
# Router for Resume → Assistance Center matching
# ----------------------------------------------------------------------
"""
Resume → Assistance Center Matching API

Endpoints:
1. POST /admin/upload-resume - Upload resume
2. POST /search - Search for matching assistance centers
3. POST /analyze - AI analysis of match
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime

from api.models import (
    ResumeUploadRequest,
    UploadResponse,
    ResumeSearchRequest,
    SearchResponse,
    SearchResult,
    AnalyzeRequest,
    AnalyzeResponse,
    AnalysisResult,
)
from api.services import UploadService, SearchService, AnalyzeService

router = APIRouter()

# ============================================================================
# Admin Endpoint: Upload Resume
# ============================================================================

@router.post("/admin/upload-resume", response_model=UploadResponse)
async def upload_resume(request: ResumeUploadRequest):
    """
    Upload a resume to the system
    
    - Creates embeddings and stores in Pinecone (`resumes` namespace)
    - Chunks resume text for better matching
    - Updates BM25 keyword index
    - Returns document ID and confirmation
    """
    try:
        service = UploadService()
        
        # Decode file content if base64
        if request.file_content.startswith("base64:"):
            resume_text = service.decode_base64_file(request.file_content[7:])
        else:
            resume_text = request.file_content
        
        # Enhance with metadata if provided
        if request.location or request.experience or request.skills:
            metadata_text = f"\n\nLocation: {request.location or 'N/A'}\n"
            metadata_text += f"Experience: {request.experience or 'N/A'}\n"
            metadata_text += f"Skills: {request.skills or 'N/A'}\n"
            resume_text = metadata_text + resume_text
        
        # Generate document ID
        doc_id = service.generate_doc_id(resume_text, prefix="resume")
        
        # Prepare metadata
        metadata = {
            "file_name": request.file_name,
            "file_type": request.file_type,
            "location": request.location or "",
            "experience": request.experience or "",
            "skills": request.skills or "",
            "uploaded_at": datetime.now().isoformat(),
        }
        
        # Upload (resumes ARE chunked)
        vectors_created, bm25_updated = service.upload_to_pinecone_and_bm25(
            doc_type="resumes",
            doc_id=doc_id,
            text=resume_text,
            metadata=metadata,
            chunk_docs=True  # Resumes are chunked
        )
        
        return UploadResponse(
            success=True,
            message=f"Resume '{request.file_name}' uploaded successfully",
            document_id=doc_id,
            vectors_created=vectors_created,
            pinecone_namespace="resumes",
            bm25_updated=bm25_updated,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ============================================================================
# User Endpoint: Search for Matching Assistance Centers
# ============================================================================

@router.post("/search", response_model=SearchResponse)
async def search_assistance(request: ResumeSearchRequest):
    """
    Search for assistance centers that match a candidate's resume
    
    - Uses hybrid search (Pinecone semantic + BM25 keyword)
    - Returns ranked list of matching assistance centers
    - Same accuracy as Streamlit app
    """
    try:
        # Compose query text from resume fields
        query_text = f"""
Candidate: {request.candidate_name}
Current Role: {request.current_role or 'N/A'}
Experience: {request.experience_years or 'N/A'} years

Skills:
{request.skills}

Professional Summary:
{request.summary or 'N/A'}

Education:
{request.education or 'N/A'}
"""
        
        # Perform search (searches ASSISTANCE namespace)
        results = SearchService.search(
            corpus_type="assistance",
            namespace="assistance",
            query_text=query_text,
            top_k=request.top_k
        )
        
        # Format results
        search_results = [SearchResult(**r) for r in results]
        
        return SearchResponse(
            success=True,
            total_results=len(search_results),
            query_summary=f"Candidate: {request.candidate_name} seeking assistance",
            results=search_results,
            search_metadata={
                "query_type": "resume_to_assistance",
                "corpus": "assistance",
                "namespace": "assistance",
                "algorithm": "Pinecone + BM25 Hybrid",
                "top_k": request.top_k,
            },
            timestamp=datetime.now().isoformat()
        )
        
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
    # Assistance center form fields
    center_name: str = Form(..., description="Assistance center name"),
    capacity: int = Form(80),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    operating_hours: str = Form("Mon–Fri 9:00 AM – 6:00 PM"),
    services: str = Form(..., description="Comma-separated services"),
    description: str = Form(..., description="Assistance center description"),
):
    """
    Get AI-powered analysis of why an assistance center matches a resume (candidate-facing)
    
    - **Upload resume file** (PDF, DOCX, TXT, RTF)
    - **Fill assistance center form** (all fields)
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
        
        # Build assistance center JSON
        assistance_json = {
            "center_name": center_name,
            "capacity": int(capacity),
            "address": address,
            "phone": phone,
            "email": email,
            "operating_hours": operating_hours,
            "services": to_csv_list(services),
            "description": description,
        }
        
        # Get analysis
        service = AnalyzeService()
        analysis = service.analyze_match(
            query_type="resume_to_assistance",
            query_json=assistance_json,
            resume_json=resume_json
        )
        
        return {
            "success": True,
            "query_id": f"resume_{filename}",
            "result_id": center_name,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

