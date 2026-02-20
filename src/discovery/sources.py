"""Job discovery sources — RSS feeds, public APIs, and career page monitors.

All sources are ToS-compliant:
- RSS feeds are explicitly designed for automated consumption
- Public APIs have documented rate limits we respect
- Career pages are fetched via their public sitemap/RSS where available
- No scraping of pages that prohibit it (robots.txt respected)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SourceType(str, Enum):
    RSS = "rss"
    API = "api"
    CAREER_RSS = "career_rss"  # Company career page RSS/Atom feeds


@dataclass
class JobSource:
    """A single job discovery source."""
    name: str
    source_type: SourceType
    url_template: str  # May contain {query} and {location} placeholders
    enabled: bool = True
    rate_limit_seconds: float = 2.0  # Min seconds between requests to this domain
    parser: str = "default"  # Parser function name for API sources
    headers: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public Job Board APIs (free, no API key required)
# ---------------------------------------------------------------------------

JOB_BOARD_SOURCES = [
    # RemoteOK — remote-only jobs, JSON API
    JobSource(
        name="RemoteOK",
        source_type=SourceType.API,
        url_template="https://remoteok.com/api",
        parser="remoteok",
        headers={"User-Agent": "JobPilot/1.0 (job search assistant)"},
    ),
    # Arbeitnow — EU + remote jobs, public JSON API
    JobSource(
        name="Arbeitnow",
        source_type=SourceType.API,
        url_template="https://www.arbeitnow.com/api/job-board-api",
        parser="arbeitnow",
    ),
    # Indeed RSS — search results as RSS feed (explicitly supported by Indeed)
    JobSource(
        name="Indeed",
        source_type=SourceType.RSS,
        url_template="https://www.indeed.com/rss?q={query}&l={location}&sort=date",
        rate_limit_seconds=3.0,
    ),
    # HackerNews Who's Hiring — monthly thread, parsed via HN API
    JobSource(
        name="HN Who's Hiring",
        source_type=SourceType.API,
        url_template="https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
        parser="hackernews",
        rate_limit_seconds=1.0,
    ),
    # GitHub Jobs (via alternative aggregator)
    JobSource(
        name="Jobicy",
        source_type=SourceType.API,
        url_template="https://jobicy.com/api/v2/remote-jobs?count=50&tag={query}",
        parser="jobicy",
    ),
    # FindWork.dev — tech jobs API
    JobSource(
        name="FindWork",
        source_type=SourceType.API,
        url_template="https://findwork.dev/api/jobs/?search={query}&sort_by=relevance",
        parser="findwork",
    ),
]

# ---------------------------------------------------------------------------
# Company Career Page RSS Feeds
# Companies that publish their job openings as RSS/Atom feeds.
# These are official, ToS-compliant feeds published BY the companies.
# ---------------------------------------------------------------------------

COMPANY_CAREER_FEEDS = [
    # FAANG + Big Tech
    JobSource(name="Google Careers", source_type=SourceType.CAREER_RSS,
             url_template="https://careers.google.com/jobs/results/rss/?q={query}"),
    JobSource(name="Microsoft Careers", source_type=SourceType.CAREER_RSS,
             url_template="https://careers.microsoft.com/professionals/us/en/rss?q={query}"),
    JobSource(name="Apple Careers", source_type=SourceType.CAREER_RSS,
             url_template="https://jobs.apple.com/en-us/search?search={query}&rss=true"),

    # Top Tech Companies with RSS/Atom career feeds
    JobSource(name="Stripe Jobs", source_type=SourceType.CAREER_RSS,
             url_template="https://stripe.com/jobs/search?query={query}"),
    JobSource(name="Shopify Careers", source_type=SourceType.CAREER_RSS,
             url_template="https://www.shopify.com/careers/search?keywords={query}"),

    # Greenhouse-hosted careers (hundreds of companies use Greenhouse)
    # Format: https://boards.greenhouse.io/{company}/feed
    JobSource(name="Coinbase (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/coinbase/feed"),
    JobSource(name="Discord (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/discord/feed"),
    JobSource(name="Notion (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/notion/feed"),
    JobSource(name="Figma (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/figma/feed"),
    JobSource(name="Datadog (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/datadog/feed"),
    JobSource(name="Cloudflare (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/cloudflare/feed"),
    JobSource(name="Twitch (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/twitch/feed"),
    JobSource(name="Plaid (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/plaid/feed"),
    JobSource(name="GitLab (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/gitlab/feed"),
    JobSource(name="Ramp (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/ramp/feed"),
    JobSource(name="Brex (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/brex/feed"),
    JobSource(name="Scale AI (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/scaleai/feed"),
    JobSource(name="Anthropic (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/anthropic/feed"),
    JobSource(name="OpenAI (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/openai/feed"),
    JobSource(name="Vercel (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/vercel/feed"),
    JobSource(name="Supabase (Greenhouse)", source_type=SourceType.CAREER_RSS,
             url_template="https://boards.greenhouse.io/supabase/feed"),

    # Lever-hosted careers (another major ATS with RSS)
    # Format: https://jobs.lever.co/{company}/feed
    JobSource(name="Netflix (Lever)", source_type=SourceType.CAREER_RSS,
             url_template="https://jobs.lever.co/netflix/feed"),
    JobSource(name="Spotify (Lever)", source_type=SourceType.CAREER_RSS,
             url_template="https://jobs.lever.co/spotify/feed"),
    JobSource(name="Reddit (Lever)", source_type=SourceType.CAREER_RSS,
             url_template="https://jobs.lever.co/reddit/feed"),
    JobSource(name="Anduril (Lever)", source_type=SourceType.CAREER_RSS,
             url_template="https://jobs.lever.co/anduril/feed"),

    # Ashby-hosted careers
    JobSource(name="Linear (Ashby)", source_type=SourceType.CAREER_RSS,
             url_template="https://jobs.ashbyhq.com/linear/feed"),
    JobSource(name="Resend (Ashby)", source_type=SourceType.CAREER_RSS,
             url_template="https://jobs.ashbyhq.com/resend/feed"),
]

# ---------------------------------------------------------------------------
# All sources combined
# ---------------------------------------------------------------------------

ALL_SOURCES = JOB_BOARD_SOURCES + COMPANY_CAREER_FEEDS


def get_enabled_sources(source_names: list[str] | None = None) -> list[JobSource]:
    """Get enabled sources, optionally filtered by name.

    Args:
        source_names: If provided, only include sources whose name contains
                      any of these strings (case-insensitive).
    """
    sources = [s for s in ALL_SOURCES if s.enabled]

    if source_names:
        filtered = []
        for s in sources:
            for name in source_names:
                if name.lower() in s.name.lower():
                    filtered.append(s)
                    break
        return filtered

    return sources


def get_greenhouse_feed_url(company_slug: str) -> str:
    """Generate a Greenhouse RSS feed URL for any company."""
    return f"https://boards.greenhouse.io/{company_slug}/feed"


def get_lever_feed_url(company_slug: str) -> str:
    """Generate a Lever RSS feed URL for any company."""
    return f"https://jobs.lever.co/{company_slug}/feed"
