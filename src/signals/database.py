"""Signals database — hiring_signals + company_scores.

Schema:
  hiring_signals  — individual signals (funding, layoff, expansion, etc.)
  company_scores  — aggregated score per company (updated on each new signal)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger(__name__)

SIGNALS_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "signals.db"

SIGNAL_TYPES = frozenset((
    "funding",       # VC/PE investment, IPO
    "expansion",     # new office, new market, hiring wave
    "acquisition",   # company bought another — often integration hiring
    "contract",      # government/enterprise contract win
    "layoff",        # workforce reduction — AVOID signal
    "leadership",    # new CTO/CPO/VP hire — often triggers team builds
    "product",       # major product launch — hiring follows
    "noise",         # detected but not actionable
))

# Base score deltas per signal type (before role-aware adjustments)
_SCORE_WEIGHTS: dict[str, float] = {
    "funding":     +0.30,
    "expansion":   +0.20,
    "acquisition": +0.15,
    "contract":    +0.25,
    "leadership":  +0.10,
    "product":     +0.10,
    "layoff":      -0.50,
    "noise":        0.00,
}

# Role-aware signal weights (2-5 YOE tech roles)
ROLE_SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "backend": {
        "funding":     0.35,  # Strong — often triggers eng hiring
        "expansion":   0.25,
        "contract":    0.30,  # Cloud/infra contracts = backend hiring
        "acquisition": 0.15,
        "leadership":  0.15,  # VP Eng hire → team builds
        "product":     0.10,
        "layoff":     -0.60,  # Engineering layoffs hit backend hard
        "noise":       0.00,
    },
    "data": {
        "funding":     0.30,
        "expansion":   0.25,
        "contract":    0.30,  # Data platform contracts
        "acquisition": 0.15,
        "leadership":  0.15,
        "product":     0.15,  # Data product launches = data team hiring
        "layoff":     -0.60,
        "noise":       0.00,
    },
    "ml": {
        "funding":     0.40,  # AI funding spikes = ML hiring
        "expansion":   0.20,
        "contract":    0.25,  # AI contracts
        "acquisition": 0.20,  # AI acquisitions = ML team absorption
        "leadership":  0.15,
        "product":     0.20,  # AI product launches
        "layoff":     -0.60,
        "noise":       0.00,
    },
    "devops": {
        "funding":     0.30,
        "expansion":   0.20,
        "contract":    0.35,  # Infrastructure contracts are #1 for devops
        "acquisition": 0.10,
        "leadership":  0.10,
        "product":     0.10,
        "layoff":     -0.60,
        "noise":       0.00,
    },
    "healthcare_tech": {
        "funding":     0.30,
        "expansion":   0.30,  # Healthcare expansion = tech hiring
        "contract":    0.35,  # Government healthcare contracts
        "acquisition": 0.20,
        "leadership":  0.20,
        "product":     0.15,
        "layoff":     -0.50,
        "noise":       0.00,
    },
    "fullstack": {
        "funding":     0.35,
        "expansion":   0.25,
        "contract":    0.20,
        "acquisition": 0.15,
        "leadership":  0.15,
        "product":     0.15,
        "layoff":     -0.60,
        "noise":       0.00,
    },
}


def _get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or SIGNALS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrate_signals_columns(conn: sqlite3.Connection) -> None:
    """Add new columns to existing tables without breaking old data."""
    new_cols = {
        "company_scores": [
            ("canonical_name", "TEXT DEFAULT ''"),
            ("hiring_window", "TEXT DEFAULT 'unknown'"),  # warm/peak/cooling/unknown
            ("last_funding_at", "TEXT DEFAULT NULL"),
            ("signal_confidence", "REAL DEFAULT 0.5"),
            ("sector_tags", "TEXT DEFAULT '[]'"),         # JSON list of detected sectors
        ],
        "hiring_signals": [
            ("canonical_company", "TEXT DEFAULT ''"),
            ("sector_tags", "TEXT DEFAULT '[]'"),
            ("target_role", "TEXT DEFAULT ''"),
        ],
    }
    for table, cols in new_cols.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for col_name, col_def in cols:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
    conn.commit()


def init_signals_db(db_path: Path | None = None) -> None:
    """Initialize signals schema. Idempotent."""
    conn = _get_conn(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS hiring_signals (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_text TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                source_name TEXT DEFAULT '',
                confidence REAL DEFAULT 0.5,
                score_delta REAL DEFAULT 0.0,
                discovered_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS company_scores (
                company TEXT PRIMARY KEY,
                hiring_score REAL DEFAULT 0.5,
                signal_count INTEGER DEFAULT 0,
                positive_signals INTEGER DEFAULT 0,
                negative_signals INTEGER DEFAULT 0,
                last_signal_at TEXT DEFAULT NULL,
                trend TEXT DEFAULT 'stable',
                notes TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_signals_company   ON hiring_signals(company);
            CREATE INDEX IF NOT EXISTS idx_signals_type      ON hiring_signals(signal_type);
            CREATE INDEX IF NOT EXISTS idx_signals_date      ON hiring_signals(discovered_at);
            CREATE INDEX IF NOT EXISTS idx_scores_score      ON company_scores(hiring_score DESC);
        """)
        _migrate_signals_columns(conn)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Signals CRUD
# ---------------------------------------------------------------------------

def save_signal(
    company: str,
    signal_type: str,
    signal_text: str = "",
    source_url: str = "",
    source_name: str = "",
    confidence: float = 0.5,
    sector_tags: list[str] | None = None,
    target_role: str = "",
    db_path: Path | None = None,
) -> dict:
    """Save a new hiring signal and update the company's score."""
    from src.signals.normalizer import normalize_company
    if signal_type not in SIGNAL_TYPES:
        signal_type = "noise"

    canonical = normalize_company(company)

    init_signals_db(db_path)
    conn = _get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        sig_id = str(uuid.uuid4())[:8]
        score_delta = _SCORE_WEIGHTS.get(signal_type, 0.0) * confidence
        sector_json = json.dumps(sector_tags or [])

        conn.execute(
            """INSERT INTO hiring_signals
               (id, company, canonical_company, signal_type, signal_text,
                source_url, source_name, confidence, score_delta,
                sector_tags, target_role, discovered_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sig_id, company, canonical, signal_type, signal_text[:1000],
             source_url, source_name, confidence, score_delta,
             sector_json, target_role, now, now),
        )

        # Update company_scores
        existing = conn.execute(
            "SELECT * FROM company_scores WHERE company = ?", (company,)
        ).fetchone()

        is_positive = score_delta > 0
        is_negative = score_delta < 0

        if existing:
            existing = dict(existing)
            new_score = min(1.0, max(0.0, existing["hiring_score"] + score_delta))
            new_count = existing["signal_count"] + 1
            new_pos = existing["positive_signals"] + (1 if is_positive else 0)
            new_neg = existing["negative_signals"] + (1 if is_negative else 0)

            # Trend: compare to previous score
            if new_score > existing["hiring_score"] + 0.05:
                trend = "up"
            elif new_score < existing["hiring_score"] - 0.05:
                trend = "down"
            else:
                trend = existing.get("trend", "stable")

            # Track last funding date for hiring window calculation
            last_funding = existing.get("last_funding_at") or ""
            if signal_type == "funding":
                last_funding = now

            conn.execute(
                """UPDATE company_scores SET
                   canonical_name = ?, hiring_score = ?, signal_count = ?,
                   positive_signals = ?, negative_signals = ?,
                   last_signal_at = ?, last_funding_at = ?, trend = ?, updated_at = ?
                   WHERE company = ?""",
                (canonical, new_score, new_count, new_pos, new_neg,
                 now, last_funding or None, trend, now, company),
            )
        else:
            init_score = min(1.0, max(0.0, 0.5 + score_delta))
            last_funding = now if signal_type == "funding" else None
            conn.execute(
                """INSERT INTO company_scores
                   (company, canonical_name, hiring_score, signal_count, positive_signals,
                    negative_signals, last_signal_at, last_funding_at, trend, updated_at)
                   VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'stable', ?)""",
                (company, canonical, init_score,
                 1 if is_positive else 0,
                 1 if is_negative else 0,
                 now, last_funding, now),
            )

        conn.commit()
        row = conn.execute(
            "SELECT * FROM hiring_signals WHERE id = ?", (sig_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_signals(
    company: str | None = None,
    signal_type: str | None = None,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    init_signals_db(db_path)
    conn = _get_conn(db_path)
    try:
        query = "SELECT * FROM hiring_signals"
        params: list = []
        conditions = []
        if company:
            conditions.append("LOWER(company) LIKE ?")
            params.append(f"%{company.lower()}%")
        if signal_type:
            conditions.append("signal_type = ?")
            params.append(signal_type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY discovered_at DESC LIMIT {limit}"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_company_score(company: str, db_path: Path | None = None) -> dict | None:
    init_signals_db(db_path)
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM company_scores WHERE LOWER(company) = ?",
            (company.lower(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_company_scores(
    min_score: float = 0.0,
    trend: str | None = None,
    limit: int = 100,
    db_path: Path | None = None,
) -> list[dict]:
    init_signals_db(db_path)
    conn = _get_conn(db_path)
    try:
        query = "SELECT * FROM company_scores WHERE hiring_score >= ?"
        params: list = [min_score]
        if trend:
            query += " AND trend = ?"
            params.append(trend)
        query += f" ORDER BY hiring_score DESC LIMIT {limit}"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_signals_stats(db_path: Path | None = None) -> dict:
    init_signals_db(db_path)
    conn = _get_conn(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM hiring_signals").fetchone()["c"]
        by_type_rows = conn.execute(
            "SELECT signal_type, COUNT(*) AS c FROM hiring_signals GROUP BY signal_type"
        ).fetchall()
        by_type = {r["signal_type"]: r["c"] for r in by_type_rows}
        companies_tracked = conn.execute(
            "SELECT COUNT(*) AS c FROM company_scores"
        ).fetchone()["c"]
        high_score = conn.execute(
            "SELECT COUNT(*) AS c FROM company_scores WHERE hiring_score >= 0.7"
        ).fetchone()["c"]
        layoff_alerts = conn.execute(
            "SELECT COUNT(*) AS c FROM company_scores WHERE hiring_score < 0.3"
        ).fetchone()["c"]
        return {
            "total_signals": total,
            "by_type": by_type,
            "companies_tracked": companies_tracked,
            "high_score_companies": high_score,
            "layoff_alerts": layoff_alerts,
        }
    finally:
        conn.close()
