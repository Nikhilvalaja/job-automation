# Setup Guide — Job Automation Ecosystem

## Prerequisites
- Python 3.12+ (tested on 3.13)
- Docker & Docker Compose
- Node.js 18+ (for Chrome extension development)
- Git
- Google Cloud account (free tier)

## Step 1: Clone & Install

```bash
git clone <your-repo-url> job-automation
cd job-automation
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Step 2: Google Cloud Setup

### 2a. Create Project
1. Go to https://console.cloud.google.com/
2. Create new project: "job-automation"
3. Note your Project ID

### 2b. Enable APIs
1. Go to APIs & Services → Library
2. Enable: **Google Sheets API**
3. Enable: **Gmail API**

### 2c. Service Account (for Sheets)
1. Go to APIs & Services → Credentials
2. Create Credentials → Service Account
3. Name: "job-automation-sheets"
4. Download JSON key → save as `credentials/service_account.json`
5. Copy the service account email (looks like: name@project.iam.gserviceaccount.com)

### 2d. Create Google Sheet
1. Create a new Google Sheet
2. Name it: "Job Applications Tracker"
3. Add header row (Row 1):
   `app_id | date_added | date_applied | company | role | source | job_url | status | last_email_date | thread_id | next_action_date | notes`
4. Share the sheet with your service account email (Editor access)
5. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`

### 2e. Gmail OAuth (for Email Bot)
1. Go to APIs & Services → Credentials
2. Create Credentials → OAuth 2.0 Client ID
3. Application type: Desktop App
4. Download JSON → save as `credentials/gmail_credentials.json`
5. Go to OAuth consent screen → add your email as Test User
6. First run of email bot will open browser for authorization

## Step 3: Telegram Bot

1. Open Telegram, search for @BotFather
2. Send `/newbot` and follow prompts
3. Copy the bot token
4. Send a message to your bot, then visit:
   `https://api.telegram.org/bot{TOKEN}/getUpdates`
5. Find your `chat_id` in the response

## Step 4: Environment Variables

```bash
cp .env.example .env
# Edit .env with your actual values
```

## Step 5: Run

```bash
# Terminal 1: Backend
uvicorn backend.main:app --reload --port 8000

# Terminal 2: Orchestrator (runs all bots)
python -m bots.orchestrator

# Terminal 3: Dashboard
streamlit run dashboard/app.py
```

## Step 6: Chrome Extension
1. Open Chrome → `chrome://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked" → select the `extension/` folder
