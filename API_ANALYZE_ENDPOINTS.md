# 🔍 **Analyze Endpoints - Complete Guide**

## **✅ All Analyze Endpoints Updated!**

All 6 analyze endpoints now accept **multipart form data** (file upload + form fields) - matching Streamlit generative files!

---

## **📋 Endpoints Overview:**

| Endpoint | Type | File Upload | Form Fields |
|----------|------|-------------|-------------|
| `POST /api/v1/j-to-r/analyze` | Employer-facing | Resume | Job Posting |
| `POST /api/v1/r-to-j/analyze` | Candidate-facing | Resume | Job Posting |
| `POST /api/v1/p-to-r/analyze` | Institution-facing | Resume | Training Posting |
| `POST /api/v1/r-to-p/analyze` | Candidate-facing | Resume | Training Posting |
| `POST /api/v1/a-to-r/analyze` | Center-facing | Resume | Assistance Posting |
| `POST /api/v1/r-to-a/analyze` | Candidate-facing | Resume | Assistance Posting |

---

## **1. Job → Resume Analysis (Employer-Facing)**

### **Endpoint:** `POST /api/v1/j-to-r/analyze`

**Purpose:** Help employers evaluate if a candidate fits a job role.

### **Request Format:**

**Content-Type:** `multipart/form-data`

#### **Form Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `resume_file` | File | ✅ Yes | Resume file (PDF, DOCX, TXT, RTF) |
| `employer_id` | Text | ❌ No | Employer ID (default: "1") |
| `job_id_external` | Text | ❌ No | External job ID |
| `company_name` | Text | ❌ No | Company name |
| `job_title` | Text | ✅ Yes | Job title |
| `description` | Text | ✅ Yes | Job description |
| `location` | Text | ❌ No | Job location |
| `job_type` | Text | ❌ No | Job type (default: "FULL_TIME") |
| `min_salary` | Number | ❌ No | Minimum salary (default: 30000) |
| `max_salary` | Number | ❌ No | Maximum salary (default: 50000) |
| `required_skills` | Text | ❌ No | Comma-separated skills |
| `qualifications_educations` | Text | ❌ No | Comma-separated qualifications |
| `posted_date` | Text | ❌ No | Posted date |
| `anonymous_posting` | Checkbox | ❌ No | Anonymous posting (default: false) |
| `is_active` | Checkbox | ❌ No | Is active (default: true) |
| `created_at` | Text | ❌ No | Created timestamp |
| `updated_at` | Text | ❌ No | Updated timestamp |

### **Postman Setup:**

```
Body → form-data

KEY                    TYPE    VALUE
─────────────────────────────────────────────────────
resume_file            File    [Select resume.pdf]
job_title              Text    Senior Python Developer
description            Text    We are seeking a Senior Python Developer...
required_skills        Text    Python, Django, Flask, AWS
location               Text    Hyderabad
company_name           Text    TechCorp Inc.
```

### **Response:**

```json
{
  "success": true,
  "query_id": "jd_Senior_Python_Developer",
  "result_id": "resume.pdf",
  "analysis": {
    "fit_score": 75,
    "summary": "The candidate shows strong alignment...",
    "strengths": [],
    "gaps": [],
    "recommendations": [],
    "detailed_analysis": "# Executive Fit Summary\n\n..."
  },
  "timestamp": "2025-12-30T20:00:00.000000"
}
```

**Note:** `detailed_analysis` contains the full markdown report (matches Streamlit output).

---

## **2. Resume → Job Analysis (Candidate-Facing)**

### **Endpoint:** `POST /api/v1/r-to-j/analyze`

**Purpose:** Help candidates understand if a job matches their profile.

### **Request Format:**

Same as `j-to-r/analyze` - same form fields, but analysis is candidate-facing.

### **Response:**

Same structure, but analysis focuses on:
- How the job fits the candidate
- What the candidate can do to improve
- Resume tweaks for this specific JD
- Cover letter hooks

---

## **3. Training → Resume Analysis (Institution-Facing)**

### **Endpoint:** `POST /api/v1/p-to-r/analyze`

**Purpose:** Help training centers evaluate if a candidate fits their program.

### **Request Format:**

**Content-Type:** `multipart/form-data`

#### **Form Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `resume_file` | File | ✅ Yes | Resume file (PDF, DOCX, TXT, RTF) |
| `center_name` | Text | ✅ Yes | Training center name |
| `capacity` | Number | ❌ No | Center capacity (default: 120) |
| `address` | Text | ❌ No | Center address |
| `phone` | Text | ❌ No | Contact phone |
| `email` | Text | ❌ No | Contact email |
| `course_duration` | Text | ❌ No | Course duration (default: "6 months") |
| `certification` | Text | ❌ No | Certification offered |
| `courses_offered` | Text | ✅ Yes | Comma-separated courses |
| `description` | Text | ✅ Yes | Training center description |

### **Postman Setup:**

```
Body → form-data

KEY                    TYPE    VALUE
─────────────────────────────────────────────────────
resume_file            File    [Select resume.pdf]
center_name            Text    TechBridge Learning Hub
courses_offered        Text    Web Development, Data Analytics, Cloud Computing
description            Text    TechBridge Learning Hub is a premier IT training...
course_duration        Text    6 months
capacity               Text    120
```

---

## **4. Resume → Training Analysis (Candidate-Facing)**

### **Endpoint:** `POST /api/v1/r-to-p/analyze`

**Purpose:** Help candidates understand if a training program matches their needs.

### **Request Format:**

Same as `p-to-r/analyze` - same form fields, but analysis is candidate-facing.

---

## **5. Assistance → Resume Analysis (Center-Facing)**

### **Endpoint:** `POST /api/v1/a-to-r/analyze`

**Purpose:** Help assistance centers evaluate if a candidate fits their services.

### **Request Format:**

**Content-Type:** `multipart/form-data`

#### **Form Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `resume_file` | File | ✅ Yes | Resume file (PDF, DOCX, TXT, RTF) |
| `center_name` | Text | ✅ Yes | Assistance center name |
| `capacity` | Number | ❌ No | Center capacity (default: 80) |
| `address` | Text | ❌ No | Center address |
| `phone` | Text | ❌ No | Contact phone |
| `email` | Text | ❌ No | Contact email |
| `operating_hours` | Text | ❌ No | Operating hours (default: "Mon–Fri 9:00 AM – 6:00 PM") |
| `services` | Text | ✅ Yes | Comma-separated services |
| `description` | Text | ✅ Yes | Assistance center description |

### **Postman Setup:**

```
Body → form-data

KEY                    TYPE    VALUE
─────────────────────────────────────────────────────
resume_file            File    [Select resume.pdf]
center_name            Text    CareerPath Assistance Center
services               Text    Career Counseling, Resume Writing, Interview Preparation
description            Text    CareerPath Assistance Center helps job seekers...
operating_hours        Text    Mon–Fri 9:00 AM – 6:00 PM
capacity               Text    80
```

---

## **6. Resume → Assistance Analysis (Candidate-Facing)**

### **Endpoint:** `POST /api/v1/r-to-a/analyze`

**Purpose:** Help candidates understand if assistance center services match their needs.

### **Request Format:**

Same as `a-to-r/analyze` - same form fields, but analysis is candidate-facing.

---

## **🧪 Testing with cURL:**

### **Example 1: Job → Resume Analysis**

```bash
curl -X POST http://localhost:8016/api/v1/j-to-r/analyze \
  -F "resume_file=@candidate_resume.pdf" \
  -F "job_title=Senior Python Developer" \
  -F "description=We are seeking a Senior Python Developer with 5+ years of experience..." \
  -F "required_skills=Python, Django, Flask, AWS" \
  -F "location=Hyderabad" \
  -F "company_name=TechCorp Inc."
```

### **Example 2: Training → Resume Analysis**

```bash
curl -X POST http://localhost:8016/api/v1/p-to-r/analyze \
  -F "resume_file=@student_resume.pdf" \
  -F "center_name=TechBridge Learning Hub" \
  -F "courses_offered=Web Development, Data Analytics, Cloud Computing" \
  -F "description=TechBridge Learning Hub is a premier IT training institute..." \
  -F "course_duration=6 months"
```

### **Example 3: Assistance → Resume Analysis**

```bash
curl -X POST http://localhost:8016/api/v1/a-to-r/analyze \
  -F "resume_file=@job_seeker_resume.pdf" \
  -F "center_name=CareerPath Assistance Center" \
  -F "services=Career Counseling, Resume Writing, Interview Preparation" \
  -F "description=CareerPath Assistance Center helps job seekers achieve their career goals..."
```

---

## **📊 Response Structure:**

All analyze endpoints return:

```json
{
  "success": true,
  "query_id": "jd_Senior_Python_Developer",
  "result_id": "resume.pdf",
  "analysis": {
    "fit_score": 75,
    "summary": "Brief summary...",
    "strengths": [],
    "gaps": [],
    "recommendations": [],
    "detailed_analysis": "# Full Markdown Report\n\n## Executive Fit Summary\n\n..."
  },
  "timestamp": "2025-12-30T20:00:00.000000"
}
```

### **Key Fields:**

- **`fit_score`**: Numeric score (0-100) - default 75
- **`summary`**: Brief summary (first 500 chars)
- **`detailed_analysis`**: **Full markdown report** (matches Streamlit output)
  - Contains all sections (Fit Summary, Strengths, Gaps, Recommendations, etc.)
  - Ready to display or download

---

## **🎯 Analysis Output:**

The `detailed_analysis` field contains a full markdown report with sections like:

### **For Job → Resume (Employer-Facing):**
1. Executive Fit Summary
2. Requirements Match Matrix
3. Concrete Evidence & Signals
4. Risks & Red Flags
5. Interview Plan
6. Calibration & Leveling
7. Offer Recommendation
8. Candidate Feedback

### **For Resume → Job (Candidate-Facing):**
1. Fit Summary
2. Strengths & Highlights
3. Gaps & Deal-Breakers
4. Skills Alignment Matrix
5. Education & Qualifications Check
6. Risks / Watch-outs
7. Resume Tweaks for THIS JD
8. Tailored Cover-Letter Hooks
9. JD-Tailored Resume Summary

### **For Training/Assistance:**
Similar structure tailored to training/assistance context.

---

## **✅ Key Features:**

1. **✅ Multipart Form Data:** File upload + form fields (matches Streamlit)
2. **✅ Full Markdown Reports:** Complete analysis in markdown format
3. **✅ Same Prompts:** Uses exact prompts from Streamlit generative files
4. **✅ Resume Parsing:** Extracts text from PDF, DOCX, TXT, RTF
5. **✅ JSON Structures:** Builds proper JSON from form fields
6. **✅ Error Handling:** Validates file and form data

---

## **🚀 Quick Test:**

### **Swagger UI:**
1. Open: http://localhost:8016/docs
2. Find: `POST /api/v1/j-to-r/analyze` (or any analyze endpoint)
3. Click "Try it out"
4. Upload resume file
5. Fill form fields
6. Click "Execute"

### **Postman:**
1. Method: POST
2. URL: `http://localhost:8016/api/v1/j-to-r/analyze`
3. Body → form-data
4. Add `resume_file` (File type)
5. Add form fields (Text type)
6. Send!

---

## **📚 Related Documentation:**

- `API_POSTMAN_DOCUMENTATION.md` - Complete API documentation
- `API_ARCHITECTURE.md` - API architecture overview
- `API_QUICK_START.md` - Quick start guide

---

**All analyze endpoints are now ready for testing!** 🎉

**Test at:** http://localhost:8016/docs


