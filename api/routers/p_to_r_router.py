# api/routers/p_to_r_router.py
# Router for Training Program → Resume matching
# ----------------------------------------------------------------------
"""
Training Program → Resume Matching API

Endpoints:
1. POST /admin/upload-training - Upload training program
2. POST /search - Search for matching resumes
3. POST /analyze - AI analysis of match
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime

from api.models import (
    TrainingUploadRequest,
    UploadResponse,
    TrainingSearchRequest,
    SearchResponse,
    SearchResult,
    AnalyzeRequest,
    AnalyzeResponse,
    AnalysisResult,
)
from api.services import UploadService, SearchService, AnalyzeService

router = APIRouter()

# ============================================================================
# Admin Endpoint: Upload Training Program
# ============================================================================

@router.post("/admin/upload-training", response_model=UploadResponse)
async def upload_training_program(request: TrainingUploadRequest):
    """
    Upload a training program to the system
    
    - Creates embeddings and stores in Pinecone (`training` namespace)
    - Updates BM25 keyword index
    - Returns document ID and confirmation
    """
    try:
        service = UploadService()
        
        # Compose training program text
        training_text = f"""
Training Center: {request.center_name}
Courses Offered: {request.courses_offered}
Duration: {request.course_duration or 'N/A'}
Certification: {request.certification or 'N/A'}
Capacity: {request.capacity or 'N/A'}
Address: {request.address or 'N/A'}
Contact: {request.email or 'N/A'} | {request.phone or 'N/A'}

Description:
{request.description or 'Premier training center offering industry-relevant courses.'}
"""
        
        # Generate document ID
        doc_id = service.generate_doc_id(training_text, prefix="training")
        
        # Prepare metadata
        metadata = {
            "center_name": request.center_name,
            "courses_offered": request.courses_offered,
            "course_duration": request.course_duration or "",
            "certification": request.certification or "",
            "capacity": request.capacity or 0,
            "address": request.address or "",
            "email": request.email or "",
            "phone": request.phone or "",
            "uploaded_at": datetime.now().isoformat(),
        }
        
        # Upload (training programs are NOT chunked)
        vectors_created, bm25_updated = service.upload_to_pinecone_and_bm25(
            doc_type="training",
            doc_id=doc_id,
            text=training_text,
            metadata=metadata,
            chunk_docs=False  # Training programs are not chunked
        )
        
        return UploadResponse(
            success=True,
            message=f"Training program '{request.center_name}' uploaded successfully",
            document_id=doc_id,
            vectors_created=vectors_created,
            pinecone_namespace="training",
            bm25_updated=bm25_updated,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ============================================================================
# User Endpoint: Search for Matching Resumes
# ============================================================================

@router.post("/search", response_model=SearchResponse)
async def search_resumes(request: TrainingSearchRequest):
    """
    Search for resumes that match a training program
    
    - Uses hybrid search (Pinecone semantic + BM25 keyword)
    - Returns ranked list of matching candidates
    - Same accuracy as Streamlit app
    """
    try:
        # Compose query text from training fields
        query_text = f"""
Training Center: {request.center_name}
Courses: {request.courses}
Duration: {request.duration or 'N/A'}
Certification: {request.certification or 'N/A'}

Description:
{request.description or 'Training program for skill development'}
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
            query_summary=f"Training: {request.center_name} - {request.courses}",
            results=search_results,
            search_metadata={
                "query_type": "training_to_resume",
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
# Generative Endpoint: AI Analysis of Match
# ============================================================================

from fastapi import File, Form, UploadFile
from api.utils.analyze_utils import read_text_from_file, resume_to_json, to_csv_list

@router.post("/analyze")
async def analyze_match(
    # Resume file upload
    resume_file: UploadFile = File(..., description="Resume file (PDF, DOCX, TXT, RTF)"),
    # Training posting form fields
    center_name: str = Form(..., description="Training center name"),
    capacity: int = Form(120),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    course_duration: str = Form("6 months"),
    certification: str = Form(""),
    courses_offered: str = Form(..., description="Comma-separated courses"),
    description: str = Form(..., description="Training center description"),
):
    """
    Get AI-powered analysis of why a resume matches a training program (institution-facing)
    
    - **Upload resume file** (PDF, DOCX, TXT, RTF)
    - **Fill training posting form** (all fields)
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
        
        # Build training posting JSON
        training_json = {
            "center_name": center_name,
            "capacity": int(capacity),
            "address": address,
            "phone": phone,
            "email": email,
            "course_duration": course_duration,
            "certification": certification,
            "courses_offered": to_csv_list(courses_offered),
            "description": description,
        }
        
        # Get analysis
        service = AnalyzeService()
        analysis = service.analyze_match(
            query_type="training_to_resume",
            query_json=training_json,
            resume_json=resume_json
        )
        
        return {
            "success": True,
            "query_id": f"training_{center_name.replace(' ', '_')}",
            "result_id": filename,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

