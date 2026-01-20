# Applicant Scoring Solution Guide

## Problem Statement

**Issue:** In the JD–Resume AI matching section, only the top 10 matching resumes were displayed. As a result, applicants whose resumes were not part of these top 10 appeared as empty entries in the applicant tracking system.

**Root Cause:** The AI matching system was limited to returning only the top 10 results. When integrating with an external applicant database, candidates who applied but weren't in the top 10 had no AI scores, resulting in null/empty data.

---

## Solution Overview

We've implemented a **dual-mode system**:

1. **Mode 1: Find Top 10 Matches** (Original functionality)
   - Discover the best candidates for a job posting
   - Shows only top 10 results

2. **Mode 2: Score Specific Applicants** (NEW)
   - Score specific applicants who applied to a job
   - Returns AI scores for ALL applicants, including:
     - ✅ **Top 10**: Best matches
     - 📊 **Ranked #11+**: Lower-ranked but valid matches
     - ❌ **Not Matched**: Very low similarity or not in database

---

## What Changed

### 1. **New Function: `score_applicants()`**
   - **Location**: `j_to_r/streamlit_user_jd_to_resume.py` (lines 356-491)
   - **Purpose**: Score a list of specific applicants, even if not in top 10
   - **Key Features**:
     - Retrieves up to 200 resume chunks (vs. default 40)
     - Returns ALL applicants with their actual rank
     - Handles "Not Matched" cases gracefully (no more empty entries)

### 2. **New UI Tab: "Score Specific Applicants"**
   - **Location**: `j_to_r/streamlit_user_jd_to_resume.py` (lines 648-832)
   - **Features**:
     - Input job details + list of applicant resume IDs
     - Color-coded results (Green=Top 10, Yellow=Ranked, Red=Not Matched)
     - Summary metrics
     - Downloadable CSV

### 3. **Standalone API Module**
   - **Location**: `j_to_r/applicant_scorer_api.py`
   - **Purpose**: Easy integration with external systems
   - **Class**: `ApplicantScorer`

---

## How to Use

### Option 1: Streamlit UI (No Code)

1. **Start the application**:
   ```bash
   cd "C:\WITS\Wits dev\AI Model\j_to_r"
   streamlit run streamlit_user_jd_to_resume.py
   ```

2. **Navigate to "Score Specific Applicants" tab**

3. **Fill in the form**:
   - **Job Details**: Title, description, required skills
   - **Applicant Resume IDs**: One per line (from your applicant database)

   Example:
   ```
   01_Liam_Carter_Senior_Java_Full_Stack_Engineer_Public_Sector_Systems
   02_Ava_Thompson_Lead_Microservices_Engineer_Identity_Access
   alex_gupta_java_developer__entry_level
   ```

4. **Click "Score These Applicants"**

5. **View Results**:
   - Color-coded table with ranks and statuses
   - Summary metrics
   - Download CSV for integration with your ATS

---

### Option 2: Python API (For Integration)

#### Basic Usage

```python
from j_to_r.applicant_scorer_api import ApplicantScorer

# Initialize
scorer = ApplicantScorer()

# Define job
job_description = {
    "title": "Java Full Stack Developer",
    "description": "We need experienced developers with Spring Boot and React",
    "required_skills": ["Java", "Spring Boot", "React", "AWS"]
}

# List of applicants (from your ATS database)
applicant_resume_ids = [
    "resume_001",
    "resume_002",
    "resume_003"
]

# Get scores
results = scorer.score_applicants(job_description, applicant_resume_ids)

# Process results
for result in results:
    print(f"Candidate: {result['candidate_name']}")
    print(f"Status: {result['status']}")
    print(f"Rank: {result['rank']}")
    print(f"Match %: {result['match_pct']}")
    print("---")
```

#### Simplified Function

```python
from j_to_r.applicant_scorer_api import score_applicants_simple

results = score_applicants_simple(
    job_title="Java Developer",
    job_description="Experienced with Spring Boot...",
    required_skills=["Java", "Spring Boot", "AWS"],
    applicant_resume_ids=["resume_001", "resume_002"]
)
```

---

### Option 3: Integration with Existing ATS

#### Scenario: Merge AI scores with applicant database

```python
import pandas as pd
from j_to_r.applicant_scorer_api import ApplicantScorer

# 1. Load your applicant database
applicants_df = pd.read_csv("applicants_for_job_123.csv")
# Columns: applicant_id, name, email, resume_id, application_date, etc.

# 2. Initialize scorer
scorer = ApplicantScorer()

# 3. Define job (from your ATS)
job = {
    "title": "Senior Java Developer",
    "description": "...",
    "required_skills": ["Java", "Spring Boot", "Microservices"]
}

# 4. Get AI scores for ALL applicants
resume_ids = applicants_df["resume_id"].tolist()
ai_scores = scorer.score_applicants(job, resume_ids)

# 5. Convert to DataFrame
ai_df = pd.DataFrame(ai_scores)

# 6. Merge with your applicant data
merged = applicants_df.merge(
    ai_df[["resume_id", "rank", "status", "match_pct"]],
    on="resume_id",
    how="left"
)

# 7. Fill missing ranks (applicants not in AI database)
merged["status"] = merged["status"].fillna("Not in AI Database")
merged["rank"] = merged["rank"].fillna(999)
merged["match_pct"] = merged["match_pct"].fillna(0.0)

# 8. Save or display
print(merged[["name", "status", "rank", "match_pct"]])
merged.to_csv("applicants_with_ai_scores.csv", index=False)
```

---

## Resume ID Format

**Important**: Resume IDs must match the format stored in ChromaDB.

### Common Formats:
1. `{filename_without_extension}`
   - Example: `john_doe_resume`

2. `{filename}.{sha256_hash}`
   - Example: `john_doe_resume.5f7810d02efb`

### How to Find the Correct Format:

```python
import chromadb

# Connect to ChromaDB
client = chromadb.PersistentClient(path="./chroma_resumes")
collection = client.get_collection(name="resumes")

# Query a few records to see the format
results = collection.get(limit=5, include=["metadatas"])

# Check the resume_id field
for meta in results["metadatas"]:
    print(meta.get("resume_id") or meta.get("parent_id"))
```

---

## Return Value Structure

Each applicant result contains:

```python
{
    "resume_id": "01_Liam_Carter...",
    "candidate_name": "Liam Carter",
    "email": "liam.carter@example.com",
    "phone": "+1-555-0100",
    "status": "Top 10",  # or "Ranked #15" or "Not Matched"
    "rank": 3,           # 1-based rank, or None if not matched
    "match_pct": 87.5,   # Relative match percentage (0-100)
    "sim": 0.845,        # Raw normalized similarity (0-1)
    "preview": "Senior Java Full Stack Engineer with 8+ years..."
}
```

### Status Values:
- **"Top 10"**: Applicant is in the top 10 AI matches
- **"Ranked #N"**: Applicant ranked beyond top 10 (e.g., "Ranked #15")
- **"Not Matched"**: Resume not found or similarity too low

---

## Configuration

### Increase Retrieval Coverage

By default, the system retrieves 200 chunks when scoring applicants. If you have many resumes, increase this in `.env`:

```bash
# .env file
R2J_TOP_K_VECTOR=500  # Retrieve more chunks for better coverage
```

### Keep Top 10 Limit for Main Search

The original "Find Top 10" functionality remains unchanged and still returns only top 10:

```bash
R2J_TOP_K_FINAL=10  # Main search limit (unchanged)
```

---

## Testing

### Test with Sample Data

```bash
cd "C:\WITS\Wits dev\AI Model\j_to_r"
python applicant_scorer_api.py
```

This will run the example in the `__main__` block and show:
- Scores for 4 sample applicants
- Status, rank, and match percentage
- Handling of non-existent resume IDs

---

## Benefits

✅ **No More Empty Entries**: All applicants get proper AI scores or "Not Matched" status

✅ **Keeps Top 10 Intact**: Original functionality unchanged

✅ **Easy Integration**: Python API for ATS integration

✅ **Full Visibility**: See actual ranks for all applicants (not just top 10)

✅ **Better UX**: Color-coded UI, summary metrics, downloadable reports

---

## Files Modified/Created

### Modified:
1. ✅ `j_to_r/streamlit_user_jd_to_resume.py`
   - Added `score_applicants()` function (lines 356-491)
   - Added Tab 2 UI (lines 498, 648-832)

2. ✅ `.env`
   - Reset to default configuration (top 10 limit)

3. ✅ `j_to_r/config_jds_resumes.py`
   - Reverted to original defaults

### Created:
1. ✅ `j_to_r/applicant_scorer_api.py`
   - Standalone Python API module
   - `ApplicantScorer` class
   - Convenience functions

2. ✅ `APPLICANT_SCORING_GUIDE.md` (this file)
   - Complete documentation

---

## Troubleshooting

### Issue: "Resume not found in AI index"

**Cause**: Resume ID doesn't exist in ChromaDB or format mismatch

**Solution**:
1. Verify resume was ingested: Check `j_to_r/resumes_store/` directory
2. Check resume ID format in ChromaDB (see "Resume ID Format" section above)
3. Re-ingest the resume using the admin tool

### Issue: All applicants showing "Not Matched"

**Cause**: Retrieval limit too low or collection name mismatch

**Solution**:
1. Increase `R2J_TOP_K_VECTOR` in `.env` (try 500 or 1000)
2. Verify collection name: Should be "resumes" (check `config_jds_resumes.py`)
3. Restart Streamlit app after changing `.env`

### Issue: Ollama embedding errors

**Cause**: Ollama not running or model not pulled

**Solution**:
```bash
# Start Ollama
ollama serve

# Pull embedding model
ollama pull nomic-embed-text
```

---

## Next Steps

1. **Test the UI**: Run Streamlit and try the "Score Specific Applicants" tab
2. **Test the API**: Run `python applicant_scorer_api.py` to see examples
3. **Integrate with ATS**: Use the Python API to merge AI scores with your applicant database
4. **Adjust Configuration**: Tune `R2J_TOP_K_VECTOR` based on your resume database size

---

## Support

For issues or questions:
- Check Ollama is running: `ollama list`
- Verify ChromaDB path: `./j_to_r/chroma_resumes`
- Check resume ingestion: `./j_to_r/resumes_store/`

---

**Last Updated**: 2025-10-31
**Solution Type**: Scenario A - Applicant Database Integration
