"""Job feed fetcher — retrieves jobs from RSS feeds and public APIs.

Handles:
- RSS/Atom feed parsing (via feedparser)
- Public JSON API parsing (RemoteOK, Arbeitnow, Jobicy, Himalayas, etc.)
- Rate limiting per domain
- ETag / If-Modified-Since caching for efficient re-fetching
- Content hash comparison for change detection
- HTML cleanup for descriptions
- Graceful error handling (one failing source doesn't block others)
"""

from __future__ import annotations

import hashlib
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


def fetch_rss(source: JobSource, query: str = "", location: str = "",
              etag: str = "", modified: str = "") -> list[dict]:
    """Fetch jobs from an RSS/Atom feed.

    Supports conditional fetching via ETag/If-Modified-Since headers.
    Returns list of dicts: {title, company, url, description, location, source_name}
    Also sets _last_etag and _last_modified on the returned list for caching.
    """
    url = source.url_template.format(query=query, location=location)

    try:
        _rate_limit(url, source.rate_limit_seconds)
        feed = feedparser.parse(url, etag=etag or None, modified=modified or None)

        # 304 Not Modified — no new content
        if feed.status == 304 if hasattr(feed, "status") else False:
            logger.debug(f"[304] {source.name} — not modified since last fetch")
            return []

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

        # Capture caching headers for next fetch
        _last_fetch_meta[source.name] = {
            "etag": getattr(feed, "etag", "") or "",
            "modified": getattr(feed, "modified", "") or "",
            "content_hash": hashlib.md5(str(feed.entries[:5]).encode()).hexdigest()[:16],
        }

        logger.info(f"Fetched {len(jobs)} jobs from {source.name}")
        return jobs

    except Exception as e:
        logger.error(f"Failed to fetch RSS from {source.name}: {e}")
        return []


# Cache of ETag/Last-Modified from most recent fetches
_last_fetch_meta: dict[str, dict] = {}


def get_last_fetch_meta(source_name: str) -> dict:
    """Get the ETag/Last-Modified from the most recent fetch of a source."""
    return _last_fetch_meta.get(source_name, {"etag": "", "modified": "", "content_hash": ""})


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
    for item in data.get("jobs", []):
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("companyName", ""),
            "url": item.get("applicationLink", "") or f"https://himalayas.app/jobs/{item.get('slug', '')}",
            "description": _clean_html(item.get("description", "")),
            "location": item.get("location", "Remote"),
            "source_name": source_name,
        })
    return jobs


def _parse_remotive(data: dict, source_name: str) -> list[dict]:
    """Parse Remotive API — all remote tech jobs."""
    jobs = []
    for item in data.get("jobs", []):
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "url": item.get("url", ""),
            "description": _clean_html(item.get("description", "")),
            "location": item.get("candidate_required_location", "Remote"),
            "source_name": source_name,
        })
    return jobs


def _parse_greenhouse(data: dict | list, source_name: str) -> list[dict]:
    """Parse Greenhouse JSON API: boards-api.greenhouse.io/v1/boards/{slug}/jobs

    Returns ALL open roles for the company — no arbitrary cap.
    """
    jobs_list = data.get("jobs", []) if isinstance(data, dict) else []
    # Company name comes from job entries
    jobs = []
    for item in jobs_list:
        location = ""
        loc = item.get("location", {})
        if isinstance(loc, dict):
            location = loc.get("name", "")
        elif isinstance(loc, str):
            location = loc
        url = item.get("absolute_url", "")
        if not url:
            url = f"https://boards.greenhouse.io/jobs/{item.get('id', '')}"
        company = item.get("company_name", "") or source_name
        jobs.append({
            "title": item.get("title", ""),
            "company": company,
            "url": url,
            "description": _clean_html(item.get("content", "") or ""),
            "location": location,
            "source_name": source_name,
        })
    return jobs


def _parse_lever(data: list | dict, source_name: str) -> list[dict]:
    """Parse Lever JSON API: api.lever.co/v0/postings/{slug}?mode=json"""
    if isinstance(data, dict):
        return []
    jobs = []
    for item in (data or []):
        cats = item.get("categories", {}) or {}
        location = cats.get("location", "")
        if not location:
            all_locs = cats.get("allLocations", [])
            location = all_locs[0] if all_locs else ""
        company = item.get("company", "") or source_name
        jobs.append({
            "title": item.get("text", ""),
            "company": company,
            "url": item.get("hostedUrl", "") or item.get("applyUrl", ""),
            "description": _clean_html(
                (item.get("descriptionPlain", "") or item.get("description", ""))[:2000]
            ),
            "location": location,
            "source_name": source_name,
        })
    return jobs


def _parse_ashby(data: dict | list, source_name: str) -> list[dict]:
    """Parse Ashby JSON API: api.ashbyhq.com/posting-api/job-board/{slug}"""
    posts = data.get("jobPostings", []) if isinstance(data, dict) else []
    jobs = []
    for item in posts:
        location = item.get("location", "") or item.get("locationName", "")
        jobs.append({
            "title": item.get("title", ""),
            "company": source_name,
            "url": item.get("jobUrl", "") or item.get("applyUrl", ""),
            "description": _clean_html(item.get("descriptionHtml", "") or ""),
            "location": location,
            "source_name": source_name,
        })
    return jobs


def _parse_smartrecruiters(data: dict | list, source_name: str) -> list[dict]:
    """Parse SmartRecruiters JSON API: careers.smartrecruiters.com/{company}/postings?format=json"""
    if isinstance(data, list):
        items = data
    else:
        items = data.get("content", [])
    jobs = []
    for item in items:
        loc_data = item.get("location", {}) or {}
        city = loc_data.get("city", "")
        country = loc_data.get("country", "")
        region = loc_data.get("region", "")
        location = ", ".join(filter(None, [city, region, country]))
        job_id = item.get("id", "")
        ref_url = item.get("ref", "")
        if not ref_url and job_id:
            ref_url = f"https://careers.smartrecruiters.com/{source_name.replace(' ', '')}/{job_id}"
        jobs.append({
            "title": item.get("name", ""),
            "company": source_name,
            "url": ref_url,
            "description": item.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", "") if isinstance(item.get("jobAd"), dict) else "",
            "location": location,
            "source_name": source_name,
        })
    return jobs


def _parse_muse(data: dict, source_name: str) -> list[dict]:
    """Parse The Muse public API: themuse.com/api/public/jobs"""
    jobs = []
    for item in data.get("results", []):
        # Extract location
        locations = item.get("locations", [])
        location = locations[0].get("name", "") if locations else ""
        # Extract company
        company_data = item.get("company", {})
        company = company_data.get("name", "") if isinstance(company_data, dict) else ""
        # Extract description (short version)
        contents = item.get("contents", "")
        from bs4 import BeautifulSoup
        desc = BeautifulSoup(contents, "html.parser").get_text(separator=" ", strip=True)[:2000] if contents else ""
        job_url = item.get("refs", {}).get("landing_page", "") if isinstance(item.get("refs"), dict) else ""
        jobs.append({
            "title": item.get("name", ""),
            "company": company,
            "url": job_url,
            "description": desc,
            "location": location,
            "source_name": source_name,
        })
    return jobs


def _parse_adzuna(data: dict, source_name: str) -> list[dict]:
    """Parse Adzuna API: api.adzuna.com/v1/api/jobs/{country}/search/{page}"""
    jobs = []
    for item in data.get("results", []):
        loc = item.get("location", {})
        area = loc.get("area", []) if isinstance(loc, dict) else []
        location = area[-1] if area else ""
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("company", {}).get("display_name", "") if isinstance(item.get("company"), dict) else "",
            "url": item.get("redirect_url", ""),
            "description": _clean_html(item.get("description", "")),
            "location": location,
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
    "remotive": _parse_remotive,
    "greenhouse": _parse_greenhouse,
    "lever": _parse_lever,
    "ashby": _parse_ashby,
    "smartrecruiters": _parse_smartrecruiters,
    "muse": _parse_muse,
    "adzuna": _parse_adzuna,
    "default": _parse_default,
}


def fetch_source(source: JobSource, query: str = "", location: str = "",
                 etag: str = "", modified: str = "") -> list[dict]:
    """Fetch jobs from any source (dispatches to RSS or API).

    Pass etag/modified from previous fetch to enable conditional requests.
    """
    if source.source_type in (SourceType.RSS, SourceType.CAREER_RSS):
        return fetch_rss(source, query, location, etag=etag, modified=modified)
    elif source.source_type == SourceType.API:
        return fetch_api(source, query, location)
    else:
        logger.warning(f"Unknown source type: {source.source_type}")
        return []


def fetch_paginated(source: JobSource, query: str = "", location: str = "",
                    max_pages: int = 10) -> list[dict]:
    """Fetch multiple pages from a paginated API source.

    Used for backfill mode and high-volume collection from APIs that support
    page-based pagination (The Muse, Adzuna, etc.).
    """
    if source.parser == "muse":
        return _fetch_muse_paginated(source, max_pages)
    elif source.parser == "adzuna":
        return _fetch_adzuna_paginated(source, query, location, max_pages)
    else:
        return fetch_api(source, query, location)


def _fetch_muse_paginated(source: JobSource, max_pages: int = 10) -> list[dict]:
    """Fetch multiple pages from The Muse API (reads page_count from response)."""
    import re as _re
    all_jobs: list[dict] = []
    base_url = source.url_template

    # Replace page=0 with a template
    if "page=0" in base_url:
        base_template = base_url.replace("page=0", "page={page}")
    else:
        base_template = base_url + "&page={page}"

    try:
        first_url = base_template.format(page=0)
        _rate_limit(first_url, source.rate_limit_seconds)
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(first_url)
            resp.raise_for_status()
            data = resp.json()

        all_jobs.extend(_parse_muse(data, source.name))
        total_pages = min(int(data.get("page_count", 1)), max_pages)
        logger.info(f"[Muse paginated] {source.name}: fetching {total_pages} pages")

        for page in range(1, total_pages):
            try:
                url = base_template.format(page=page)
                _rate_limit(url, source.rate_limit_seconds)
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    page_data = resp.json()
                page_jobs = _parse_muse(page_data, source.name)
                if not page_jobs:
                    break
                all_jobs.extend(page_jobs)
            except Exception as e:
                logger.warning(f"[Muse page {page}] {e}")
                break

        logger.info(f"[Muse paginated] {source.name}: {len(all_jobs)} total jobs")
    except Exception as e:
        logger.error(f"Muse paginated fetch failed for {source.name}: {e}")

    return all_jobs


def _fetch_adzuna_paginated(source: JobSource, query: str, location: str,
                             max_pages: int = 5) -> list[dict]:
    """Fetch multiple pages from Adzuna (/search/1, /search/2, ...)."""
    import re as _re
    all_jobs: list[dict] = []

    for page in range(1, max_pages + 1):
        try:
            url = _re.sub(r"/search/\d+", f"/search/{page}", source.url_template)
            _rate_limit(url, source.rate_limit_seconds)
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
            jobs = _parse_adzuna(data, source.name)
            if not jobs:
                break
            all_jobs.extend(jobs)
        except Exception as e:
            logger.warning(f"[Adzuna page {page}] {e}")
            break

    return all_jobs
