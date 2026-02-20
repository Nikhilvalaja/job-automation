"""Discovery API — search, filter, and manage discovered jobs.

Endpoints:
- GET  /discovery/jobs          — Search with LinkedIn-level filters + sorting
- GET  /discovery/jobs/{id}     — Get full job details
- GET  /discovery/stats         — Dashboard statistics
- GET  /discovery/sources       — Per-source fetch statistics
- PATCH /discovery/jobs/{id}    — Update status (save, dismiss, apply)
- POST /discovery/jobs/{id}/apply — Mark as applied + push to main tracker
- POST /discovery/parse         — Trigger keyword parsing on unparsed jobs
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.discovery.database import (
    get_job_by_id,
    get_source_stats,
    get_stats,
    get_unparsed_jobs,
    init_db,
    mark_applied,
    mark_tracked,
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
    sort_by: str = Query("score", description="score, newest, oldest, company, title"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> DiscoverySearchResponse:
    """Search discovered jobs with advanced filters and sorting."""
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
        sort_by=sort_by,
        limit=per_page,
        offset=offset,
    )
    return DiscoverySearchResponse(jobs=jobs, total=total, page=page, per_page=per_page)


@router.get("/jobs/{job_id}")
async def get_discovered_job(job_id: str):
    """Get full details for a single discovered job."""
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/stats", response_model=DiscoveryStatsResponse)
async def discovery_stats() -> DiscoveryStatsResponse:
    """Get discovery database statistics."""
    stats = get_stats()
    return DiscoveryStatsResponse(**stats)


@router.get("/sources")
async def source_statistics():
    """Get per-source fetch statistics."""
    return {"sources": get_source_stats()}


@router.patch("/jobs/{job_id}")
async def update_job_status(job_id: str, body: StatusUpdate):
    """Update a discovered job's status."""
    if body.status not in ("new", "saved", "applied", "dismissed"):
        raise HTTPException(status_code=400, detail="Status must be: new, saved, applied, dismissed")
    update_status(job_id, body.status)
    return {"ok": True, "id": job_id, "status": body.status}


@router.post("/jobs/{job_id}/apply")
async def apply_to_job(job_id: str):
    """Mark a discovered job as applied and push it to the main tracker.

    Returns the job URL so the frontend can open it.
    """
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Mark applied in discovery DB
    mark_applied(job_id)

    # Push to main tracker (Google Sheets via backend /jobs endpoint)
    tracked = False
    try:
        from src.config import get_settings
        import httpx

        settings = get_settings()
        resp = httpx.post(
            f"{settings.backend_url}/jobs",
            json={
                "company": job.get("company", "Unknown"),
                "role": job["title"],
                "source": f"Discovery ({job.get('source_name', '')})",
                "job_url": job["url"],
                "status": "Applied",
                "notes": f"[Discovery] Score: {job.get('match_score', 0):.2f} | {job.get('category', '')}",
            },
            timeout=10.0,
        )
        if resp.status_code == 201:
            mark_tracked(job_id)
            tracked = True
    except Exception:
        pass  # Tracker push is best-effort

    return {
        "ok": True,
        "id": job_id,
        "url": job["url"],
        "tracked": tracked,
        "title": job["title"],
        "company": job.get("company", ""),
    }


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
