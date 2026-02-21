"""Discovery Bot — automatically finds new job opportunities.

Scans 200+ sources for job postings matching your preferences:
1. Public job board APIs (RemoteOK, Arbeitnow, Jobicy, FindWork)
2. Indeed RSS search results
3. 170+ company career page RSS feeds (Greenhouse, Lever, Ashby)

Stores results in SQLite database with structured metadata.
Runs keyword-based parsing to extract category, experience level,
job type, skills, etc. (ML/GPT upgrade coming later).

Usage:
    python -m bots.discovery_bot.run                            # Run discovery
    python -m bots.discovery_bot.run --dry-run                  # Preview without saving
    python -m bots.discovery_bot.run --sources remoteok,indeed  # Specific sources only
    python -m bots.discovery_bot.run --parse-only               # Only parse unparsed jobs
"""

from __future__ import annotations

import argparse
import io
import sys

from bots.base import BaseBot
from src.config import get_settings
from src.discovery.database import (
    get_all_ats_ids,
    get_all_fingerprints,
    get_all_urls,
    get_source_cache,
    get_stats,
    get_unparsed_jobs,
    init_db,
    insert_job,
    extract_ats_job_id,
    rebuild_fts_index,
    should_fetch_source,
    update_parsed_fields,
    update_source_stats,
    _compute_fingerprint,
)
from src.discovery.fetcher import fetch_source, get_last_fetch_meta
from src.discovery.parser import JobParser
from src.discovery.preferences import JobPreferences, score_job
from src.discovery.jsonld import extract_jobs_from_url, JSONLD_COMPANY_REGISTRY
from src.discovery.sources import get_enabled_sources, SourceType
from src.notifications.telegram import TelegramNotifier
from src.utils.logging import get_logger

# ---------------------------------------------------------------------------
# Query Grid — role families × location buckets for permissive APIs
# ---------------------------------------------------------------------------

ROLE_FAMILIES = [
    "software engineer",
    "backend engineer",
    "data engineer",
    "ML engineer",
    "python developer",
    "data analyst",
    "business analyst",
    "analytics engineer",
    "devops engineer",
    "platform engineer",
]

LOCATION_BUCKETS = [
    "remote",
    "New York",
    "San Francisco",
    "Seattle",
    "Austin",
    "Chicago",
    "Boston",
    "Atlanta",
    "United States",
]

# Sources that support query + location parameters (use query grid)
QUERY_GRID_SOURCES = {
    "findwork",   # supports ?search=keyword
    "jobicy",     # supports ?tag=keyword&location=...
}

logger = get_logger(__name__)


class DiscoveryBot(BaseBot):
    """Finds new job opportunities and stores them in the discovery database."""

    def __init__(
        self,
        source_filter: list[str] | None = None,
        dry_run: bool = False,
        parse_only: bool = False,
    ) -> None:
        super().__init__("discovery")
        self.source_filter = source_filter
        self.dry_run = dry_run
        self.parse_only = parse_only
        self._notifier: TelegramNotifier | None = None
        self._preferences: JobPreferences | None = None
        self._parser: JobParser | None = None

    def start(self) -> None:
        super().start()
        init_db()
        self._notifier = TelegramNotifier()
        self._preferences = JobPreferences.from_config()
        self._parser = JobParser()

        if self._preferences.keywords:
            logger.info(f"Discovery keywords: {self._preferences.keywords}")
        else:
            logger.info("No discovery keywords set — will accept all jobs")

    def run_once(self) -> dict:
        """Discover new jobs and parse them."""
        if self.parse_only:
            return self._run_parse_only()

        return self._run_discovery()

    def _run_discovery(self) -> dict:
        """Full discovery: fetch → score → store → parse.

        Uses 3-layer architecture:
        - Query grid: role families × location buckets for permissive APIs
        - Adaptive scheduling (skip sources not yet due)
        - ETag/If-Modified-Since caching for efficient re-fetching
        - URL + fingerprint + ATS job_id dedup (cross-source matching)
        - JSON-LD crawl for company career pages not on any ATS
        - Per-source stats tracking
        """
        prefs = self._preferences or JobPreferences.from_config()

        # Build query grid: each (keyword, location) pair = one query
        keywords = prefs.keywords or ROLE_FAMILIES[:3]
        locations = prefs.locations or ["remote"]

        # Limit grid size to avoid excessive API calls per run
        # Full grid runs in scheduled modes; quick runs use first keyword only
        max_keywords = len(ROLE_FAMILIES)
        max_locations = len(LOCATION_BUCKETS)
        query_grid = [
            (kw, loc)
            for kw in (keywords + ROLE_FAMILIES)[:max_keywords]
            for loc in (locations + LOCATION_BUCKETS)[:max_locations]
        ]
        # Deduplicate query pairs while preserving order
        seen_pairs: set[tuple] = set()
        unique_grid: list[tuple] = []
        for pair in query_grid:
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                unique_grid.append(pair)

        logger.info(f"Query grid: {len(unique_grid)} combinations "
                    f"({len(set(kw for kw, _ in unique_grid))} keywords × "
                    f"{len(set(loc for _, loc in unique_grid))} locations)")

        # Load existing URLs, fingerprints, and ATS IDs from DB for dedup
        existing_urls = get_all_urls()
        existing_fps = get_all_fingerprints()
        existing_ats_ids = get_all_ats_ids()
        logger.info(
            f"Loaded {len(existing_urls)} URLs + {len(existing_fps)} fingerprints "
            f"+ {len(existing_ats_ids)} ATS IDs for dedup"
        )

        sources = get_enabled_sources(self.source_filter)

        # Adaptive scheduling: skip sources that aren't due yet
        skipped_sources = 0
        due_sources = []
        for source in sources:
            if should_fetch_source(source.name):
                due_sources.append(source)
            else:
                skipped_sources += 1

        logger.info(
            f"Scanning {len(due_sources)} sources "
            f"(skipped {skipped_sources} not yet due)..."
        )

        # Fetch from due sources with ETag caching
        # ATS company feeds (Greenhouse/Lever/Ashby/SmartRecruiters): one URL per company, no grid
        # Permissive APIs (FindWork, Jobicy): run full query grid
        all_jobs: list[dict] = []
        source_errors = 0

        for source in due_sources:
            try:
                cache = get_source_cache(source.name)

                # For query-grid-capable sources, run multiple queries
                if source.parser in QUERY_GRID_SOURCES and not self.source_filter:
                    source_jobs = []
                    for query, location in unique_grid[:6]:  # Cap at 6 combos per grid source
                        jobs = fetch_source(
                            source, query=query, location=location,
                            etag=cache.get("etag", ""), modified=cache.get("last_modified", ""),
                        )
                        source_jobs.extend(jobs)
                    jobs = source_jobs
                else:
                    # Single fetch (ATS company feeds, RSS, fixed-URL APIs)
                    query = keywords[0] if keywords else "software engineer"
                    location = locations[0] if locations else ""
                    jobs = fetch_source(
                        source, query=query, location=location,
                        etag=cache.get("etag", ""), modified=cache.get("last_modified", ""),
                    )

                all_jobs.extend(jobs)

                # Track source stats with caching metadata
                meta = get_last_fetch_meta(source.name)
                layer = "A" if source.source_type.value == "api" else "B"
                update_source_stats(
                    source.name, source.source_type.value, source.url_template,
                    job_count=len(jobs), layer=layer,
                    etag=meta.get("etag", ""),
                    last_modified=meta.get("modified", ""),
                    content_hash=meta.get("content_hash", ""),
                )
            except Exception as e:
                logger.error(f"Source {source.name} failed: {e}")
                source_errors += 1
                update_source_stats(
                    source.name, source.source_type.value, source.url_template,
                    job_count=0, error=True,
                )

        # JSON-LD company career page crawl (for companies not on any ATS)
        # Only run on full discovery cycles (not filtered/quick runs)
        jsonld_jobs = 0
        if not self.source_filter:
            logger.info(f"JSON-LD crawl: checking {len(JSONLD_COMPANY_REGISTRY)} company career pages...")
            for company_def in JSONLD_COMPANY_REGISTRY[:20]:  # Cap at 20 per run
                try:
                    jobs = extract_jobs_from_url(
                        company_def["careers_url"],
                        company_def.get("company_name", company_def["name"]),
                    )
                    for job in jobs:
                        job["source_name"] = f"JSON-LD:{company_def['name']}"
                    all_jobs.extend(jobs)
                    jsonld_jobs += len(jobs)
                except Exception as e:
                    logger.debug(f"JSON-LD crawl failed for {company_def['name']}: {e}")

            if jsonld_jobs > 0:
                logger.info(f"JSON-LD crawl: found {jsonld_jobs} additional jobs")

        logger.info(f"Found {len(all_jobs)} total jobs across all sources")

        # Score, filter, dedup (URL + fingerprint + ATS ID), store
        matched = []
        rejected = 0
        duplicates = 0
        stored = 0

        for job in all_jobs:
            # Dedup pass 1: exact URL match
            if job["url"] in existing_urls:
                duplicates += 1
                continue

            # Dedup pass 2: ATS job_id match (same job posted across aggregators)
            ats_id = extract_ats_job_id(job.get("url", ""))
            if ats_id and ats_id in existing_ats_ids:
                duplicates += 1
                continue

            # Dedup pass 3: fingerprint match (catches same job from different sources)
            fp = _compute_fingerprint(
                job.get("title", ""), job.get("company", ""), job.get("location", ""),
            )
            if fp in existing_fps:
                duplicates += 1
                continue

            score = score_job(
                title=job["title"],
                description=job.get("description", ""),
                company=job.get("company", ""),
                location=job.get("location", ""),
                preferences=prefs,
            )

            if score < 0:
                rejected += 1
                continue

            if score >= prefs.min_match_score:
                job["score"] = score
                matched.append(job)
                existing_urls.add(job["url"])
                existing_fps.add(fp)
                if ats_id:
                    existing_ats_ids.add(ats_id)

        matched.sort(key=lambda j: j["score"], reverse=True)

        logger.info(
            f"Matched: {len(matched)} | Duplicates: {duplicates} | "
            f"Rejected: {rejected} | Errors: {source_errors}"
        )

        # Store in SQLite
        if not self.dry_run:
            for job in matched:
                job_id = insert_job(job)
                if job_id:
                    stored += 1
                    # Immediately parse with keyword parser
                    if self._parser:
                        try:
                            fields = self._parser.parse(job)
                            update_parsed_fields(job_id, fields)
                        except Exception as e:
                            logger.debug(f"Parse failed for {job_id}: {e}")
        else:
            for job in matched[:30]:
                print(f"  [{job['score']:.2f}] {job['title']} at {job.get('company', '?')} ({job['source_name']})")
                print(f"         {job['url']}")
            stored = len(matched)

        # Also push top matches to main tracker (Google Sheets)
        if not self.dry_run:
            settings = get_settings()
            tracker_pushed = 0
            for job in matched[:10]:  # Top 10 to tracker
                try:
                    resp = self.client.post(
                        f"{settings.backend_url}/jobs",
                        json={
                            "company": job.get("company", "Unknown"),
                            "role": job["title"],
                            "source": job["source_name"],
                            "job_url": job["url"],
                            "status": "To Apply",
                            "notes": f"[Discovery] Score: {job['score']:.2f}",
                        },
                    )
                    if resp.status_code == 201:
                        tracker_pushed += 1
                except Exception:
                    pass

        # Telegram notification — only for high-signal new jobs
        # Filters: first_seen within last 2 hours + score >= priority threshold
        if not self.dry_run and self._notifier and self._notifier.is_configured():
            from src.discovery.database import get_new_jobs_since
            PRIORITY_SCORE_THRESHOLD = 0.3  # Only notify if score >= 30%
            new_jobs = get_new_jobs_since(hours=2)
            priority_jobs = [
                j for j in new_jobs
                if (j.get("match_score") or 0) >= PRIORITY_SCORE_THRESHOLD
            ]

            if priority_jobs:
                job_lines = "\n".join(
                    f"  [{j.get('match_score', 0):.0%}] {j['title']} @ {j.get('company', '?')}"
                    for j in priority_jobs[:8]
                )
                more = f"\n  ...and {len(priority_jobs) - 8} more" if len(priority_jobs) > 8 else ""
                self._notifier.send_message(
                    f"*🎯 {len(priority_jobs)} High-Match Jobs (last 2h)*\n\n{job_lines}{more}\n\n"
                    f"_Total stored this run: {stored}_"
                )
            elif stored > 0:
                # Low-signal summary (all stored, no high-priority matches)
                self._notifier.send_message(
                    f"*Discovery: {stored} new jobs stored* "
                    f"(none scored ≥{PRIORITY_SCORE_THRESHOLD:.0%} this cycle)"
                )

        # Rebuild FTS index after batch insert
        if stored > 0 and not self.dry_run:
            rebuild_fts_index()

        stats = {
            "sources_scanned": len(due_sources),
            "sources_skipped": skipped_sources,
            "total_found": len(all_jobs),
            "matched": len(matched),
            "stored": stored,
            "duplicates": duplicates,
            "rejected": rejected,
            "errors": source_errors,
        }
        logger.info(f"Discovery complete: {stats}")
        return stats

    def _run_parse_only(self) -> dict:
        """Parse unparsed jobs in the database."""
        unparsed = get_unparsed_jobs(limit=50)
        if not unparsed:
            logger.info("No unparsed jobs to process")
            return {"parsed": 0}

        parser = self._parser or JobParser()
        count = 0
        for job in unparsed:
            try:
                fields = parser.parse(job)
                update_parsed_fields(job["id"], fields)
                count += 1
            except Exception as e:
                logger.debug(f"Parse error: {e}")

        logger.info(f"Parsed {count}/{len(unparsed)} jobs")
        return {"parsed": count, "total": len(unparsed)}


def main() -> None:
    """CLI entry point for the Discovery Bot."""
    parser = argparse.ArgumentParser(
        prog="discovery-bot",
        description="Discover new job opportunities from 200+ sources",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview discovered jobs without saving")
    parser.add_argument("--sources", type=str, default="",
                        help="Comma-separated source names to scan (default: all)")
    parser.add_argument("--parse-only", action="store_true",
                        help="Only parse unparsed jobs (no fetching)")
    parser.add_argument("--stats", action="store_true",
                        help="Show database statistics and exit")

    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # Stats mode
    if args.stats:
        init_db()
        stats = get_stats()
        print(f"\n  Discovery Database Stats")
        print("  " + "=" * 50)
        print(f"  Total jobs:    {stats['total']}")
        print(f"  Parsed:        {stats['parsed']}")
        print(f"  Unparsed:      {stats['unparsed']}")
        if stats['by_category']:
            print(f"\n  By Category:")
            for cat, cnt in stats['by_category'].items():
                print(f"    {cat:<20} {cnt}")
        if stats['by_level']:
            print(f"\n  By Level:")
            for lvl, cnt in stats['by_level'].items():
                print(f"    {lvl:<20} {cnt}")
        print()
        return

    source_filter = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else None
    bot = DiscoveryBot(source_filter=source_filter, dry_run=args.dry_run, parse_only=args.parse_only)

    mode = "PARSE ONLY" if args.parse_only else ("DRY RUN" if args.dry_run else "LIVE")
    print(f"\n  Discovery Bot ({mode})")
    print("  " + "=" * 50)

    bot.start()
    try:
        stats = bot.run_safe()
        if stats:
            for k, v in stats.items():
                print(f"  {k:<20} {v}")
        print()
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
