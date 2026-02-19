"""Tracker Bot — CLI for adding and managing job applications via the backend API.

Usage:
    python -m bots.tracker_bot.run add --company "Google" --role "SWE" --source "LinkedIn"
    python -m bots.tracker_bot.run list
    python -m bots.tracker_bot.run list --status Applied
    python -m bots.tracker_bot.run update <app_id> --status Applied
    python -m bots.tracker_bot.run delete <app_id>
"""

from __future__ import annotations

import argparse
import json
import sys

from bots.base import BaseBot
from src.models import JobStatus


class TrackerBot(BaseBot):
    """CLI bot for manually adding/updating job applications."""

    def __init__(self) -> None:
        super().__init__("tracker")

    def run_once(self) -> None:
        """Not used for tracker — it's a CLI tool, not a scheduled bot."""
        pass

    def add_job(
        self,
        company: str,
        role: str,
        source: str = "",
        job_url: str = "",
        status: str = "To Apply",
        notes: str = "",
    ) -> dict | None:
        """Add a new job application via POST /jobs."""
        payload = {
            "company": company,
            "role": role,
            "source": source,
            "job_url": job_url,
            "status": status,
            "notes": notes,
        }
        self.logger.info(f"Adding job: {company} / {role}")
        resp = self.client.post("/jobs", json=payload)

        if resp.status_code == 201:
            job = resp.json()
            self.logger.info(f"Created job {job['app_id']}: {company} / {role}")
            return job
        else:
            self.logger.error(f"Failed to add job: {resp.status_code} — {resp.text}")
            return None

    def list_jobs(self, status_filter: str | None = None) -> list[dict]:
        """List all jobs via GET /jobs."""
        params = {}
        if status_filter:
            params["status"] = status_filter

        resp = self.client.get("/jobs", params=params)

        if resp.status_code == 200:
            data = resp.json()
            return data.get("jobs", [])
        else:
            self.logger.error(f"Failed to list jobs: {resp.status_code} — {resp.text}")
            return []

    def update_job(self, app_id: str, **fields: str) -> dict | None:
        """Update a job via PATCH /jobs/{app_id}."""
        # Filter out None values
        payload = {k: v for k, v in fields.items() if v is not None}
        if not payload:
            self.logger.warning("No fields to update")
            return None

        self.logger.info(f"Updating job {app_id}: {list(payload.keys())}")
        resp = self.client.patch(f"/jobs/{app_id}", json=payload)

        if resp.status_code == 200:
            job = resp.json()
            self.logger.info(f"Updated job {app_id}")
            return job
        else:
            self.logger.error(f"Failed to update {app_id}: {resp.status_code} — {resp.text}")
            return None

    def delete_job(self, app_id: str) -> dict | None:
        """Soft-delete a job via DELETE /jobs/{app_id}."""
        self.logger.info(f"Deleting (archiving) job {app_id}")
        resp = self.client.delete(f"/jobs/{app_id}")

        if resp.status_code == 200:
            self.logger.info(f"Archived job {app_id}")
            return resp.json()
        else:
            self.logger.error(f"Failed to delete {app_id}: {resp.status_code} — {resp.text}")
            return None


def _print_job(job: dict) -> None:
    """Pretty-print a single job record."""
    print(f"  {job['app_id']}  | {job['status']:<12} | {job['company']:<20} | {job['role']:<25} | {job.get('source', '')}")


def _print_jobs_table(jobs: list[dict]) -> None:
    """Print jobs as a formatted table."""
    if not jobs:
        print("No jobs found.")
        return
    print(f"\n  {'ID':<10} | {'Status':<12} | {'Company':<20} | {'Role':<25} | {'Source'}")
    print(f"  {'-'*10}-+-{'-'*12}-+-{'-'*20}-+-{'-'*25}-+-{'-'*15}")
    for job in jobs:
        _print_job(job)
    print(f"\n  Total: {len(jobs)} jobs\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tracker-bot",
        description="CLI for managing job applications via the backend API",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- add ---
    add_parser = subparsers.add_parser("add", help="Add a new job application")
    add_parser.add_argument("--company", "-c", required=True, help="Company name")
    add_parser.add_argument("--role", "-r", required=True, help="Job title/role")
    add_parser.add_argument("--source", "-s", default="", help="Where you found the job (LinkedIn, Indeed, etc.)")
    add_parser.add_argument("--url", "-u", default="", help="Job posting URL")
    add_parser.add_argument("--status", default="To Apply", choices=[s.value for s in JobStatus], help="Initial status")
    add_parser.add_argument("--notes", "-n", default="", help="Notes")

    # --- list ---
    list_parser = subparsers.add_parser("list", help="List all job applications")
    list_parser.add_argument("--status", default=None, choices=[s.value for s in JobStatus], help="Filter by status")

    # --- update ---
    update_parser = subparsers.add_parser("update", help="Update a job application")
    update_parser.add_argument("app_id", help="Job application ID")
    update_parser.add_argument("--status", default=None, choices=[s.value for s in JobStatus], help="New status")
    update_parser.add_argument("--notes", "-n", default=None, help="Update notes")
    update_parser.add_argument("--company", default=None, help="Update company")
    update_parser.add_argument("--role", default=None, help="Update role")

    # --- delete ---
    delete_parser = subparsers.add_parser("delete", help="Archive a job application")
    delete_parser.add_argument("app_id", help="Job application ID")

    args = parser.parse_args()
    bot = TrackerBot()

    try:
        bot.start()

        if args.command == "add":
            job = bot.add_job(
                company=args.company,
                role=args.role,
                source=args.source,
                job_url=args.url,
                status=args.status,
                notes=args.notes,
            )
            if job:
                print(f"\nJob created successfully!")
                _print_jobs_table([job])
            else:
                print("Failed to create job. Is the backend running?", file=sys.stderr)
                sys.exit(1)

        elif args.command == "list":
            jobs = bot.list_jobs(status_filter=args.status)
            _print_jobs_table(jobs)

        elif args.command == "update":
            job = bot.update_job(
                args.app_id,
                status=args.status,
                notes=args.notes,
                company=args.company,
                role=args.role,
            )
            if job:
                print(f"\nJob updated successfully!")
                _print_jobs_table([job])
            else:
                print(f"Failed to update job {args.app_id}.", file=sys.stderr)
                sys.exit(1)

        elif args.command == "delete":
            job = bot.delete_job(args.app_id)
            if job:
                print(f"\nJob {args.app_id} archived successfully.")
            else:
                print(f"Failed to delete job {args.app_id}.", file=sys.stderr)
                sys.exit(1)

    except httpx.ConnectError:
        print(
            f"Could not connect to backend at {bot.backend_url}.\n"
            f"Make sure the backend is running: uvicorn backend.main:app --reload",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
