"""Company hiring score over time — decay, trend, composite scoring.

Hiring score is NOT just count of signals.
It considers:
  - Signal recency (older signals decay)
  - Signal type weights (funding > product, layoff is strongly negative)
  - Confidence of each signal
  - Trend direction (improving vs worsening)
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from src.signals.database import (
    get_signals,
    get_company_score,
    list_company_scores,
    save_signal,
    init_signals_db,
    _get_conn,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Decay half-life: signal influence halves every N days
DECAY_HALF_LIFE_DAYS = 30

# Weight per signal type (before confidence and decay)
_TYPE_WEIGHTS: dict[str, float] = {
    "funding":     0.35,
    "expansion":   0.25,
    "acquisition": 0.20,
    "contract":    0.30,
    "leadership":  0.15,
    "product":     0.10,
    "layoff":     -0.60,
    "noise":       0.00,
}


def _decay_factor(discovered_at: str) -> float:
    """Exponential decay: signal from 30 days ago = 50% weight."""
    try:
        dt = datetime.fromisoformat(discovered_at)
        days_ago = (datetime.utcnow() - dt).days
        return math.exp(-math.log(2) * days_ago / DECAY_HALF_LIFE_DAYS)
    except (ValueError, TypeError):
        return 0.5


def recompute_company_score(
    company: str,
    db_path: Path | None = None,
) -> float:
    """Recompute hiring score from scratch using all signals with decay.

    Formula:
        score = 0.5 + sum(type_weight * confidence * decay_factor) / normalization

    Clamped to [0.0, 1.0].
    """
    signals = get_signals(company=company, limit=200, db_path=db_path)
    if not signals:
        return 0.50  # No data → neutral

    weighted_sum = 0.0
    for sig in signals:
        tw = _TYPE_WEIGHTS.get(sig["signal_type"], 0.0)
        conf = sig.get("confidence", 0.5)
        decay = _decay_factor(sig.get("discovered_at", ""))
        weighted_sum += tw * conf * decay

    # Normalize: max possible sum if all signals were funding at conf=1, decay=1
    # Soft normalization: divide by signal_count to prevent runaway scores
    normalization = max(len(signals), 1)
    score = 0.5 + (weighted_sum / normalization)
    return min(1.0, max(0.0, score))


def compute_trend(
    company: str,
    window_days: int = 14,
    db_path: Path | None = None,
) -> str:
    """Compute hiring trend: 'up', 'down', or 'stable'.

    Compare average score_delta in last 14 days vs. baseline.
    """
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


def refresh_company_score(
    company: str,
    db_path: Path | None = None,
) -> dict:
    """Recompute and persist the company hiring score + trend."""
    init_signals_db(db_path)
    score = recompute_company_score(company, db_path=db_path)
    trend = compute_trend(company, db_path=db_path)

    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        existing = conn.execute(
            "SELECT * FROM company_scores WHERE LOWER(company) = ?",
            (company.lower(),)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE company_scores SET
                   hiring_score = ?, trend = ?, updated_at = ?
                   WHERE LOWER(company) = ?""",
                (score, trend, now, company.lower()),
            )
        else:
            conn.execute(
                """INSERT INTO company_scores
                   (company, hiring_score, signal_count, positive_signals,
                    negative_signals, trend, updated_at)
                   VALUES (?, ?, 0, 0, 0, ?, ?)""",
                (company, score, trend, now),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "company": company,
        "hiring_score": score,
        "trend": trend,
    }


def get_top_companies(
    min_score: float = 0.65,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    """Get top-scoring companies (likely hiring)."""
    return list_company_scores(min_score=min_score, limit=limit, db_path=db_path)


def get_avoid_companies(
    max_score: float = 0.30,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    """Get companies with low scores (layoff signals, avoid)."""
    init_signals_db(db_path)
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM company_scores
               WHERE hiring_score <= ? ORDER BY hiring_score ASC LIMIT ?""",
            (max_score, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def enrich_jobs_with_signals(
    companies: list[str],
    db_path: Path | None = None,
) -> dict[str, dict]:
    """For a list of companies, return their signal data (for dashboard enrichment).

    Returns dict[company_name] → {hiring_score, trend, signal_count, has_layoff}
    """
    result = {}
    for company in companies:
        score_data = get_company_score(company, db_path=db_path)
        signals = get_signals(company=company, limit=5, db_path=db_path)
        has_layoff = any(s["signal_type"] == "layoff" for s in signals)
        if score_data:
            result[company] = {
                "hiring_score": score_data["hiring_score"],
                "trend": score_data["trend"],
                "signal_count": score_data["signal_count"],
                "has_layoff": has_layoff,
            }
        else:
            result[company] = {
                "hiring_score": 0.5,
                "trend": "stable",
                "signal_count": 0,
                "has_layoff": has_layoff,
            }
    return result
