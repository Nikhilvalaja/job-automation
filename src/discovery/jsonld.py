"""JSON-LD schema.org/JobPosting extractor.

Extracts structured job data from company career pages that publish
schema.org JobPosting markup in <script type="application/ld+json"> tags.

This is the cleanest legal "web extraction" strategy:
- We're reading structured data the company explicitly publishes
- No HTML scraping / DOM parsing
- Respects robots.txt (checked before crawling)
- Rate-limited per domain

Usage:
    from src.discovery.jsonld import extract_jobs_from_url, detect_ats

    jobs = extract_jobs_from_url("https://careers.example.com/jobs")
    ats = detect_ats("https://careers.example.com/jobs/12345")
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from src.utils.logging import get_logger

logger = get_logger(__name__)

# Rate limiting per domain
_last_request_time: dict[str, float] = {}
_robots_cache: dict[str, RobotFileParser] = {}

# How we identify ourselves
USER_AGENT = "JobPilot/1.0 (+https://github.com/Nikhilvalaja/job-automation; job search bot)"
MIN_DELAY_SECONDS = 2.0  # Min delay between requests to same domain


# ---------------------------------------------------------------------------
# ATS Detection — prefer JSON APIs over crawling when possible
# ---------------------------------------------------------------------------

ATS_PATTERNS = {
    "greenhouse": [
        r"boards\.greenhouse\.io",
        r"boards-api\.greenhouse\.io",
        r"greenhouse\.io/careers",
    ],
    "lever": [
        r"jobs\.lever\.co",
        r"api\.lever\.co",
        r"lever\.co/careers",
    ],
    "ashby": [
        r"jobs\.ashbyhq\.com",
        r"api\.ashbyhq\.com",
        r"app\.ashbyhq\.com",
    ],
    "smartrecruiters": [
        r"careers\.smartrecruiters\.com",
        r"smartrecruiters\.com/careers",
    ],
    "workday": [
        r"myworkdayjobs\.com",
        r"wd\d+\.myworkdayjobs\.com",
        r"workday\.com/en-us/pages/careers",
    ],
    "icims": [
        r"careers-\w+\.icims\.com",
        r"icims\.com/jobs",
    ],
    "taleo": [
        r"taleo\.net",
        r"oraclecloud\.com/hcmUI/CandidateExperience",
    ],
    "successfactors": [
        r"successfactors\.com",
        r"successfactors\.eu",
    ],
    "bamboohr": [
        r"bamboohr\.com/careers",
        r"\.bamboohr\.com/jobs",
    ],
    "jobvite": [
        r"hire\.jobvite\.com",
        r"jobs\.jobvite\.com",
    ],
    "breezy": [
        r"breezy\.hr",
        r"app\.breezyhr\.com",
    ],
    "workable": [
        r"apply\.workable\.com",
        r"\.workable\.com/j/",
    ],
}


def detect_ats(url: str) -> str | None:
    """Detect which ATS platform a URL belongs to.

    Returns ATS name ('greenhouse', 'lever', etc.) or None if unknown.
    """
    for ats_name, patterns in ATS_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return ats_name
    return None


def get_preferred_api_url(ats: str, company_slug: str) -> str | None:
    """Get the JSON API URL for a known ATS + company slug.

    Returns the API URL if we know how to fetch it, None otherwise.
    """
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{company_slug}"
    if ats == "smartrecruiters":
        return f"https://careers.smartrecruiters.com/{company_slug}/postings?format=json&limit=100"
    return None


# ---------------------------------------------------------------------------
# robots.txt checker
# ---------------------------------------------------------------------------

def _can_fetch(url: str) -> bool:
    """Check if robots.txt allows us to fetch this URL."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if robots_url not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
            _robots_cache[robots_url] = rp
        except Exception:
            # If robots.txt can't be read, assume allowed
            return True

    return _robots_cache[robots_url].can_fetch(USER_AGENT, url)


def _rate_limit(url: str) -> None:
    """Enforce per-domain rate limiting."""
    domain = urlparse(url).netloc
    last = _last_request_time.get(domain, 0)
    elapsed = time.time() - last
    if elapsed < MIN_DELAY_SECONDS:
        time.sleep(MIN_DELAY_SECONDS - elapsed)
    _last_request_time[domain] = time.time()


# ---------------------------------------------------------------------------
# JSON-LD extraction core
# ---------------------------------------------------------------------------

def _extract_jsonld_blocks(html: str) -> list[dict]:
    """Extract all JSON-LD blocks from an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            content = script.string or ""
            if not content.strip():
                continue
            data = json.loads(content)
            blocks.append(data)
        except (json.JSONDecodeError, Exception):
            continue
    return blocks


def _find_job_postings(blocks: list[dict]) -> list[dict]:
    """Find JobPosting entries from JSON-LD blocks.

    Handles:
    - Single JobPosting object
    - Array of JobPosting objects
    - @graph container with JobPosting items
    - ItemList containing JobPosting
    """
    postings = []

    def _is_job_posting(obj: dict) -> bool:
        t = obj.get("@type", "")
        if isinstance(t, list):
            return "JobPosting" in t
        return t == "JobPosting"

    def _process(obj: dict | list) -> None:
        if isinstance(obj, list):
            for item in obj:
                _process(item)
        elif isinstance(obj, dict):
            if _is_job_posting(obj):
                postings.append(obj)
            # Check @graph
            if "@graph" in obj:
                _process(obj["@graph"])
            # Check itemListElement
            if "itemListElement" in obj:
                _process(obj["itemListElement"])

    for block in blocks:
        _process(block)

    return postings


def _normalize_posting(posting: dict, source_url: str, company_name: str) -> dict | None:
    """Normalize a schema.org JobPosting into our standard job dict."""
    title = posting.get("title", "") or posting.get("name", "")
    if not title:
        return None

    # Company
    hiring_org = posting.get("hiringOrganization", {})
    if isinstance(hiring_org, dict):
        company = hiring_org.get("name", company_name)
    else:
        company = company_name

    # Location
    job_location = posting.get("jobLocation", {})
    location = ""
    if isinstance(job_location, dict):
        address = job_location.get("address", {})
        if isinstance(address, dict):
            city = address.get("addressLocality", "")
            state = address.get("addressRegion", "")
            country = address.get("addressCountry", "")
            location = ", ".join(filter(None, [city, state, country]))
        elif isinstance(address, str):
            location = address
    elif isinstance(job_location, list) and job_location:
        first_loc = job_location[0]
        if isinstance(first_loc, dict):
            addr = first_loc.get("address", {})
            if isinstance(addr, dict):
                city = addr.get("addressLocality", "")
                state = addr.get("addressRegion", "")
                location = ", ".join(filter(None, [city, state]))

    # Remote / Employment type
    remote_type = "unknown"
    remote_status = posting.get("jobLocationType", "")
    if remote_status == "TELECOMMUTE":
        remote_type = "remote"
    work_loc = posting.get("applicantLocationRequirements", {})
    if work_loc:
        remote_type = "remote"

    # URL to apply
    apply_url = posting.get("url", "") or posting.get("sameAs", "") or source_url

    # Description
    desc_raw = posting.get("description", "")
    if desc_raw:
        desc = BeautifulSoup(desc_raw, "html.parser").get_text(separator=" ", strip=True)[:2000]
    else:
        desc = ""

    # Salary
    salary_text = ""
    salary_range = posting.get("baseSalary", {})
    if isinstance(salary_range, dict):
        value = salary_range.get("value", {})
        if isinstance(value, dict):
            min_val = value.get("minValue", "")
            max_val = value.get("maxValue", "")
            currency = salary_range.get("currency", "USD")
            if min_val and max_val:
                salary_text = f"{currency} {min_val}-{max_val}"

    return {
        "title": str(title).strip(),
        "company": str(company).strip(),
        "url": str(apply_url).strip(),
        "description": desc,
        "location": location,
        "remote_type": remote_type,
        "salary_text": salary_text,
        "source_name": "JSON-LD",
    }


# ---------------------------------------------------------------------------
# Link discovery — find job links on career listing pages
# ---------------------------------------------------------------------------

def _extract_job_links(html: str, base_url: str) -> list[str]:
    """Extract candidate job-detail links from a career listing page."""
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc

    job_link_patterns = [
        r"/jobs?/",
        r"/careers?/",
        r"/openings?/",
        r"/positions?/",
        r"/roles?/",
        r"/apply",
        r"/posting",
        r"/vacancy",
        r"/requisition",
        r"/jd/",
    ]

    links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Only follow same-domain links
        if parsed.netloc != base_domain:
            continue

        path = parsed.path.lower()
        if any(re.search(p, path) for p in job_link_patterns):
            # Filter out listing pages (usually short paths like /jobs)
            # Prefer detail pages (longer paths)
            if len(path.split("/")) >= 3:
                links.add(full_url)

    return list(links)[:50]  # Cap at 50 links per page


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_page(url: str, timeout: float = 20.0) -> str | None:
    """Fetch a URL and return HTML content, respecting robots.txt and rate limits."""
    if not _can_fetch(url):
        logger.info(f"[robots.txt] Blocked: {url}")
        return None

    _rate_limit(url)

    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code in (429, 503):
                logger.warning(f"Rate limited by {urlparse(url).netloc} — backing off")
                time.sleep(10)
            elif resp.status_code in (403, 401):
                logger.warning(f"Blocked by {urlparse(url).netloc} — stopping crawl")
            return None
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def extract_jobs_from_url(url: str, company_name: str = "") -> list[dict]:
    """Extract job postings from a URL using JSON-LD schema.org markup.

    First checks if the page has JSON-LD JobPosting blocks directly.
    If the page is a job listing (multiple jobs), also discovers and
    fetches individual job detail pages.

    Args:
        url: Career page or job listing URL
        company_name: Fallback company name if not found in markup

    Returns:
        List of normalized job dicts
    """
    # Check if URL belongs to a known ATS — prefer their JSON API
    ats = detect_ats(url)
    if ats in ("greenhouse", "lever", "ashby", "smartrecruiters"):
        logger.info(f"URL belongs to {ats} ATS — use their JSON API instead of JSON-LD crawl")
        return []

    html = fetch_page(url)
    if not html:
        return []

    if not company_name:
        # Try to extract company name from page title
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("title")
        company_name = title_tag.get_text().split("|")[0].split("-")[0].strip() if title_tag else urlparse(url).netloc

    jobs = []

    # Try direct JSON-LD extraction from this page
    blocks = _extract_jsonld_blocks(html)
    postings = _find_job_postings(blocks)

    if postings:
        for posting in postings:
            job = _normalize_posting(posting, url, company_name)
            if job:
                jobs.append(job)
        logger.info(f"[JSON-LD] {url} → {len(jobs)} jobs (direct)")
    else:
        # No direct postings — try to find job detail links and crawl them
        job_links = _extract_job_links(html, url)
        logger.info(f"[JSON-LD] {url} → No direct postings, found {len(job_links)} links to check")

        for link in job_links[:20]:  # Cap at 20 detail pages per listing
            detail_html = fetch_page(link)
            if not detail_html:
                continue
            detail_blocks = _extract_jsonld_blocks(detail_html)
            detail_postings = _find_job_postings(detail_blocks)
            for posting in detail_postings:
                job = _normalize_posting(posting, link, company_name)
                if job:
                    jobs.append(job)

        logger.info(f"[JSON-LD] {url} → {len(jobs)} jobs (from detail pages)")

    return jobs


def extract_jobs_from_sitemap(sitemap_url: str, company_name: str = "", max_pages: int = 30) -> list[dict]:
    """Extract jobs by crawling sitemap.xml and finding JobPosting pages.

    More efficient than crawling the full site — sitemaps list all pages.
    """
    html = fetch_page(sitemap_url)
    if not html:
        return []

    # Parse sitemap XML
    soup = BeautifulSoup(html, "xml")
    urls = [loc.get_text() for loc in soup.find_all("loc")]

    job_path_patterns = [
        r"/jobs?/",
        r"/careers?/",
        r"/openings?/",
        r"/positions?/",
        r"/roles?/",
        r"/apply",
        r"/posting",
    ]

    job_page_urls = [
        u for u in urls
        if any(re.search(p, u, re.IGNORECASE) for p in job_path_patterns)
    ][:max_pages]

    logger.info(f"[Sitemap] Found {len(job_page_urls)} potential job pages in {sitemap_url}")

    jobs = []
    for page_url in job_page_urls:
        html = fetch_page(page_url)
        if not html:
            continue
        blocks = _extract_jsonld_blocks(html)
        postings = _find_job_postings(blocks)
        for posting in postings:
            job = _normalize_posting(posting, page_url, company_name)
            if job:
                jobs.append(job)

    logger.info(f"[Sitemap] {sitemap_url} → {len(jobs)} jobs total")
    return jobs


# ---------------------------------------------------------------------------
# Company registry helpers
# ---------------------------------------------------------------------------

# Companies with JSON-LD JobPosting on their career pages
# (not on Greenhouse/Lever/Ashby — those have better JSON APIs)
JSONLD_COMPANY_REGISTRY = [
    {"name": "Netflix", "careers_url": "https://jobs.netflix.com/search", "company_name": "Netflix"},
    {"name": "Apple", "careers_url": "https://jobs.apple.com/en-us/search", "company_name": "Apple"},
    {"name": "Microsoft", "careers_url": "https://careers.microsoft.com/us/en/search-results", "company_name": "Microsoft"},
    {"name": "Google", "careers_url": "https://careers.google.com/jobs/results/", "company_name": "Google"},
    {"name": "Amazon", "careers_url": "https://www.amazon.jobs/en/search", "company_name": "Amazon"},
    {"name": "Meta", "careers_url": "https://www.metacareers.com/jobs", "company_name": "Meta"},
    {"name": "LinkedIn", "careers_url": "https://careers.linkedin.com/jobs", "company_name": "LinkedIn"},
    {"name": "Salesforce", "careers_url": "https://careers.salesforce.com/en/jobs/", "company_name": "Salesforce"},
    {"name": "Oracle", "careers_url": "https://careers.oracle.com/jobs/#en/sites/jobsearch/jobs", "company_name": "Oracle"},
    {"name": "IBM", "careers_url": "https://www.ibm.com/employment/search.html", "company_name": "IBM"},
    {"name": "Intel", "careers_url": "https://jobs.intel.com/page/careers", "company_name": "Intel"},
    {"name": "NVIDIA", "careers_url": "https://www.nvidia.com/en-us/about-nvidia/careers/", "company_name": "NVIDIA"},
    {"name": "Qualcomm", "careers_url": "https://careers.qualcomm.com/careers", "company_name": "Qualcomm"},
    {"name": "AMD", "careers_url": "https://careers.amd.com/careers-home/jobs", "company_name": "AMD"},
    {"name": "Broadcom", "careers_url": "https://careers.broadcom.com/careers", "company_name": "Broadcom"},
    {"name": "Texas Instruments", "careers_url": "https://careers.ti.com/jobs", "company_name": "Texas Instruments"},
    {"name": "Cisco", "careers_url": "https://jobs.cisco.com/jobs/SearchJobs", "company_name": "Cisco"},
    {"name": "Dell Technologies", "careers_url": "https://jobs.dell.com/search-jobs", "company_name": "Dell Technologies"},
    {"name": "HP Inc", "careers_url": "https://jobs.hp.com/jobsearch/SearchJobs", "company_name": "HP Inc"},
    {"name": "HPE", "careers_url": "https://careers.hpe.com/us/en/search-results", "company_name": "HPE"},
    {"name": "SAP", "careers_url": "https://jobs.sap.com/search/", "company_name": "SAP"},
    {"name": "Adobe", "careers_url": "https://careers.adobe.com/us/en/search-results", "company_name": "Adobe"},
    {"name": "Autodesk", "careers_url": "https://www.autodesk.com/careers/job-listing", "company_name": "Autodesk"},
    {"name": "ServiceNow", "careers_url": "https://careers.servicenow.com/jobs", "company_name": "ServiceNow"},
    {"name": "Workday", "careers_url": "https://www.workday.com/en-us/company/careers.html", "company_name": "Workday"},
    {"name": "Intuit", "careers_url": "https://jobs.intuit.com/search-jobs", "company_name": "Intuit"},
    {"name": "PayPal", "careers_url": "https://careers.pypl.com/home/", "company_name": "PayPal"},
    {"name": "Visa (Workday)", "careers_url": "https://corporate.visa.com/en/jobs/", "company_name": "Visa"},
    {"name": "Twitter/X", "careers_url": "https://careers.twitter.com/en/jobs.html", "company_name": "X Corp"},
    {"name": "Shopify", "careers_url": "https://www.shopify.com/careers/search", "company_name": "Shopify"},
    {"name": "Atlassian", "careers_url": "https://www.atlassian.com/company/careers/all-jobs", "company_name": "Atlassian"},
    {"name": "Zoom", "careers_url": "https://careers.zoom.us/jobs/search", "company_name": "Zoom"},
    {"name": "Slack", "careers_url": "https://slack.com/careers", "company_name": "Slack"},
    {"name": "Dropbox", "careers_url": "https://jobs.dropbox.com/all-jobs", "company_name": "Dropbox"},
    {"name": "Twitch", "careers_url": "https://www.twitch.tv/jobs/", "company_name": "Twitch"},
    {"name": "Airbnb", "careers_url": "https://careers.airbnb.com/positions/", "company_name": "Airbnb"},
    {"name": "Uber", "careers_url": "https://www.uber.com/us/en/careers/list/", "company_name": "Uber"},
    {"name": "Lyft", "careers_url": "https://www.lyft.com/careers/data", "company_name": "Lyft"},
    {"name": "DoorDash", "careers_url": "https://careers.doordash.com/jobs/", "company_name": "DoorDash"},
    {"name": "Instacart", "careers_url": "https://careers.instacart.com/", "company_name": "Instacart"},
    {"name": "Robinhood", "careers_url": "https://careers.robinhood.com/", "company_name": "Robinhood"},
    {"name": "Coinbase", "careers_url": "https://www.coinbase.com/careers/positions", "company_name": "Coinbase"},
    {"name": "Spotify", "careers_url": "https://www.lifeatspotify.com/jobs", "company_name": "Spotify"},
    {"name": "Reddit", "careers_url": "https://www.redditinc.com/careers", "company_name": "Reddit"},
    {"name": "Pinterest", "careers_url": "https://www.pinterestcareers.com/jobs/", "company_name": "Pinterest"},
    {"name": "Snap", "careers_url": "https://careers.snap.com/jobs", "company_name": "Snap"},
    {"name": "Twitter", "careers_url": "https://careers.twitter.com/en/jobs.html", "company_name": "Twitter"},
    {"name": "Bytedance/TikTok", "careers_url": "https://jobs.bytedance.com/en/position", "company_name": "ByteDance"},
    {"name": "Stripe", "careers_url": "https://stripe.com/jobs/search", "company_name": "Stripe"},
    {"name": "Square", "careers_url": "https://careers.squareup.com/us/en/jobs", "company_name": "Square"},
    {"name": "Figma", "careers_url": "https://www.figma.com/careers/", "company_name": "Figma"},
    {"name": "Notion", "careers_url": "https://www.notion.so/careers", "company_name": "Notion"},
    {"name": "Linear", "careers_url": "https://linear.app/careers", "company_name": "Linear"},
    {"name": "Vercel", "careers_url": "https://vercel.com/careers", "company_name": "Vercel"},
    {"name": "Supabase", "careers_url": "https://supabase.com/careers", "company_name": "Supabase"},
    {"name": "PlanetScale", "careers_url": "https://planetscale.com/careers", "company_name": "PlanetScale"},
    {"name": "Retool", "careers_url": "https://retool.com/careers", "company_name": "Retool"},
    {"name": "Airtable", "careers_url": "https://airtable.com/careers", "company_name": "Airtable"},
    {"name": "Webflow", "careers_url": "https://webflow.com/careers", "company_name": "Webflow"},
    {"name": "Contentful", "careers_url": "https://www.contentful.com/careers/", "company_name": "Contentful"},
    {"name": "Intercom", "careers_url": "https://www.intercom.com/careers", "company_name": "Intercom"},
    {"name": "HubSpot", "careers_url": "https://www.hubspot.com/jobs", "company_name": "HubSpot"},
    {"name": "Zendesk", "careers_url": "https://jobs.zendesk.com/us/en", "company_name": "Zendesk"},
]
