# Roadmap — Job Automation Ecosystem

> Personal job search platform — as powerful as LinkedIn/Indeed, built for one user.
> Deterministic logic first. LLM second. Validation always.

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

## System Philosophy

```
This is NOT a free-form LLM rewriting tool.
This is a CONSTRAINED OPTIMIZATION ENGINE.

Deterministic logic first.    → Rules, regex, dictionaries
LLM second.                   → Only where rules can't reach
Validation always.            → Every LLM output is checked
Human approves.               → Bot drafts, you decide

Never invents experience.
Never fabricates skills.
Never violates word constraints.
```

---

## Architecture Vision

```
    DATA LAYER                     INTELLIGENCE LAYER              ACTION LAYER
+------------------+             +------------------------+      +------------------+
| Job Feeds (297)  |------+      | JD Normalizer (M10)    |---+  | Resume Optimizer |
| (GH/Lever/Ashby) |      |      | (must-have/nice-have)  |   |  | (M11) — rewrite  |
+------------------+      |      +------------------------+   |  | under constraints|
| Public APIs      |------+----> | Resume Structure (M10) |---+->+------------------+
| (RemoteOK, etc)  |      |      | (bullets, skills, emb) |   |  | Outreach Copilot |
+------------------+      |      +------------------------+   |  | (M14) — drafts,  |
| Gmail API        |------+      | Scoring Engine (M10)   |---+  | you approve      |
| (own emails)     |      |      | (weighted formula)     |   |  +------------------+
+------------------+      |      +------------------------+   |  | CRM Bot (M12)    |
| News/Press/WARN  |------+      | Signal Classifier      |---+  | contacts, follow |
| (M13 signals)    |      |      | (M13) — hiring predict |   |  | ups, cooldowns   |
+------------------+      |      +------------------------+   |  +------------------+
| Own Files        |------+      | Validation Engine      |---+  | Notifier         |
| (resume, notes)  |             | (M11) — zero tolerance |      | (alerts only)    |
+------------------+             +------------------------+      +------------------+
```

### 7 Bots (Final State)

| Bot | Role | Schedule |
|-----|------|----------|
| **Collector Bot** (M9, done) | ATS/boards/RSS -> normalize -> dedupe -> store | Every 30-120 min (adaptive) |
| **Resume Scorer** (M10) | Score every new job against your resume | On new job insert |
| **Resume Optimizer** (M11) | Generate constrained resume variants for top matches | On demand |
| **CRM Bot** (M12) | People + threads + follow-ups -> "today's actions" | Every 15 min |
| **Signal Bot** (M13) | News/press/contracts/WARN -> company hiring score | Every 6 hours |
| **Outreach Bot** (M14) | Draft messages + sequences + A/B test (human approval) | Daily |
| **Supervisor Dashboard** (M16) | One screen: Top Jobs + Who to message + Follow-ups + Signals | Always-on UI |

---

## Upcoming Milestones

---

### M10: Resume Intelligence Engine (Phase 1 — Deterministic + Embeddings)

**Goal:** Score how well a JD matches your resume. Identify missing skills. Rank your best bullets. No rewriting yet — pure analysis.

**Philosophy:** Deterministic first, LLM only for embeddings.

#### Module 1 — JD Ingestion & Normalization

Upgrade `src/discovery/parser.py` into a full JD normalization service.

**Input:** Raw job description text (from DB)

**Output:** Structured JD object:
```json
{
  "title_norm": "data engineer",
  "seniority_level": "senior",
  "location_type": "remote",
  "must_have_skills": ["python", "spark", "airflow"],
  "nice_to_have_skills": ["dbt", "kubernetes"],
  "responsibilities": ["Build data pipelines", "Maintain data warehouse"],
  "cleaned_text": "..."
}
```

**Tasks:**
- Remove EEO/legal/benefits boilerplate (regex patterns)
- Normalize titles (`Data Engineer II` -> `data_engineer`, `Sr.` -> `senior`)
- Extract skills using dictionary lookup + regex patterns (no LLM)
- Classify must-have vs nice-to-have using rule heuristics:
  - "required", "must", "mandatory" -> must-have
  - "preferred", "nice to have", "bonus" -> nice-to-have

**New files:**
```
src/ml/jd_normalizer.py       — JD cleaning, boilerplate removal, structured extraction
src/ml/skill_taxonomy.py      — Master skill dictionary (500+ skills with aliases)
src/ml/title_normalizer.py    — Title normalization rules
```

#### Module 2 — Resume Structuring Engine

Parse your resume into structured units that the scoring engine can work with.

**Output:**
```json
{
  "summary_lines": ["5+ years backend engineer..."],
  "skills_tokens": ["python", "aws", "postgresql", "spark"],
  "experience": [
    {
      "company": "Stripe",
      "role": "Senior Backend Engineer",
      "bullets": [
        {
          "bullet_id": "stripe_1",
          "text": "Reduced API latency by 40% serving 10M+ requests/day",
          "word_count": 9,
          "tools": ["api", "redis"],
          "metrics": ["40%", "10M+"],
          "embedding": [0.012, -0.034, ...]
        }
      ]
    }
  ],
  "skill_inventory_master_list": ["python", "java", "aws", "postgresql", "redis", ...]
}
```

**Critical rule:** `skill_inventory_master_list` is the ONLY allowed skill injection pool. If a skill isn't in this list, it cannot be added to any rewrite.

**New files:**
```
src/ml/resume_parser.py        — Parse resume text into structured units
src/ml/bullet_analyzer.py      — Extract tools, metrics, word count from each bullet
```

#### Module 3 — Embedding & Similarity Engine

Use OpenAI embeddings (`text-embedding-3-small`) for semantic matching.

**Compute:**
- JD embedding (full cleaned text)
- Resume summary embedding
- Each bullet embedding
- `cosine_similarity(bullet, JD)` for every bullet
- `cosine_similarity(summary, JD)` for overall match

**Weighted Score Formula:**
```python
match_score = (
    0.40 * must_have_coverage +      # % of must-have skills you have
    0.20 * title_alignment +          # cosine sim of title vs your roles
    0.20 * bullet_similarity_avg +    # avg cosine sim of top 6 bullets vs JD
    0.10 * domain_alignment +         # same industry/domain match
    0.10 * tools_overlap              # % of JD tools in your skill inventory
)
```

**Output per job:**
```json
{
  "match_score": 0.87,
  "missing_must_haves": ["spark", "airflow"],
  "top_6_relevant_bullets": ["stripe_1", "stripe_3", "meta_2", ...],
  "skill_overlap": {"matched": 8, "total": 10, "missing": ["spark", "airflow"]},
  "recommended_resume_variant": "emphasis_data_pipeline"
}
```

**New files:**
```
src/ml/embeddings.py           — OpenAI embedding client (batch + cache)
src/ml/scorer.py               — Weighted scoring formula
src/ml/cache.py                — Embedding cache (SQLite blob storage, avoid re-embedding)
```

**New DB tables:**
```sql
job_descriptions (
    jd_id TEXT PRIMARY KEY,        -- same as discovered_jobs.id
    raw_text TEXT,
    cleaned_text TEXT,
    structured_json TEXT,          -- JSON blob: must_have_skills, nice_to_have, etc.
    embedding_vector BLOB          -- cached embedding
)

resume_bullets (
    bullet_id TEXT PRIMARY KEY,
    resume_version TEXT,
    company TEXT,
    role TEXT,
    text TEXT,
    word_count INTEGER,
    tools_array TEXT,              -- comma-separated
    metrics_array TEXT,            -- comma-separated
    embedding_vector BLOB
)
```

**Changes to existing code:**
- `database.py`: add `relevance_score REAL`, `missing_skills TEXT` columns to `discovered_jobs`
- `discovery_bot/run.py`: after insert, auto-score against resume embedding
- Dashboard: show relevance score, missing skills, bullet recommendations

**New dependencies:** `numpy`, `tiktoken`

**Tests:** ~25 new (JD normalization, resume parsing, bullet analysis, scoring formula, embedding mock, skill taxonomy)

---

### M11: Resume Optimizer (Phase 2 — Controlled Rewrite + Validation)

**Goal:** Generate tailored resume variants under strict constraints. Bot proposes, validation engine checks, you approve.

**Philosophy:** LLM is used ONLY for rewriting bullets. Everything else is deterministic. Every rewrite is validated before you see it.

#### Module 4 — Controlled Rewrite Engine

**Input:** JD structured object + selected top bullets + allowed keyword swap map + skill inventory

**LLM prompt enforces:**
- Do NOT introduce new tools not in `skill_inventory_master_list`
- Do NOT change metrics (numbers, percentages, outcomes)
- Maintain original word count ±3
- Keep same quantified outcomes
- Only use skills present in skill inventory
- Return structured output with reasoning

**LLM output:**
```json
{
  "rewritten_bullets": [
    {
      "bullet_id": "stripe_1",
      "original": "Reduced API latency by 40% serving 10M+ requests/day",
      "rewritten": "Optimized data pipeline latency by 40% processing 10M+ records/day",
      "keyword_swaps": [{"from": "API", "to": "data pipeline"}],
      "word_count_delta": 1
    }
  ],
  "reasoning": "Aligned language with JD emphasis on data pipeline work"
}
```

**New files:**
```
src/ml/rewriter.py             — Constrained LLM rewrite with structured prompts
src/ml/keyword_mapper.py       — Safe keyword swap map (API->pipeline, build->architect, etc.)
```

#### Module 5 — Validation Engine (Zero Tolerance)

After every rewrite, run automatic validation:

| Check | Rule | Fail Action |
|-------|------|-------------|
| Word count | `abs(new - old) <= 3` | Reject bullet |
| New skills | `new_skills ⊆ skill_inventory` | Reject bullet |
| Metrics preserved | Same numbers/percentages | Reject bullet |
| Embedding similarity | `cosine_sim(old, new) >= 0.90` | Reject bullet |
| Named entities | Company names, tool names preserved | Reject bullet |

**If validation fails:** Reject rewrite, fall back to recommendation-only mode (show which bullets to emphasize + missing skills, no rewriting).

**New files:**
```
src/ml/validator.py            — Post-rewrite validation engine
src/ml/diff_report.py          — Generate visual diff (original vs rewritten)
```

**Dashboard additions:**
- Resume variant viewer with side-by-side diff
- Approve/reject per-bullet
- "Recommendation only" mode (no rewriting, just advice)
- Variant history

**New DB table:**
```sql
resume_variants (
    variant_id TEXT PRIMARY KEY,
    jd_id TEXT,
    resume_version TEXT,
    match_score REAL,
    rewrite_status TEXT,           -- "approved", "rejected", "pending"
    bullets_json TEXT,             -- rewritten bullets with diff
    validation_report TEXT,        -- JSON: which checks passed/failed
    created_at TEXT
)
```

**Tests:** ~20 new (rewrite constraints, validation checks, diff generation, rejection flow)

---

### M12: CRM + Contact Database

**Goal:** One place where every person + company + thread is tracked. The "relationship database."

**What it teaches the system:**
- Track touchpoints and next steps
- Enforce cooldowns: no more than 1 follow-up/week
- Merge duplicates (same person, different sources)
- Recommend next best action daily

**New entities:**
```sql
contacts (
    contact_id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT UNIQUE,
    company TEXT,
    role TEXT,                   -- "recruiter", "hiring_manager", "engineer"
    source TEXT,                 -- "gmail", "linkedin", "manual"
    last_contacted_at TEXT,
    next_action_date TEXT,
    status TEXT,                 -- "active", "cold", "blocked"
    tags TEXT,
    notes TEXT
)

conversations (
    thread_id TEXT PRIMARY KEY,
    contact_id TEXT,
    job_id TEXT,
    stage TEXT,                  -- "initial", "follow_up_1", "follow_up_2", "replied", "dead"
    last_message_at TEXT,
    next_follow_up TEXT,
    cooldown_until TEXT
)
```

**New files:**
```
src/crm/database.py            — Contacts + conversations SQLite DB
src/crm/dedup.py               — Contact merge logic
src/crm/cooldown.py            — Outreach cooldown rules
bots/crm_bot/run.py            — CRM Bot: scans Gmail, updates touchpoints, suggests actions
backend/routers/crm.py         — API endpoints
```

**Tests:** ~20 new

---

### M13: Hiring Signal Engine

**Goal:** Detect hiring before the job appears. Watch public signals.

**Signal sources (all public):**
- Company RSS / blog / newsroom — "expanding team", "opening new office"
- Press releases (PR Newswire RSS) — funding announcements, acquisitions
- WARN notices (public state databases) — layoffs to avoid
- USASpending / contract awards — government contract wins = hiring spikes

**New files:**
```
src/signals/sources.py         — Signal source definitions
src/signals/classifier.py      — "hiring signal" vs "noise" text classifier
src/signals/scorer.py          — Company hiring score over time
src/signals/database.py        — Signals SQLite DB
bots/signal_bot/run.py         — Signal Bot
backend/routers/signals.py     — API endpoints
```

**New tables:**
```sql
hiring_signals (
    signal_id TEXT PRIMARY KEY,
    company TEXT,
    signal_type TEXT,            -- "funding", "expansion", "acquisition", "contract", "layoff"
    signal_text TEXT,
    source_url TEXT,
    confidence REAL,
    discovered_at TEXT
)

company_scores (
    company TEXT PRIMARY KEY,
    hiring_score REAL,
    signal_count INTEGER,
    last_signal_at TEXT,
    trend TEXT                   -- "up", "down", "stable"
)
```

**Output:** "Company X likely hiring in 30 days" / "Avoid Company Y (layoff signals)"

**Tests:** ~15 new

---

### M14: Outreach Copilot

**Goal:** Increase response rate while staying compliant. Bot drafts, you approve. Never auto-sends.

**New files:**
```
src/outreach/drafter.py        — LLM-powered message drafter
src/outreach/sequences.py      — Multi-touch sequence engine
src/outreach/rules.py          — Anti-spam rules, cooldown enforcement
src/outreach/ab_test.py        — A/B variant tracking
bots/outreach_bot/run.py       — Outreach Bot: generates daily action list
backend/routers/outreach.py    — API endpoints
```

**Sequence flow:**
```
Day 0:  Initial message (drafted) -> [You approve] -> Sent -> Track in CRM
Day 3:  Check for reply. If no reply -> Draft follow-up 1 -> [You approve]
Day 7:  Check for reply. If no reply -> Draft follow-up 2 (final) -> [You approve]
Day 14: If no reply -> Mark "cold" in CRM. Stop.
```

**ML (later):** Response likelihood model, multi-armed bandit for message optimization

**Tests:** ~15 new

---

### M15: Referral Discovery

**Goal:** Find the best referral paths using data you already have.

**Inputs (no scraping):**
- Your contacts list (from CRM)
- Email history
- Alumni lists if publicly accessible

**Referral score by closeness:**
```
you already spoke before        → 1.0
same previous company           → 0.7
same school                     → 0.5
same location/industry          → 0.3
2nd-degree (contact's contact)  → 0.2
```

**Output:** "For [Job at Stripe], your best path is [Alice (ex-Stripe, emailed in Jan)]"

**Tests:** ~10 new

---

### M16: Supervisor Dashboard (Unified Command Center)

**Goal:** One screen: Today's Top Jobs + Who to message + Follow-ups due + Signals

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

**ML: Learn from outcomes:**
- Which outreach got replies? -> train response predictor
- Which jobs led to interviews? -> improve relevance scorer
- Which resume variants got callbacks? -> optimize rewrite strategy

**Tests:** ~10 new

---

## Build Order

```
YOU ARE HERE
     |
     v
M10: Resume Intelligence Engine     <-- foundation: JD normalization + resume parsing
     |                                   + embeddings + scoring formula
     v                                   (deterministic first, no rewriting)
M11: Resume Optimizer                <-- LLM rewrite under constraints
     |                                   + validation engine (zero tolerance)
     v                                   + diff reports + approval UI
M12: CRM + Contacts                  <-- relationship database, cooldowns
     |
     v
M13: Hiring Signals                  <-- predict hiring before jobs appear
     |
     v
M14: Outreach Copilot               <-- draft messages, sequences (needs M12)
     |
     v
M15: Referral Discovery              <-- contact graph, closeness scoring (needs M12)
     |
     v
M16: Supervisor Dashboard            <-- integrates everything, learns from outcomes
```

**Why this order:**
- M10 first: scoring engine is used by everything (discovery, outreach, signals)
- M11 right after: resume optimization needs M10's embeddings + JD normalizer
- M12 before M14/M15: outreach and referrals both need the contact database
- M13 independent: can be built anytime
- M16 last: integration layer that ties everything together

---

## 12 Competencies Checklist

| # | Competency | Milestone | Status |
|---|-----------|-----------|--------|
| 1 | Normalize companies (aliases, domains) | M9 | DONE |
| 2 | Normalize titles (Sr/Senior, DE/Data Engineer) | M10 | Planned |
| 3 | Detect ATS type from URL | M9 | DONE |
| 4 | Pull jobs via structured endpoints when possible | M9 | DONE |
| 5 | Dedupe via URL + ID + embedding similarity | M9 (URL+ID), M10 (embedding) | Partial |
| 6 | Extract skills & tags from JD (must-have vs nice-to-have) | M10 | Planned |
| 7 | Score relevance vs your resume (weighted formula) | M10 | Planned |
| 8 | Track first_seen vs posted_at vs refreshed | M9 | DONE |
| 9 | Classify emails into pipeline stages | M3 | DONE |
| 10 | Enforce outreach cooldown + anti-spam limits | M12, M14 | Planned |
| 11 | Recommend next best action daily | M14, M16 | Planned |
| 12 | Learn from outcomes (interview/reply/reject) | M16 | Planned |

---

## Success Metrics

| Metric | Target | Measured By |
|--------|--------|-------------|
| Resume match score accuracy | Manual validation on 50 jobs | M10 |
| No hallucinated skills | 0 tolerance | M11 validation engine |
| Rewrite rejection rate | < 20% | M11 validation stats |
| Bullet semantic similarity | >= 0.9 (old vs rewritten) | M11 validation engine |
| Reduced manual tailoring time | 60% less | M11 user tracking |
| Response rate (outreach) | Track improvement over baseline | M14 |
| Interview conversion (per resume variant) | Track per variant | M16 |

---

## What We Are NOT Building

- Inventing experience
- Fabricating skills
- Rewriting entire resumes blindly
- Outsmarting ATS with spam keywords
- Replacing human judgment
- Scraping private networks (LinkedIn profiles, etc.)
- Auto-sending messages without approval

---

## Tech Stack (Current + Planned)

| Package | Milestone | Why |
|---------|-----------|-----|
| `feedparser` | M9 (done) | RSS/Atom feed parsing |
| `beautifulsoup4` | M9 (done) | HTML cleanup |
| `numpy` | M10 | Cosine similarity computation |
| `tiktoken` | M10 | Token counting for embeddings |
| `python-docx` | M11 | DOCX resume export |
| `scikit-learn` | M13, M16 | Text classification, logistic regression |

---

## Current System Stats

- **Sources:** 297 (184 Greenhouse + 66 Lever + 30 Ashby + 14 APIs + 3 RSS)
- **Database tables:** discovered_jobs (30+ cols), discovery_sources, companies, jobs_fts (FTS5)
- **Dedup:** 3-pass (URL + ATS job_id + fingerprint)
- **Scheduling:** Adaptive (60-360 min based on source productivity)
- **Caching:** ETag + If-Modified-Since, content hash for change detection
- **Tests:** 159 passing
- **Commits:** 10 on main
