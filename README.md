# Job Automation Ecosystem

Enterprise-grade job application automation system with multi-bot architecture.

## What It Does

- **Tracks** job applications in Google Sheets with full lifecycle management
- **Monitors** Gmail for status updates (applied, interview, reject, offer) automatically
- **Reminds** you about applications with no response after 7 days via Telegram
- **Captures** jobs with one click using a Chrome extension
- **Generates** tailored cover letters using ChatGPT
- **Discovers** new job postings from email alerts
- **Suggests** which resume version to use based on job description keywords
- **Visualizes** your pipeline with a real-time Streamlit dashboard
- **Runs 24/7** via Docker Compose with auto-restart

## Architecture

```
Chrome Extension → FastAPI Backend → Google Sheets
Gmail API → Email Bot → Backend → Sheets
Orchestrator → All Bots (scheduled)
Streamlit Dashboard → Backend → Sheets
```

All writes to Google Sheets are centralized through the FastAPI backend.
Each bot runs independently — one failing doesn't crash others.

## Quick Start

```bash
# 1. Setup
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # Fill in your keys

# 2. Run
uvicorn backend.main:app --reload          # Backend
python -m bots.orchestrator                # All bots
streamlit run dashboard/app.py             # Dashboard
```

See [docs/SETUP.md](docs/SETUP.md) for full setup instructions.

## Project Structure

```
backend/     → FastAPI REST API (central hub)
bots/        → Individual automation bots
dashboard/   → Streamlit analytics dashboard
extension/   → Chrome extension for job capture
src/         → Shared modules (config, sheets, gmail, notifications, llm)
tests/       → Pytest test suite
docs/        → Documentation (DEVLOG, ARCHITECTURE, API, SETUP, DEPLOYMENT)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + Uvicorn |
| Database | Google Sheets (gspread) |
| Email | Gmail API (OAuth 2.0) |
| Scheduling | APScheduler |
| Dashboard | Streamlit + Plotly |
| Notifications | Telegram Bot |
| AI | OpenAI GPT-4o |
| Extension | Chrome Manifest v3 |
| Deploy | Docker Compose |
