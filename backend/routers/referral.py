"""Referral Discovery API router.

Endpoints:
  GET  /referral/paths           — Find referral paths for a company
  GET  /referral/summary/{company} — Full referral summary for a company
  POST /referral/enrich          — Enrich a list of jobs with referral data
  GET  /referral/stats           — CRM-level referral coverage stats
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/referral", tags=["referral"])


class EnrichJobsRequest(BaseModel):
    jobs: list[dict]
    top_n: int = 3


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

@router.get("/paths")
def get_referral_paths(
    company: str = Query(..., description="Target company name"),
    job_title: str = Query("", description="Target role (optional)"),
    top_n: int = Query(5, ge=1, le=20),
    min_score: float = Query(0.20, ge=0.0, le=1.0),
):
    from src.referral.finder import find_referral_paths
    paths = find_referral_paths(
        target_company=company,
        job_title=job_title,
        top_n=top_n,
        min_score=min_score,
    )
    return {
        "company": company,
        "job_title": job_title,
        "paths": [
            {
                "contact_id": p.contact_id,
                "name": p.contact_name,
                "email": p.contact_email,
                "company": p.company,
                "score": p.score,
                "tier": p.tier,
                "reasons": p.reasons,
                "last_contacted": p.last_contacted,
                "touchpoint_count": p.touchpoint_count,
                "suggested_ask": p.suggested_ask,
            }
            for p in paths
        ],
        "count": len(paths),
    }


@router.get("/summary/{company_name}")
def get_referral_summary(
    company_name: str,
    job_title: str = Query(""),
):
    from src.referral.finder import get_referral_summary
    return get_referral_summary(target_company=company_name, job_title=job_title)


# ---------------------------------------------------------------------------
# Enrich jobs
# ---------------------------------------------------------------------------

@router.post("/enrich")
def enrich_jobs(req: EnrichJobsRequest):
    from src.referral.finder import enrich_jobs_with_referrals
    enriched = enrich_jobs_with_referrals(req.jobs, top_n=req.top_n)
    return {"jobs": enriched, "count": len(enriched)}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def referral_stats():
    """Return CRM contact breakdown useful for referral coverage."""
    from src.crm.database import list_contacts
    contacts = list_contacts(limit=1000)
    total = len(contacts)
    with_company = sum(1 for c in contacts if c.get("company"))
    spoke_before = sum(1 for c in contacts if c.get("last_contacted_at"))
    companies = list({c["company"] for c in contacts if c.get("company")})
    return {
        "total_contacts": total,
        "contacts_with_company": with_company,
        "contacts_spoken_to": spoke_before,
        "unique_companies": len(companies),
        "top_companies": companies[:20],
    }
