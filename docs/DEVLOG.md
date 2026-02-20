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

## 2026-02-19 — Milestone 8: Cover Letter Generator

### What Was Built
- **LLM Client** (`src/llm/client.py`): OpenAI API wrapper
  - Lazy-initialized OpenAI client with `is_configured()` check
  - `chat()` method with system/user prompts, temperature, max_tokens
  - Retry with exponential backoff on APIError/RateLimitError (3 attempts)
- **Prompt Templates** (`src/llm/prompts.py`):
  - `COVER_LETTER_SYSTEM`: Expert career coach system prompt (tone, structure, format rules)
  - `COVER_LETTER_USER`: Template with company/role/JD/resume placeholders
  - `COVER_LETTER_TEMPLATE`: Simple fallback template (no API key needed)
- **Cover Letter Generator** (`src/llm/generator.py`):
  - `generate()` dispatches to LLM or template mode
  - Falls back to template if OpenAI not configured (even if LLM mode requested)
  - Truncates JD to 4000 chars and resume to 3000 chars to prevent token overuse
- **API Endpoint** (`backend/routers/cover_letter.py`):
  - `POST /cover-letter` with CoverLetterRequest/CoverLetterResponse models
  - Validates: company+role required, JD required for LLM mode
  - Lazy singleton generator instance
- **Dashboard Cover Letter tab** — select a tracked job or enter custom details, choose LLM/template mode, generate and copy
- **Startup scripts** — `start.bat` and `start-silent.vbs` for one-click launch and silent auto-start on Windows login
- **9 cover letter tests** (`tests/test_llm/test_cover_letter.py`):
  - Template mode: generates, personalizes, falls back when no API key
  - LLM mode (mocked): OpenAI call, resume inclusion, JD truncation
  - API endpoint: template works, missing company → 400, missing JD in LLM mode → 400

### Design Decisions
- Two modes: LLM (GPT-powered, needs OPENAI_API_KEY) and template (zero-cost fallback)
- Template mode always works — no external dependencies needed
- JD/resume truncation prevents excessive token usage and cost
- Generator is a lazy singleton — only one OpenAI client per process
- Safety: LLM client never logs prompts or responses (may contain personal info)

### Test Results
- **70/70 tests passing**: 14 backend + 24 email rules + 12 orchestrator + 11 reminder + 9 cover letter

---

## 2026-02-19 — Milestone 9: Discovery Bot (4 iterations)

### Discovery v1 (fc8e814)
- Basic RSS/API fetcher with 30 sources
- feedparser for RSS, httpx for APIs
- JobPreferences + keyword-based scoring
- SQLite database with basic fields

### Discovery v2 (b6cf3b9)
- Expanded to 182 sources (131 Greenhouse + 46 Lever + 5 boards)
- Keyword-based job parser (no GPT) — detects category, level, skills, salary, remote
- LinkedIn-level search filters (category, level, years, job type, remote, keyword, company)
- 41 tests

### Discovery v3 (5b412bf)
- Expanded to 297 sources (+115: quant finance, gaming, healthcare, education, consulting)
- Company name normalization (suffix stripping + alias resolution)
- Fingerprint-based dedup (md5 of normalized title+company+location)
- ETag/If-Modified-Since caching for efficient re-fetching
- Per-source stats tracking with ETag metadata
- Dashboard upgrade: sort dropdown, clickable URLs, job detail panel, apply/save/dismiss buttons
- API endpoints: GET /discovery/jobs/{id}, POST /discovery/jobs/{id}/apply, GET /discovery/sources, GET /discovery/companies
- 137 tests

### Discovery v4 (1447d90)
- FTS5 full-text search virtual table (title, company, description, skills, location)
- Adaptive scheduling: dynamic fetch intervals based on source productivity/errors
  - 3+ errors → 360 min, dry → 240 min, productive → 60 min, default 120 min
- ATS job_id extraction from Greenhouse/Lever/Ashby URLs for cross-source dedup
- Newness window tracking: first_seen_at, last_seen_at for truly new job detection
- 3-pass dedup in bot: URL → ATS job_id → fingerprint
- API endpoints: GET /discovery/search (FTS), /new (recent), /stale (closed jobs)
- 159 tests (22 new: ATS extraction, adaptive scheduling, FTS5, newness, ATS dedup)

### Design Decisions (Discovery)
- RSS + API only (no browser scraping) — reliable, fast, doesn't violate ToS
- SQLite with WAL mode for concurrent access
- Content-external FTS5 with 'rebuild' command (not manual INSERT)
- Adaptive scheduling prevents hammering dead sources while keeping productive ones fresh
- 3-pass dedup catches: exact URL, same ATS job across aggregators, same job with different URLs
- Company normalization handles: "Stripe Inc" = "Stripe", "Facebook" = "Meta"

### Roadmap Created
- Full master roadmap at docs/ROADMAP.md covering M10-M15
- M10: ML Scoring Layer (embeddings, skill extraction, title normalization)
- M11: CRM + Contact Database (people, threads, cooldowns)
- M12: Hiring Signal Engine (news/press/funding/WARN classification)
- M13: Outreach Copilot (draft messages, sequences, A/B testing)
- M14: Referral Discovery (contact graph, closeness scoring)
- M15: Supervisor Dashboard (unified command center, learn from outcomes)
- Architecture doc updated with target state diagram

### Test Results
- **159/159 tests passing**: 14 backend + 89 discovery + 24 email + 12 orchestrator + 11 reminder + 9 cover letter

---

## 2026-02-20 — Roadmap v2: Resume Intelligence Engine

### What Changed
Major roadmap restructure to integrate the Resume Optimization Engine into the milestone plan.

**Old M10** was "ML Scoring Layer" — basic embeddings + skill NER.

**New M10** is "Resume Intelligence Engine" — a full 5-module system:
1. JD Ingestion & Normalization (upgrade parser.py, must-have vs nice-to-have)
2. Resume Structure Engine (bullets, tools, metrics, skill inventory master list)
3. Embedding & Similarity Engine (OpenAI embeddings, weighted scoring formula)
4. Controlled Rewrite Engine (M11 — LLM under strict constraints)
5. Validation Engine (M11 — zero tolerance for hallucination)

**Milestone shift:**
- Old: M10 Scoring → M11 CRM → M12 Signals → M13 Outreach → M14 Referral → M15 Dashboard
- New: M10 Resume Intelligence → M11 Resume Optimizer → M12 CRM → M13 Signals → M14 Outreach → M15 Referral → M16 Dashboard

### Philosophy Established
- "Deterministic first, LLM second, Validation always"
- Never invent experience, never fabricate skills
- skill_inventory_master_list is the ONLY allowed skill injection pool
- Every LLM rewrite validated: word count ±3, no new skills, metrics preserved, embedding sim ≥0.9

### Success Metrics Defined
- 0 hallucinated skills (zero tolerance)
- Rewrite rejection rate < 20%
- Bullet semantic similarity ≥ 0.9
- Reduced manual tailoring time by 60%

---

## 2026-02-20 — Milestone 10: Resume Intelligence Engine (Phase 1)

### Built
9 new modules:

1. **Skill Taxonomy** (`src/ml/skill_taxonomy.py`) — 500+ skills, 18 categories, alias resolution, greedy phrase matching
2. **Title Normalizer** (`src/ml/title_normalizer.py`) — 14 canonical roles, 7 seniority levels, title similarity scoring
3. **JD Normalizer** (`src/ml/jd_normalizer.py`) — boilerplate removal, must-have vs nice-to-have, confidence scoring
4. **Bullet Analyzer** (`src/ml/bullet_analyzer.py`) — metric extraction, tool detection, word count
5. **Resume Parser** (`src/ml/resume_parser.py`) — section detection, experience parsing, skill inventory master list
6. **Embedding Service** (`src/ml/embeddings.py`) — OpenAI + TF-IDF fallback, SQLite cache, batch API
7. **Scoring Engine** (`src/ml/scorer.py`) — weighted formula: 0.40 must_have + 0.20 title + 0.20 bullet + 0.10 domain + 0.10 tools
8. **Backup Utility** (`src/utils/backup.py`) — daily backups, 7+4 rotation, health reporting
9. **Retention Policy** (`src/utils/retention.py`) — archive after 90 days, protected statuses, VACUUM

### Safety Infrastructure
- Automated daily backups with rotation
- Protected statuses: saved/applied/interested NEVER auto-deleted
- Embedding cache: never re-embed same text, saves API costs
- Health endpoint: DB size, row count, backup status

### Tests: 277 passing (up from 159)
118 new tests across 6 test files.

---
