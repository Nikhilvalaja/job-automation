"""Supervisor API router — unified command center.

Endpoints:
  GET  /supervisor/today        — Today's priority actions (all systems)
  GET  /supervisor/stats        — System-wide snapshot stats
  GET  /supervisor/funnel       — Pipeline funnel
  GET  /supervisor/top-jobs     — Top scoring unapplied jobs
  GET  /supervisor/avoid        — Companies with layoff signals
"""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


@router.get("/today")
def get_todays_actions(
    max_total: int = Query(20, ge=1, le=50),
    include_jobs: bool = Query(True),
    include_signals: bool = Query(True),
    include_referrals: bool = Query(True),
):
    from src.supervisor.engine import get_todays_actions
    actions = get_todays_actions(
        max_total=max_total,
        include_jobs=include_jobs,
        include_signals=include_signals,
        include_referrals=include_referrals,
    )
    return {"actions": actions, "count": len(actions)}


@router.get("/stats")
def get_stats():
    from src.supervisor.engine import get_system_stats
    return get_system_stats()


@router.get("/funnel")
def get_funnel():
    from src.supervisor.engine import get_pipeline_funnel
    return get_pipeline_funnel()


@router.get("/top-jobs")
def top_jobs(
    min_score: float = Query(0.70, ge=0.0, le=1.0),
    limit: int = Query(10, ge=1, le=50),
):
    """Top scoring jobs with best resume suggestion."""
    try:
        from src.database import get_db
        conn = get_db()
        rows = conn.execute(
            """SELECT job_id, company, role, url, match_score, source,
                      date_applied, status
               FROM jobs
               WHERE match_score >= ?
               ORDER BY match_score DESC
               LIMIT ?""",
            (min_score, limit),
        ).fetchall()
        conn.close()
        return {"jobs": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        return {"jobs": [], "count": 0, "error": str(e)}


@router.get("/avoid")
def avoid_list(
    max_score: float = Query(0.30, ge=0.0, le=1.0),
    limit: int = Query(10, ge=1, le=50),
):
    """Companies with layoff/decline signals — avoid applying."""
    try:
        from src.signals.database import list_company_scores
        companies = list_company_scores(limit=limit * 5)
        avoid = [c for c in companies if c.get("hiring_score", 1.0) <= max_score][:limit]
        return {"companies": avoid, "count": len(avoid)}
    except Exception as e:
        return {"companies": [], "count": 0, "error": str(e)}
