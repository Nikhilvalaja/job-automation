# Development Log — Job Automation Ecosystem

This file tracks every milestone, decision, issue, and resolution throughout the project.
Print this at the end for a complete development history.

---

## 2026-02-18 — Project Inception

### Decisions Made
- **Project location:** `C:\Users\valaj\Desktop\job-automation\`
- **Backend:** FastAPI (async, auto-docs, Pydantic-native)
- **Database:** Google Sheets via gspread + Service Account auth
- **Gmail:** OAuth 2.0 Desktop flow (service accounts can't access personal Gmail)
- **LLM:** OpenAI (ChatGPT) as primary, abstraction layer for future providers
- **Notifications:** Telegram Bot API
- **Scheduling:** APScheduler (in-process, persistent job store)
- **Dashboard:** Streamlit + Plotly
- **Extension:** Chrome Manifest v3
- **Deployment:** Docker Compose with restart policies
- **Logging:** Structured text logs with rotation (10MB max, 5 backups)
- **Config:** Pydantic BaseSettings loading from .env

### System Requirements Found
- Python 3.13 (at C:\Users\valaj\AppData\Local\Programs\Python\Python313\python.exe)
- Docker v29.1.3
- Node.js v20.11.1, npm 10.2.4
- Git v2.51
- No existing Google API credentials (need to create from scratch)

### Milestone 0 Completed
- Full project scaffold created (21 directories, 21 __init__.py files)
- Configuration system (pydantic-settings, .env based)
- Structured logging with rotation
- Retry decorator with exponential backoff + jitter
- Shared Pydantic models (JobStatus, JobCreate, JobUpdate, JobResponse)
- Documentation framework (DEVLOG, ARCHITECTURE, SETUP)
- Git initialized

### Milestone 1 Completed
- FastAPI backend with CORS, request logging middleware, global error handler
- Google Sheets client (gspread + service account auth, retry logic, connection pooling)
- Job CRUD endpoints: POST/GET/PATCH/DELETE /jobs, PATCH /jobs/by-thread/{thread_id}
- Health check endpoints: GET /health, GET /ready (verifies Sheets connection)
- Dependency injection for SheetsClient singleton
- Sheet column schema mapping (12 columns, auto-header creation)
- UTF-8 console fix for Windows logging

---

## 2026-02-18 — Milestone 2: Tracker Bot

### What Was Built
- **BaseBot abstract class** (`bots/base.py`): httpx client, logger, start/stop lifecycle, error handling wrapper
- **Tracker Bot CLI** (`bots/tracker_bot/run.py`): full CLI with subcommands:
  - `add` — create new job application via POST /jobs
  - `list` — list all jobs with optional status filter via GET /jobs
  - `update` — update job fields via PATCH /jobs/{app_id}
  - `delete` — soft-delete (archive) via DELETE /jobs/{app_id}
- **Backend tests** (`tests/test_backend/test_jobs_router.py`): 13 tests with in-memory FakeSheetsClient
- **GitHub repo created**: https://github.com/Nikhilvalaja/job-automation (public)

### Design Decisions
- BaseBot uses sync httpx.Client (not async) since bots run as separate processes
- Tracker bot is CLI-only (no scheduling needed — it's a manual tool)
- Tests use FastAPI dependency override with FakeSheetsClient — no Google credentials needed

---

## 2026-02-19 — Milestone 3: Email Bot (Gmail Monitor)

### What Was Built
- **Gmail API client** (`src/gmail/client.py`): OAuth 2.0 Desktop flow, token refresh, read-only
  - Methods: `get_recent_messages()`, `get_message_detail()`, `get_thread()`, `apply_label()`
  - Body extraction handles multipart/nested MIME structures
  - Safety: only requests readonly + labels + modify scopes (never send/delete)
- **Email classification rules engine** (`src/gmail/rules.py`):
  - 5 rule categories: Applied (priority 2), Reject (3), Assessment (4), Interview (5), Offer (6)
  - ~50 keywords across all categories covering common job email patterns
  - Priority-based: highest priority wins on conflict (e.g., offer beats applied)
  - Confidence levels: "high" for subject matches, "medium" for body matches
  - Case-insensitive matching
- **Gmail label manager** (`src/gmail/labels.py`):
  - Auto-creates labels under `JobBot/` prefix (Applied, Assessment, Interview, Rejected, Offer, Processed)
  - Caches label IDs to minimize API calls
- **Email Bot** (`bots/email_bot/run.py`):
  - Fetches recent inbox emails, skips already-processed (via JobBot/Processed label)
  - Classifies each email, updates job status via PATCH /jobs/by-thread/{thread_id}
  - Applies status label + processed label for idempotent re-runs
  - CLI with `--minutes` flag and `--dry-run` mode for safe testing
- **24 classification tests** (`tests/test_bots/test_email_rules.py`):
  - Tests all 5 categories, no-match cases, priority conflicts, confidence levels, case handling

### Design Decisions
- Rule-based classification (not LLM) for speed, determinism, and zero API cost
- Thread ID matching links emails to tracked applications (same thread_id in Sheets)
- "JobBot/Processed" label prevents reprocessing the same email
- Dry-run mode lets user preview classifications without modifying anything
- Body text capped at 5000 chars to prevent memory issues with large emails

---

## 2026-02-19 — Milestone 4: Reminder Bot + Telegram Notifications

### What Was Built
- **NotificationChannel base** (`src/notifications/base.py`): abstract interface for all notification providers
- **Telegram notifier** (`src/notifications/telegram.py`):
  - Sends messages via Telegram Bot API using httpx (sync)
  - Methods: `send_message()`, `send_job_alert()`, `send_summary()`, `send_followup_reminder()`
  - Markdown formatting, retry logic, graceful skip if not configured
- **Reminder Bot** (`bots/reminder_bot/run.py`):
  - Fetches all "Applied" jobs from backend, checks against threshold (default 7 days)
  - Uses `last_email_date` if available, falls back to `date_applied`
  - Marks stale jobs as "No Reply" via PATCH /jobs/{app_id}
  - Sends single Telegram summary with all stale applications
  - CLI with `--days` flag and `--dry-run` mode
- **11 reminder tests** (`tests/test_bots/test_reminder_logic.py`):
  - Stale detection, threshold boundary, last_email_date precedence, empty/invalid dates

### Design Decisions
- Telegram Bot API via httpx (not python-telegram-bot async) — keeps bots sync and simple
- Single summary message instead of one per job — avoids Telegram rate limits
- Graceful degradation: bot works without Telegram configured (just logs)
- `last_email_date` takes precedence over `date_applied` to avoid false positives

---

## 2026-02-19 — Milestone 5: Orchestrator (SuperBot)

### What Was Built
- **BotScheduler engine** (`src/scheduler/engine.py`): APScheduler wrapper
  - `add_interval_bot()` — schedule a bot every N minutes (e.g., email bot every 5 min)
  - `add_daily_bot()` — schedule a bot at a specific time (e.g., reminder bot at 9:00 AM)
  - Coalesce missed runs, max 1 instance per bot, graceful start/stop
  - `get_jobs()` for status display, `running` property
- **Orchestrator** (`bots/orchestrator/run.py`): central scheduler for all bots
  - Registers Email Bot (interval) and Reminder Bot (daily cron)
  - CLI flags: `--no-email`, `--no-reminder`, `--run-now`, `--status`
  - Sends Telegram notification on startup/shutdown
  - Graceful shutdown via Ctrl+C / SIGTERM
  - Signal handling for clean process termination
- **12 orchestrator tests** (`tests/test_bots/test_orchestrator.py`):
  - Scheduler: interval/daily registration, immediate run, start/stop lifecycle
  - Bot isolation: failing bot doesn't crash scheduler
  - Orchestrator: init flags, disable individual bots

### Design Decisions
- BackgroundScheduler (thread-based) — bots run in background threads, main thread handles signals
- `coalesce=True` — if a run was missed, only run once (not catch up N times)
- `max_instances=1` — never overlap two runs of the same bot
- Each bot's `run_safe()` catches exceptions — one bot crashing never affects others
- Startup notification via Telegram shows which bots are scheduled

---

## 2026-02-19 — Milestone 6: Chrome Extension

### What Was Built
- **Chrome Manifest v3 extension** (`extension/`):
  - Popup UI with form to add jobs directly from any page
  - Auto-fills current page URL and detects source (LinkedIn, Indeed, etc.)
  - Content script extracts company name and role from job posting pages
  - Shows last 5 tracked jobs with status badges
  - Backend connection indicator (green/red dot)
  - Configurable backend URL (default: localhost:8000)
- **Content script** (`extension/content.js`): auto-extracts job details from:
  - LinkedIn, Indeed, Glassdoor, Lever, Greenhouse, Workday
  - Generic fallback using `<h1>` and `og:site_name` meta tag
- **Background service worker** (`extension/background.js`): initializes default settings on install
- **Icons**: 16x16, 48x48, 128x128 blue "JT" icons

### Design Decisions
- Manifest v3 (latest Chrome extension standard) — no deprecated APIs
- Content script is read-only — never modifies the job posting page
- Backend URL stored in `chrome.storage.local` — survives extension updates
- XSS prevention: all dynamic text rendered via `escapeHtml()` helper
- AbortSignal.timeout on all fetch calls — never hangs on dead backend

---

## 2026-02-19 — Milestone 7: Dashboard (Streamlit + Plotly)

### What Was Built
- **Streamlit dashboard** (`dashboard/app.py`):
  - KPI cards: total, applied, interviews, offers, rejected, no reply
  - Status distribution donut chart (Plotly)
  - Applications by source horizontal bar chart
  - Application timeline with daily bars + cumulative line (dual y-axis)
  - Full job table with multi-filter (status, source, search)
  - Quick status update from the dashboard
  - Add new job form in sidebar
  - Backend connection status indicator
  - 30-second cache with manual refresh button

### Design Decisions
- Streamlit for rapid development + auto-refresh capability
- Plotly for interactive charts (hover, zoom, pan)
- Backend URL configurable (defaults to localhost:8000)
- `@st.cache_data(ttl=30)` for performance — fetches only every 30 seconds
- Responsive layout with wide mode for better chart display

---

## 2026-02-19 — Extension v2 + Dashboard v2 Upgrade

### Chrome Extension v2
- **Floating track button** on all job pages — one-click save with preview panel
- **Auto-detect Apply clicks** — monitors Easy Apply, Submit, Apply Now buttons and auto-tracks
- **Full page extraction** — company, role, salary, location, job type, skills, description
- **Modular extractors** (`extension/extractors.js`): LinkedIn, Indeed, Glassdoor, Lever, Greenhouse, Workday, ZipRecruiter, Wellfound + generic fallback
- **Context menu** — right-click "Track This Job" on any page
- **Keyboard shortcut** — Ctrl+Shift+J to quick-track
- **Badge counter** — shows today's application count on extension icon
- **Duplicate detection** — checks URL before adding, warns if already tracked
- **Toast notifications** — visual feedback for all actions
- **Preview panel** — slide-in panel showing extracted details before saving
- **14 supported job sites** (LinkedIn, Indeed, Glassdoor, Lever, Greenhouse, Workday, ZipRecruiter, Dice, Monster, Wellfound, BuiltIn, SimplyHired, CareerBuilder + generic)

### Dashboard v2
- **5 tabs**: Overview, Applications, Bot Controls, Email Rules, Sites & Sources
- **Response rate KPI** — tracks what % of applications got replies
- **Conversion funnel** — Total → Applied → Assessment → Interview → Offer
- **Bot Control Center** — shows all 4 bots with commands, schedules, dry-run options
- **Email Classification Rules** — view built-in rules, add custom rules with keywords
- **Sites & Sources tracker** — per-source stats with response rates
- **8 KPI cards** (total, applied, replied, interviews, offers, rejected, response rate, sources count)

---
