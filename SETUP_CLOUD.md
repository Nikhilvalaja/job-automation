# JobPilot — Cloud Setup Guide
## Run Bots 24/7 Even When Laptop is Off

---

## What Runs in the Cloud (GitHub Actions — FREE)

| Bot | Runs Every | What it does |
|-----|-----------|-------------|
| Discovery Bot | 30 min | Finds new jobs from 297 sources |
| Signal Bot | 2 hours | Tracks company hiring signals |

Results → sent to **Telegram** + saved to **Google Sheets**

---

## Step 1: Push Code to GitHub

```bash
cd /path/to/job-automation
git add .
git commit -m "feat: add GitHub Actions workflows"
git push origin main
```

---

## Step 2: Add GitHub Secrets

Go to: **GitHub → Your Repo → Settings → Secrets and variables → Actions → New repository secret**

Add these secrets one by one:

| Secret Name | Value |
|------------|-------|
| `TELEGRAM_BOT_TOKEN` | `8207879923:AAGuW1vy8DFXcGLMJW6BGNdnNGdaIqw9d88` |
| `TELEGRAM_CHAT_ID` | `8248608168` |
| `GOOGLE_SHEET_ID` | `1yW6D92PdO4TyBO6vHfs5Qu8tTul998fP6UXa3UxU0vY` |
| `OPENAI_API_KEY` | (your OpenAI key — optional for cover letters) |
| `DISCOVERY_KEYWORDS` | `software engineer,software developer,backend developer,frontend developer,full stack developer,junior developer,data engineer,data scientist,data analyst,ML engineer,machine learning engineer,python developer,business analyst,financial analyst,cloud engineer,devops engineer,epic analyst,analytics engineer,platform engineer` |
| `DISCOVERY_LOCATIONS` | `remote,new york,san francisco,seattle,austin,chicago,boston,atlanta,los angeles,denver,dallas,washington dc,miami,philadelphia,portland,minneapolis,houston,san diego,raleigh,phoenix,united states` |
| `DISCOVERY_EXCLUDED_KEYWORDS` | `senior staff,principal,director,vp,vice president,intern,c-level` |
| `ADZUNA_APP_ID` | `234c7209` |
| `ADZUNA_API_KEY` | `acf278cb73feb0113ead83faa2281f0b` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | (see below) |

### For GOOGLE_SERVICE_ACCOUNT_JSON:
1. Open `credentials/decent-booster-484319-i2-3eefecefe5e7.json`
2. Copy the **entire file contents** (it's JSON)
3. Paste as the secret value

---

## Step 3: Enable GitHub Actions

Go to: **GitHub → Your Repo → Actions → Enable workflows**

The first run will trigger automatically. After that:
- Discovery Bot: every 30 minutes
- Signal Bot: every 2 hours

---

## Step 4: Verify It's Working

1. Go to GitHub → Actions tab
2. Click the latest "Discovery Bot" run
3. Check the logs — you should see "Found X new jobs"
4. Check your Telegram — you'll get a notification with the jobs found

---

## What Works Without Laptop

| Feature | Works? | How |
|---------|--------|-----|
| Job discovery (finding new jobs) | ✅ | GitHub Actions (30min) |
| Company signal tracking | ✅ | GitHub Actions (2hr) |
| Telegram notifications | ✅ | Sent from GitHub cloud |
| Google Sheets (view jobs) | ✅ | Google's servers |
| Chrome Extension (capture jobs) | ✅ | Any Chrome browser |
| Dashboard (view/manage) | ❌ Need laptop | Run start.bat |
| Cover letter generator | ❌ Need laptop | Run start.bat |

---

## Dashboard on Other Devices (Optional — Free)

Deploy to **Streamlit Community Cloud**:
1. Go to share.streamlit.io
2. Connect GitHub account
3. Select repo + `dashboard/app.py`
4. Add secrets in Streamlit settings

Or deploy backend+dashboard to **Railway** ($5/month):
- Always-on, fast, persistent database
- One-click GitHub deploy

---

## Daily Job Collection Estimate

Based on active sources:
- **API sources** (RemoteOK, Arbeitnow, Jobicy, FindWork): ~150-300 jobs/day checked
- **RSS sources** (BuiltIn, We Work Remotely, etc.): ~50-100 jobs/day checked
- **After keyword filtering**: ~20-50 matching jobs/day saved
- **Over 30 days**: ~600-1500 curated jobs matching your profile

The bot auto-deduplicates, so you won't see the same job twice.

---

## Local Start (When Laptop Is Open)

Double-click `start.bat` → Dashboard opens at http://localhost:8501

The dashboard shows all jobs found by the cloud bots (they write to the same DB when synced, or view via Google Sheets).
