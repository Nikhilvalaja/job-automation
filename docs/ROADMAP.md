# Roadmap — Job Automation Ecosystem

## Completed Milestones (M0-M9)

| # | Milestone | What It Does | Tests |
|---|-----------|-------------|-------|
| M0 | Scaffold | Project structure, config, logging, retry, models | - |
| M1 | Backend | FastAPI + Google Sheets CRUD | 14 |
| M2 | Tracker Bot | CLI to add/list/update/delete jobs | - |
| M3 | Email Bot | Gmail monitor, auto-classify emails into pipeline stages | 24 |
| M4 | Reminder Bot | Stale application detection + Telegram alerts | 11 |
| M5 | Orchestrator | APScheduler-based SuperBot, runs all bots on schedule | 12 |
| M6 | Chrome Extension | Auto-extract job details from 14 sites, one-click track | - |
| M7 | Dashboard | Streamlit + Plotly with KPIs, charts, tables, filters | - |
| M8 | Cover Letter | LLM + template modes, tone control, resume tailor | 9 |
| M9 | Discovery Bot | 297 sources, SQLite DB, FTS5, adaptive scheduling, 3-pass dedup | 89 |

**Current total: 159 tests passing**

---

## Architecture Vision

```
                    DATA LAYER                    INTELLIGENCE LAYER           ACTION LAYER
              (what we're allowed               (ML decides what             (bots execute
               to collect)                       matters)                     within rules)
              +-----------------+               +------------------+         +----------------+
              |  Gmail API      |               | Job Relevance    |         | Draft Messages |
              |  (own emails)   |----+          | Scorer (embed)   |---+     | (you approve)  |
              +-----------------+    |          +------------------+   |     +----------------+
              |  Public RSS/    |    |          | Hiring Signal    |   |     | Create Tasks / |
              |  Career Pages   |----+--------> | Classifier       |---+---->| Reminders      |
              +-----------------+    |          +------------------+   |     +----------------+
              |  Public APIs    |    |          | Reply Likelihood |   |     | Update Tracker |
              |  (USAJobs,etc)  |----+          | Predictor        |---+     +----------------+
              +-----------------+    |          +------------------+   |     | Send Notifs    |
              |  Own Files      |    |          | Next Best Action |   |     | (Telegram)     |
              |  (resume,notes) |----+          | Recommender      |---+     +----------------+
              +-----------------+               +------------------+
```

### 6 Bots (Final State)

| Bot | Role | Schedule |
|-----|------|----------|
| **Collector Bot** (M9, done) | ATS/boards/RSS -> normalize -> dedupe -> store | Every 30-120 min (adaptive) |
| **Signal Bot** (M12) | News/press/contracts/WARN -> company hiring score | Every 6 hours |
| **CRM Bot** (M11) | People + threads + follow-ups -> "today's actions" | Every 15 min |
| **Outreach Bot** (M13) | Draft messages + sequences + A/B test (human approval) | Daily |
| **Notifier Bot** (enhanced M4) | Only high-relevance, newly-seen alerts | Real-time triggers |
| **Supervisor Dashboard** (M15) | One screen: Top Jobs + Who to message + Follow-ups + Signals | Always-on UI |

---

## Upcoming Milestones

### M10: ML Scoring Layer (Module C Intelligence)

**Goal:** Replace keyword matching with semantic understanding using OpenAI embeddings.

**What it teaches the system:**
- Score relevance: resume <-> JD embedding similarity (competency #7)
- Extract skills & tags from JD via NER (competency #6)
- Normalize titles: Sr/Senior, DE/Data Engineer (competency #2)
- Only alert if relevance > threshold AND first_seen < X hours (competency #8)

**New files:**
```
src/ml/embeddings.py          — OpenAI embedding client (text-embedding-3-small)
src/ml/scorer.py              — Cosine similarity scorer (resume vs JD)
src/ml/skill_extractor.py     — NER-based skill extraction from descriptions
src/ml/title_normalizer.py    — Title normalization (Senior -> senior, DE -> data_engineer)
```

**Changes:**
- `database.py`: add `embedding_vector BLOB` column, `relevance_score REAL`
- `discovery_bot/run.py`: embed each new job, compute cosine sim vs resume
- `parser.py`: upgrade with ML skill extraction
- Dashboard: show relevance score, skill tags

**New dependencies:** `numpy`, `tiktoken` (already have `openai`)

**Tests:** ~15 new (embedding mock, scorer, skill extraction, title normalization)

---

### M11: CRM + Contact Database (Module A)

**Goal:** One place where every person + company + thread is tracked. The "relationship database."

**What it teaches the system:**
- Merge duplicates: same person, different sources (competency #1 extended)
- Track touchpoints and next steps
- Enforce cooldowns: no more than 1 follow-up/week (competency #10)
- Recommend next best action daily (competency #11)

**New entities:**
```sql
-- People you've interacted with
contacts (
    contact_id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT UNIQUE,
    company TEXT,           -- normalized
    role TEXT,              -- "recruiter", "hiring_manager", "engineer"
    source TEXT,            -- "gmail", "linkedin", "manual"
    last_contacted_at TEXT,
    next_action_date TEXT,
    status TEXT,            -- "active", "cold", "blocked"
    tags TEXT,              -- comma-separated
    notes TEXT
)

-- Conversation threads linked to contacts
conversations (
    thread_id TEXT PRIMARY KEY,  -- gmail thread ID
    contact_id TEXT,
    job_id TEXT,                 -- linked discovered job (if any)
    stage TEXT,                  -- "initial", "follow_up_1", "follow_up_2", "replied", "dead"
    last_message_at TEXT,
    next_follow_up TEXT,
    cooldown_until TEXT          -- anti-spam enforcement
)
```

**New files:**
```
src/crm/database.py           — Contacts + conversations SQLite DB
src/crm/dedup.py              — Contact merge logic (same email, fuzzy name match)
src/crm/cooldown.py           — Outreach cooldown rules
bots/crm_bot/run.py           — CRM Bot: scans Gmail, updates touchpoints, suggests actions
backend/routers/crm.py        — API endpoints for contacts/conversations
```

**Changes:**
- Email Bot: link classified emails to contacts
- Dashboard: new "CRM" tab with contact list, conversation timeline, next actions
- Orchestrator: register CRM bot (every 15 min)

**Tests:** ~20 new

---

### M12: Hiring Signal Engine (Module B)

**Goal:** Detect hiring before the job appears. Watch public signals to predict which companies will post roles soon.

**What it teaches the system:**
- Text classification: "hiring signal" vs "noise"
- Trend scoring per company (signal strength over time)
- Avoid bad targets (layoff signals)

**Signal sources (all public, no scraping):**
```
Company RSS / blog / newsroom           — "expanding team", "opening new office"
Press releases (PR Newswire RSS)        — funding announcements, acquisitions
WARN notices (public state databases)   — layoffs to avoid
USASpending / contract awards           — government contract wins = hiring spikes
GitHub repo activity (optional)         — active repos = growing eng team
Career page update frequency            — frequent updates = actively hiring
```

**New files:**
```
src/signals/sources.py         — Signal source definitions (RSS feeds, APIs)
src/signals/classifier.py      — "hiring signal" vs "noise" text classifier
src/signals/scorer.py          — Company hiring score (signal strength over time)
src/signals/database.py        — Signals SQLite DB (signals, company_scores)
bots/signal_bot/run.py         — Signal Bot: fetches signals, classifies, scores
backend/routers/signals.py     — API endpoints for signals
```

**New tables:**
```sql
hiring_signals (
    signal_id TEXT PRIMARY KEY,
    company TEXT,               -- normalized
    signal_type TEXT,           -- "funding", "expansion", "acquisition", "contract", "layoff"
    signal_text TEXT,
    source_url TEXT,
    confidence REAL,
    discovered_at TEXT
)

company_scores (
    company TEXT PRIMARY KEY,
    hiring_score REAL,          -- 0.0 to 1.0
    signal_count INTEGER,
    last_signal_at TEXT,
    trend TEXT                  -- "up", "down", "stable"
)
```

**Output:** "Company X likely hiring data engineers in 30 days" / "Avoid Company Y (layoff signals)"

**Tests:** ~15 new

---

### M13: Outreach Copilot (Module D)

**Goal:** Increase response rate while staying compliant. Bot drafts, you approve.

**What it teaches the system:**
- Draft short messages based on job + resume
- Create 2-touch sequences (initial + follow-up) with cooldown rules
- Track responses via Gmail threads and update CRM
- Response likelihood model (competency #12)

**New files:**
```
src/outreach/drafter.py        — LLM-powered message drafter (templates + GPT)
src/outreach/sequences.py      — Multi-touch sequence engine (initial, follow-up 1, follow-up 2)
src/outreach/rules.py          — Anti-spam rules, cooldown enforcement
src/outreach/ab_test.py        — Simple A/B variant tracking (message length, tone, timing)
bots/outreach_bot/run.py       — Outreach Bot: generates daily action list
backend/routers/outreach.py    — API: get suggestions, approve/reject, send
```

**Key constraint:** Bot drafts, human approves. Never auto-sends.

**Sequence flow:**
```
Day 0:  Initial message (drafted) -> [You approve] -> Sent -> Track in CRM
Day 3:  Check for reply. If no reply -> Draft follow-up 1 -> [You approve]
Day 7:  Check for reply. If no reply -> Draft follow-up 2 (final) -> [You approve]
Day 14: If no reply -> Mark "cold" in CRM. Stop.
```

**ML (later):**
- Response likelihood model: features = role match score, company size, message length, day/time sent, prior touches
- Multi-armed bandit for message variant optimization

**Tests:** ~15 new

---

### M14: Referral Discovery (Module E)

**Goal:** Find the best referral paths using data you already have.

**Inputs (no scraping needed):**
- Your contacts list (manually entered or from CRM)
- Email history ("met someone at X company before")
- Alumni lists if publicly accessible
- Company "people directory" pages if public

**New files:**
```
src/referral/graph.py          — Contact graph builder
src/referral/scorer.py         — Referral closeness scoring
src/referral/suggester.py      — "Ask A to intro to B" suggestions
```

**Referral score by closeness:**
```
you already spoke before        → 1.0 (hot lead)
same previous company           → 0.7
same school                     → 0.5
same location/industry          → 0.3
2nd-degree (contact's contact)  → 0.2
```

**Output:** "For [Job at Stripe], your best referral path is [Alice (ex-Stripe, you emailed in Jan)]"

**Tests:** ~10 new

---

### M15: Supervisor Dashboard (Unified Command Center)

**Goal:** One screen to rule them all. "Today's Top Jobs + Who to message + Follow-ups due + Signals"

**Dashboard sections:**
```
+--------------------------------------------------------------+
|  TODAY'S ACTIONS (priority-ranked)                             |
|  1. Follow up with Alice (Stripe) — 3 days since last message |
|  2. Apply: ML Engineer at Anthropic (score: 0.94)             |
|  3. New signal: DataDog raised $200M (hiring score: 0.87)     |
+--------------------------------------------------------------+
|  TOP JOBS (ML-ranked)  |  SIGNALS          |  CRM ACTIVITY    |
|  - Anthropic (0.94)    |  DataDog: funding |  Alice: replied   |
|  - Stripe (0.91)       |  Figma: expanding |  Bob: follow up   |
|  - Google (0.88)       |  Avoid: Lyft      |  Carol: cold       |
+--------------------------------------------------------------+
|  PIPELINE FUNNEL  |  RESPONSE RATES  |  BOT HEALTH             |
|  100 → 40 → 10   |  Outreach: 22%   |  Collector: 297 sources  |
|  → 5 → 2 offers  |  Referral: 45%   |  Signal: 15 feeds        |
+--------------------------------------------------------------+
```

**ML feature: "Learn from outcomes"** (competency #12)
- Which outreach got replies? -> train response predictor
- Which jobs led to interviews? -> improve relevance scorer
- Which sources produce quality roles? -> adaptive source weighting

---

## 12 Competencies Checklist

| # | Competency | Milestone | Status |
|---|-----------|-----------|--------|
| 1 | Normalize companies (aliases, domains) | M9 | DONE |
| 2 | Normalize titles (Sr/Senior, DE/Data Engineer) | M10 | Planned |
| 3 | Detect ATS type from URL | M9 | DONE |
| 4 | Pull jobs via structured endpoints when possible | M9 | DONE |
| 5 | Dedupe via URL + ID + embedding similarity | M9 (URL+ID), M10 (embedding) | Partial |
| 6 | Extract skills & tags from JD | M10 | Planned |
| 7 | Score relevance vs your resume | M10 | Planned |
| 8 | Track first_seen vs posted_at vs refreshed | M9 | DONE |
| 9 | Classify emails into pipeline stages | M3 | DONE |
| 10 | Enforce outreach cooldown + anti-spam limits | M11, M13 | Planned |
| 11 | Recommend next best action daily | M13, M15 | Planned |
| 12 | Learn from outcomes (interview/reply/reject) | M15 | Planned |

---

## Recommended Build Order

```
YOU ARE HERE
     |
     v
M10: ML Scoring Layer          <-- highest ROI, foundation for everything
     |
     v
M11: CRM + Contacts            <-- unlocks outreach + referral modules
     |
     v
M12: Hiring Signals            <-- independent, can run in parallel with M11
     |
     v
M13: Outreach Copilot          <-- needs M11 (CRM) + M10 (scoring)
     |
     v
M14: Referral Discovery         <-- needs M11 (CRM)
     |
     v
M15: Supervisor Dashboard       <-- integrates everything into one view
```

**Why this order:**
- M10 first because ML scoring is used by every other module (relevance, signals, outreach)
- M11 before M13/M14 because outreach and referrals both need the contact database
- M12 is independent and can be built anytime (even in parallel with M11)
- M15 last because it's the integration layer that ties everything together

---

## Tech Stack Additions (Planned)

| Package | Used In | Why |
|---------|---------|-----|
| `numpy` | M10 | Cosine similarity computation |
| `tiktoken` | M10 | Token counting for embeddings |
| `scikit-learn` | M12, M15 | Text classification, logistic regression |
| `sentence-transformers` (optional) | M10 | Local embeddings if you want to avoid API costs |

---

## Current System Stats

- **Sources:** 297 (184 Greenhouse + 66 Lever + 30 Ashby + 14 APIs + 3 RSS)
- **Database tables:** discovered_jobs (30+ columns), discovery_sources, companies, jobs_fts (FTS5)
- **Dedup:** 3-pass (URL + ATS job_id + fingerprint)
- **Scheduling:** Adaptive (60-360 min based on source productivity)
- **Caching:** ETag + If-Modified-Since for HTTP, content hash for change detection
- **Tests:** 159 passing
- **Commits:** 9 on main
