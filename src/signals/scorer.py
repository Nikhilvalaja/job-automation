"""Company hiring score — role-aware, decay-based, with hiring lag window.

Scoring layers:
1. Base score: exponential decay per signal (30d half-life)
2. Role-aware weights: signals weighted by target role
3. Sector boost: signal text matches role-relevant sectors (+bonus)
4. Multi-signal confidence: more signals in short window = higher confidence
5. Hiring lag window: 0-30d warm → 30-90d peak → 90d+ cooling

Priority score (combining resume match + signals):
  priority = 0.50 * match_score + 0.30 * signal_score
            + 0.10 * sector_boost + 0.10 * hiring_window_bonus
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from src.signals.database import (
    get_signals,
    get_company_score,
    list_company_scores,
    get_signals_stats,
    init_signals_db,
    _get_conn,
    ROLE_SIGNAL_WEIGHTS,
)
from src.signals.normalizer import normalize_company
from src.utils.logging import get_logger

logger = get_logger(__name__)

DECAY_HALF_LIFE_DAYS = 30

# Sector boost keywords per role — these phrases in signal text earn a boost
_SECTOR_BOOST_KEYWORDS: dict[str, list[str]] = {
    "backend": [
        "infrastructure", "cloud platform", "microservices", "api platform",
        "distributed systems", "kubernetes", "aws", "gcp", "azure", "backend",
        "data platform", "streaming", "kafka", "spark", "database", "reliability",
    ],
    "data": [
        "data platform", "data warehouse", "analytics", "machine learning",
        "etl", "spark", "dbt", "snowflake", "databricks", "data infrastructure",
        "healthcare data", "ehr", "health informatics", "data engineering",
        "business intelligence", "real-time analytics",
    ],
    "ml": [
        "artificial intelligence", "machine learning", "deep learning", "llm",
        "generative ai", "ai platform", "neural network", "model training",
        "mlops", "foundation model", "nlp", "computer vision",
    ],
    "devops": [
        "infrastructure", "cloud migration", "devops", "sre", "kubernetes",
        "ci/cd", "platform engineering", "reliability", "observability",
        "federal contract", "government cloud", "dod", "fedramp",
    ],
    "healthcare_tech": [
        "healthcare", "health tech", "ehr", "epic", "cerner", "hipaa",
        "patient data", "clinical", "hospital", "telemedicine", "health it",
        "health informatics", "medical records", "digital health",
        "population health", "care management",
    ],
    "fullstack": [
        "product engineering", "full-stack", "web platform", "saas",
        "consumer app", "developer tools", "platform launch", "growth",
    ],
}

# Sectors that should NOT get a boost (for tech roles)
_NEGATIVE_SECTOR_KEYWORDS: list[str] = [
    "retail store", "brick-and-mortar", "sales leadership", "franchise",
    "restaurant", "logistics operations", "store opening", "physical expansion",
]

# Hiring window bonuses
_HIRING_WINDOW_BONUSES: dict[str, float] = {
    "warm":    0.05,   # 0-30 days: pipeline being built
    "peak":    0.15,   # 30-90 days: active hiring
    "cooling": 0.02,   # 90+ days: mostly filled
    "unknown": 0.00,
}


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

def _decay_factor(discovered_at: str) -> float:
    """Exponential decay: signal from 30 days ago = 50% weight."""
    try:
        dt = datetime.fromisoformat(discovered_at)
        days_ago = (datetime.utcnow() - dt).days
        return math.exp(-math.log(2) * days_ago / DECAY_HALF_LIFE_DAYS)
    except (ValueError, TypeError):
        return 0.5


# ---------------------------------------------------------------------------
# Hiring lag window
# ---------------------------------------------------------------------------

def compute_hiring_window(last_funding_at: str | None) -> str:
    """Determine hiring window based on last funding date.

    0–30 days  → "warm"   (pipeline being built, post-announcement)
    30–90 days → "peak"   (active hiring push)
    90+ days   → "cooling" (most roles filled)
    None       → "unknown"
    """
    if not last_funding_at:
        return "unknown"
    try:
        dt = datetime.fromisoformat(last_funding_at)
        days_since = (datetime.utcnow() - dt).days
        if days_since <= 30:
            return "warm"
        elif days_since <= 90:
            return "peak"
        return "cooling"
    except (ValueError, TypeError):
        return "unknown"


# ---------------------------------------------------------------------------
# Multi-signal confidence
# ---------------------------------------------------------------------------

def compute_signal_confidence(
    company: str,
    window_days: int = 30,
    db_path: Path | None = None,
) -> float:
    """Higher confidence when multiple signals appear in a short window.

    3+ signals in 30 days → 0.90
    2 signals             → 0.75
    1 signal              → 0.60
    0 signals             → 0.30
    """
    cutoff = (datetime.utcnow() - timedelta(days=window_days)).isoformat()
    signals = get_signals(company=company, limit=20, db_path=db_path)
    recent = [s for s in signals if s.get("discovered_at", "") >= cutoff]
    n = len(recent)
    if n >= 3:
        return 0.90
    elif n == 2:
        return 0.75
    elif n == 1:
        return 0.60
    return 0.30


# ---------------------------------------------------------------------------
# Sector boost
# ---------------------------------------------------------------------------

def compute_sector_boost(
    signal_texts: list[str],
    target_role: str = "backend",
) -> float:
    """Compute sector relevance boost from signal text content.

    Checks if signal text contains role-relevant sector keywords.
    Returns 0.0–0.20 boost.

    Also applies negative check — non-tech sectors don't get boost.
    """
    if not signal_texts or not target_role:
        return 0.0

    combined = " ".join(signal_texts).lower()

    # Negative check — if text is about non-tech sector, no boost
    if any(neg_kw in combined for neg_kw in _NEGATIVE_SECTOR_KEYWORDS):
        return 0.0

    boost_keywords = _SECTOR_BOOST_KEYWORDS.get(target_role, [])
    hits = sum(1 for kw in boost_keywords if kw in combined)

    # Graduated boost: 1 hit = 0.05, 2 hits = 0.10, 3+ hits = 0.20
    if hits >= 3:
        return 0.20
    elif hits == 2:
        return 0.10
    elif hits == 1:
        return 0.05
    return 0.0


# ---------------------------------------------------------------------------
# Role-aware company score recomputation
# ---------------------------------------------------------------------------

def recompute_company_score(
    company: str,
    target_role: str = "backend",
    db_path: Path | None = None,
) -> float:
    """Recompute hiring score with role-aware weights and decay.

    Formula:
        score = 0.5 + sum(role_weight * confidence * decay) / normalization
    """
    signals = get_signals(company=company, limit=200, db_path=db_path)
    if not signals:
        return 0.50

    role_weights = ROLE_SIGNAL_WEIGHTS.get(target_role, ROLE_SIGNAL_WEIGHTS["backend"])

    weighted_sum = 0.0
    for sig in signals:
        rw = role_weights.get(sig["signal_type"], 0.0)
        conf = sig.get("confidence", 0.5)
        decay = _decay_factor(sig.get("discovered_at", ""))
        weighted_sum += rw * conf * decay

    normalization = max(len(signals), 1)
    score = 0.5 + (weighted_sum / normalization)
    return min(1.0, max(0.0, score))


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def compute_trend(
    company: str,
    window_days: int = 14,
    db_path: Path | None = None,
) -> str:
    signals = get_signals(company=company, limit=100, db_path=db_path)
    if not signals:
        return "stable"

    cutoff = (datetime.utcnow() - timedelta(days=window_days)).isoformat()
    recent = [s for s in signals if s.get("discovered_at", "") >= cutoff]
    older = [s for s in signals if s.get("discovered_at", "") < cutoff]

    recent_avg = sum(s.get("score_delta", 0.0) for s in recent) / max(len(recent), 1)
    older_avg = sum(s.get("score_delta", 0.0) for s in older) / max(len(older), 1)

    delta = recent_avg - older_avg
    if delta > 0.05:
        return "up"
    elif delta < -0.05:
        return "down"
    return "stable"


# ---------------------------------------------------------------------------
# Refresh + persist
# ---------------------------------------------------------------------------

def refresh_company_score(
    company: str,
    target_role: str = "backend",
    db_path: Path | None = None,
) -> dict:
    """Recompute and persist company score, window, confidence, trend."""
    init_signals_db(db_path)
    canonical = normalize_company(company)
    score = recompute_company_score(company, target_role=target_role, db_path=db_path)
    trend = compute_trend(company, db_path=db_path)
    confidence = compute_signal_confidence(company, db_path=db_path)

    # Sector boost from recent signal texts
    recent_signals = get_signals(company=company, limit=10, db_path=db_path)
    signal_texts = [s.get("signal_text", "") for s in recent_signals]
    sector_boost = compute_sector_boost(signal_texts, target_role)

    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        existing = conn.execute(
            "SELECT last_funding_at FROM company_scores WHERE LOWER(company) = ?",
            (company.lower(),)
        ).fetchone()
        last_funding = existing["last_funding_at"] if existing else None
        window = compute_hiring_window(last_funding)

        if conn.execute(
            "SELECT 1 FROM company_scores WHERE LOWER(company) = ?", (company.lower(),)
        ).fetchone():
            conn.execute(
                """UPDATE company_scores SET
                   canonical_name = ?, hiring_score = ?, trend = ?,
                   signal_confidence = ?, hiring_window = ?, updated_at = ?
                   WHERE LOWER(company) = ?""",
                (canonical, score, trend, confidence, window, now, company.lower()),
            )
        else:
            conn.execute(
                """INSERT INTO company_scores
                   (company, canonical_name, hiring_score, signal_count, positive_signals,
                    negative_signals, trend, signal_confidence, hiring_window, updated_at)
                   VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?, ?)""",
                (company, canonical, score, trend, confidence, window, now),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "company": company,
        "canonical_name": canonical,
        "hiring_score": score,
        "trend": trend,
        "signal_confidence": confidence,
        "hiring_window": window,
        "sector_boost": sector_boost,
    }


# ---------------------------------------------------------------------------
# Priority score formula
# ---------------------------------------------------------------------------

def compute_priority_score(
    match_score: float,
    signal_score: float,
    sector_boost: float = 0.0,
    hiring_window: str = "unknown",
    has_layoff: bool = False,
) -> float:
    """Compute combined priority score for a job opportunity.

    Formula:
        priority = 0.50 * match_score
                 + 0.30 * signal_score
                 + 0.10 * sector_boost (normalized)
                 + 0.10 * hiring_window_bonus

    Layoff signal is a hard penalty: -0.30 from final score.
    """
    window_bonus = _HIRING_WINDOW_BONUSES.get(hiring_window, 0.0)
    score = (
        0.50 * match_score
        + 0.30 * signal_score
        + 0.10 * (sector_boost / 0.20)   # normalize sector_boost (max 0.20 → 1.0)
        + 0.10 * window_bonus / 0.15      # normalize window bonus (max 0.15 → 1.0)
    )
    if has_layoff:
        score -= 0.30
    return min(1.0, max(0.0, score))


# ---------------------------------------------------------------------------
# Priority jobs filter
# ---------------------------------------------------------------------------

def get_priority_jobs(
    target_role: str = "backend",
    min_match_score: float = 0.60,
    hiring_windows: list[str] | None = None,
    min_signal_score: float = 0.40,
    exclude_layoff: bool = True,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    """Return top priority jobs combining resume match + signal scores.

    Queries the jobs DB for scored jobs, enriches with signal data,
    re-ranks by priority score.

    Returns list of enriched job dicts sorted by priority_score DESC.
    """
    hiring_windows = hiring_windows or ["warm", "peak", "unknown"]

    # Pull top-scored jobs from main jobs DB
    jobs = _get_scored_jobs(min_match_score=min_match_score, limit=100)

    if not jobs:
        return []

    # Get unique companies
    companies = list({j.get("company", "") for j in jobs if j.get("company")})
    signal_data = enrich_jobs_with_signals(companies, target_role=target_role, db_path=db_path)

    results = []
    for job in jobs:
        company = job.get("company", "")
        canonical = normalize_company(company)
        sig = signal_data.get(company) or signal_data.get(canonical) or {}

        signal_score = sig.get("hiring_score", 0.50)
        sector_boost = sig.get("sector_boost", 0.0)
        window = sig.get("hiring_window", "unknown")
        has_layoff = sig.get("has_layoff", False)

        if exclude_layoff and has_layoff:
            continue
        if window not in hiring_windows:
            continue
        if signal_score < min_signal_score and signal_score != 0.50:
            # Allow neutral (0.50) through, block low-signal companies
            continue

        priority = compute_priority_score(
            match_score=job.get("relevance_score", 0.0),
            signal_score=signal_score,
            sector_boost=sector_boost,
            hiring_window=window,
            has_layoff=has_layoff,
        )

        results.append({
            **job,
            "canonical_company": canonical,
            "signal_score": signal_score,
            "signal_trend": sig.get("trend", "stable"),
            "signal_confidence": sig.get("signal_confidence", 0.30),
            "hiring_window": window,
            "sector_boost": sector_boost,
            "has_layoff": has_layoff,
            "priority_score": round(priority, 3),
        })

    results.sort(key=lambda x: x["priority_score"], reverse=True)
    return results[:limit]


def _get_scored_jobs(min_match_score: float = 0.60, limit: int = 100) -> list[dict]:
    """Pull scored jobs from the main jobs DB."""
    try:
        from src.crm.database import CRM_DB_PATH
        # The main jobs DB is next to crm.db
        jobs_db = CRM_DB_PATH.parent / "jobs.db"
        if not jobs_db.exists():
            return []
        conn = __import__("sqlite3").connect(str(jobs_db))
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute(
            """SELECT id, title, company, url, relevance_score,
                      missing_skills, status, source
               FROM discovered_jobs
               WHERE relevance_score >= ?
                 AND status NOT IN ('dismissed', 'archived')
               ORDER BY relevance_score DESC
               LIMIT ?""",
            (min_match_score, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"Could not query jobs DB: {e}")
        return []


def enrich_jobs_with_signals(
    companies: list[str],
    target_role: str = "backend",
    db_path: Path | None = None,
) -> dict[str, dict]:
    """Enrich a list of companies with their signal data.

    Returns dict[company_name] → {hiring_score, trend, signal_count,
                                   hiring_window, sector_boost, has_layoff}
    """
    result = {}
    for company in companies:
        canonical = normalize_company(company)
        score_data = get_company_score(company, db_path=db_path)
        if not score_data and canonical != company:
            score_data = get_company_score(canonical, db_path=db_path)

        signals = get_signals(company=company, limit=10, db_path=db_path)
        has_layoff = any(s["signal_type"] == "layoff" for s in signals)
        signal_texts = [s.get("signal_text", "") for s in signals]
        sector_boost = compute_sector_boost(signal_texts, target_role)

        if score_data:
            window = compute_hiring_window(score_data.get("last_funding_at"))
            result[company] = {
                "hiring_score": score_data["hiring_score"],
                "trend": score_data.get("trend", "stable"),
                "signal_count": score_data.get("signal_count", 0),
                "signal_confidence": score_data.get("signal_confidence", 0.30),
                "hiring_window": window,
                "sector_boost": sector_boost,
                "has_layoff": has_layoff,
            }
        else:
            result[company] = {
                "hiring_score": 0.50,
                "trend": "stable",
                "signal_count": 0,
                "signal_confidence": 0.30,
                "hiring_window": "unknown",
                "sector_boost": sector_boost,
                "has_layoff": has_layoff,
            }
    return result


# ---------------------------------------------------------------------------
# Top / Avoid (convenience wrappers)
# ---------------------------------------------------------------------------

def get_top_companies(
    min_score: float = 0.65,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    return list_company_scores(min_score=min_score, limit=limit, db_path=db_path)


def get_avoid_companies(
    max_score: float = 0.30,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    init_signals_db(db_path)
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM company_scores WHERE hiring_score <= ? ORDER BY hiring_score ASC LIMIT ?",
            (max_score, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
