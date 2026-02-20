"""Job feed fetcher — retrieves jobs from RSS feeds and public APIs.

Handles:
- RSS/Atom feed parsing (via feedparser)
- Public JSON API parsing (RemoteOK, Arbeitnow, Jobicy, etc.)
- Rate limiting per domain
- HTML cleanup for descriptions
- Graceful error handling (one failing source doesn't block others)
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from src.discovery.sources import JobSource, SourceType
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Track last request time per domain for rate limiting
_last_request: dict[str, float] = {}


def _rate_limit(url: str, min_delay: float) -> None:
    """Wait if needed to respect rate limits."""
    domain = urlparse(url).netloc
    last = _last_request.get(domain, 0)
    elapsed = time.time() - last
    if elapsed < min_delay:
        time.sleep(min_delay - elapsed)
    _last_request[domain] = time.time()


def _clean_html(html: str) -> str:
    """Strip HTML tags and clean up whitespace."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text[:2000]  # Cap description length


def fetch_rss(source: JobSource, query: str = "", location: str = "") -> list[dict]:
    """Fetch jobs from an RSS/Atom feed.

    Returns list of dicts: {title, company, url, description, location, source_name}
    """
    url = source.url_template.format(query=query, location=location)

    try:
        _rate_limit(url, source.rate_limit_seconds)
        feed = feedparser.parse(url)

        if feed.bozo and not feed.entries:
            logger.warning(f"Feed error for {source.name}: {feed.bozo_exception}")
            return []

        jobs = []
        for entry in feed.entries[:50]:  # Cap at 50 per source
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = _clean_html(entry.get("summary", "") or entry.get("description", ""))

            # Try to extract company from various feed formats
            company = ""
            if hasattr(entry, "author"):
                company = entry.author
            elif " at " in title:
                parts = title.rsplit(" at ", 1)
                if len(parts) == 2:
                    title, company = parts[0].strip(), parts[1].strip()
            elif " - " in title:
                parts = title.rsplit(" - ", 1)
                if len(parts) == 2:
                    title, company = parts[0].strip(), parts[1].strip()

            # Extract location from title or description
            loc = ""
            if hasattr(entry, "location"):
                loc = entry.location

            if title and link:
                jobs.append({
                    "title": title,
                    "company": company,
                    "url": link,
                    "description": summary,
                    "location": loc,
                    "source_name": source.name,
                })

        logger.info(f"Fetched {len(jobs)} jobs from {source.name}")
        return jobs

    except Exception as e:
        logger.error(f"Failed to fetch RSS from {source.name}: {e}")
        return []


def fetch_api(source: JobSource, query: str = "", location: str = "") -> list[dict]:
    """Fetch jobs from a public JSON API.

    Routes to the correct parser based on source.parser field.
    """
    url = source.url_template.format(query=query, location=location)

    try:
        _rate_limit(url, source.rate_limit_seconds)

        headers = {"User-Agent": "JobPilot/1.0 (job search assistant)"}
        headers.update(source.headers)

        with httpx.Client(timeout=30.0, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        parser_fn = API_PARSERS.get(source.parser, _parse_default)
        jobs = parser_fn(data, source.name)

        logger.info(f"Fetched {len(jobs)} jobs from {source.name}")
        return jobs

    except Exception as e:
        logger.error(f"Failed to fetch API from {source.name}: {e}")
        return []


# ---------------------------------------------------------------------------
# API-specific parsers
# ---------------------------------------------------------------------------

def _parse_remoteok(data: list | dict, source_name: str) -> list[dict]:
    """Parse RemoteOK API response."""
    if isinstance(data, dict):
        return []
    jobs = []
    for item in data[:50]:
        if isinstance(item, dict) and item.get("position"):
            jobs.append({
                "title": item.get("position", ""),
                "company": item.get("company", ""),
                "url": item.get("url", ""),
                "description": _clean_html(item.get("description", "")),
                "location": item.get("location", "Remote"),
                "source_name": source_name,
            })
    return jobs


def _parse_arbeitnow(data: dict, source_name: str) -> list[dict]:
    """Parse Arbeitnow API response."""
    jobs = []
    for item in data.get("data", [])[:50]:
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "url": item.get("url", ""),
            "description": _clean_html(item.get("description", "")),
            "location": item.get("location", ""),
            "source_name": source_name,
        })
    return jobs


def _parse_jobicy(data: dict, source_name: str) -> list[dict]:
    """Parse Jobicy API response."""
    jobs = []
    for item in data.get("jobs", [])[:50]:
        jobs.append({
            "title": item.get("jobTitle", ""),
            "company": item.get("companyName", ""),
            "url": item.get("url", ""),
            "description": _clean_html(item.get("jobDescription", "")),
            "location": item.get("jobGeo", ""),
            "source_name": source_name,
        })
    return jobs


def _parse_findwork(data: dict, source_name: str) -> list[dict]:
    """Parse FindWork API response."""
    jobs = []
    for item in data.get("results", [])[:50]:
        jobs.append({
            "title": item.get("role", ""),
            "company": item.get("company_name", ""),
            "url": item.get("url", ""),
            "description": _clean_html(item.get("text", "")),
            "location": item.get("location", ""),
            "source_name": source_name,
        })
    return jobs


def _parse_hackernews(data: dict, source_name: str) -> list[dict]:
    """Parse HN Who's Hiring thread (single item, kids are comments)."""
    # This parser is called per-comment, not for the parent
    # The bot handles the HN flow separately
    return []


def _parse_himalayas(data: dict, source_name: str) -> list[dict]:
    """Parse Himalayas API response."""
    jobs = []
    for item in data.get("jobs", [])[:50]:
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("companyName", ""),
            "url": item.get("applicationLink", "") or f"https://himalayas.app/jobs/{item.get('slug', '')}",
            "description": _clean_html(item.get("description", "")),
            "location": item.get("location", ""),
            "source_name": source_name,
        })
    return jobs


def _parse_default(data: list | dict, source_name: str) -> list[dict]:
    """Fallback parser for unknown API formats."""
    logger.warning(f"No parser for {source_name}, skipping")
    return []


API_PARSERS = {
    "remoteok": _parse_remoteok,
    "arbeitnow": _parse_arbeitnow,
    "jobicy": _parse_jobicy,
    "findwork": _parse_findwork,
    "hackernews": _parse_hackernews,
    "himalayas": _parse_himalayas,
    "default": _parse_default,
}


def fetch_source(source: JobSource, query: str = "", location: str = "") -> list[dict]:
    """Fetch jobs from any source (dispatches to RSS or API)."""
    if source.source_type in (SourceType.RSS, SourceType.CAREER_RSS):
        return fetch_rss(source, query, location)
    elif source.source_type == SourceType.API:
        return fetch_api(source, query, location)
    else:
        logger.warning(f"Unknown source type: {source.source_type}")
        return []
