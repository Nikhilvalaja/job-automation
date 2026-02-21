"""Gmail Job Alert Ingestion Bot.

Reads job alert emails from Gmail (both accounts) and extracts job URLs
to push into the discovery database fetch queue.

KEY PRINCIPLE: Email is only used for DISCOVERY of job URLs.
The actual job data is fetched from the source page/API, ensuring
uniform job schema regardless of email format.

Supported email sources:
- LinkedIn Job Alerts (jobs-noreply@linkedin.com)
- Indeed Job Alerts (jobalerts@indeed.com, indeed@email.indeed.com)
- Dice Job Alerts (alerts@dice.com)
- Glassdoor Job Alerts (noreply@glassdoor.com)
- ZipRecruiter (alerts@ziprecruiter.com)
- Google Alerts (googlealerts-noreply@google.com)
- Handshake (noreply@joinhandshake.com)
- Company-specific alert emails

De-noising:
- Only processes emails with real job URLs
- Skips duplicate URLs (already in DB)
- 24h dedup window to avoid re-processing same alert
- Canonicalizes URLs (strips tracking params)

Usage:
    python -m bots.gmail_ingest_bot.run           # Run ingestion
    python -m bots.gmail_ingest_bot.run --dry-run  # Preview without saving
    python -m bots.gmail_ingest_bot.run --hours 24 # Look back N hours
"""

from __future__ import annotations

import base64
import io
import re
import sys
from datetime import datetime, timedelta
from email import message_from_bytes
from email.header import decode_header
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bots.base import BaseBot
from src.discovery.database import (
    get_all_urls,
    get_new_jobs_since,
    init_db,
    insert_job,
    rebuild_fts_index,
    update_source_stats,
)
from src.discovery.fetcher import fetch_source
from src.discovery.jsonld import extract_jobs_from_url, detect_ats
from src.discovery.sources import JobSource, SourceType
from src.notifications.telegram import TelegramNotifier
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Known job alert senders
# ---------------------------------------------------------------------------

JOB_ALERT_SENDERS = {
    "jobs-noreply@linkedin.com": "LinkedIn",
    "jobalerts@indeed.com": "Indeed",
    "indeed@email.indeed.com": "Indeed",
    "noreply@indeed.com": "Indeed",
    "alerts@dice.com": "Dice",
    "noreply@glassdoor.com": "Glassdoor",
    "alerts@ziprecruiter.com": "ZipRecruiter",
    "noreply@ziprecruiter.com": "ZipRecruiter",
    "googlealerts-noreply@google.com": "Google Alerts",
    "noreply@joinhandshake.com": "Handshake",
    "jobs@monster.com": "Monster",
    "alerts@careerbuilder.com": "CareerBuilder",
    "noreply@simplyhired.com": "SimplyHired",
    "notifications@greenhouse.io": "Greenhouse Alert",
    "alerts@lever.co": "Lever Alert",
    "noreply@wellfound.com": "Wellfound",
    "noreply@ycombinator.com": "YC Jobs",
    "no-reply@builtinnyc.com": "BuiltIn",
    "no-reply@builtinsf.com": "BuiltIn",
    "noreply@remoteok.com": "RemoteOK",
    "hello@remotive.com": "Remotive",
    "jobs@weworkremotely.com": "WeWorkRemotely",
}

# URL patterns that indicate a job posting link (not homepage/unsubscribe)
JOB_URL_PATTERNS = [
    r"jobs\.lever\.co/[\w-]+/[a-f0-9-]{36}",
    r"boards\.greenhouse\.io/[\w-]+/jobs/\d+",
    r"jobs\.ashbyhq\.com/[\w-]+/[a-f0-9-]{36}",
    r"careers\.smartrecruiters\.com/[\w-]+/\d+",
    r"linkedin\.com/jobs/view/",
    r"indeed\.com/viewjob\?jk=",
    r"dice\.com/job-detail/",
    r"glassdoor\.com/job-listing/",
    r"ziprecruiter\.com/c/",
    r"wellfound\.com/jobs/",
    r"handshake\.com/jobs/",
    r"/jobs?/\d{4,}",  # Generic job ID in URL path
    r"/apply/\d{4,}",
    r"/careers?/\w{8,}",  # Long slug = likely a job posting
]

# Tracking/redirect params to strip from URLs for canonicalization
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "trk", "trkCampaign", "trkInfo", "refId",  # LinkedIn
    "from", "dest",  # Indeed
    "mktgSrc", "s",  # Dice
    "src", "srs", "pos",  # ZipRecruiter
    "chl", "gclid", "fbclid", "msclkid",  # Generic tracking
}

# ATS redirect/tracking domains to follow through
REDIRECT_DOMAINS = {
    "click.linkedin.com",
    "r.email.indeed.com",
    "email.ziprecruiter.com",
    "email.glassdoor.com",
}


# ---------------------------------------------------------------------------
# URL extraction and canonicalization
# ---------------------------------------------------------------------------

def extract_urls_from_text(text: str) -> list[str]:
    """Extract all HTTP/HTTPS URLs from plain text or HTML."""
    # Match URLs in text
    url_pattern = re.compile(
        r'https?://[^\s<>"\')\]]+',
        re.IGNORECASE,
    )
    raw_urls = url_pattern.findall(text)

    # Also extract from href attributes
    href_pattern = re.compile(r'href=["\']?(https?://[^"\'>\s]+)', re.IGNORECASE)
    raw_urls.extend(href_pattern.findall(text))

    return list(set(raw_urls))


def is_job_url(url: str) -> bool:
    """Check if a URL looks like a job posting (not a homepage or promo)."""
    url_lower = url.lower()

    # Must be long enough to be a real job page
    if len(url) < 30:
        return False

    # Skip unsubscribe / preferences links
    skip_patterns = [
        "unsubscribe", "opt-out", "preferences", "settings", "privacy",
        "terms", "help", "support", "about", "contact", "login", "signup",
        "homepage", "www.linkedin.com/in/",  # Profile links
    ]
    if any(p in url_lower for p in skip_patterns):
        return False

    # Check for known job URL patterns
    for pattern in JOB_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True

    return False


def canonicalize_url(url: str) -> str:
    """Strip tracking parameters and normalize the URL."""
    try:
        parsed = urlparse(url)
        # Follow known redirect domains — strip to just the real URL
        if parsed.netloc in REDIRECT_DOMAINS:
            # Try to extract the real URL from query params
            params = parse_qs(parsed.query)
            for key in ("url", "dest", "u", "link"):
                if key in params:
                    return canonicalize_url(params[key][0])
            return url  # Can't resolve, return as-is

        # Strip tracking params
        params = parse_qs(parsed.query)
        clean_params = {k: v for k, v in params.items() if k not in TRACKING_PARAMS}

        clean_query = urlencode({k: v[0] for k, v in clean_params.items()}, doseq=False)
        canonical = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
            parsed.params,
            clean_query,
            "",  # Remove fragment
        ))
        return canonical
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Gmail email parsing
# ---------------------------------------------------------------------------

def decode_email_body(msg) -> str:
    """Extract text content from an email message."""
    body_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body_parts.append(payload.decode(charset, errors="replace"))
        except Exception:
            pass

    return "\n".join(body_parts)


def get_sender(msg) -> str:
    """Extract sender email from message."""
    from_header = msg.get("From", "")
    # Extract email address from "Name <email>" format
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).lower()
    return from_header.lower().strip()


# ---------------------------------------------------------------------------
# Gmail Bot
# ---------------------------------------------------------------------------

class GmailIngestBot(BaseBot):
    """Reads job alert emails and pushes URLs into discovery database."""

    def __init__(self, dry_run: bool = False, lookback_hours: int = 6) -> None:
        super().__init__("gmail_ingest")
        self.dry_run = dry_run
        self.lookback_hours = lookback_hours
        self._notifier: Optional[TelegramNotifier] = None

    def start(self) -> None:
        super().start()
        init_db()
        self._notifier = TelegramNotifier()

    def run_once(self) -> dict:
        """Scan both Gmail accounts for job alert emails."""
        total_emails = 0
        total_urls = 0
        total_stored = 0
        total_skipped = 0

        # Try both Gmail accounts
        for account_num in (1, 2):
            try:
                service = self._get_gmail_service(account_num)
                if service is None:
                    continue
                stats = self._process_account(service, account_num)
                total_emails += stats["emails"]
                total_urls += stats["urls"]
                total_stored += stats["stored"]
                total_skipped += stats["skipped"]
            except Exception as e:
                logger.warning(f"Gmail account {account_num} failed: {e}")

        result = {
            "emails_scanned": total_emails,
            "urls_found": total_urls,
            "stored": total_stored,
            "skipped": total_skipped,
        }
        logger.info(f"Gmail ingest complete: {result}")

        if total_stored > 0 and not self.dry_run:
            rebuild_fts_index()

        return result

    def _get_gmail_service(self, account_num: int):
        """Get Gmail API service for the specified account."""
        try:
            if account_num == 1:
                from src.gmail.service import get_gmail_service
                return get_gmail_service()
            else:
                from src.gmail.multi_account import get_account2_service
                return get_account2_service()
        except Exception as e:
            logger.debug(f"Gmail account {account_num} not available: {e}")
            return None

    def _process_account(self, service, account_num: int) -> dict:
        """Process job alert emails from one Gmail account."""
        emails_scanned = 0
        urls_found = 0
        stored = 0
        skipped = 0

        # Load existing URLs to avoid re-inserting
        existing_urls = get_all_urls()

        # Search for job alert emails from known senders
        # newer_than:Xh means within last N hours
        query = (
            f"label:job_alerts newer_than:{self.lookback_hours}h"
            f" OR (newer_than:{self.lookback_hours}h"
            f" from:({' OR '.join(list(JOB_ALERT_SENDERS.keys())[:10])}))"
        )

        try:
            result = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=50,
            ).execute()
        except Exception as e:
            logger.error(f"Gmail list failed for account {account_num}: {e}")
            return {"emails": 0, "urls": 0, "stored": 0, "skipped": 0}

        messages = result.get("messages", [])
        logger.info(f"Gmail account {account_num}: found {len(messages)} alert emails")

        for msg_ref in messages:
            try:
                msg_data = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="raw",
                ).execute()

                raw = base64.urlsafe_b64decode(msg_data["raw"])
                email_msg = message_from_bytes(raw)
                sender = get_sender(email_msg)
                source_label = JOB_ALERT_SENDERS.get(sender, "Email Alert")

                emails_scanned += 1
                body = decode_email_body(email_msg)

                # Extract all URLs from email body
                raw_urls = extract_urls_from_text(body)

                for raw_url in raw_urls:
                    canonical = canonicalize_url(raw_url)

                    # Filter: must look like a job posting
                    if not is_job_url(canonical):
                        continue

                    urls_found += 1

                    # Skip already-known URLs
                    if canonical in existing_urls:
                        skipped += 1
                        continue

                    if self.dry_run:
                        logger.info(f"[DRY-RUN] Would ingest: {canonical} (from {source_label})")
                        stored += 1
                        continue

                    # Try to fetch actual job data from the URL
                    job = self._fetch_job_from_url(canonical, source_label)
                    if job:
                        job_id = insert_job(job)
                        if job_id:
                            stored += 1
                            existing_urls.add(canonical)
                            logger.info(f"Ingested job: {job['title']} at {job.get('company', '?')}")
                        else:
                            skipped += 1
                    else:
                        # Store URL as a minimal record so we don't lose it
                        minimal_job = {
                            "title": "Job from " + source_label,
                            "company": "",
                            "url": canonical,
                            "description": "",
                            "location": "",
                            "source_name": f"Gmail:{source_label}",
                        }
                        job_id = insert_job(minimal_job)
                        if job_id:
                            stored += 1
                            existing_urls.add(canonical)

            except Exception as e:
                logger.debug(f"Failed to process email {msg_ref['id']}: {e}")

        return {
            "emails": emails_scanned,
            "urls": urls_found,
            "stored": stored,
            "skipped": skipped,
        }

    def _fetch_job_from_url(self, url: str, source_label: str) -> dict | None:
        """Fetch actual job data from a URL using ATS API or JSON-LD."""
        try:
            # Check if it's a known ATS URL — use their JSON API
            ats = detect_ats(url)

            if ats in ("greenhouse", "lever", "ashby", "smartrecruiters"):
                # Extract company slug from URL and use the JSON API
                slug = self._extract_ats_slug(url, ats)
                if slug:
                    # Build proper API URL and use our existing fetcher
                    api_url_map = {
                        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
                        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                        "smartrecruiters": f"https://careers.smartrecruiters.com/{slug}/postings?format=json&limit=1",
                    }
                    # For single job URLs, fall through to JSON-LD
                    pass

            # Try JSON-LD extraction from the job detail page
            jobs = extract_jobs_from_url(url, source_label)
            if jobs:
                job = jobs[0]
                job["source_name"] = f"Gmail:{source_label}"
                job["url"] = url  # Use the canonical URL we found
                return job

        except Exception as e:
            logger.debug(f"Failed to fetch job from {url}: {e}")

        return None

    def _extract_ats_slug(self, url: str, ats: str) -> str | None:
        """Extract company slug from an ATS job URL."""
        patterns = {
            "greenhouse": re.compile(r"boards\.greenhouse\.io/(\w+)/jobs"),
            "lever": re.compile(r"jobs\.lever\.co/([\w-]+)/"),
            "ashby": re.compile(r"jobs\.ashbyhq\.com/([\w-]+)/"),
            "smartrecruiters": re.compile(r"careers\.smartrecruiters\.com/([\w-]+)/"),
        }
        pattern = patterns.get(ats)
        if pattern:
            match = pattern.search(url)
            if match:
                return match.group(1)
        return None


def main() -> None:
    """CLI entry point."""
    import argparse

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="gmail-ingest-bot",
        description="Ingest job URLs from Gmail job alert emails",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without saving to DB")
    parser.add_argument("--hours", type=int, default=6,
                        help="Look back N hours for emails (default: 6)")
    args = parser.parse_args()

    bot = GmailIngestBot(dry_run=args.dry_run, lookback_hours=args.hours)
    bot.start()
    result = bot.run_once()
    bot.stop()

    print(f"\nGmail Ingest Results:")
    print(f"  Emails scanned: {result['emails_scanned']}")
    print(f"  Job URLs found: {result['urls_found']}")
    print(f"  New jobs stored: {result['stored']}")
    print(f"  Duplicates skipped: {result['skipped']}")


if __name__ == "__main__":
    main()
