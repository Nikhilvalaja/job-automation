"""CRM Bot — Gmail scanner + touchpoint logger + today's actions dispatcher.

What it does each run:
1. Scan Gmail for new job-related emails (sent + received)
2. Detect contacts (recruiter names, emails, companies)
3. Log touchpoints (email_sent, email_received) to CRM
4. Update conversation stages automatically
5. Print today's actions (follow-ups due)
6. Send Telegram summary

CLI:
  python -m bots.crm_bot.run [--dry-run] [--scan-days=7] [--actions-only]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from src.crm.database import (
    init_crm_db,
    upsert_contact,
    get_or_create_conversation,
    log_touchpoint,
    update_conversation_stage,
    get_todays_actions,
    get_crm_stats,
)
from src.crm.cooldown import (
    can_contact,
    apply_cooldown,
    clear_cooldown,
    suggest_next_followup,
    next_stage,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Gmail scanner (requires google-auth + gmail API)
# ---------------------------------------------------------------------------

_JOB_KEYWORDS = [
    "application", "recruiter", "hiring", "interview", "opportunity",
    "position", "role", "job", "offer", "resume", "cv", "candidate",
    "reach out", "connect", "career",
]

_ROLE_HINTS = {
    "recruiter": ["recruiter", "talent", "staffing", "hr ", "human resources"],
    "hiring_manager": ["engineering manager", "head of", "director", "vp of"],
    "engineer": ["software engineer", "sre", "devops", "data engineer", "ml engineer"],
}


def _detect_role(name: str, email: str, snippet: str) -> str:
    text = f"{name} {email} {snippet}".lower()
    for role, hints in _ROLE_HINTS.items():
        if any(h in text for h in hints):
            return role
    return "unknown"


def _is_job_related(subject: str, snippet: str) -> bool:
    text = f"{subject} {snippet}".lower()
    return any(kw in text for kw in _JOB_KEYWORDS)


def _extract_company_from_email(email: str) -> str:
    """Best-effort company extraction from email domain."""
    if "@" not in email:
        return ""
    domain = email.split("@")[1]
    # Skip generic providers
    generic = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"}
    if domain in generic:
        return ""
    # e.g. "stripe.com" -> "Stripe", "eng.google.com" -> "Google"
    parts = domain.split(".")
    # Use second-level domain
    company_part = parts[-2] if len(parts) >= 2 else parts[0]
    return company_part.capitalize()


def scan_gmail(
    scan_days: int = 7,
    dry_run: bool = False,
) -> dict:
    """Scan Gmail for job-related emails and log touchpoints.

    Returns stats dict.
    """
    try:
        from src.bots.email_bot.gmail_client import GmailClient
        gmail = GmailClient()
    except Exception as e:
        logger.warning(f"Gmail client unavailable: {e}")
        return {"scanned": 0, "contacts_found": 0, "touchpoints_logged": 0, "error": str(e)}

    since = (datetime.utcnow() - timedelta(days=scan_days)).strftime("%Y/%m/%d")
    stats = {"scanned": 0, "contacts_found": 0, "touchpoints_logged": 0}

    # Scan sent emails (outbound)
    try:
        sent = gmail.list_messages(query=f"in:sent after:{since}", max_results=100)
        for msg in sent:
            stats["scanned"] += 1
            to_email = msg.get("to", "")
            if not to_email or not _is_job_related(msg.get("subject", ""), msg.get("snippet", "")):
                continue

            company = _extract_company_from_email(to_email)
            role = _detect_role(msg.get("to_name", ""), to_email, msg.get("snippet", ""))

            if not dry_run:
                contact = upsert_contact(
                    email=to_email,
                    name=msg.get("to_name", ""),
                    company=company,
                    role=role,
                    source="gmail",
                )
                conv = get_or_create_conversation(
                    contact_id=contact["id"],
                    subject=msg.get("subject", ""),
                )
                log_touchpoint(
                    contact_id=contact["id"],
                    conversation_id=conv["id"],
                    type="email_sent",
                    subject=msg.get("subject", ""),
                    summary=msg.get("snippet", "")[:200],
                    raw_snippet=msg.get("snippet", ""),
                    gmail_thread_id=msg.get("thread_id", ""),
                    gmail_message_id=msg.get("id", ""),
                    direction="outbound",
                    occurred_at=msg.get("date"),
                )
                stats["touchpoints_logged"] += 1
            stats["contacts_found"] += 1
    except Exception as e:
        logger.warning(f"Sent scan error: {e}")

    # Scan inbox (inbound replies)
    try:
        received = gmail.list_messages(query=f"in:inbox after:{since}", max_results=100)
        for msg in received:
            stats["scanned"] += 1
            from_email = msg.get("from", "")
            if not from_email or not _is_job_related(msg.get("subject", ""), msg.get("snippet", "")):
                continue

            company = _extract_company_from_email(from_email)

            if not dry_run:
                contact = upsert_contact(
                    email=from_email,
                    name=msg.get("from_name", ""),
                    company=company,
                    role=_detect_role(msg.get("from_name", ""), from_email, msg.get("snippet", "")),
                    source="gmail",
                )
                conv = get_or_create_conversation(
                    contact_id=contact["id"],
                    subject=msg.get("subject", ""),
                )
                log_touchpoint(
                    contact_id=contact["id"],
                    conversation_id=conv["id"],
                    type="email_received",
                    subject=msg.get("subject", ""),
                    summary=msg.get("snippet", "")[:200],
                    raw_snippet=msg.get("snippet", ""),
                    gmail_thread_id=msg.get("thread_id", ""),
                    gmail_message_id=msg.get("id", ""),
                    direction="inbound",
                    occurred_at=msg.get("date"),
                )
                # Auto-clear cooldown on reply
                clear_cooldown(conv["id"])
                stats["touchpoints_logged"] += 1
            stats["contacts_found"] += 1
    except Exception as e:
        logger.warning(f"Inbox scan error: {e}")

    return stats


# ---------------------------------------------------------------------------
# Today's actions
# ---------------------------------------------------------------------------

def get_actions_summary() -> list[dict]:
    """Return today's due follow-ups with recommended action."""
    actions = get_todays_actions()
    enriched = []
    for action in actions:
        allowed, reason = can_contact(action["contact_id"], action["conv_id"])
        nxt = next_stage(action["stage"])
        suggested_date = suggest_next_followup(action["stage"], action.get("last_message_at"))
        enriched.append({
            **action,
            "can_contact": allowed,
            "block_reason": reason if not allowed else None,
            "recommended_next_stage": nxt,
            "suggested_followup_date": suggested_date,
            "action_label": _action_label(action["stage"], allowed),
        })
    return enriched


def _action_label(stage: str, allowed: bool) -> str:
    if not allowed:
        return "SKIP (cooldown)"
    labels = {
        "initial": "Send follow-up #1",
        "follow_up_1": "Send follow-up #2",
        "follow_up_2": "Final follow-up",
    }
    return labels.get(stage, "Follow up")


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------

def _send_telegram(text: str) -> None:
    try:
        import requests
        from src.config import settings
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return
        requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(scan_days: int = 7, dry_run: bool = False, actions_only: bool = False) -> dict:
    """Main CRM bot run."""
    init_crm_db()

    scan_stats = {"scanned": 0, "contacts_found": 0, "touchpoints_logged": 0}
    if not actions_only:
        logger.info(f"Scanning Gmail ({scan_days}d)...")
        scan_stats = scan_gmail(scan_days=scan_days, dry_run=dry_run)
        logger.info(
            f"Gmail scan: {scan_stats['scanned']} msgs, "
            f"{scan_stats['contacts_found']} contacts, "
            f"{scan_stats['touchpoints_logged']} touchpoints"
        )

    actions = get_actions_summary()
    stats = get_crm_stats()

    logger.info(
        f"CRM: {stats['total_contacts']} contacts, "
        f"{stats['follow_ups_due']} follow-ups due, "
        f"{stats['replied_count']} replied"
    )

    if actions:
        logger.info(f"Today's actions ({len(actions)}):")
        for a in actions[:10]:
            status = "OK" if a["can_contact"] else f"SKIP ({a['block_reason']})"
            logger.info(
                f"  [{status}] {a['name']} @ {a['company']} — {a['action_label']}"
            )

    # Telegram summary
    if not dry_run and (scan_stats.get("contacts_found", 0) > 0 or actions):
        lines = [
            "*CRM Bot Summary*",
            f"Scanned: {scan_stats.get('scanned', 0)} emails",
            f"New contacts: {scan_stats.get('contacts_found', 0)}",
            f"Follow-ups due: {len(actions)}",
            f"Reply rate: {stats['reply_rate']:.0%}",
        ]
        if actions:
            lines.append("\n*Today's Actions:*")
            for a in actions[:5]:
                lines.append(f"  • {a['name']} @ {a['company']} — {a['action_label']}")
        _send_telegram("\n".join(lines))

    return {
        "scan_stats": scan_stats,
        "actions": actions,
        "crm_stats": stats,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CRM Bot")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--scan-days", type=int, default=7, help="Days to scan back")
    parser.add_argument("--actions-only", action="store_true", help="Skip Gmail scan")
    args = parser.parse_args()

    result = run(
        scan_days=args.scan_days,
        dry_run=args.dry_run,
        actions_only=args.actions_only,
    )
    print(f"\nDone. Actions due: {len(result['actions'])}")
