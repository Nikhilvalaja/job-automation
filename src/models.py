"""Shared Pydantic models used across all modules.

These are the data contracts between backend, bots, dashboard, and extension.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, enum.Enum):
    """All possible states for a job application."""
    TO_APPLY = "To Apply"
    APPLIED = "Applied"
    ASSESSMENT = "Assessment"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECT = "Reject"
    NO_REPLY = "No Reply"
    WITHDRAWN = "Withdrawn"
    ARCHIVED = "Archived"


class JobCreate(BaseModel):
    """Schema for creating a new job application."""
    company: str
    role: str
    source: str = ""
    job_url: str = ""
    status: JobStatus = JobStatus.TO_APPLY
    date_applied: Optional[date] = None
    notes: str = ""


class JobUpdate(BaseModel):
    """Schema for updating a job application. All fields optional."""
    company: Optional[str] = None
    role: Optional[str] = None
    source: Optional[str] = None
    job_url: Optional[str] = None
    status: Optional[JobStatus] = None
    date_applied: Optional[date] = None
    last_email_date: Optional[date] = None
    thread_id: Optional[str] = None
    next_action_date: Optional[date] = None
    notes: Optional[str] = None


class JobResponse(BaseModel):
    """Schema returned when reading a job application."""
    app_id: str
    date_added: str
    date_applied: str
    company: str
    role: str
    source: str
    job_url: str
    status: JobStatus
    last_email_date: str
    thread_id: str
    next_action_date: str
    notes: str


class JobListResponse(BaseModel):
    """Wrapper for returning multiple jobs."""
    jobs: list[JobResponse]
    total: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str = "0.1.0"
    sheets_connected: bool = False


class CoverLetterRequest(BaseModel):
    """Request to generate a cover letter."""
    company: str
    role: str
    job_description: str
    resume_text: str = ""
    tone: str = "professional"  # professional, conversational, technical, executive
    extra_instructions: str = ""  # user's custom instructions (e.g., "mention my AWS certs")
    mode: str = "llm"  # "template" or "llm"


class CoverLetterResponse(BaseModel):
    """Generated cover letter response."""
    cover_letter: str
    mode: str
    tokens_used: int = 0


class ResumeTailorRequest(BaseModel):
    """Request to tailor a resume for a specific job."""
    company: str
    role: str
    job_description: str
    resume_text: str
    focus_skills: list[str] = []  # skills to emphasize


class ResumeTailorResponse(BaseModel):
    """Tailored resume response."""
    tailored_resume: str
    changes_summary: str
    tokens_used: int = 0
