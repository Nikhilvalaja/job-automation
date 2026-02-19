"""Job application CRUD endpoints.

All Google Sheets writes are centralized here. Bots, extension, and dashboard
all go through these endpoints.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_sheets_client
from src.models import JobCreate, JobListResponse, JobResponse, JobStatus, JobUpdate
from src.sheets.client import SheetsClient
from src.utils.logging import get_logger

logger = get_logger("backend.routers.jobs")

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _sheets_error(e: Exception) -> HTTPException:
    """Convert Sheets errors into clean HTTP responses."""
    logger.error(f"Sheets operation failed: {e}")
    if isinstance(e, FileNotFoundError):
        return HTTPException(status_code=503, detail="Google Sheets credentials not configured")
    return HTTPException(status_code=502, detail=f"Google Sheets error: {type(e).__name__}")


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    job: JobCreate,
    sheets: SheetsClient = Depends(get_sheets_client),
) -> JobResponse:
    """Create a new job application entry."""
    try:
        return sheets.add_job(job)
    except HTTPException:
        raise
    except Exception as e:
        raise _sheets_error(e)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = None,
    sheets: SheetsClient = Depends(get_sheets_client),
) -> JobListResponse:
    """List all job applications, optionally filtered by status."""
    try:
        jobs = sheets.get_all_jobs(status_filter=status)
        return JobListResponse(jobs=jobs, total=len(jobs))
    except HTTPException:
        raise
    except Exception as e:
        raise _sheets_error(e)


@router.get("/{app_id}", response_model=JobResponse)
async def get_job(
    app_id: str,
    sheets: SheetsClient = Depends(get_sheets_client),
) -> JobResponse:
    """Get a single job application by ID."""
    try:
        job = sheets.get_job(app_id)
    except Exception as e:
        raise _sheets_error(e)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {app_id} not found")
    return job


@router.patch("/{app_id}", response_model=JobResponse)
async def update_job(
    app_id: str,
    updates: JobUpdate,
    sheets: SheetsClient = Depends(get_sheets_client),
) -> JobResponse:
    """Update specific fields of a job application."""
    try:
        job = sheets.update_job(app_id, updates)
    except Exception as e:
        raise _sheets_error(e)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {app_id} not found")
    return job


@router.patch("/by-thread/{thread_id}", response_model=JobResponse)
async def update_job_by_thread(
    thread_id: str,
    updates: JobUpdate,
    sheets: SheetsClient = Depends(get_sheets_client),
) -> JobResponse:
    """Update a job application by Gmail thread ID (used by email bot)."""
    try:
        job = sheets.update_by_thread_id(thread_id, updates)
    except Exception as e:
        raise _sheets_error(e)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job with thread {thread_id} not found")
    return job


@router.delete("/{app_id}", response_model=JobResponse)
async def delete_job(
    app_id: str,
    sheets: SheetsClient = Depends(get_sheets_client),
) -> JobResponse:
    """Soft delete a job application (sets status to Archived)."""
    try:
        job = sheets.update_job(app_id, JobUpdate(status=JobStatus.ARCHIVED))
    except Exception as e:
        raise _sheets_error(e)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {app_id} not found")
    return job
