# Architecture — Job Automation Ecosystem

## System Overview

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
|  (OAuth 2.0)   |       |  (Central API)   |       |  (Database)      |
+----------------+       +--------+----------+       +------------------+
                                  ^
                                  |
                    +-------------+-------------+
                    |             |              |
              +-----+---+  +----+----+  +------+------+
              | Email   |  | Remind  |  | Discovery   |
              | Bot     |  | Bot     |  | Bot         |
              +---------+  +---------+  +-------------+
              | Resume  |  | Cover   |
              | Bot     |  | Letter  |
              +---------+  +---------+
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

## Data Flow

1. **Job Entry:** Chrome Extension OR Tracker Bot CLI → POST /jobs → Backend → Google Sheets
2. **Email Monitor:** Gmail API → Email Bot → classify → PATCH /jobs → Backend → Google Sheets
3. **Reminders:** Reminder Bot → GET /jobs (stale) → PATCH /jobs → Telegram notification
4. **Discovery:** Gmail alerts → Discovery Bot → POST /jobs → Backend → Google Sheets
5. **Dashboard:** Streamlit → GET /jobs → Backend → displays pipeline

## Key Principles

- **Single writer:** All writes to Google Sheets go through the Backend API (never direct from bots)
- **Bot isolation:** Each bot runs independently; one failing doesn't crash others
- **Retry everywhere:** All external API calls use exponential backoff with jitter
- **Config-driven:** All settings in .env, no hardcoded values
- **Idempotent:** Bots can re-run safely (duplicate detection, thread ID matching)
- **Observable:** Structured logging, health endpoints, Telegram alerts on failures
