# Architecture — Job Automation Ecosystem

## System Overview (Current — M0-M9)

```
                         +-------------------+
                         |  Chrome Extension |
                         |  (Job Capture)    |
                         +--------+----------+
                                  |
                                  | POST /jobs
                                  v
+----------------+       +--------+----------+       +------------------+
|  Gmail API     | <---> |  FastAPI Backend  | <---> |  Google Sheets   |
|  (OAuth 2.0)   |       |  (Central API)   |       |  (Tracker DB)    |
+----------------+       +--------+----------+       +------------------+
                                  ^
                                  |
                    +-------------+-------------+
                    |             |              |
              +-----+---+  +----+----+  +------+------+
              | Email   |  | Remind  |  | Discovery   |
              | Bot     |  | Bot     |  | Bot (297)   |
              +---------+  +---------+  +-------------+
              | Tracker |  | Cover   |       |
              | Bot     |  | Letter  |   SQLite DB
              +---------+  +---------+   (FTS5, dedup)
                    |
                    v
              +-----+-------+       +------------------+
              | Orchestrator | ----> | Telegram Bot     |
              | (SuperBot)   |       | (Notifications)  |
              +-------------+       +------------------+
                    |
                    v
              +-----+-------+
              | Streamlit   |
              | Dashboard   |
              +-------------+
```

## Target Architecture (M10-M15)

```
    DATA LAYER                     INTELLIGENCE LAYER          ACTION LAYER
+------------------+             +--------------------+      +------------------+
| Gmail API        |------+      | ML Scorer (M10)    |---+  | Outreach Copilot |
| (own emails)     |      |      | (embeddings)       |   |  | (M13) — drafts,  |
+------------------+      |      +--------------------+   |  | you approve      |
| ATS Feeds (297)  |------+----> | Signal Classifier  |---+->+------------------+
| (Greenhouse,     |      |      | (M12) — hiring     |   |  | CRM Bot (M11)    |
|  Lever, Ashby)   |      |      | predictions        |   |  | contacts, follow |
+------------------+      |      +--------------------+   |  | ups, cooldowns   |
| Public APIs      |------+      | Reply Predictor    |---+  +------------------+
| (RemoteOK, etc)  |      |      | (M15) — learn from |   |  | Notifier         |
+------------------+      |      | outcomes           |   |  | (high-relevance  |
| News/Press/WARN  |------+      +--------------------+   |  |  alerts only)    |
| (M12 signals)    |      |      | Referral Scorer    |---+  +------------------+
+------------------+      |      | (M14) — closeness  |      | Supervisor UI    |
| Own Files        |------+      | paths              |      | (M15) — unified  |
| (resume, notes)  |             +--------------------+      | command center   |
+------------------+                                         +------------------+
```

## 3-Layer Architecture

### Layer A: Aggregator Feeds + APIs
- Public job boards: RemoteOK, Arbeitnow, Jobicy, FindWork, Himalayas, We Work Remotely
- Indeed RSS, BuiltIn RSS
- Fetch every 30-120 min (adaptive scheduling)

### Layer B: ATS Endpoints (highest signal)
- Greenhouse career feed RSS (184 companies)
- Lever career feed RSS (66 companies)
- Ashby career feed RSS (30 companies)
- Fetch every 60-240 min (adaptive scheduling)

### Layer C: Long-tail / Signals
- Company newsrooms, press release RSS
- WARN notices, USASpending contract awards
- Career page update frequency monitoring
- Fetch daily/weekly

## Discovery Pipeline

```
Ingestion → Normalize → Dedupe → Score → Enrich → Store → Serve
    |            |          |        |        |        |        |
  Fetcher    Company     3-pass   ML emb   Parser  SQLite   FastAPI
  (RSS/API)  normalize   URL →    cosine   (skills, (FTS5,   + Dashboard
             + title     ATS →    sim vs   level,   WAL,
             normalize   finger-  resume   salary)  indexes)
                         print
```

## Database Design

### Current (SQLite with WAL mode)

```
discovered_jobs (30+ columns)
├── Dedup: fingerprint, ats_job_id, url (UNIQUE)
├── Scoring: match_score, relevance_score (M10)
├── ML fields: category, level, skills, job_type, remote_type, salary
├── Newness: first_seen_at, last_seen_at, posted_at
└── Indexes: 11 indexes + FTS5 virtual table

discovery_sources
├── Scheduling: fetch_interval_minutes, consecutive_errors
├── Caching: etag, last_modified, content_hash
└── Layer: A (aggregator), B (ATS), C (long-tail)

companies
├── Canonical: name_raw, name_normalized
├── Metadata: ats_type, domain, career_url
└── Stats: job_count, first_seen, last_seen
```

### Planned (M11+)

```
contacts (CRM)
├── Person: name, email, company, role
├── Status: last_contacted, next_action, cooldown
└── Source: gmail, linkedin, manual

conversations (CRM)
├── Thread: gmail_thread_id, contact_id, job_id
├── Stage: initial, follow_up_1, replied, dead
└── Scheduling: next_follow_up, cooldown_until

hiring_signals (M12)
├── Signal: type, text, source_url, confidence
└── Company: normalized name, hiring_score, trend
```

## Data Flow

1. **Job Entry:** Chrome Extension OR Tracker Bot CLI → POST /jobs → Backend → Google Sheets
2. **Email Monitor:** Gmail API → Email Bot → classify → PATCH /jobs → Backend → Google Sheets
3. **Reminders:** Reminder Bot → GET /jobs (stale) → PATCH /jobs → Telegram notification
4. **Discovery:** 297 sources → Fetcher → 3-pass dedup → Score → SQLite → FastAPI → Dashboard
5. **Signals (M12):** News/RSS → classify → company score → predict hiring → Dashboard
6. **Outreach (M13):** CRM → draft message → [you approve] → Gmail → track response
7. **Dashboard:** Streamlit → FastAPI → displays pipeline + jobs + signals + CRM

## Key Principles

- **Single writer:** All writes to Google Sheets go through the Backend API (never direct from bots)
- **Bot isolation:** Each bot runs independently; one failing doesn't crash others
- **Retry everywhere:** All external API calls use exponential backoff with jitter
- **Config-driven:** All settings in .env, no hardcoded values
- **Idempotent:** Bots can re-run safely (duplicate detection, thread ID matching)
- **Observable:** Structured logging, health endpoints, Telegram alerts on failures
- **Human-in-the-loop:** Outreach bot drafts, you approve. Never auto-sends.
- **Adaptive:** Source scheduling adjusts based on productivity and error rates
- **Privacy-first:** Only collect from public sources + own Gmail. No scraping private networks.
