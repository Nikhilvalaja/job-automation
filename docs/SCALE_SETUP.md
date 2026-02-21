# 🚀 Job Discovery Scale Setup Guide
## Target: 100K+ Jobs in DB | Daily Fresh Jobs from Everywhere Legal

---

## Current Capacity After Latest Update
| Source Type | Count | Jobs per Run |
|---|---|---|
| Greenhouse JSON API | ~390 companies | ~50K-100K jobs |
| Lever JSON API | ~153 companies | ~20K-40K jobs |
| Ashby JSON API | ~55 companies | ~3K-8K jobs |
| SmartRecruiters JSON API | ~104 enterprises | ~20K-50K jobs |
| Public Job Board APIs | ~20 boards | ~5K-15K jobs |
| The Muse API | 5 categories | ~2K-5K jobs |
| RSS Feeds | ~10 feeds | ~500-1K jobs |
| **TOTAL** | **~737 sources** | **~100K-200K potential** |

---

## Phase A: Free APIs (No Setup Needed — Already Integrated) ✅

These are already working:
- **Remotive** — remote engineering/devops/data jobs
- **RemoteOK** — remote tech jobs
- **Arbeitnow** — European + remote jobs
- **Jobicy** — remote jobs
- **Himalayas** — quality remote roles
- **We Work Remotely** — RSS feeds
- **Y Combinator Jobs** — YC company jobs
- **The Muse** — 20K+ US tech jobs (**NEW**)
- **All Greenhouse/Lever/Ashby/SmartRecruiters company feeds** (**EXPANDED**)

---

## Phase B: Adzuna API (Free, 250 requests/day)

### Step 1: Sign up
1. Go to: https://developer.adzuna.com/signup
2. Create a free account
3. Go to your dashboard → API Access tab
4. Copy your **App ID** and **App Key**

### Step 2: Add to .env
```
ADZUNA_APP_ID=your_app_id_here
ADZUNA_API_KEY=your_app_key_here
```

### Step 3: Uncomment in sources.py
Find the commented Adzuna block in `src/discovery/sources.py` and uncomment it:
```python
JobSource(name="Adzuna US (Tech)", source_type=SourceType.API,
          url_template="https://api.adzuna.com/v1/api/jobs/us/search/1?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_API_KEY}&results_per_page=50&what=software+engineer",
          parser="adzuna", rate_limit_seconds=2.0, enabled=True),
```

**Why Adzuna:** Aggregates from company career pages, Indeed, jobsite.co.uk, etc. ~1-3M jobs across US/UK/AU/CA.

---

## Phase C: LinkedIn Job Alerts → Gmail Ingestion

**This is LEGAL: You're reading your own email, not scraping LinkedIn.**

### Step 1: Set up LinkedIn Job Alerts
1. Go to LinkedIn.com → Jobs → Job Alerts
2. Create alerts for each role family:
   - "Software Engineer" → Remote → Alert: **Daily**
   - "Data Engineer" → Remote → Alert: **Daily**
   - "Backend Developer" → Remote → Alert: **Daily**
   - "ML Engineer" → Remote → Alert: **Daily**
   - "Python Developer" → Remote → Alert: **Daily**
   - "Data Analyst" → Remote → Alert: **Daily**
   - "Business Analyst" → Remote → Alert: **Daily**
   - "Product Manager" → Remote → Alert: **Weekly** (unless you're targeting PM roles)
3. Make sure LinkedIn sends alerts to **valajashekarnikhil12@gmail.com**

### Step 2: Set up Indeed Job Alerts
1. Go to Indeed.com
2. Search: "software engineer remote"
3. Click "Get email alerts for this search"
4. Use **valajashekarnikhil12@gmail.com**
5. Repeat for: data engineer, backend developer, ML engineer, python developer

### Step 3: Set up Dice Job Alerts
1. Go to Dice.com → Sign up / Login
2. Search for your keywords
3. Save search → Enable email alerts
4. Use **valajashekarnikhil12@gmail.com**

### Step 4: Set up Glassdoor Job Alerts
1. Go to Glassdoor.com
2. Search "software engineer" + "Remote"
3. Save the job alert → daily emails

### Step 5: Set up Handshake (for entry level / new grad roles)
1. Go to joinhandshake.com
2. Create alerts for software engineer, data engineer
3. Email alerts to your Gmail

### Step 6: Label your alerts in Gmail
Create a Gmail filter for all job alert emails:
1. Gmail → Settings → Filters → Create new filter
2. From: `jobs-noreply@linkedin.com OR jobalerts@indeed.com OR alerts@dice.com OR noreply@glassdoor.com OR noreply@handshake.com`
3. Action: Apply label **"job_alerts"**, Skip inbox (optional)

---

## Phase D: Google Alerts → Gmail Ingestion

Google Alerts monitors the web for new pages matching your keywords.
Great for: company blog announcements, job board aggregators, niche sites.

### Create Google Alerts
1. Go to: https://www.google.com/alerts
2. Create alerts (use **valajashekarnikhil12@gmail.com**):

```
Search term: "data engineer" "we're hiring" site:linkedin.com OR site:greenhouse.io
Frequency: As it happens
How many: All results
```

Create one alert per row:
| Alert Query | Frequency |
|---|---|
| "software engineer" "now hiring" -senior -staff | Daily |
| "data engineer" "we're hiring" | Daily |
| "ML engineer" "open position" | Daily |
| "backend developer" remote hiring | Daily |
| "Epic analyst" OR "Cogito analyst" OR "Clarity analyst" hiring | Daily |
| "data warehouse" "ETL developer" hiring | Weekly |
| site:jobs.lever.co "data engineer" | Daily |
| site:boards.greenhouse.io "software engineer" | Daily |

### Why Epic/Cogito/Clarity alerts?
These are specialized Epic Systems EHR module analyst roles — high demand, less competition. Good niche to target.

---

## Phase E: Workday Companies (The Biggest ATS — 500K+ jobs)

Workday is used by: Google, Apple, Meta, Amazon, Microsoft, Target, Nike, General Electric, FedEx, JP Morgan, Goldman Sachs, Deloitte, EY, KPMG, and thousands more.

**Workday JSON API format:**
```
https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{company}/External_Careers/jobs
POST with JSON body: {"limit": 20, "offset": 0, "searchText": "engineer"}
```

### Known Workday tenants to add to sources.py:
```python
# Add to src/discovery/sources.py — needs a special Workday parser
def _wd(name: str, tenant: str, company_path: str) -> JobSource:
    return JobSource(name=name, source_type=SourceType.API, parser="workday",
                     url_template=f"https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{company_path}/External_Careers/jobs",
                     rate_limit_seconds=2.0)

WORKDAY_FEEDS = [
    _wd("Google", "google", "Google"),
    _wd("Apple", "apple", "Apple"),
    _wd("Meta", "meta", "Meta_External"),
    _wd("Goldman Sachs", "gs", "GS"),
    _wd("JP Morgan", "jpmc", "JPMorgan"),
    _wd("Nike", "nike", "Nike"),
    _wd("Target", "target", "Target"),
    _wd("Deloitte", "deloittedigital", "Deloitte"),
    _wd("EY", "ey", "EY"),
    _wd("General Electric", "ge", "GE"),
    _wd("FedEx", "fedex", "FedEx"),
    _wd("Walmart (WD)", "walmart", "Walmart"),
    _wd("CVS Health", "cvs", "CVSHealth"),
    _wd("UnitedHealth", "uhg", "UHG"),
    _wd("Anthem", "anthem", "Anthem"),
    _wd("Pfizer", "pfizer", "Pfizer"),
    _wd("Johnson & Johnson", "jnj", "JNJ"),
    _wd("Merck", "merck", "Merck"),
    _wd("AbbVie", "abbvie", "AbbVie"),
    _wd("Moderna", "moderna", "Moderna"),
    _wd("Boeing", "boeing", "Boeing"),
    _wd("Lockheed Martin", "lmt", "LMT"),
    _wd("Raytheon", "rtx", "Raytheon"),
    _wd("Northrop Grumman", "northropgrumman", "NGC"),
    _wd("General Dynamics", "gdls", "GD"),
]
```

**Note:** Workday requires POST requests (not GET), needs special handling. Coming in next update.

---

## Phase F: iCIMS + Taleo (Phase 3 — Later)

These are used by large traditional companies (banks, hospitals, government contractors).

**iCIMS API pattern:**
```
https://careers-{company}.icims.com/jobs/search?in_iframe=1&ss=1&searchLocation=
```

**Oracle Taleo pattern:**
```
https://{company}.taleo.net/careersection/External/jobsearch.ftl?lang=en
```

These require company-specific tenant discovery. Lower priority vs Greenhouse/Workday.

---

## Phase G: Schema.org JSON-LD Career Page Crawler ✅ (Just Built)

The `src/discovery/jsonld.py` module now handles this.

### Companies in the registry (60+ already):
- Apple, Google, Microsoft, Amazon, Meta, Netflix, LinkedIn, Salesforce
- Shopify, Atlassian, Zoom, Slack, Dropbox, Airbnb, Uber, Lyft, DoorDash
- Stripe, Square, Figma, Notion, Linear, Vercel, Supabase, and 40+ more

### How to add a company to the crawler:
```python
# In src/discovery/jsonld.py → JSONLD_COMPANY_REGISTRY
{"name": "Company Name", "careers_url": "https://careers.example.com/jobs", "company_name": "Company Name"},
```

### Usage:
```python
from src.discovery.jsonld import extract_jobs_from_url
jobs = extract_jobs_from_url("https://careers.example.com/jobs", "Example Corp")
```

---

## Phase H: Recruiter Websites (Legal Approach Only)

### Sites that allow bot access:
| Site | Approach | Notes |
|---|---|---|
| Himalayas.app | JSON API (already integrated) | Quality remote jobs |
| We Work Remotely | RSS (already integrated) | Quality remote |
| Remote.co | RSS (already integrated) | Remote jobs |
| Remotive.com | JSON API (already integrated) | Remote tech |
| AngelList/Wellfound | RSS (already integrated) | Startups |
| Y Combinator | RSS (already integrated) | YC companies |
| The Muse | JSON API (just added) | US companies |
| Adzuna | JSON API (requires free key) | Aggregator |

### Sites that send email alerts (Gmail ingestion approach):
| Site | Alert Type | Notes |
|---|---|---|
| LinkedIn | Daily/Weekly digest | Set up in Phase C |
| Indeed | Daily | Set up in Phase C |
| Dice | Daily | For tech roles |
| Glassdoor | Daily/Weekly | Company-specific |
| ZipRecruiter | Daily | Broad reach |
| Monster | Daily | Traditional market |
| CareerBuilder | Daily | Traditional market |
| Simplyhired | Daily | Aggregator |
| Getwork | Daily | Remote focus |
| Jobvite | Per posting | Company-specific |

---

## Query Grid Implementation (Phase I — Next Sprint)

To get 100K+ without noise, run each source across a **query grid**:

```python
ROLE_FAMILIES = {
    "backend":   ["backend engineer", "software engineer", "API engineer", "python developer"],
    "data":      ["data engineer", "analytics engineer", "ETL developer", "data pipeline"],
    "ml":        ["ML engineer", "machine learning", "AI engineer", "deep learning"],
    "analyst":   ["business analyst", "BI analyst", "data analyst", "reporting analyst"],
    "devops":    ["devops engineer", "platform engineer", "SRE", "infrastructure engineer"],
    "frontend":  ["frontend engineer", "react developer", "UI engineer"],
    "fullstack": ["full stack engineer", "software engineer"],
}

LOCATION_BUCKETS = [
    "remote",
    "New York",
    "San Francisco",
    "Seattle",
    "Austin",
    "Chicago",
    "Boston",
    "Atlanta",
    "Denver",
    "Los Angeles",
    "United States",  # nationwide when API supports it
]
```

This creates: `7 role families × 11 locations = 77 query combinations` per API.
With 5 APIs × 77 queries = **385 API calls per cycle** = ~50K-200K jobs/day.

---

## Quick Checklist

### Do TODAY (takes 15 minutes):
- [ ] Sign up for Adzuna API: https://developer.adzuna.com
- [ ] Set up LinkedIn Job Alerts (5 keywords × 3 locations)
- [ ] Set up Indeed Job Alerts (5 keywords)
- [ ] Set up Dice alerts
- [ ] Create Gmail filter for `label:job_alerts`

### Set up second Gmail for alerts:
- [ ] Run: `python -m src.gmail.setup_account2` (opens browser)
- [ ] Sign in with valajashekarnikhil12@gmail.com

### This week:
- [ ] Add GitHub Secrets from SETUP_CLOUD.md
- [ ] Monitor GitHub Actions runs for discovery bot
- [ ] Check dashboard for new jobs

### Next sprint:
- [ ] Implement Workday POST API parser
- [ ] Build query grid (role × location) for public APIs
- [ ] Build Gmail URL ingestion bot (reads job_alerts label)
- [ ] Add Adzuna with query grid

---

## Expected Job Volume After Full Setup

| Phase | Sources Added | New Jobs/Day |
|---|---|---|
| Current (GH/Lever/Ashby/SR/Boards) | 737 sources | 1K-5K/day (new postings) |
| + Adzuna (5 queries) | +5 queries | +500-2K/day |
| + Gmail alerts (5 platforms) | +daily emails | +200-500/day |
| + Workday (25 tenants) | +25 tenants | +2K-10K/day |
| + Query grid (role × location) | ×10 multiplier | ×5-10 more |
| **Total realistic** | **800+ sources** | **5K-20K new/day** |
| **DB total after 30 days** | — | **150K-600K jobs** |

The DB total grows fast because jobs stay in the DB even after they're filled.
Fresh daily additions = new applications opportunities.
