"""Signal Bot — fetches public signals and scores companies.

Run every 6 hours via orchestrator.

Flow per run:
1. Fetch all enabled RSS/API signal sources
2. Parse feed entries (title + summary)
3. Classify each entry (funding/layoff/expansion/etc.)
4. Filter: actionable signals only (confidence >= 0.50, not noise)
5. Dedup: skip if same company+type already seen in last 24h
6. Save new signals to DB + update company scores
7. Refresh decayed scores for all tracked companies
8. Telegram summary: top hiring + avoid list

CLI:
  python -m bots.signal_bot.run [--dry-run] [--companies stripe,google]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from src.signals.database import (
    init_signals_db,
    save_signal,
    get_signals,
    get_signals_stats,
)
from src.signals.sources import get_enabled_sources
from src.signals.classifier import classify_feed_entries, is_actionable, classify_text
from src.signals.scorer import (
    refresh_company_score,
    get_top_companies,
    get_avoid_companies,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Feed fetcher
# ---------------------------------------------------------------------------

def fetch_feed(url: str, timeout: int = 20) -> list[dict]:
    """Fetch an RSS feed and return parsed entries."""
    try:
        import feedparser
        feed = feedparser.parse(url)
        entries = []
        for e in feed.entries[:50]:  # cap at 50 per source
            entries.append({
                "title": e.get("title", ""),
                "summary": e.get("summary", "") or e.get("description", ""),
                "link": e.get("link", ""),
                "published": e.get("published", ""),
            })
        return entries
    except Exception as exc:
        logger.warning(f"Feed fetch error ({url[:60]}...): {exc}")
        return []


# ---------------------------------------------------------------------------
# Dedup check
# ---------------------------------------------------------------------------

def _already_seen(company: str, signal_type: str, db_path: Path | None = None) -> bool:
    """Check if we already have this company+type signal within last 24h."""
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    signals = get_signals(company=company, signal_type=signal_type, db_path=db_path)
    return any(s.get("discovered_at", "") >= cutoff for s in signals)


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def scan_sources(
    dry_run: bool = False,
    company_filter: list[str] | None = None,
    db_path: Path | None = None,
) -> dict:
    """Fetch all signal sources and save new signals."""
    sources = get_enabled_sources()
    stats = {
        "sources_scanned": 0,
        "entries_fetched": 0,
        "signals_found": 0,
        "signals_saved": 0,
        "companies_updated": set(),
    }

    for source in sources:
        logger.info(f"Scanning: {source.name}")
        entries = fetch_feed(source.url)
        stats["sources_scanned"] += 1
        stats["entries_fetched"] += len(entries)

        classified = classify_feed_entries(entries)

        for entry in classified:
            company = entry.get("company", "").strip()
            sig_type = entry.get("signal_type", "noise")
            conf = entry.get("confidence", 0.0)

            # Skip noise or low confidence
            if sig_type == "noise" or conf < 0.50:
                continue
            # Skip if no company detected
            if not company:
                continue
            # Apply company filter if given
            if company_filter and not any(
                cf.lower() in company.lower() for cf in company_filter
            ):
                continue

            stats["signals_found"] += 1

            # Dedup
            if _already_seen(company, sig_type, db_path=db_path):
                continue

            if not dry_run:
                save_signal(
                    company=company,
                    signal_type=sig_type,
                    signal_text=f"{entry.get('title', '')} — {entry.get('summary', '')}"[:1000],
                    source_url=entry.get("link", ""),
                    source_name=source.name,
                    confidence=conf,
                    sector_tags=entry.get("sector_tags", []),
                    db_path=db_path,
                )
                stats["companies_updated"].add(company)
                stats["signals_saved"] += 1
                logger.info(f"  [{sig_type.upper()} {conf:.0%}] {company}: {entry.get('title', '')[:80]}")

    # Refresh scores for all updated companies
    if not dry_run:
        for company in stats["companies_updated"]:
            refresh_company_score(company, db_path=db_path)

    stats["companies_updated"] = list(stats["companies_updated"])
    return stats


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

def run(
    dry_run: bool = False,
    company_filter: list[str] | None = None,
    db_path: Path | None = None,
) -> dict:
    init_signals_db(db_path)

    logger.info("Signal Bot starting...")
    scan_stats = scan_sources(
        dry_run=dry_run,
        company_filter=company_filter,
        db_path=db_path,
    )

    top = get_top_companies(min_score=0.70, limit=5, db_path=db_path)
    avoid = get_avoid_companies(max_score=0.25, limit=3, db_path=db_path)
    db_stats = get_signals_stats(db_path=db_path)

    logger.info(
        f"Scan done: {scan_stats['sources_scanned']} sources, "
        f"{scan_stats['signals_found']} signals, "
        f"{scan_stats['signals_saved']} saved"
    )

    if top:
        logger.info("Top hiring companies:")
        for c in top:
            logger.info(f"  {c['company']}: {c['hiring_score']:.2f} ({c['trend']})")

    if avoid:
        logger.info("Avoid (layoff signals):")
        for c in avoid:
            logger.info(f"  {c['company']}: {c['hiring_score']:.2f}")

    # Telegram
    if not dry_run and (scan_stats["signals_saved"] > 0 or top):
        lines = [
            "*Signal Bot Summary*",
            f"Sources scanned: {scan_stats['sources_scanned']}",
            f"Signals saved: {scan_stats['signals_saved']}",
            f"Companies tracked: {db_stats.get('companies_tracked', 0)}",
        ]
        if top:
            lines.append("\n*Top Hiring Companies:*")
            for c in top[:3]:
                arrow = {"up": "↑", "down": "↓", "stable": "→"}.get(c["trend"], "")
                lines.append(f"  • {c['company']}: {c['hiring_score']:.0%} {arrow}")
        if avoid:
            lines.append("\n*Avoid (Layoff Signals):*")
            for c in avoid[:2]:
                lines.append(f"  • {c['company']}: {c['hiring_score']:.0%} ↓")
        _send_telegram("\n".join(lines))

    return {
        "scan_stats": scan_stats,
        "top_companies": top,
        "avoid_companies": avoid,
        "db_stats": db_stats,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Signal Bot")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--companies", type=str, default="", help="Comma-separated company filter")
    args = parser.parse_args()

    companies = [c.strip() for c in args.companies.split(",") if c.strip()] or None
    result = run(dry_run=args.dry_run, company_filter=companies)
    print(f"\nDone. {result['scan_stats']['signals_saved']} signals saved.")
