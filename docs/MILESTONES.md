# JobPilot — Complete Project Documentation
## All Milestones: M0 → M16

**Author:** Nikhil Valaja
**GitHub:** https://github.com/Nikhilvalaja/job-automation
**Started:** 2025 | **Completed:** February 2026
**Total Tests:** 463 passing | **Total Milestones:** 17 (M0–M16)

---

## Project Vision

Build a fully automated job application ecosystem that:
- **Discovers** thousands of jobs from 300+ sources every 30 minutes (even when laptop is off)
- **Scores and ranks** jobs against your profile using ML
- **Generates** tailored cover letters and resumes with AI
- **Tracks** every application, follow-up, and response
- **Notifies** you via Telegram in real-time
- **Syncs** everything to Google Sheets (accessible anywhere)
- **Captures** jobs with a Chrome extension (one click on any job page)
- **Manages** outreach sequences and referral paths through your network

---

## Architecture Overview

```
Browser Extension
       │ capture jobs
       ▼
FastAPI Backend (port 8000)
       │
       ├── Google Sheets API ──── track applications
       ├── Gmail API ─────────── email monitoring
       ├── Telegram Bot ──────── notifications
       ├── OpenAI API ────────── cover letters, parsing
       │
       ├── SQLite Databases:
       │   ├── data/discovered_jobs.db  ← 300+ sources, 4+ jobs/30min
       │   ├── data/crm.db              ← contacts, conversations
       │   ├── data/signals.db          ← company hiring signals
       │   ├── data/outreach.db         ← email sequences
       │   └── data/discovery.db        ← source metadata
       │
Streamlit Dashboard (port 8501)
       │
       └── 14 tabs: Today★ | Discovery | Applications | My Resumes
               | Cover Letter | Resume Tailor | Bot Controls
               | Email Rules | Sites | CRM | Outreach | Referrals
               | Signals | Supervisor
```

---

## M0 — Project Foundation
**Goal:** Core infrastructure, Google Sheets integration, basic job tracker

### What Was Built
- **FastAPI backend** with full CRUD for job applications
- **Google Sheets sync** — service account OAuth, bi-directional sync
- **Basic dashboard** — Streamlit app with application list
- **Chrome extension** scaffold — capture jobs from browser
- **SQLite tracker** — applications with status, notes, URLs
- **Telegram notifier** — send messages via bot token
- **Project structure** — `src/`, `backend/`, `dashboard/`, `tests/`, `bots/`

### Key Files
- `backend/main.py` — FastAPI app entry point
- `backend/routers/jobs.py` — CRUD endpoints for applications
- `src/sheets/client.py` — Google Sheets integration
- `src/notifications/telegram.py` — Telegram bot client
- `src/config.py` — Settings from environment variables

### Config (.env)
```
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/...json
GOOGLE_SHEET_ID=1yW6D92PdO4TyBO6vHfs5Qu8tTul998fP6UXa3UxU0vY
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## M1 — Chrome Extension
**Goal:** One-click job capture from any job listing page

### What Was Built
- **Chrome extension** (`extension/`) with Manifest V3
- **Content script** — scrapes job title, company, URL, JD from the page
- **Popup UI** — shows captured data before saving
- **Background service worker** — sends data to local backend (POST /jobs)
- **Auto-detect** — recognizes Greenhouse, Lever, LinkedIn, Indeed, Workday formats
- **Google Sheets integration** — captured jobs appear in the sheet instantly

### How It Works
1. Visit any job listing page
2. Click the JobPilot extension icon
3. Extension auto-extracts: company name, role, URL, job description
4. Click "Capture" → saved to tracker + synced to Google Sheets
5. Telegram notification: "New job captured: [role] at [company]"

### Key Files
- `extension/manifest.json` — Chrome extension config
- `extension/content.js` — page scraping logic
- `extension/popup.html` / `popup.js` — extension UI
- `extension/background.js` — API communication

---

## M2 — Gmail Integration
**Goal:** Monitor inbox for application confirmations, interview requests, rejections

### What Was Built
- **Gmail OAuth 2.0** — secure token-based auth (no password stored)
- **Email rules engine** — regex patterns to classify emails by type
- **Auto-status updates** — "Applied" → "Interview" → "Rejected" based on email content
- **Email bot** — runs every 5 minutes, scans inbox
- **Dashboard tab** — "Email Rules" view to manage patterns

### Email Pattern Types
- `application_confirmed` — "Thank you for applying" patterns
- `interview_request` — "We'd like to schedule" patterns
- `rejection` — "We've decided to move forward with other candidates"
- `assessment` — "Complete this coding challenge" patterns

### Key Files
- `src/gmail/client.py` — Gmail API wrapper
- `src/gmail/rules.py` — email classification rules
- `src/gmail/labels.py` — Gmail label management
- `bots/email_bot/run.py` — email monitoring bot

---

## M3 — Orchestrator Bot (Super Bot)
**Goal:** Central scheduler that runs all bots automatically

### What Was Built
- **BaseBot class** — common interface: `start()`, `run_once()`, `run_safe()`, `stop()`
- **Orchestrator** — manages all bots with APScheduler
- **Adaptive scheduling** — bots adjust frequency based on results
- **CLI interface** — `python -m bots.orchestrator.run` with flags
- **Health monitoring** — tracks bot failures, retries automatically

### Bots Managed
| Bot | Default Interval | Purpose |
|-----|-----------------|---------|
| Discovery Bot | 30 min | Find new jobs |
| Email Bot | 5 min | Monitor Gmail |
| Reminder Bot | Daily 9am | Follow-up reminders |
| Signal Bot | 2 hr | Track company signals |

### Key Files
- `bots/base.py` — BaseBot abstract class
- `bots/orchestrator/run.py` — central scheduler

---

## M4 — Reminder Bot
**Goal:** Automated follow-up reminders for stale applications

### What Was Built
- **Follow-up detection** — finds applications with no update in N days
- **Priority ranking** — sorts by company prestige, match score, days waiting
- **Telegram summaries** — daily 9am digest of what needs follow-up
- **Dashboard view** — "Reminders" section in Applications tab
- **Configurable threshold** — `FOLLOWUP_THRESHOLD_DAYS=7` in .env

### Key Files
- `bots/reminder_bot/run.py` — reminder bot
- `src/scheduler/` — scheduling utilities

---

## M5 — Cover Letter Generator
**Goal:** AI-generated, job-specific cover letters

### What Was Built
- **OpenAI GPT-4o-mini** integration — generates personalized letters
- **JD parser** — extracts requirements from job descriptions
- **Template system** — multiple tones (professional, enthusiastic, concise)
- **Dashboard tab** — "Cover Letter" with inline editor
- **History** — saves all generated letters with job association
- **Export** — copy to clipboard, download as .txt

### How It Works
1. Paste job URL or description into dashboard
2. Select resume/profile to use
3. Click "Generate" → GPT creates tailored letter
4. Edit in dashboard
5. Copy and send

### Key Files
- `src/llm/generator.py` — cover letter generation
- `src/llm/prompts.py` — prompt templates
- `backend/routers/cover_letter.py` — API endpoints

---

## M6 — Discovery Bot (Job Finder)
**Goal:** Automatically find thousands of matching jobs from 300+ sources

### What Was Built
- **297 active sources:**
  - 6 API sources (RemoteOK, Arbeitnow, Jobicy, FindWork, Jooble, Adzuna)
  - 8 RSS feeds (We Work Remotely, BuiltIn, Remote.co, etc.)
  - 283 company career page feeds (Greenhouse, Lever, Ashby ATS)
- **3-layer architecture:**
  - Layer A: Public job board APIs (best reliability)
  - Layer B: ATS career RSS (Greenhouse/Lever/Ashby — 280+ companies)
  - Layer C: Long-tail RSS (niche boards)
- **3-pass deduplication:** URL → ATS job_id → fingerprint hash
- **Adaptive scheduling:** sources checked every 60–360 min based on productivity
- **Keyword scoring:** jobs ranked by match to your keywords
- **ETag caching:** conditional HTTP requests to avoid re-downloading unchanged feeds

### Sources Breakdown
| Type | Count | Examples |
|------|-------|---------|
| Public APIs | 6 | RemoteOK, Arbeitnow, Jobicy, FindWork |
| RSS feeds | 8 | We Work Remotely, Remote.co, Remotive |
| Greenhouse ATS | 184 | Stripe, Airbnb, Figma, Anthropic, etc. |
| Lever ATS | 66 | Notion, Airtable, Scale AI, etc. |
| Ashby ATS | 30 | Linear, Vercel, Retool, etc. |

### Key Config (.env)
```
DISCOVERY_KEYWORDS=software engineer,backend developer,ML engineer,python developer,data engineer
DISCOVERY_LOCATIONS=remote,new york
DISCOVERY_EXCLUDED_KEYWORDS=senior staff,principal,director,intern,lead
DISCOVERY_BOT_INTERVAL_MINUTES=30
```

### Key Files
- `src/discovery/database.py` — SQLite with FTS5, 30+ column schema
- `src/discovery/fetcher.py` — HTTP fetcher with ETag caching
- `src/discovery/sources.py` — 297 source definitions
- `src/discovery/preferences.py` — keyword scoring
- `bots/discovery_bot/run.py` — main bot with dry-run mode

---

## M7 — FTS5 Search + Adaptive Scheduling
**Goal:** Fast full-text search across all jobs, smart source scheduling

### What Was Built
- **SQLite FTS5** — content-external virtual table for instant search
- **FTS rebuild pattern** — uses `INSERT INTO jobs_fts(jobs_fts) VALUES('rebuild')` (not DELETE+INSERT)
- **Adaptive intervals** — sources that find 0 jobs get slower schedules
- **Company normalization** — "Amazon.com" = "Amazon", "Meta Platforms" = "Meta"
- **ATS job_id extraction** — cross-source dedup from URL patterns

### Key Technical Details
- FTS5 content-external: triggers keep it synced with main table
- Scoring with FTS rank: `bm25(jobs_fts, 10.0, 1.0)` weights title 10x body
- Greedy skill matching: sorted by length (longest skills first) to avoid "react" matching "react native"

---

## M8 — Resume Parser + ML Pipeline
**Goal:** Parse, score, and store resumes for job matching

### What Was Built
- **Resume parser** — extracts bullets, skills, experience, education from text/DOCX
- **Skill taxonomy** — 500+ technical skills with synonyms and categories
- **Resume store** — multiple resume versions with metadata
- **Embedding cache** — sentence transformers for semantic similarity
- **Resume Tailor tab** — side-by-side job vs resume analysis

### Key Files
- `src/ml/resume_parser.py` — resume text extraction
- `src/ml/skill_taxonomy.py` — 500+ skills, greedy matching
- `src/ml/resume_store.py` — version storage
- `src/ml/embeddings.py` — sentence transformer cache

---

## M9 — JD Normalizer + Scoring Engine
**Goal:** Score job descriptions against resume for precise matching

### What Was Built
- **JD normalizer** — extracts must-have skills, preferred skills, title, domain
- **Scoring engine** with 5 components:
  - `0.40` Must-have skills coverage
  - `0.20` Title similarity
  - `0.20` Bullet-to-requirement similarity (embeddings)
  - `0.10` Domain match (backend, ML, data, etc.)
  - `0.10` Tools overlap
- **Bullet analyzer** — sentence-level analysis of resume bullets
- **Dashboard** — color-coded match scores (green/yellow/red)

### Key Files
- `src/ml/jd_normalizer.py` — JD parsing and extraction
- `src/ml/scorer.py` — 5-component scoring
- `src/ml/bullet_analyzer.py` — bullet-level analysis

---

## M10 — Resume Intelligence Dashboard
**Goal:** "My Resumes" tab with full resume management

### What Was Built
- **My Resumes tab** — upload, view, compare resumes
- **Score breakdown** — shows each of the 5 scoring components
- **Skills gap analysis** — what's missing vs what's strong
- **Resume Tailor tab** — paste JD → get tailored suggestions
- **Variant store** — A/B test different resume versions
- **DB health dashboard** — backup status, DB sizes

### Key Files
- `src/ml/variant_store.py` — resume variant management
- `src/ml/keyword_mapper.py` — keyword to skill mapping
- `dashboard/app.py` — 9 tabs at this point

---

## M11 — CRM (Contact Relationship Manager)
**Goal:** Track networking contacts, conversations, follow-up due dates

### What Was Built
- **Contacts database** — name, company, role, email, tags, notes
- **Conversation tracking** — multi-stage email threads
- **Touchpoint log** — outbound/inbound messages with timestamps
- **Follow-up scheduler** — flags contacts due for re-engagement
- **CRM tab in dashboard** — searchable contact table
- **CRM stats** — active conversations, contacts by company
- **Cooldown system** — `can_contact()` checks last contact date

### Conversation Stages
`initial` → `follow_up_1` → `follow_up_2` → `cold` → `replied` → `closed`

### Key Files
- `src/crm/database.py` — contacts, conversations, touchpoints
- `src/crm/cooldown.py` — contact cooldown rules
- `src/crm/dedup.py` — contact deduplication

---

## M12 — Company Signals Tracker
**Goal:** Track hiring signals (funding, layoffs, growth) for target companies

### What Was Built
- **Signals database** — funding rounds, layoffs, hiring announcements
- **Company scorer** — `hiring_score` 0-1 from signal history
- **Trend detection** — `up`/`down`/`stable` based on recent signals
- **Hiring window** — `peak`/`warm`/`cooling`/`unknown` classification
- **Avoid list** — companies with layoff signals auto-flagged
- **Signals tab in dashboard** — sortable company table with scores

### Signal Types
- `funding` — Series A/B/C, IPO → positive signal
- `layoff` → strong negative signal
- `hiring_spree` → strong positive
- `product_launch` → moderate positive
- `revenue_growth` → positive

### Key Files
- `src/signals/database.py` — signals + company scores
- `src/signals/scorer.py` — hiring score calculation
- `backend/routers/signals.py` — REST API

---

## M13 — Referral Discovery v1
**Goal:** Find warm introduction paths through your CRM contacts

### What Was Built
- **5-tier closeness scoring:**
  - `direct` (1.0) — spoke with them + they work there
  - `works_there` (0.85) — works at target company
  - `former` (0.70) — formerly worked there (detected from notes)
  - `industry` (0.35) — same industry/tech sector
  - `none` (0.0) — no connection
- **Referral finder** — `find_referral_paths(company, job_title)` returns ranked contacts
- **Suggested ask** — generates message suggestion based on tier and context
- **Enrich jobs** — bulk adds `best_referral` field to job list

### Key Files
- `src/referral/scorer.py` — closeness scoring
- `src/referral/finder.py` — path finding across CRM

---

## M14 — Outreach Copilot
**Goal:** Draft and approve email sequences — NEVER auto-sends

### Design Philosophy
Human-in-the-loop: every email is a **draft** that you approve before sending. The bot writes, you decide.

### What Was Built
- **3-touch email sequences:**
  - Day 0: Initial outreach
  - Day 3: First follow-up
  - Day 7: Final follow-up
- **Draft system:** pending → approved → sent (you must approve each)
- **Anti-spam rules:**
  - Max 5 emails/day globally
  - Max 2 emails/company/week
  - CRM cooldown passthrough (respects existing conversations)
  - No duplicate pending drafts
- **A/B variant system** — 2 template variants per stage, UCB1 algorithm picks winner
- **LLM drafting** — optional GPT-powered drafts (falls back to templates)
- **Outreach tab** — 4 sub-tabs: Pending Drafts, Sequences, A/B Stats, New Sequence

### Email Sequence Stages
```
initial (day 0) → follow_up_1 (day 3) → follow_up_2 (day 7) → completed
```

### Key Files
- `src/outreach/database.py` — sequences, drafts, variants, stats
- `src/outreach/drafter.py` — template + LLM draft generation
- `src/outreach/rules.py` — anti-spam rule checks
- `src/outreach/sequences.py` — sequence cycle runner
- `backend/routers/outreach.py` — 12 REST endpoints
- `bots/outreach_bot/run.py` — bot CLI

---

## M15 — Referral Discovery v2 (Enhanced)
**Goal:** Add role alignment, signal boost, fatigue control, smart ask messages

### Enhancements Over M13
- **Role alignment multiplier:** contact's role × your target role
  - Same function → 1.0x
  - DevOps ↔ Engineering → 0.75x
  - Data ↔ Engineering → 0.70x
  - Leadership → 0.80x
  - Sales → 0.40x (discounted)
- **Signal boost multiplier:** hot companies get higher referral priority
  - Hiring score ≥ 0.80 → 1.30x boost
  - Hiring score ≥ 0.65 → 1.15x boost
  - Layoff risk < 0.30 → 0.50x penalty
- **Hiring window multiplier:**
  - `peak` (recent funding) → 1.30x
  - `warm` → 1.20x
  - `cooling` → 0.85x
- **Referral fatigue control:**
  - Block if messaged < 14 days ago
  - Block if 2+ unanswered outbound in 30 days
  - Unblock if they replied
- **Context-aware ask messages:**
  - Uses contact tier, their role, your target job, signal context
  - Former employee → "Since you worked at Figma..."
  - Direct → "As a Backend Engineer at Stripe, you'd know..."

### Final Score Formula
```
final_score = closeness × role_alignment × signal_multiplier × window_multiplier
```

### Key Files
- `src/referral/scorer.py` — full v2 scoring with all multipliers
- `src/referral/finder.py` — updated with fatigue filtering

---

## M16 — Supervisor Dashboard (Today's Command Center)
**Goal:** Single unified view of everything that needs your attention today

### What Was Built
- **Today's Actions** — priority-ranked list from ALL systems
- **Action types (sorted by priority):**
  | Priority | Action | Source |
  |---------|--------|--------|
  | 0.97 | CRM Reply received | CRM |
  | 0.90 | Outreach draft needs approval | Outreach |
  | 0.80 | Follow-up due | CRM |
  | match_score | High-score job to apply to | Jobs DB |
  | hiring_score | Hot company hiring signal | Signals |
  | 0.65 | Warm intro available | Referrals |
- **System stats header** — total jobs, applied, signals, contacts, pending drafts
- **Pipeline funnel** — discovered → to_apply → applied → interviewing → offer
- **Avoid list** — companies with layoff signals (don't apply there)
- **Top jobs** — top scoring unapplied jobs with resume suggestion
- **"Today ★" tab** in dashboard — first tab, always visible

### Key Files
- `src/supervisor/engine.py` — aggregates all systems
- `backend/routers/supervisor.py` — REST API (5 endpoints)

---

## Cloud Deployment (GitHub Actions)

### Discovery Bot — Runs Every 30 Minutes (Even When Laptop Is Off)
- `.github/workflows/discovery-bot.yml`
- Runs on GitHub's free servers
- Caches SQLite DB between runs
- Sends Telegram notifications with new jobs found

### Signal Bot — Runs Every 2 Hours
- `.github/workflows/signal-bot.yml`
- Tracks company hiring signals continuously

### Setup Required
See `SETUP_CLOUD.md` for step-by-step GitHub Secrets configuration.

---

## Final Stats

| Metric | Value |
|--------|-------|
| Total milestones | 17 (M0–M16) |
| Test suite | **463 tests passing** |
| Discovery sources | **297** (6 API + 8 RSS + 283 ATS) |
| Dashboard tabs | **14 tabs** |
| API endpoints | **50+** |
| SQLite databases | **5** (jobs, CRM, signals, outreach, discovery) |
| Services integrated | Google Sheets, Gmail, Telegram, OpenAI |

---

## What Works on Each Device

| Feature | Laptop (local) | Other devices | Laptop off |
|---------|---------------|---------------|-----------|
| Chrome Extension | ✅ | ✅ (any Chrome) | ✅ |
| Google Sheets | ✅ | ✅ | ✅ |
| Telegram notifications | ✅ | ✅ (phone) | ✅ (cloud) |
| Dashboard | ✅ | ❌ | ❌ |
| Discovery Bot | ✅ | — | ✅ (cloud) |
| Cover Letter | ✅ | ❌ | ❌ |

---

## How to Start

**Local (laptop open):**
Double-click `start.bat` → Dashboard at http://localhost:8501

**Cloud (always running):**
See `SETUP_CLOUD.md` — set up GitHub Actions + 8 secrets

---

*JobPilot — Built with FastAPI, SQLite, Streamlit, OpenAI, and a lot of coffee.*
