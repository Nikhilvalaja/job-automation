"""Referral path finder.

For a given job (company + title), finds the best referral contacts
from the CRM database and returns them ranked by final_score.

final_score = closeness * role_alignment * signal_multiplier * hiring_window_multiplier
Fatigue-blocked contacts are excluded.
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
    use_signals: bool = True,
    crm_db_path: Path | None = None,
) -> list[ReferralScore]:
    """Find best referral contacts for target_company from CRM.

    Excludes fatigue-blocked contacts.
    Ranks by final_score (closeness × role_alignment × signal × hiring_window).
    """
    from src.crm.database import list_contacts, get_touchpoints

    contacts = list_contacts(limit=500, db_path=crm_db_path)
    if not contacts:
        logger.info(f"No CRM contacts found for referral search ({target_company})")
        return []

    results: list[ReferralScore] = []
    for contact in contacts:
        if contact.get("status") in ("blocked", "archived"):
            continue

        try:
            tps = get_touchpoints(contact_id=contact["id"], db_path=crm_db_path)
        except Exception:
            tps = []

        rs = score_contact_for_company(
            contact=contact,
            target_company=target_company,
            target_job_title=job_title,
            touchpoints=tps,
            use_signals=use_signals,
        )

        # Exclude fatigue-blocked or below threshold
        if rs.fatigue_blocked:
            logger.debug(f"  Fatigue-blocked: {rs.contact_email} — {rs.fatigue_reason}")
            continue

        if rs.final_score >= min_score:
            results.append(rs)

    results.sort(key=lambda x: x.final_score, reverse=True)
    return results[:top_n]


def get_referral_summary(
    target_company: str,
    job_title: str = "",
    use_signals: bool = True,
    crm_db_path: Path | None = None,
) -> dict:
    """Get a human-readable referral summary for a company."""
    paths = find_referral_paths(
        target_company=target_company,
        job_title=job_title,
        top_n=10,
        use_signals=use_signals,
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
        f"({', '.join(best.reasons[:3])}) — score {best.final_score:.0%}"
    )

    return {
        "company": target_company,
        "job_title": job_title,
        "best_path": {
            "name": best.contact_name,
            "email": best.contact_email,
            "score": best.final_score,
            "closeness_score": best.closeness_score,
            "role_alignment_score": best.role_alignment_score,
            "signal_multiplier": best.signal_multiplier,
            "hiring_window": best.hiring_window,
            "tier": best.tier,
            "reasons": best.reasons,
            "suggested_ask": best.suggested_ask,
        },
        "total_paths": len(paths),
        "paths": [_path_dict(p) for p in paths],
        "summary": summary_line,
    }


def _path_dict(p: ReferralScore) -> dict:
    return {
        "contact_id": p.contact_id,
        "name": p.contact_name,
        "email": p.contact_email,
        "company": p.company,
        "contact_role": p.contact_role,
        "score": p.final_score,
        "closeness_score": p.closeness_score,
        "role_alignment_score": p.role_alignment_score,
        "signal_multiplier": p.signal_multiplier,
        "hiring_window_multiplier": p.hiring_window_multiplier,
        "tier": p.tier,
        "reasons": p.reasons,
        "last_contacted": p.last_contacted,
        "touchpoint_count": p.touchpoint_count,
        "hiring_window": p.hiring_window,
        "signal_context": p.signal_context,
        "suggested_ask": p.suggested_ask,
    }


def enrich_jobs_with_referrals(
    jobs: list[dict],
    top_n: int = 3,
    use_signals: bool = True,
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
            use_signals=use_signals,
            crm_db_path=crm_db_path,
        )

        best = paths[0] if paths else None
        enriched.append({
            **job,
            "referral_paths": [_path_dict(p) for p in paths],
            "best_referral": {
                "name": best.contact_name,
                "email": best.contact_email,
                "score": best.final_score,
                "tier": best.tier,
                "suggested_ask": best.suggested_ask,
            } if best else None,
        })

    return enriched
