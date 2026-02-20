"""Signal source definitions — RSS feeds, news APIs, WARN notices.

All sources are public RSS/API. No scraping, no login required.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SignalSource:
    name: str
    source_type: str        # "rss", "api", "html"
    url: str                # URL template — use {query} for company name if needed
    signal_types: list[str] # which signal types this source produces
    enabled: bool = True
    requires_query: bool = False  # True if URL needs company name substitution


# ---------------------------------------------------------------------------
# Funding / Business news
# ---------------------------------------------------------------------------

FUNDING_SOURCES: list[SignalSource] = [
    SignalSource(
        name="PR Newswire — Tech",
        source_type="rss",
        url="https://www.prnewswire.com/rss/news-releases-list.rss",
        signal_types=["funding", "expansion", "acquisition", "product"],
    ),
    SignalSource(
        name="BusinessWire — Tech",
        source_type="rss",
        url="https://feed.businesswire.com/rss/home/?rss=G1",
        signal_types=["funding", "acquisition", "contract", "product"],
    ),
    SignalSource(
        name="GlobeNewswire — Finance",
        source_type="rss",
        url="https://www.globenewswire.com/RssFeed/subjectcode/23-Financial+and+Business+services",
        signal_types=["funding", "acquisition"],
    ),
    SignalSource(
        name="TechCrunch — Startups",
        source_type="rss",
        url="https://techcrunch.com/category/startups/feed/",
        signal_types=["funding", "acquisition", "expansion"],
    ),
    SignalSource(
        name="VentureBeat",
        source_type="rss",
        url="https://venturebeat.com/feed/",
        signal_types=["funding", "product", "expansion"],
    ),
]

# ---------------------------------------------------------------------------
# WARN Act (Layoff notices — US public data)
# Sources aggregate WARN filings from state labor departments
# ---------------------------------------------------------------------------

WARN_SOURCES: list[SignalSource] = [
    SignalSource(
        name="WARN Tracker — RSS",
        source_type="rss",
        url="https://warn-tracker.com/feed",
        signal_types=["layoff"],
        enabled=True,
    ),
    SignalSource(
        name="Layoffs.fyi RSS",
        source_type="rss",
        url="https://layoffs.fyi/feed/",
        signal_types=["layoff"],
        enabled=True,
    ),
]

# ---------------------------------------------------------------------------
# Government contracts (USASpending proxy — RSS)
# Contract wins often precede significant hiring
# ---------------------------------------------------------------------------

CONTRACT_SOURCES: list[SignalSource] = [
    SignalSource(
        name="GovWin — Federal Contracts",
        source_type="rss",
        url="https://www.govwin.com/rss/newsroom.rss",
        signal_types=["contract"],
        enabled=True,
    ),
]

# ---------------------------------------------------------------------------
# Company leadership / expansion
# ---------------------------------------------------------------------------

EXPANSION_SOURCES: list[SignalSource] = [
    SignalSource(
        name="Business Insider — Tech",
        source_type="rss",
        url="https://feeds.businessinsider.com/custom/all",
        signal_types=["leadership", "expansion", "acquisition"],
    ),
    SignalSource(
        name="ZDNet — Business",
        source_type="rss",
        url="https://www.zdnet.com/topic/business/rss.xml",
        signal_types=["contract", "expansion", "product"],
    ),
]

# ---------------------------------------------------------------------------
# All sources combined
# ---------------------------------------------------------------------------

ALL_SIGNAL_SOURCES: list[SignalSource] = (
    FUNDING_SOURCES
    + WARN_SOURCES
    + CONTRACT_SOURCES
    + EXPANSION_SOURCES
)


def get_enabled_sources(signal_type: str | None = None) -> list[SignalSource]:
    """Return enabled sources, optionally filtered by signal type."""
    sources = [s for s in ALL_SIGNAL_SOURCES if s.enabled]
    if signal_type:
        sources = [s for s in sources if signal_type in s.signal_types]
    return sources
