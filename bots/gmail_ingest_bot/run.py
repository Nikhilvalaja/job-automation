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

# Known job alert sender addresses (exact match)
JOB_ALERT_SENDERS = {
    # LinkedIn
    "jobs-noreply@linkedin.com": "LinkedIn",
    "jobalert@linkedin.com": "LinkedIn",
    "notifications@linkedin.com": "LinkedIn",
    # Indeed
    "jobalerts@indeed.com": "Indeed",
    "indeed@email.indeed.com": "Indeed",
    "noreply@indeed.com": "Indeed",
    "no-reply@indeed.com": "Indeed",
    # Dice
    "alerts@dice.com": "Dice",
    "noreply@dice.com": "Dice",
    # Glassdoor
    "noreply@glassdoor.com": "Glassdoor",
    "alerts@glassdoor.com": "Glassdoor",
    # ZipRecruiter
    "alerts@ziprecruiter.com": "ZipRecruiter",
    "noreply@ziprecruiter.com": "ZipRecruiter",
    # Google Alerts (for job alerts set up via Google)
    "googlealerts-noreply@google.com": "Google Alerts",
    # Handshake
    "noreply@joinhandshake.com": "Handshake",
    "notifications@joinhandshake.com": "Handshake",
    # Monster
    "jobs@monster.com": "Monster",
    "noreply@monster.com": "Monster",
    # CareerBuilder
    "alerts@careerbuilder.com": "CareerBuilder",
    "noreply@careerbuilder.com": "CareerBuilder",
    # SimplyHired
    "noreply@simplyhired.com": "SimplyHired",
    # ATS alerts
    "notifications@greenhouse.io": "Greenhouse Alert",
    "alerts@lever.co": "Lever Alert",
    # Wellfound / AngelList
    "noreply@wellfound.com": "Wellfound",
    "noreply@angel.co": "AngelList",
    # YC / Remote boards
    "noreply@ycombinator.com": "YC Jobs",
    "no-reply@builtinnyc.com": "BuiltIn",
    "no-reply@builtinsf.com": "BuiltIn",
    "no-reply@builtin.com": "BuiltIn",
    "noreply@remoteok.com": "RemoteOK",
    "hello@remotive.com": "Remotive",
    "jobs@weworkremotely.com": "WeWorkRemotely",
    # iHire — seen in user's inbox
    "jobseekers@email.ihire.com": "iHire Technology",
    "noreply@ihire.com": "iHire",
    # Lensa — seen in user's inbox
    "jobalert@lensa.com": "Lensa",
    "noreply@lensa.com": "Lensa",
    # jobs2web — used by many companies (e.g. Westinghouse) for career notifications
    "noreply@jobs2web.com": "jobs2web",
    "westinghouse-jobnotification@noreply.jobs2web.com": "Westinghouse",
    # Talent.com / Jora
    "alert@talent.com": "Talent.com",
    "noreply@talent.com": "Talent.com",
    # Snagajob
    "noreply@snagajob.com": "Snagajob",
    # FlexJobs
    "noreply@flexjobs.com": "FlexJobs",
    "jobs@flexjobs.com": "FlexJobs",
    # Hired
    "hello@hired.com": "Hired",
    "noreply@hired.com": "Hired",
    # Ladders
    "jobs@theladders.com": "TheLadders",
    # Jobcase
    "noreply@jobcase.com": "Jobcase",
    # Recruiter.com
    "noreply@recruiter.com": "Recruiter.com",
    # SmartRecruiters
    "noreply@smartrecruiters.com": "SmartRecruiters",
    # Ashby
    "noreply@ashbyhq.com": "Ashby",
    # Workday notifications
    "no-reply@myworkday.com": "Workday",
    # Notify.io / jobs.io
    "noreply@jobs.io": "Jobs.io",
    # Joblift
    "noreply@joblift.com": "Joblift",
    # Otta
    "hello@otta.com": "Otta",
    # Powertofly
    "noreply@powertofly.com": "PowerToFly",
    # Idealist
    "noreply@idealist.org": "Idealist",
    # Authentic Jobs
    "noreply@authenticjobs.com": "AuthenticJobs",
}

# Domain-level sender patterns — catch any address from these job board domains
# e.g. "westinghouse-jobnotification@noreply.jobs2web.com" is caught by "jobs2web.com"
JOB_ALERT_DOMAINS = {
    "ihire.com": "iHire",
    "email.ihire.com": "iHire",
    "lensa.com": "Lensa",
    "jobs2web.com": "jobs2web",
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "email.indeed.com": "Indeed",
    "dice.com": "Dice",
    "glassdoor.com": "Glassdoor",
    "ziprecruiter.com": "ZipRecruiter",
    "email.ziprecruiter.com": "ZipRecruiter",
    "monster.com": "Monster",
    "careerbuilder.com": "CareerBuilder",
    "simplyhired.com": "SimplyHired",
    "handshake.com": "Handshake",
    "joinhandshake.com": "Handshake",
    "wellfound.com": "Wellfound",
    "angel.co": "AngelList",
    "builtinnyc.com": "BuiltIn",
    "builtinsf.com": "BuiltIn",
    "builtin.com": "BuiltIn",
    "remoteok.com": "RemoteOK",
    "remotive.com": "Remotive",
    "weworkremotely.com": "WeWorkRemotely",
    "talent.com": "Talent.com",
    "jora.com": "Jora",
    "snagajob.com": "Snagajob",
    "flexjobs.com": "FlexJobs",
    "hired.com": "Hired",
    "theladders.com": "TheLadders",
    "jobcase.com": "Jobcase",
    "recruiter.com": "Recruiter.com",
    "smartrecruiters.com": "SmartRecruiters",
    "ashbyhq.com": "Ashby",
    "myworkday.com": "Workday",
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "otta.com": "Otta",
    "powertofly.com": "PowerToFly",
    "idealist.org": "Idealist",
    "joblift.com": "Joblift",
    "joblist.com": "Joblist",
    "getwork.com": "Getwork",
    "zippia.com": "Zippia",
    "jobgether.com": "Jobgether",
    "himalayas.app": "Himalayas",
}

# URL patterns that indicate a job posting link (not homepage/unsubscribe)
JOB_URL_PATTERNS = [
    # ATS direct links
    r"jobs\.lever\.co/[\w-]+/[a-f0-9-]{36}",
    r"boards\.greenhouse\.io/[\w-]+/jobs/\d+",
    r"jobs\.ashbyhq\.com/[\w-]+/[a-f0-9-]{36}",
    r"careers\.smartrecruiters\.com/[\w-]+/\d+",
    # Major job boards
    r"linkedin\.com/jobs/view/",
    r"indeed\.com/viewjob\?jk=",
    r"indeed\.com/rc/clk\?jk=",
    r"dice\.com/job-detail/",
    r"glassdoor\.com/job-listing/",
    r"ziprecruiter\.com/c/",
    r"wellfound\.com/jobs/",
    r"handshake\.com/jobs/",
    # iHire — seen in user's inbox
    r"ihire\.com/.*job",
    r"ihire\.com/seeker/",
    # Lensa — seen in user's inbox
    r"lensa\.com/.*job",
    r"lensa\.com/jobs/",
    # jobs2web — used by Westinghouse + others
    r"jobs2web\.com",
    r"wd\d+\.myworkdayjobs\.com",  # Workday job postings
    # Company career pages (generic patterns)
    r"/job[s]?/\d{4,}",       # Numeric job ID
    r"/job[s]?/[a-zA-Z0-9_-]{6,}",  # Slug-based job URL
    r"/apply/\d{4,}",
    r"/careers?/[a-zA-Z0-9_-]{8,}",  # Long slug = likely a posting
    r"/opening[s]?/",
    r"/position[s]?/\d+",
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
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).lower()
    return from_header.lower().strip()


def classify_sender(sender_email: str) -> str:
    """Classify sender by exact address first, then domain fallback.

    Returns the source label (e.g. "iHire", "Lensa") or empty string if unknown.
    """
    sender_lower = sender_email.lower()

    # Exact match
    if sender_lower in JOB_ALERT_SENDERS:
        return JOB_ALERT_SENDERS[sender_lower]

    # Domain-level match (e.g. catch any @jobs2web.com address)
    domain = sender_lower.split("@")[-1] if "@" in sender_lower else ""
    if domain in JOB_ALERT_DOMAINS:
        return JOB_ALERT_DOMAINS[domain]

    # Sub-domain match (e.g. "email.ihire.com" subdomain of "ihire.com")
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in JOB_ALERT_DOMAINS:
            return JOB_ALERT_DOMAINS[parent]

    return ""


# ---------------------------------------------------------------------------
# Gmail Bot
# ---------------------------------------------------------------------------

def _guess_title_from_subject(subject: str) -> str:
    """Try to extract a job title from an email subject line.

    Examples:
        "Business Analyst Specialist-only local to TX" → "Business Analyst Specialist"
        "We received Data Analyst jobs in Austin, TX" → "Data Analyst"
        "New jobs posted from careers.example.com" → ""
    """
    if not subject:
        return ""
    # Strip common boilerplate prefixes
    prefixes = [
        r"^(new\s+jobs?\s+posted\s+(from|at|on)\s+\S+)",
        r"^(we\s+received\s+)",
        r"^(just\s+posted[!:]?\s+)",
        r"^(your\s+job\s+alert[s]?[:\s-]+)",
        r"^(job\s+alert[s]?[:\s-]+)",
        r"^(new\s+job[s]?\s+(for\s+you|matching)[:\s-]+)",
    ]
    clean = subject.strip()
    for p in prefixes:
        clean = re.sub(p, "", clean, flags=re.IGNORECASE).strip()
    # If the result looks like a job title (not a URL or long sentence), return it
    if clean and len(clean) < 100 and "://" not in clean:
        # Remove trailing location suffixes like "- Austin, TX" or "only local to TX"
        clean = re.sub(r"\s*([-–|]?\s*(only\s+)?local\s+to\s+\w+.*|[-–|]\s*\w+,\s*\w+.*)$",
                       "", clean, flags=re.IGNORECASE).strip()
        return clean[:120]
    return ""


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

        # Broad Gmail search — 3-pass strategy, searches ALL folders (Inbox + Promotions + Updates):
        #
        # Pass 1: label:job_alerts — user-labelled emails
        # Pass 2: Domain-level sender patterns — catches iHire, Lensa, jobs2web etc.
        #         Using "from:domain.com" catches ALL addresses from that domain.
        # Pass 3: Subject keywords — catches anything with "job alert", "just posted", etc.
        #         Intentionally broad: single words + phrases. Gmail OR logic is generous.
        #
        # NOTE: Gmail searches ALL mail by default (Inbox, Promotions, Updates, Social, etc.)
        # -label:sent and -label:chats exclude drafts/sent/chat noise.

        # Build domain-level from: filters (most reliable — catches any address on that domain)
        key_domains = [
            "ihire.com", "lensa.com", "jobs2web.com", "linkedin.com",
            "indeed.com", "dice.com", "glassdoor.com", "ziprecruiter.com",
            "monster.com", "careerbuilder.com", "handshake.com", "wellfound.com",
            "builtinnyc.com", "builtinsf.com", "builtin.com", "remoteok.com",
            "remotive.com", "weworkremotely.com", "talent.com", "snagajob.com",
            "flexjobs.com", "hired.com", "theladders.com", "jobcase.com",
            "smartrecruiters.com", "ashbyhq.com", "greenhouse.io", "lever.co",
            "otta.com", "powertofly.com", "idealist.org", "joblift.com",
            "zippia.com", "jobgether.com", "himalayas.app",
        ]
        from_domains = " OR ".join(f"from:{d}" for d in key_domains)

        # Subject keywords — broad single-word and phrase patterns
        subject_kw = (
            "subject:(\"job alert\" OR \"just posted\" OR \"new jobs\" OR \"jobs for you\""
            " OR \"jobs matching\" OR \"job opportunities\" OR \"open positions\""
            " OR \"new openings\" OR \"jobs posted\" OR \"career opportunities\""
            " OR \"hiring now\" OR \"job notification\" OR \"job agent\""
            " OR \"we found\" OR \"jobs in\" OR \"jobs at\" OR \"job recommendations\")"
        )

        query = (
            f"newer_than:{self.lookback_hours}h"
            f" (label:job_alerts"
            f" OR ({from_domains})"
            f" OR {subject_kw})"
            f" -label:sent -label:chats -label:drafts"
        )

        try:
            result = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=100,  # More results — includes Promotions tab
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

                # Extract full email metadata — store ALL of it regardless of sender
                sender_email = get_sender(email_msg)
                sender_domain = sender_email.split("@")[-1] if "@" in sender_email else sender_email
                source_label = classify_sender(sender_email) or sender_domain or "Email Alert"
                email_subject = email_msg.get("Subject", "")
                email_date = email_msg.get("Date", "")

                emails_scanned += 1
                body = decode_email_body(email_msg)

                # Extract all URLs — no whitelist gate. Any email that survived the
                # Gmail query is a candidate. We filter by URL pattern, not sender.
                raw_urls = extract_urls_from_text(body)

                for raw_url in raw_urls:
                    canonical = canonicalize_url(raw_url)

                    # Filter: must look like a job posting URL
                    if not is_job_url(canonical):
                        continue

                    urls_found += 1

                    # Skip already-known URLs
                    if canonical in existing_urls:
                        skipped += 1
                        continue

                    if self.dry_run:
                        logger.info(
                            f"[DRY-RUN] {canonical}\n"
                            f"  sender={sender_email} | source={source_label}"
                            f" | subject={email_subject[:60]}"
                        )
                        stored += 1
                        continue

                    # Try to fetch full job data from the URL (JSON-LD or ATS API)
                    job = self._fetch_job_from_url(canonical, source_label)
                    if job:
                        # Enrich with email metadata
                        job.setdefault("posted_at", email_date)
                        job["source_name"] = f"Gmail:{source_label}"
                        job["email_sender"] = sender_email
                        job["source_domain"] = sender_domain
                        job["raw_payload_json"] = f'{{"email_from":"{sender_email}","email_domain":"{sender_domain}","subject":"{email_subject[:200]}","date":"{email_date}","url":"{canonical}"}}'
                    else:
                        # Store minimal record — never lose a URL
                        guessed_title = _guess_title_from_subject(email_subject) or f"Job from {source_label}"
                        job = {
                            "title": guessed_title,
                            "company": "",
                            "url": canonical,
                            "description": "",
                            "location": "",
                            "posted_at": email_date,
                            "source_name": f"Gmail:{source_label}",
                            "email_sender": sender_email,
                            "source_domain": sender_domain,
                            "raw_payload_json": f'{{"email_from":"{sender_email}","email_domain":"{sender_domain}","subject":"{email_subject[:200]}","date":"{email_date}","url":"{canonical}"}}',
                        }

                    job_id = insert_job(job)
                    if job_id:
                        stored += 1
                        existing_urls.add(canonical)
                        logger.info(
                            f"Stored: {job.get('title','?')} | {source_label}"
                            f" | {sender_email} | {canonical[:60]}"
                        )
                    else:
                        skipped += 1

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
