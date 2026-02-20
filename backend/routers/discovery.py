"""Discovery API — search, filter, and manage discovered jobs.

Endpoints:
- GET  /discovery/jobs      — Search with LinkedIn-level filters
- GET  /discovery/stats     — Dashboard statistics
- PATCH /discovery/jobs/{id} — Update status (save, dismiss, apply)
- POST /discovery/parse     — Trigger ML parsing on unparsed jobs
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.discovery.database import (
    get_stats,
    get_unparsed_jobs,
    init_db,
    search_jobs,
    update_parsed_fields,
    update_status,
)
from src.discovery.parser import JobParser

router = APIRouter(prefix="/discovery", tags=["discovery"])

# Ensure DB tables exist on import
init_db()


class DiscoverySearchResponse(BaseModel):
    jobs: list[dict]
    total: int
    page: int
    per_page: int


class DiscoveryStatsResponse(BaseModel):
    total: int
    parsed: int
    unparsed: int
    by_category: dict
    by_level: dict
    by_type: dict
    by_status: dict


class StatusUpdate(BaseModel):
    status: str  # new, saved, applied, dismissed


@router.get("/jobs", response_model=DiscoverySearchResponse)
async def search_discovered_jobs(
    category: str = Query("", description="backend, data_science, ml_engineer, etc."),
    experience_level: str = Query("", description="entry, mid, senior, lead, staff"),
    years_min: int = Query(0, description="Min years of experience"),
    years_max: int = Query(99, description="Max years of experience"),
    job_type: str = Query("", description="full_time, part_time, contract, internship"),
    remote_type: str = Query("", description="remote, hybrid, onsite"),
    keyword: str = Query("", description="Search in title, description, skills"),
    company: str = Query("", description="Filter by company name"),
    status: str = Query("", description="new, saved, applied, dismissed"),
    min_score: float = Query(0.0, description="Minimum match score"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> DiscoverySearchResponse:
    """Search discovered jobs with advanced filters."""
    offset = (page - 1) * per_page
    jobs, total = search_jobs(
        category=category,
        experience_level=experience_level,
        experience_years_min=years_min,
        experience_years_max=years_max,
        job_type=job_type,
        remote_type=remote_type,
        keyword=keyword,
        company=company,
        status=status,
        min_score=min_score,
        limit=per_page,
        offset=offset,
    )
    return DiscoverySearchResponse(jobs=jobs, total=total, page=page, per_page=per_page)


@router.get("/stats", response_model=DiscoveryStatsResponse)
async def discovery_stats() -> DiscoveryStatsResponse:
    """Get discovery database statistics."""
    stats = get_stats()
    return DiscoveryStatsResponse(**stats)


@router.patch("/jobs/{job_id}")
async def update_job_status(job_id: str, body: StatusUpdate):
    """Update a discovered job's status."""
    if body.status not in ("new", "saved", "applied", "dismissed"):
        raise HTTPException(status_code=400, detail="Status must be: new, saved, applied, dismissed")
    update_status(job_id, body.status)
    return {"ok": True, "id": job_id, "status": body.status}


@router.post("/parse")
async def parse_unparsed_jobs(limit: int = Query(20, ge=1, le=100)):
    """Run keyword parser on unparsed discovered jobs."""
    unparsed = get_unparsed_jobs(limit=limit)
    if not unparsed:
        return {"parsed": 0, "message": "No unparsed jobs"}

    parser = JobParser()
    count = 0
    for job in unparsed:
        try:
            fields = parser.parse(job)
            update_parsed_fields(job["id"], fields)
            count += 1
        except Exception:
            pass

    return {"parsed": count, "total_unparsed": len(unparsed)}
