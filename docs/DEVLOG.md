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
