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
    }
