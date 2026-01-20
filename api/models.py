# api/models.py
# Pydantic Models for Request/Response Validation
# ----------------------------------------------------------------------

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime

# ============================================================================
# Base Models
# ============================================================================

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    services: Dict[str, str]

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: str

# ============================================================================
# Admin Endpoint Models (Upload/Ingest)
# ============================================================================

class ResumeUploadRequest(BaseModel):
    """Request body for uploading a resume"""
    file_content: str = Field(..., description="Base64 encoded resume file or raw text")
    file_name: str = Field(..., description="Original filename (e.g., john_doe_resume.pdf)")
    file_type: str = Field("pdf", description="File type: pdf, docx, txt, rtf")
    
    # Optional metadata from form
    location: Optional[str] = Field(None, description="Candidate location")
    experience: Optional[str] = Field(None, description="Years of experience")
    skills: Optional[str] = Field(None, description="Comma-separated skills")
    
    class Config:
        json_schema_extra = {
            "example": {
                "file_content": "base64_encoded_content_here...",
                "file_name": "john_doe_resume.pdf",
                "file_type": "pdf",
                "location": "Hyderabad",
                "experience": "5 years",
                "skills": "Python, Django, PostgreSQL"
            }
        }

class JobUploadRequest(BaseModel):
    """Request body for uploading a job description"""
    title: str = Field(..., description="Job title")
    company: Optional[str] = Field(None, description="Company name")
    location: Optional[str] = Field(None, description="Job location")
    description: str = Field(..., description="Full job description")
    required_skills: Optional[str] = Field(None, description="Required skills (comma-separated)")
    experience: Optional[str] = Field(None, description="Required experience")
    salary: Optional[str] = Field(None, description="Salary range")
    job_type: Optional[str] = Field("Full-time", description="Job type")
    url: Optional[str] = Field(None, description="Job posting URL")
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "Senior Python Developer",
                "company": "TechCorp Inc.",
                "location": "Hyderabad, India",
                "description": "We are seeking a Senior Python Developer with 5+ years of experience...",
                "required_skills": "Python, Django, Flask, PostgreSQL, Docker, AWS",
                "experience": "5+ years",
                "salary": "$80K - $120K",
                "job_type": "Full-time",
                "url": "https://example.com/jobs/123"
            }
        }

class TrainingUploadRequest(BaseModel):
    """Request body for uploading training center posting"""
    center_name: str = Field(..., description="Training center name")
    courses_offered: str = Field(..., description="Courses offered (comma-separated)")
    course_duration: Optional[str] = Field(None, description="Course duration")
    certification: Optional[str] = Field(None, description="Certification offered")
    description: Optional[str] = Field(None, description="Training center description")
    capacity: Optional[int] = Field(None, description="Training capacity")
    address: Optional[str] = Field(None, description="Physical address")
    email: Optional[str] = Field(None, description="Contact email")
    phone: Optional[str] = Field(None, description="Contact phone")
    
    class Config:
        json_schema_extra = {
            "example": {
                "center_name": "TechBridge Learning Hub",
                "courses_offered": "Web Development, Data Analytics, Cloud Computing",
                "course_duration": "6 months",
                "certification": "Industry Certified by NASSCOM",
                "description": "Premier IT training institute...",
                "capacity": 50,
                "address": "Hyderabad, India",
                "email": "contact@techbridge.com",
                "phone": "+91-9876543210"
            }
        }

class AssistanceUploadRequest(BaseModel):
    """Request body for uploading assistance center posting"""
    center_name: str = Field(..., description="Assistance center name")
    services: str = Field(..., description="Services offered (comma-separated)")
    operating_hours: Optional[str] = Field(None, description="Operating hours")
    description: Optional[str] = Field(None, description="Center description")
    capacity: Optional[int] = Field(None, description="Service capacity")
    address: Optional[str] = Field(None, description="Physical address")
    email: Optional[str] = Field(None, description="Contact email")
    phone: Optional[str] = Field(None, description="Contact phone")
    
    class Config:
        json_schema_extra = {
            "example": {
                "center_name": "CareerPath Assistance Center",
                "services": "Career Counseling, Resume Writing, Interview Preparation",
                "operating_hours": "Mon-Fri 9:00 AM - 6:00 PM",
                "description": "Helps job seekers achieve career goals...",
                "capacity": 30,
                "address": "Hyderabad, India",
                "email": "support@careerpath.com",
                "phone": "+91-9123456780"
            }
        }

class UploadResponse(BaseModel):
    """Response after successful upload"""
    success: bool
    message: str
    document_id: str
    vectors_created: int
    pinecone_namespace: str
    bm25_updated: bool
    timestamp: str

# ============================================================================
# Search Endpoint Models
# ============================================================================

class JobSearchRequest(BaseModel):
    """Search for matching resumes using job description"""
    title: str = Field(..., description="Job title")
    company: Optional[str] = Field(None, description="Company name")
    location: Optional[str] = Field(None, description="Job location")
    description: str = Field(..., description="Job description")
    required_skills: Optional[str] = Field(None, description="Required skills")
    top_k: int = Field(10, ge=1, le=100, description="Number of results to return")
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "Senior Python Developer",
                "company": "TechCorp",
                "location": "Hyderabad",
                "description": "We need a Python developer with Django experience...",
                "required_skills": "Python, Django, PostgreSQL",
                "top_k": 10
            }
        }

class ResumeSearchRequest(BaseModel):
    """Search for matching jobs using resume details"""
    candidate_name: str = Field(..., description="Candidate name")
    current_role: Optional[str] = Field(None, description="Current role")
    experience_years: Optional[int] = Field(None, description="Years of experience")
    skills: str = Field(..., description="Skills (comma-separated)")
    summary: Optional[str] = Field(None, description="Professional summary")
    education: Optional[str] = Field(None, description="Education background")
    location_preference: Optional[str] = Field(None, description="Location preference")
    top_k: int = Field(10, ge=1, le=100, description="Number of results")
    
    class Config:
        json_schema_extra = {
            "example": {
                "candidate_name": "Amit Kumar",
                "current_role": "Senior Python Developer",
                "experience_years": 5,
                "skills": "Python, Django, Flask, PostgreSQL, Docker, AWS",
                "summary": "Experienced developer with 5+ years in web applications...",
                "education": "B.Tech Computer Science",
                "location_preference": "Hyderabad, Remote",
                "top_k": 10
            }
        }

class TrainingSearchRequest(BaseModel):
    """Search for matching resumes using training program details"""
    center_name: str = Field(..., description="Training center name")
    courses: str = Field(..., description="Courses offered")
    duration: Optional[str] = Field(None, description="Course duration")
    certification: Optional[str] = Field(None, description="Certification")
    description: Optional[str] = Field(None, description="Program description")
    top_k: int = Field(10, ge=1, le=100, description="Number of results")
    
    class Config:
        json_schema_extra = {
            "example": {
                "center_name": "TechBridge Learning Hub",
                "courses": "Web Development, Data Analytics",
                "duration": "6 months",
                "certification": "NASSCOM Certified",
                "description": "Premier IT training institute...",
                "top_k": 10
            }
        }

class AssistanceSearchRequest(BaseModel):
    """Search for matching resumes using assistance center details"""
    center_name: str = Field(..., description="Assistance center name")
    services: str = Field(..., description="Services offered")
    operating_hours: Optional[str] = Field(None, description="Operating hours")
    description: Optional[str] = Field(None, description="Center description")
    top_k: int = Field(10, ge=1, le=100, description="Number of results")
    
    class Config:
        json_schema_extra = {
            "example": {
                "center_name": "CareerPath Assistance",
                "services": "Career Counseling, Interview Prep",
                "operating_hours": "Mon-Fri 9-6",
                "description": "Helps job seekers...",
                "top_k": 10
            }
        }

class SearchResult(BaseModel):
    """Individual search result"""
    rank: int
    score: float = Field(..., description="Match score (0-1 scale)")
    score_percentage: str = Field(..., description="Match score as percentage")
    semantic_score: Optional[float] = None
    keyword_score: Optional[float] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: Optional[str] = None
    experience: Optional[str] = None
    education: Optional[str] = None
    location: Optional[str] = None
    title: Optional[str] = None  # For jobs
    company: Optional[str] = None  # For jobs
    center_name: Optional[str] = None  # For training/assistance
    services: Optional[str] = None  # For assistance
    courses: Optional[str] = None  # For training
    text_preview: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class SearchResponse(BaseModel):
    """Response from search endpoints"""
    success: bool
    total_results: int
    query_summary: str
    results: List[SearchResult]
    search_metadata: Dict[str, Any]
    timestamp: str

# ============================================================================
# Generative/Analysis Endpoint Models
# ============================================================================

class AnalyzeRequest(BaseModel):
    """Request for AI analysis"""
    query_text: str = Field(..., description="Query text (JD, resume, etc.)")
    result_id: str = Field(..., description="ID of the match result to analyze")
    analysis_type: str = Field("detailed", description="Type of analysis: detailed, brief, comparison")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query_text": "Senior Python Developer with Django experience...",
                "result_id": "resume_abc123",
                "analysis_type": "detailed"
            }
        }

class AnalysisResult(BaseModel):
    """AI-generated analysis result"""
    fit_score: int = Field(..., ge=0, le=100, description="Overall fit score (0-100)")
    summary: str = Field(..., description="Brief summary of the match")
    strengths: List[str] = Field(..., description="Key strengths/matches")
    gaps: List[str] = Field(..., description="Gaps or mismatches")
    recommendations: List[str] = Field(..., description="Recommendations")
    detailed_analysis: str = Field(..., description="Detailed explanation")

class AnalyzeResponse(BaseModel):
    """Response from analyze endpoints"""
    success: bool
    query_id: str
    result_id: str
    analysis: AnalysisResult
    timestamp: str

# ============================================================================
# Batch Operations (Optional)
# ============================================================================

class BatchSearchRequest(BaseModel):
    """Batch search request"""
    queries: List[Dict[str, Any]] = Field(..., description="List of search queries")
    top_k: int = Field(10, ge=1, le=100, description="Results per query")

class BatchSearchResponse(BaseModel):
    """Batch search response"""
    success: bool
    total_queries: int
    results: List[SearchResponse]
    timestamp: str

