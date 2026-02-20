"""Supervisor engine — aggregates today's priority actions from all systems.

Pulls from:
  - Outreach: pending drafts awaiting approval
  - CRM: follow-ups due, replies received
  - Jobs DB: top-scoring unapplied jobs
  - Signals: recent strong hiring signals
  - Referral: warm intro opportunities for top companies

Returns a unified action list sorted by priority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# Action types
ACTION_OUTREACH_DRAFT = "outreach_draft"   # pending draft needs approval
ACTION_CRM_FOLLOWUP  = "crm_followup"     # follow-up due
ACTION_CRM_REPLY     = "crm_reply"        # someone replied — top priority
ACTION_JOB_APPLY     = "job_apply"        # high-score job to apply to
ACTION_SIGNAL_HOT    = "signal_hot"       # new strong hiring signal
ACTION_REFERRAL      = "referral_path"    # warm intro available

# Base priorities per action type (before data-driven adjustments)
_BASE_PRIORITIES = {
    ACTION_CRM_REPLY:     0.97,
    ACTION_OUTREACH_DRAFT: 0.90,
    ACTION_CRM_FOLLOWUP:  0.80,
    ACTION_JOB_APPLY:     0.75,   # will be replaced by match_score
    ACTION_SIGNAL_HOT:    0.70,
    ACTION_REFERRAL:      0.65,
}


@dataclass
class Action:
    action_type: str
    priority: float         # 0.0 – 1.0 (higher = do first)
    title: str
    description: str
    action_label: str       # button text: "Approve", "Follow Up", "Apply", etc.
    source: str             # system that generated this
    data: dict = field(default_factory=dict)
    timestamp: str = ""     # ISO datetime of when this became relevant


def _now() -> str:
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Outreach drafts
# ---------------------------------------------------------------------------

def _get_outreach_actions(limit: int = 5) -> list[Action]:
    try:
        from src.outreach.database import list_drafts
        drafts = list_drafts(status="pending", limit=limit)
        actions = []
        for d in drafts:
            actions.append(Action(
                action_type=ACTION_OUTREACH_DRAFT,
                priority=_BASE_PRIORITIES[ACTION_OUTREACH_DRAFT],
                title=f"Review draft: {d.get('subject', '')[:55]}",
                description=f"To: {d.get('contact_email','')} @ {d.get('company','')} [{d.get('stage','')}]",
                action_label="Approve Draft",
                source="outreach",
                data={"draft_id": d["id"], "stage": d.get("stage"), "company": d.get("company")},
                timestamp=d.get("created_at", _now()),
            ))
        return actions
    except Exception:
        return []


# ---------------------------------------------------------------------------
# CRM follow-ups
# ---------------------------------------------------------------------------

def _get_crm_actions(limit: int = 5) -> list[Action]:
    try:
        from src.crm.database import get_todays_actions
        crm_items = get_todays_actions(limit=limit)
        actions = []
        for item in crm_items:
            contact = item.get("contact", {})
            conv = item.get("latest_conversation", {})
            stage = conv.get("stage", "initial") if conv else "initial"
            last_at = contact.get("last_contacted_at", "")
            days_str = ""
            if last_at:
                try:
                    days = (datetime.utcnow() - datetime.fromisoformat(last_at)).days
                    days_str = f" — {days}d since last contact"
                except Exception:
                    pass

            actions.append(Action(
                action_type=ACTION_CRM_FOLLOWUP,
                priority=_BASE_PRIORITIES[ACTION_CRM_FOLLOWUP],
                title=f"Follow up: {contact.get('name','')} @ {contact.get('company','')}",
                description=f"Stage: {stage}{days_str}",
                action_label="Follow Up",
                source="crm",
                data={"contact_id": contact.get("id"), "email": contact.get("email"),
                      "company": contact.get("company"), "stage": stage},
                timestamp=last_at or _now(),
            ))
        return actions
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Top jobs to apply to
# ---------------------------------------------------------------------------

def _get_job_actions(min_score: float = 0.70, limit: int = 5) -> list[Action]:
    try:
        from src.database import get_db
        conn = get_db()
        rows = conn.execute(
            """SELECT job_id, company, role, url, match_score, source
               FROM jobs
               WHERE status = 'To Apply'
               AND match_score >= ?
               ORDER BY match_score DESC
               LIMIT ?""",
            (min_score, limit),
        ).fetchall()
        conn.close()

        actions = []
        for r in rows:
            score = r["match_score"] or min_score
            actions.append(Action(
                action_type=ACTION_JOB_APPLY,
                priority=min(0.99, float(score)),
                title=f"Apply: {r['role']} at {r['company']}",
                description=f"Match score: {score:.0%} | Source: {r.get('source','')}",
                action_label="Apply ▸",
                source="jobs",
                data={"job_id": r["job_id"], "company": r["company"],
                      "role": r["role"], "url": r["url"], "match_score": score},
            ))
        return actions
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Hot hiring signals
# ---------------------------------------------------------------------------

def _get_signal_actions(limit: int = 5) -> list[Action]:
    try:
        from src.signals.database import list_company_scores
        hot = list_company_scores(min_score=0.72, limit=limit)
        actions = []
        for co in hot:
            trend = co.get("trend", "stable")
            arrow = {"up": "↑", "down": "↓", "stable": "→"}.get(trend, "")
            actions.append(Action(
                action_type=ACTION_SIGNAL_HOT,
                priority=min(0.99, co.get("hiring_score", 0.7)),
                title=f"Hot signal: {co['company']} {arrow}",
                description=(
                    f"Hiring score: {co['hiring_score']:.0%} | "
                    f"{co.get('signal_count',0)} signals | "
                    f"window: {co.get('hiring_window','unknown')}"
                ),
                action_label="View Signals",
                source="signals",
                data={"company": co["company"], "hiring_score": co["hiring_score"],
                      "trend": trend, "hiring_window": co.get("hiring_window","unknown")},
                timestamp=co.get("last_signal_at", _now()),
            ))
        return actions
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Referral opportunities
# ---------------------------------------------------------------------------

def _get_referral_actions(limit: int = 3) -> list[Action]:
    try:
        from src.signals.database import list_company_scores
        from src.referral.finder import find_referral_paths
        top_signal_cos = list_company_scores(min_score=0.70, limit=10)
        actions = []
        for co in top_signal_cos:
            if len(actions) >= limit:
                break
            paths = find_referral_paths(
                target_company=co["company"],
                top_n=1,
                min_score=0.60,
                use_signals=False,
            )
            if not paths:
                continue
            best = paths[0]
            actions.append(Action(
                action_type=ACTION_REFERRAL,
                priority=min(0.99, best.final_score * co["hiring_score"]),
                title=f"Intro: {best.contact_name} → {co['company']}",
                description=(
                    f"{best.tier} contact | score {best.final_score:.0%} | "
                    f"hiring signal {co['hiring_score']:.0%}"
                ),
                action_label="Get Intro",
                source="referral",
                data={"company": co["company"], "contact_name": best.contact_name,
                      "contact_email": best.contact_email, "score": best.final_score,
                      "suggested_ask": best.suggested_ask},
            ))
        return actions
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Unified aggregator
# ---------------------------------------------------------------------------

def get_todays_actions(
    max_total: int = 20,
    include_jobs: bool = True,
    include_signals: bool = True,
    include_referrals: bool = True,
) -> list[dict]:
    """Return priority-ranked action list from all systems."""
    actions: list[Action] = []

    actions.extend(_get_outreach_actions(limit=5))
    actions.extend(_get_crm_actions(limit=5))
    if include_jobs:
        actions.extend(_get_job_actions(limit=5))
    if include_signals:
        actions.extend(_get_signal_actions(limit=5))
    if include_referrals:
        actions.extend(_get_referral_actions(limit=3))

    actions.sort(key=lambda a: a.priority, reverse=True)

    return [
        {
            "action_type": a.action_type,
            "priority": round(a.priority, 3),
            "title": a.title,
            "description": a.description,
            "action_label": a.action_label,
            "source": a.source,
            "data": a.data,
            "timestamp": a.timestamp,
        }
        for a in actions[:max_total]
    ]


# ---------------------------------------------------------------------------
# System-wide stats snapshot
# ---------------------------------------------------------------------------

def get_system_stats() -> dict:
    """Aggregate stats from all subsystems for the dashboard header."""
    stats: dict[str, Any] = {}

    # Jobs
    try:
        from src.database import get_db
        conn = get_db()
        stats["total_jobs"] = conn.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
        stats["to_apply"] = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE status = 'To Apply'"
        ).fetchone()["c"]
        stats["applied"] = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE status = 'Applied'"
        ).fetchone()["c"]
        stats["interviewing"] = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE status = 'Interviewing'"
        ).fetchone()["c"]
        conn.close()
    except Exception:
        stats.update({"total_jobs": 0, "to_apply": 0, "applied": 0, "interviewing": 0})

    # Signals
    try:
        from src.signals.database import get_signals_stats
        sig = get_signals_stats()
        stats["signal_companies"] = sig.get("companies_tracked", 0)
        stats["hot_companies"] = sig.get("high_score_companies", 0)
        stats["layoff_alerts"] = sig.get("layoff_alerts", 0)
    except Exception:
        stats.update({"signal_companies": 0, "hot_companies": 0, "layoff_alerts": 0})

    # CRM
    try:
        from src.crm.database import get_crm_stats
        crm = get_crm_stats()
        stats["crm_contacts"] = crm.get("total_contacts", 0)
        stats["crm_active_conversations"] = crm.get("active_conversations", 0)
    except Exception:
        stats.update({"crm_contacts": 0, "crm_active_conversations": 0})

    # Outreach
    try:
        from src.outreach.database import get_outreach_stats
        out = get_outreach_stats()
        stats["outreach_pending_drafts"] = out.get("pending_drafts", 0)
        stats["outreach_reply_rate"] = out.get("reply_rate", 0.0)
        stats["outreach_active_sequences"] = out.get("active_sequences", 0)
    except Exception:
        stats.update({"outreach_pending_drafts": 0, "outreach_reply_rate": 0.0,
                      "outreach_active_sequences": 0})

    stats["generated_at"] = _now()
    return stats


# ---------------------------------------------------------------------------
# Pipeline funnel
# ---------------------------------------------------------------------------

def get_pipeline_funnel() -> dict:
    """Jobs funnel: discovered → to_apply → applied → interviewing → offer."""
    try:
        from src.database import get_db
        conn = get_db()
        stages = {
            "discovered": "SELECT COUNT(*) AS c FROM jobs",
            "to_apply":    "SELECT COUNT(*) AS c FROM jobs WHERE status = 'To Apply'",
            "applied":     "SELECT COUNT(*) AS c FROM jobs WHERE status = 'Applied'",
            "interviewing":"SELECT COUNT(*) AS c FROM jobs WHERE status = 'Interviewing'",
            "offer":       "SELECT COUNT(*) AS c FROM jobs WHERE status IN ('Offer','Accepted')",
        }
        funnel = {}
        for stage, sql in stages.items():
            funnel[stage] = conn.execute(sql).fetchone()["c"]
        conn.close()
        return funnel
    except Exception:
        return {"discovered": 0, "to_apply": 0, "applied": 0, "interviewing": 0, "offer": 0}
