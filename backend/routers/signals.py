"""Signals API router.

Endpoints:
  GET  /signals/sources          — List signal sources
  GET  /signals                  — List signals (filterable)
  POST /signals                  — Save a manual signal
  GET  /signals/companies        — List company scores
  GET  /signals/companies/{name} — Get company score + signals
  POST /signals/companies/{name}/refresh  — Recompute score
  GET  /signals/top              — Top hiring companies
  GET  /signals/avoid            — Companies with layoff signals
  GET  /signals/stats            — Signal stats
  POST /signals/classify         — Classify arbitrary text
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalCreateRequest(BaseModel):
    company: str
    signal_type: str
    signal_text: str = ""
    source_url: str = ""
    source_name: str = "manual"
    confidence: float = Field(0.75, ge=0.0, le=1.0)


class ClassifyRequest(BaseModel):
    text: str
    company_hint: str = ""


class EnrichRequest(BaseModel):
    companies: list[str]
    target_role: str = "backend"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

@router.get("/sources")
def list_sources():
    from src.signals.sources import ALL_SIGNAL_SOURCES
    return {
        "sources": [
            {
                "name": s.name,
                "source_type": s.source_type,
                "signal_types": s.signal_types,
                "enabled": s.enabled,
            }
            for s in ALL_SIGNAL_SOURCES
        ]
    }


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

@router.get("/signals")
def list_signals(
    company: str | None = Query(None),
    signal_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    from src.signals.database import get_signals
    return {"signals": get_signals(company=company, signal_type=signal_type, limit=limit)}


@router.post("/signals")
def create_signal(req: SignalCreateRequest):
    from src.signals.database import save_signal
    sig = save_signal(
        company=req.company,
        signal_type=req.signal_type,
        signal_text=req.signal_text,
        source_url=req.source_url,
        source_name=req.source_name,
        confidence=req.confidence,
    )
    return sig


# ---------------------------------------------------------------------------
# Company scores
# ---------------------------------------------------------------------------

@router.get("/companies")
def list_companies(
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    trend: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    from src.signals.database import list_company_scores
    return {"companies": list_company_scores(min_score=min_score, trend=trend, limit=limit)}


@router.get("/companies/{company_name}")
def get_company(company_name: str):
    from src.signals.database import get_company_score, get_signals
    score = get_company_score(company_name)
    if not score:
        raise HTTPException(404, f"No signals for '{company_name}'")
    signals = get_signals(company=company_name, limit=20)
    return {**score, "recent_signals": signals}


@router.post("/companies/{company_name}/refresh")
def refresh_company(company_name: str):
    from src.signals.scorer import refresh_company_score
    return refresh_company_score(company_name)


# ---------------------------------------------------------------------------
# Top / Avoid
# ---------------------------------------------------------------------------

@router.get("/top")
def top_companies(
    min_score: float = Query(0.65, ge=0.0, le=1.0),
    limit: int = Query(20, ge=1, le=100),
):
    from src.signals.scorer import get_top_companies
    return {"companies": get_top_companies(min_score=min_score, limit=limit)}


@router.get("/avoid")
def avoid_companies(
    max_score: float = Query(0.30, ge=0.0, le=1.0),
    limit: int = Query(20, ge=1, le=100),
):
    from src.signals.scorer import get_avoid_companies
    return {"companies": get_avoid_companies(max_score=max_score, limit=limit)}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats():
    from src.signals.database import get_signals_stats
    return get_signals_stats()


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

@router.post("/classify")
def classify_text(req: ClassifyRequest):
    from src.signals.classifier import classify_text as _classify
    result = _classify(req.text, company_hint=req.company_hint)
    return {
        "signal_type": result.signal_type,
        "confidence": result.confidence,
        "matched_keywords": result.matched_keywords,
        "company": result.company,
        "amount": result.amount,
        "sector_tags": result.sector_tags,
    }


# ---------------------------------------------------------------------------
# Priority filter
# ---------------------------------------------------------------------------

@router.get("/priority-filter")
def get_priority_jobs(
    target_role: str = Query("backend"),
    min_match_score: float = Query(0.60, ge=0.0, le=1.0),
    min_signal_score: float = Query(0.40, ge=0.0, le=1.0),
    hiring_windows: str = Query("warm,peak,unknown"),
    exclude_layoff: bool = Query(True),
    limit: int = Query(20, ge=1, le=100),
):
    """Priority Application Filter — jobs ranked by match score + hiring signal.

    Returns jobs where:
    - resume match_score >= min_match_score
    - company signal score is rising (not layoff)
    - hiring_window is active (warm/peak)
    - sector matches target role

    priority_score = 0.50*match + 0.30*signal + 0.10*sector_boost + 0.10*window
    """
    from src.signals.scorer import get_priority_jobs as _get
    windows = [w.strip() for w in hiring_windows.split(",") if w.strip()]
    jobs = _get(
        target_role=target_role,
        min_match_score=min_match_score,
        hiring_windows=windows,
        min_signal_score=min_signal_score,
        exclude_layoff=exclude_layoff,
        limit=limit,
    )
    return {"priority_jobs": jobs, "count": len(jobs), "target_role": target_role}


@router.post("/enrich")
def enrich_companies(req: EnrichRequest):
    """Enrich a list of companies with signal data for a target role."""
    from src.signals.scorer import enrich_jobs_with_signals
    return enrich_jobs_with_signals(req.companies, target_role=req.target_role)


@router.get("/hiring-window/{company_name}")
def get_hiring_window(company_name: str):
    """Get current hiring window for a company."""
    from src.signals.database import get_company_score
    from src.signals.scorer import compute_hiring_window
    score = get_company_score(company_name)
    if not score:
        return {"company": company_name, "hiring_window": "unknown", "last_funding_at": None}
    window = compute_hiring_window(score.get("last_funding_at"))
    return {
        "company": company_name,
        "canonical_name": score.get("canonical_name", company_name),
        "hiring_window": window,
        "last_funding_at": score.get("last_funding_at"),
        "hiring_score": score.get("hiring_score", 0.5),
    }
