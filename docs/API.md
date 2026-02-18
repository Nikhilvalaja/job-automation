# API Reference — Job Automation Ecosystem

Base URL: `http://localhost:8000`

## Health

### GET /health
Basic health check.

**Response:** `{"status": "ok", "version": "0.1.0", "sheets_connected": false}`

### GET /ready
Readiness check (verifies Sheets connection).

**Response:** `{"status": "ready", "version": "0.1.0", "sheets_connected": true}`

## Jobs

### POST /jobs
Create a new job application.

**Request Body:**
```json
{
  "company": "Google",
  "role": "Software Engineer",
  "source": "LinkedIn",
  "job_url": "https://careers.google.com/...",
  "status": "Applied",
  "date_applied": "2026-02-18",
  "notes": "Referred by John"
}
```

**Response:** `JobResponse` with generated `app_id`

### GET /jobs
List all job applications.

**Query Params:** `?status=Applied` (optional filter)

**Response:** `{"jobs": [...], "total": 42}`

### GET /jobs/{app_id}
Get a single job by ID.

### PATCH /jobs/{app_id}
Update job fields. Only send fields you want to change.

**Request Body:**
```json
{
  "status": "Interview",
  "notes": "Phone screen scheduled for Friday"
}
```

### PATCH /jobs/by-thread/{thread_id}
Update a job by Gmail thread ID (used by email bot).

### DELETE /jobs/{app_id}
Soft delete (sets status to "Archived").

## Cover Letter

### POST /cover-letter/generate
Generate a cover letter.

**Request Body:**
```json
{
  "company": "Google",
  "role": "Software Engineer",
  "job_description": "We are looking for...",
  "resume_text": "Experienced developer with...",
  "mode": "llm"
}
```

**Response:** `{"cover_letter": "Dear Hiring Manager,...", "mode": "llm", "tokens_used": 350}`
