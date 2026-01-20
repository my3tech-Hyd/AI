# api/routers/a_to_r_router.py
# Router for Assistance Center → Resume matching
# ----------------------------------------------------------------------
"""
Assistance Center → Resume Matching API

Endpoints:
1. POST /admin/upload-assistance - Upload assistance center
2. POST /search - Search for matching resumes
3. POST /analyze - AI analysis of match
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime

from api.models import (
    AssistanceUploadRequest,
    UploadResponse,
    AssistanceSearchRequest,
    SearchResponse,
    SearchResult,
    AnalyzeRequest,
    AnalyzeResponse,
    AnalysisResult,
)
from api.services import UploadService, SearchService, AnalyzeService

router = APIRouter()

# ============================================================================
# Admin Endpoint: Upload Assistance Center
# ============================================================================

@router.post("/admin/upload-assistance", response_model=UploadResponse)
async def upload_assistance_center(request: AssistanceUploadRequest):
    """
    Upload an assistance center to the system
    
    - Creates embeddings and stores in Pinecone (`assistance` namespace)
    - Updates BM25 keyword index
    - Returns document ID and confirmation
    """
    try:
        service = UploadService()
        
        # Compose assistance center text
        assistance_text = f"""
Assistance Center: {request.center_name}
Services Offered: {request.services}
Operating Hours: {request.operating_hours or 'N/A'}
Capacity: {request.capacity or 'N/A'}
Address: {request.address or 'N/A'}
Contact: {request.email or 'N/A'} | {request.phone or 'N/A'}

Description:
{request.description or 'Professional assistance center providing career support services.'}
"""
        
        # Generate document ID
        doc_id = service.generate_doc_id(assistance_text, prefix="assistance")
        
        # Prepare metadata
        metadata = {
            "center_name": request.center_name,
            "services": request.services,
            "operating_hours": request.operating_hours or "",
            "capacity": request.capacity or 0,
            "address": request.address or "",
            "email": request.email or "",
            "phone": request.phone or "",
            "uploaded_at": datetime.now().isoformat(),
        }
        
        # Upload (assistance centers are NOT chunked)
        vectors_created, bm25_updated = service.upload_to_pinecone_and_bm25(
            doc_type="assistance",
            doc_id=doc_id,
            text=assistance_text,
            metadata=metadata,
            chunk_docs=False  # Assistance centers are not chunked
        )
        
        return UploadResponse(
            success=True,
            message=f"Assistance center '{request.center_name}' uploaded successfully",
            document_id=doc_id,
            vectors_created=vectors_created,
            pinecone_namespace="assistance",
            bm25_updated=bm25_updated,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ============================================================================
# User Endpoint: Search for Matching Resumes
# ============================================================================

@router.post("/search", response_model=SearchResponse)
async def search_resumes(request: AssistanceSearchRequest):
    """
    Search for resumes that match an assistance center's services
    
    - Uses hybrid search (Pinecone semantic + BM25 keyword)
    - Returns ranked list of matching candidates
    - Same accuracy as Streamlit app
    """
    try:
        # Compose query text from assistance fields
        query_text = f"""
Assistance Center: {request.center_name}
Services: {request.services}
Operating Hours: {request.operating_hours or 'N/A'}

Description:
{request.description or 'Assistance services for career development and job placement'}
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
            query_summary=f"Assistance: {request.center_name} - {request.services}",
            results=search_results,
            search_metadata={
                "query_type": "assistance_to_resume",
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
    Get AI-powered analysis of why a resume matches an assistance center (center-facing)
    
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
            query_type="assistance_to_resume",
            query_json=assistance_json,
            resume_json=resume_json
        )
        
        return {
            "success": True,
            "query_id": f"assistance_{center_name.replace(' ', '_')}",
            "result_id": filename,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

