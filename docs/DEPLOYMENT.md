# Deployment Guide — Job Automation Ecosystem

## Local Development

```bash
# Start backend
uvicorn backend.main:app --reload --port 8000

# Start bots
python -m bots.orchestrator

# Start dashboard
streamlit run dashboard/app.py
```

## Docker Compose (Production)

```bash
# Build and start all services
docker compose up -d --build

# Check status
docker compose ps

# View logs
docker compose logs -f backend
docker compose logs -f orchestrator
docker compose logs -f dashboard

# Stop
docker compose down
```

## Auto-Start on Windows Boot

### Option A: Windows Task Scheduler
1. Open Task Scheduler
2. Create Basic Task → "Job Automation"
3. Trigger: "When the computer starts"
4. Action: Start a program
5. Program: `docker`
6. Arguments: `compose -f C:\Users\valaj\Desktop\job-automation\docker-compose.yml up -d`

### Option B: Startup Folder
1. Create `start-job-automation.bat`:
   ```bat
   cd C:\Users\valaj\Desktop\job-automation
   docker compose up -d
   ```
2. Place in: `shell:startup` folder

## Monitoring

- **Backend health:** http://localhost:8000/health
- **Dashboard:** http://localhost:8501
- **Logs:** `logs/job_automation.log` and `logs/errors.log`
- **Telegram:** Bot sends alerts on failures

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Sheets 403 | Re-share sheet with service account email |
| Gmail token expired | Delete `credentials/gmail_token.json`, restart email bot |
| Telegram not sending | Verify bot token and chat_id in .env |
| Container crash loop | Check `docker compose logs <service>` |
| Port in use | Change ports in docker-compose.yml |
