# api/main.py
# FastAPI Main Application - AI Matching System
# ----------------------------------------------------------------------
"""
AI-Powered Job, Training, and Assistance Matching API

This API provides endpoints for:
- Job Description ↔ Resume matching
- Training Programs ↔ Resume matching
- Assistance Centers ↔ Resume matching

All endpoints use Pinecone hybrid search (semantic + keyword)
with generative AI capabilities for detailed analysis.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from datetime import datetime

# Import routers
from api.routers import (
    j_to_r_router,
    r_to_j_router,
    p_to_r_router,
    r_to_p_router,
    a_to_r_router,
    r_to_a_router,
)

# ============================================================================
# FastAPI App Configuration
# ============================================================================

app = FastAPI(
    title="AI Matching System API",
    description="""
    ## 🎯 AI-Powered Matching System
    
    This API provides intelligent matching between:
    - **Jobs ↔ Resumes**
    - **Training Programs ↔ Resumes**
    - **Assistance Centers ↔ Resumes**
    
    ### 🔍 Features
    - **Hybrid Search**: Combines semantic (vector) and keyword (BM25) search
    - **Pinecone Vector Database**: Scalable, cloud-hosted vector storage
    - **Generative AI Analysis**: Detailed explanations and insights
    - **High Accuracy**: Same algorithms as production Streamlit apps
    
    ### 📊 Endpoints
    Each module has 3 endpoints:
    - `/admin` - Upload/ingest data (resumes, jobs, training, assistance)
    - `/search` - Search and retrieve matches
    - `/analyze` - Get AI-generated analysis and explanations
    
    ### 🔧 Modules
    - `j_to_r`: Job Description → Resume Search
    - `r_to_j`: Resume → Job Description Search
    - `p_to_r`: Training Program → Resume Search
    - `r_to_p`: Resume → Training Program Search
    - `a_to_r`: Assistance Center → Resume Search
    - `r_to_a`: Resume → Assistance Center Search
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "WITS AI Team",
        "email": "support@wits.ai",
    },
    license_info={
        "name": "Proprietary",
    },
)

# ============================================================================
# CORS Middleware
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Routers
# ============================================================================

app.include_router(
    j_to_r_router.router,
    prefix="/api/v1/j-to-r",
    tags=["Job → Resume (j_to_r)"]
)

app.include_router(
    r_to_j_router.router,
    prefix="/api/v1/r-to-j",
    tags=["Resume → Job (r_to_j)"]
)

app.include_router(
    p_to_r_router.router,
    prefix="/api/v1/p-to-r",
    tags=["Training → Resume (p_to_r)"]
)

app.include_router(
    r_to_p_router.router,
    prefix="/api/v1/r-to-p",
    tags=["Resume → Training (r_to_p)"]
)

app.include_router(
    a_to_r_router.router,
    prefix="/api/v1/a-to-r",
    tags=["Assistance → Resume (a_to_r)"]
)

app.include_router(
    r_to_a_router.router,
    prefix="/api/v1/r-to-a",
    tags=["Resume → Assistance (r_to_a)"]
)

# ============================================================================
# Root & Health Check Endpoints
# ============================================================================

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information"""
    return {
        "message": "AI Matching System API",
        "version": "1.0.0",
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "docs": "/docs",
        "modules": [
            "j_to_r (Job → Resume)",
            "r_to_j (Resume → Job)",
            "p_to_r (Training → Resume)",
            "r_to_p (Resume → Training)",
            "a_to_r (Assistance → Resume)",
            "r_to_a (Resume → Assistance)",
        ],
        "endpoints_per_module": {
            "admin": "Upload/ingest data",
            "search": "Search and retrieve matches",
            "analyze": "Get AI-generated analysis"
        }
    }

@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "pinecone": "connected",
            "ollama": "connected",
            "bm25": "loaded"
        }
    }

@app.get("/api/v1/info", tags=["Info"])
async def api_info():
    """Detailed API information"""
    return {
        "api_name": "AI Matching System",
        "version": "1.0.0",
        "description": "Hybrid AI-powered matching system using Pinecone + BM25",
        "total_endpoints": 18,
        "modules": {
            "j_to_r": {
                "description": "Match job descriptions to candidate resumes",
                "endpoints": [
                    "POST /api/v1/j-to-r/admin/upload-jd",
                    "POST /api/v1/j-to-r/search",
                    "POST /api/v1/j-to-r/analyze"
                ]
            },
            "r_to_j": {
                "description": "Find relevant jobs for a candidate resume",
                "endpoints": [
                    "POST /api/v1/r-to-j/admin/upload-resume",
                    "POST /api/v1/r-to-j/search",
                    "POST /api/v1/r-to-j/analyze"
                ]
            },
            "p_to_r": {
                "description": "Match training programs to candidate resumes",
                "endpoints": [
                    "POST /api/v1/p-to-r/admin/upload-training",
                    "POST /api/v1/p-to-r/search",
                    "POST /api/v1/p-to-r/analyze"
                ]
            },
            "r_to_p": {
                "description": "Find training programs for candidates",
                "endpoints": [
                    "POST /api/v1/r-to-p/admin/upload-resume",
                    "POST /api/v1/r-to-p/search",
                    "POST /api/v1/r-to-p/analyze"
                ]
            },
            "a_to_r": {
                "description": "Match assistance centers to candidate resumes",
                "endpoints": [
                    "POST /api/v1/a-to-r/admin/upload-assistance",
                    "POST /api/v1/a-to-r/search",
                    "POST /api/v1/a-to-r/analyze"
                ]
            },
            "r_to_a": {
                "description": "Find assistance centers for candidates",
                "endpoints": [
                    "POST /api/v1/r-to-a/admin/upload-resume",
                    "POST /api/v1/r-to-a/search",
                    "POST /api/v1/r-to-a/analyze"
                ]
            }
        },
        "technology_stack": {
            "framework": "FastAPI",
            "vector_db": "Pinecone",
            "keyword_search": "BM25",
            "embeddings": "Ollama (nomic-embed-text)",
            "generative_ai": "OpenAI GPT-4o-mini"
        }
    }

# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.now().isoformat()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "timestamp": datetime.now().isoformat()
        }
    )

# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

