"""Discovery Bot — automatically finds new job opportunities.

Scans multiple sources for job postings matching your preferences:
1. Public job board APIs (RemoteOK, Arbeitnow, Jobicy, FindWork)
2. Indeed RSS search results
3. 25+ company career page RSS feeds (Greenhouse, Lever, Ashby)
4. Recruiter emails from Gmail (optional)

All sources are ToS-compliant — uses only RSS feeds and public APIs.

Usage:
    python -m bots.discovery_bot.run                          # Run discovery
    python -m bots.discovery_bot.run --dry-run                # Preview without saving
    python -m bots.discovery_bot.run --sources remoteok,indeed  # Specific sources only
"""

from __future__ import annotations

import argparse
import io
import sys

from bots.base import BaseBot
from src.config import get_settings
from src.discovery.fetcher import fetch_source
from src.discovery.preferences import JobPreferences, score_job
from src.discovery.sources import get_enabled_sources
from src.notifications.telegram import TelegramNotifier
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DiscoveryBot(BaseBot):
    """Finds new job opportunities and adds them to the tracker."""

    def __init__(
        self,
        source_filter: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        super().__init__("discovery")
        self.source_filter = source_filter
        self.dry_run = dry_run
        self._notifier: TelegramNotifier | None = None
        self._preferences: JobPreferences | None = None
        self._existing_urls: set[str] | None = None

    def start(self) -> None:
        super().start()
        self._notifier = TelegramNotifier()
        self._preferences = JobPreferences.from_config()

        if self._preferences.keywords:
            logger.info(f"Discovery keywords: {self._preferences.keywords}")
        else:
            logger.info("No discovery keywords set — will accept all jobs")

    def run_once(self) -> dict:
        """Discover new jobs from all enabled sources."""
        settings = get_settings()
        prefs = self._preferences or JobPreferences.from_config()

        # Get search query from first keyword (for APIs that need it)
        query = prefs.keywords[0] if prefs.keywords else "software engineer"
        location = prefs.locations[0] if prefs.locations else ""

        # Load existing job URLs to deduplicate
        existing_urls = self._load_existing_urls()

        # Get enabled sources
        sources = get_enabled_sources(self.source_filter)
        logger.info(f"Scanning {len(sources)} sources...")

        # Fetch from all sources
        all_jobs: list[dict] = []
        source_errors = 0

        for source in sources:
            try:
                jobs = fetch_source(source, query=query, location=location)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"Source {source.name} failed: {e}")
                source_errors += 1

        logger.info(f"Found {len(all_jobs)} total jobs across all sources")

        # Score and filter
        matched = []
        rejected = 0
        duplicates = 0

        for job in all_jobs:
            # Deduplicate by URL
            if job["url"] in existing_urls:
                duplicates += 1
                continue

            # Score against preferences
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
                existing_urls.add(job["url"])  # Don't create same job twice in one run

        # Sort by score (best matches first)
        matched.sort(key=lambda j: j["score"], reverse=True)

        # Cap at 20 new jobs per run to avoid flooding
        matched = matched[:20]

        logger.info(
            f"Matched: {len(matched)} | Duplicates: {duplicates} | "
            f"Rejected: {rejected} | Errors: {source_errors}"
        )

        # Save to tracker (unless dry run)
        created = 0
        if not self.dry_run:
            for job in matched:
                try:
                    resp = self.client.post(
                        f"{settings.backend_url}/jobs",
                        json={
                            "company": job.get("company", "Unknown"),
                            "role": job["title"],
                            "source": job["source_name"],
                            "job_url": job["url"],
                            "status": "To Apply",
                            "notes": f"[Discovery Bot] Score: {job['score']:.2f} | {job.get('location', '')}",
                        },
                    )
                    if resp.status_code == 201:
                        created += 1
                    else:
                        logger.warning(f"Failed to create job: {resp.status_code}")
                except Exception as e:
                    logger.error(f"Error creating job: {e}")
        else:
            # Dry run — just print
            for job in matched:
                print(f"  [{job['score']:.2f}] {job['title']} at {job.get('company', '?')} ({job['source_name']})")
                print(f"         {job['url']}")
            created = len(matched)

        # Send Telegram notification
        if created > 0 and not self.dry_run and self._notifier and self._notifier.is_configured():
            job_list = "\n".join(
                f"  - {j['title']} at {j.get('company', '?')} ({j['source_name']})"
                for j in matched[:10]
            )
            more = f"\n  ...and {len(matched) - 10} more" if len(matched) > 10 else ""
            self._notifier.send_message(
                f"*Discovery Bot Found {created} New Jobs*\n\n{job_list}{more}"
            )

        stats = {
            "sources_scanned": len(sources),
            "total_found": len(all_jobs),
            "matched": len(matched),
            "created": created,
            "duplicates": duplicates,
            "rejected": rejected,
            "errors": source_errors,
        }
        logger.info(f"Discovery complete: {stats}")
        return stats

    def _load_existing_urls(self) -> set[str]:
        """Load URLs of existing jobs to prevent duplicates."""
        if self._existing_urls is not None:
            return self._existing_urls

        settings = get_settings()
        try:
            resp = self.client.get(f"{settings.backend_url}/jobs")
            if resp.status_code == 200:
                jobs = resp.json().get("jobs", [])
                self._existing_urls = {j.get("job_url", "") for j in jobs if j.get("job_url")}
                logger.info(f"Loaded {len(self._existing_urls)} existing job URLs for dedup")
            else:
                self._existing_urls = set()
        except Exception:
            logger.warning("Could not load existing jobs for dedup — will skip dedup")
            self._existing_urls = set()

        return self._existing_urls


def main() -> None:
    """CLI entry point for the Discovery Bot."""
    parser = argparse.ArgumentParser(
        prog="discovery-bot",
        description="Discover new job opportunities from job boards and career pages",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview discovered jobs without saving to tracker",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="",
        help="Comma-separated source names to scan (default: all)",
    )

    args = parser.parse_args()

    # Fix Windows console encoding
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    source_filter = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else None

    bot = DiscoveryBot(source_filter=source_filter, dry_run=args.dry_run)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\n  Discovery Bot ({mode})")
    print("  " + "=" * 50)

    bot.start()
    try:
        stats = bot.run_safe()
        if stats:
            print(f"\n  Sources scanned: {stats['sources_scanned']}")
            print(f"  Jobs found:      {stats['total_found']}")
            print(f"  Matched:         {stats['matched']}")
            print(f"  Created:         {stats['created']}")
            print(f"  Duplicates:      {stats['duplicates']}")
            print(f"  Rejected:        {stats['rejected']}")
            print(f"  Errors:          {stats['errors']}")
        print()
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
