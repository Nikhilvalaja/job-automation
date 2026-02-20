# Architecture — Job Automation Ecosystem

> Personal job search platform — as powerful as LinkedIn/Indeed, built for one user.
> Deterministic logic first. LLM second. Validation always.

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

## Target Architecture (M10-M16)

```
    DATA LAYER                     INTELLIGENCE LAYER              ACTION LAYER
+------------------+             +------------------------+      +------------------+
| Job Feeds (297)  |------+      | JD Normalizer (M10)    |      | Resume Optimizer |
| (GH/Lever/Ashby) |      |      | must-have / nice-have  |      | (M11) — rewrite  |
+------------------+      |      | skill taxonomy         |      | under constraints|
| Public APIs      |------+      +------------------------+      | validation engine|
| (RemoteOK, etc)  |      |      | Resume Structurer(M10) |      +------------------+
+------------------+      +----> | bullets, tools, metrics|---+  | Outreach Copilot |
| Gmail API        |------+      | skill inventory lock   |   |  | (M14) — drafts,  |
| (own emails)     |      |      +------------------------+   |  | you approve      |
+------------------+      |      | Embedding Scorer (M10) |   +->+------------------+
| News/Press/WARN  |------+      | cosine sim, weighted   |   |  | CRM Bot (M12)    |
| (M13 signals)    |      |      | formula, bullet rank   |   |  | contacts, follow |
+------------------+      |      +------------------------+   |  | ups, cooldowns   |
| Own Files        |------+      | Signal Classifier(M13) |---+  +------------------+
| (resume, notes)  |             | hiring predictions     |      | Notifier         |
+------------------+             +------------------------+      | (alerts only)    |
                                 | Validation Engine(M11) |      +------------------+
                                 | zero tolerance checks  |      | Supervisor UI    |
                                 +------------------------+      | (M16) — unified  |
                                                                 +------------------+
```

## Resume Intelligence Pipeline (M10-M11)

```
JD Text                          Your Resume
   |                                  |
   v                                  v
+----------------+            +------------------+
| JD Normalizer  |            | Resume Parser    |
| - boilerplate  |            | - bullets[]      |
|   removal      |            | - tools[]        |
| - must_have[]  |            | - metrics[]      |
| - nice_have[]  |            | - word_count     |
| - title_norm   |            | - skill_inventory|
+-------+--------+            +--------+---------+
        |                              |
        v                              v
+-------+------------------------------+---------+
|           Embedding Service (OpenAI)            |
|  JD embedding    bullet embeddings    summary   |
+-----------------------+-------------------------+
                        |
                        v
+-----------------------------------------------+
|           Scoring Engine (deterministic)        |
|                                                 |
|  match_score = 0.40 * must_have_coverage        |
|              + 0.20 * title_alignment            |
|              + 0.20 * bullet_similarity_avg      |
|              + 0.10 * domain_alignment           |
|              + 0.10 * tools_overlap              |
|                                                 |
|  Output: score, missing_skills, top_6_bullets   |
+-----------------------+-------------------------+
                        |
                        v (M11 only, on demand)
+-----------------------------------------------+
|        Controlled Rewrite Engine (LLM)          |
|  - Only skills from skill_inventory             |
|  - Word count ± 3                               |
|  - Preserve all metrics                         |
|  - Keyword swaps from approved map              |
+-----------------------+-------------------------+
                        |
                        v
+-----------------------------------------------+
|        Validation Engine (zero tolerance)        |
|  [ ] word_count delta ≤ 3                       |
|  [ ] no new skills outside inventory            |
|  [ ] all metrics/numbers preserved              |
|  [ ] embedding sim(old, new) ≥ 0.90             |
|  [ ] named entities preserved                   |
|  FAIL → reject, fallback to recommend-only      |
+-----------------------+-------------------------+
                        |
                        v
              +-------------------+
              | Diff Report       |
              | (you approve)     |
              +-------------------+
```

## 3-Layer Job Ingestion

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

## Database Design

### Current (SQLite with WAL mode)

```
discovered_jobs (30+ columns)
├── Dedup: fingerprint, ats_job_id, url (UNIQUE)
├── Scoring: match_score, relevance_score
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

### Planned (M10+)

```
job_descriptions (M10)
├── JD: raw_text, cleaned_text, structured_json
├── Skills: must_have[], nice_to_have[]
└── Embedding: embedding_vector BLOB

resumes (M10)
├── Identity: resume_id, name, file_path
├── Content: raw_text, structured_json
├── Skills: skill_inventory (master list)
└── Flags: is_default, uploaded_at

resume_bullets (M10)
├── Bullet: text, word_count, tools[], metrics[]
├── Context: company, role, resume_version
└── Embedding: embedding_vector BLOB

resume_variants (M11)
├── Variant: jd_id, match_score, rewrite_status
├── Content: bullets_json (rewritten with diff)
└── Validation: validation_report JSON

contacts (M12)
├── Person: name, email, company, role
├── Status: last_contacted, next_action, cooldown
└── Source: gmail, linkedin, manual

conversations (M12)
├── Thread: gmail_thread_id, contact_id, job_id
├── Stage: initial, follow_up_1, replied, dead
└── Scheduling: next_follow_up, cooldown_until

hiring_signals (M13)
├── Signal: type, text, source_url, confidence
└── Company: normalized name, hiring_score, trend
```

## Data Flow

1. **Job Entry:** Chrome Extension OR Tracker Bot CLI → POST /jobs → Backend → Google Sheets
2. **Email Monitor:** Gmail API → Email Bot → classify → PATCH /jobs → Backend → Google Sheets
3. **Reminders:** Reminder Bot → GET /jobs (stale) → PATCH /jobs → Telegram notification
4. **Discovery:** 297 sources → Fetcher → 3-pass dedup → Score → SQLite → FastAPI → Dashboard
5. **Resume Score (M10):** New job → JD normalize → embed → score vs resume → rank
6. **Resume Optimize (M11):** Top match → constrained rewrite → validate → diff report → you approve
7. **Signals (M13):** News/RSS → classify → company score → predict hiring → Dashboard
8. **Outreach (M14):** CRM → draft message → [you approve] → Gmail → track response
9. **Dashboard:** Streamlit → FastAPI → displays all: pipeline + jobs + signals + CRM + resume variants

## Safety & Reliability

### Data Protection Strategy

```
data/
├── discovered_jobs.db          ← Main database (WAL mode)
├── backups/
│   ├── 2026-02-20.db          ← Daily automatic backup
│   ├── 2026-02-19.db
│   ├── ...                    ← Keep 7 daily + 4 weekly
│   └── weekly-2026-02-14.db
└── sheets_backup/
    └── applications-2026-02-20.json  ← Google Sheets snapshot
```

**Protection layers:**
1. **WAL mode** — prevents corruption from concurrent reads
2. **Atomic transactions** — every insert/update is wrapped
3. **Daily backups** — automatic copy before first bot run of the day
4. **Backup rotation** — 7 daily + 4 weekly, auto-delete older
5. **Pre-migration backup** — snapshot before any schema change
6. **Protected statuses** — saved/applied/interested jobs are NEVER auto-deleted

### Scale Design (100K+ Jobs)

```
                WRITE PATH                          READ PATH
297 sources → batch insert             Dashboard → paginated API (50/page)
    ↓           (100 at a time)            ↓
SQLite WAL ←────────────────────→ FTS5 full-text search
    ↓                                     ↓
Retention policy                    Indexed WHERE clauses
(archive after 90 days)             (11 indexes cover all filters)
    ↓
archived_jobs table
(queryable but separate)
```

**Never in memory at once:** All queries use `LIMIT/OFFSET`. API returns max 200 rows. Dashboard pages 50 at a time.

### AI Accuracy Guarantees

```
JD Text
  ↓
Keyword Parser (deterministic)  ─────────────→ baseline result
  ↓                                                  ↑
LLM Parser (if configured)     ─── validate against ─┘
  ↓                                 (disagreements flagged)
Confidence Score (0.0-1.0)
  ↓
Low (<0.5) → flagged for human review in dashboard
High (≥0.8) → auto-accepted with audit trail
```

## Key Principles

- **Deterministic first:** Rules, regex, dictionaries before any LLM call
- **LLM second:** Only where deterministic logic can't reach
- **Validation always:** Every LLM output is checked; zero tolerance for hallucination
- **Human-in-the-loop:** Bot drafts, you approve. Never auto-sends. Never auto-applies.
- **Single writer:** All writes to Google Sheets go through the Backend API
- **Bot isolation:** Each bot runs independently; one failing doesn't crash others
- **Retry everywhere:** All external API calls use exponential backoff with jitter
- **Config-driven:** All settings in .env, no hardcoded values
- **Idempotent:** Bots can re-run safely (duplicate detection, thread ID matching)
- **Observable:** Structured logging, health endpoints, Telegram alerts on failures
- **Adaptive:** Source scheduling adjusts based on productivity and error rates
- **Privacy-first:** Only public sources + own Gmail. No scraping private networks.
- **Never fabricate:** Never invent experience, skills, or metrics
- **Backup always:** Daily automated backups, protected statuses, retention policy
- **Paginate always:** Never load all data into memory, enforce LIMIT on all queries
