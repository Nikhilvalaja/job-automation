"""Referral path finder.

For a given job (company + title), finds the best referral contacts
from the CRM database and returns them ranked by closeness score.

Usage:
    paths = find_referral_paths("Stripe", job_title="Backend Engineer", top_n=5)
    # Returns list of ReferralScore, sorted best-first
"""

from __future__ import annotations

from pathlib import Path

from src.referral.scorer import ReferralScore, score_contact_for_company
from src.utils.logging import get_logger

logger = get_logger(__name__)


def find_referral_paths(
    target_company: str,
    job_title: str = "",
    top_n: int = 5,
    min_score: float = 0.20,
    crm_db_path: Path | None = None,
) -> list[ReferralScore]:
    """Find best referral contacts for target_company from CRM.

    Args:
        target_company: Company you're applying to
        job_title: Optional role for context
        top_n: Max results to return
        min_score: Minimum closeness score to include
        crm_db_path: CRM DB path (default: production)

    Returns:
        List of ReferralScore sorted by score descending
    """
    from src.crm.database import list_contacts, get_touchpoints

    contacts = list_contacts(limit=500, db_path=crm_db_path)
    if not contacts:
        logger.info(f"No CRM contacts found for referral search ({target_company})")
        return []

    results: list[ReferralScore] = []
    for contact in contacts:
        # Skip blocked/archived contacts
        if contact.get("status") in ("blocked", "archived"):
            continue

        # Get touchpoints for recency scoring
        try:
            tps = get_touchpoints(contact_id=contact["id"], db_path=crm_db_path)
        except Exception:
            tps = []

        rs = score_contact_for_company(
            contact=contact,
            target_company=target_company,
            touchpoints=tps,
        )

        if rs.score >= min_score:
            results.append(rs)

    results.sort(key=lambda x: x.score, reverse=True)
    return results[:top_n]


def get_referral_summary(
    target_company: str,
    job_title: str = "",
    crm_db_path: Path | None = None,
) -> dict:
    """Get a human-readable referral summary for a company."""
    paths = find_referral_paths(
        target_company=target_company,
        job_title=job_title,
        top_n=10,
        crm_db_path=crm_db_path,
    )

    if not paths:
        return {
            "company": target_company,
            "job_title": job_title,
            "best_path": None,
            "total_paths": 0,
            "paths": [],
            "summary": f"No referral contacts found for {target_company}.",
        }

    best = paths[0]
    summary_line = (
        f"Best path to {target_company}: {best.contact_name} "
        f"({', '.join(best.reasons)}) — score {best.score:.0%}"
    )

    return {
        "company": target_company,
        "job_title": job_title,
        "best_path": {
            "name": best.contact_name,
            "email": best.contact_email,
            "score": best.score,
            "tier": best.tier,
            "reasons": best.reasons,
            "suggested_ask": best.suggested_ask,
        },
        "total_paths": len(paths),
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
        "summary": summary_line,
    }


def enrich_jobs_with_referrals(
    jobs: list[dict],
    top_n: int = 3,
    crm_db_path: Path | None = None,
) -> list[dict]:
    """Add referral data to a list of job dicts (each must have 'company' key)."""
    enriched = []
    for job in jobs:
        company = job.get("company", "")
        if not company:
            enriched.append({**job, "referral_paths": [], "best_referral": None})
            continue

        paths = find_referral_paths(
            target_company=company,
            job_title=job.get("role", ""),
            top_n=top_n,
            crm_db_path=crm_db_path,
        )

        best = paths[0] if paths else None
        enriched.append({
            **job,
            "referral_paths": [
                {
                    "name": p.contact_name,
                    "email": p.contact_email,
                    "score": p.score,
                    "tier": p.tier,
                    "reasons": p.reasons,
                }
                for p in paths
            ],
            "best_referral": {
                "name": best.contact_name,
                "email": best.contact_email,
                "score": best.score,
                "tier": best.tier,
                "suggested_ask": best.suggested_ask,
            } if best else None,
        })

    return enriched
