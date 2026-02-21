"""Mobile/Share-to capture endpoint.

Lets you paste a job URL from your phone (or any device on the same WiFi)
and stores it in the discovery database without needing the full extension.

Usage:
  1. On phone, open http://<laptop-ip>:8000/capture
  2. Paste the job URL + optional company/title
  3. Hit Save — job is stored and scored instantly
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

from src.discovery.database import init_db, insert_job, get_all_urls
from src.discovery.preferences import JobPreferences, score_job
from src.utils.logging import get_logger

router = APIRouter(prefix="/capture", tags=["capture"])
logger = get_logger(__name__)

_FORM_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JobPilot — Capture Job</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f172a; color: #e2e8f0;
    display: flex; justify-content: center; align-items: flex-start;
    min-height: 100vh; padding: 24px 16px;
  }}
  .card {{
    background: #1e293b; border-radius: 16px; padding: 28px 24px;
    width: 100%; max-width: 480px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; color: #f1f5f9; }}
  .sub {{ font-size: 0.85rem; color: #64748b; margin-bottom: 24px; }}
  label {{ font-size: 0.85rem; color: #94a3b8; display: block; margin-bottom: 6px; }}
  input, textarea {{
    width: 100%; background: #0f172a; border: 1.5px solid #334155;
    border-radius: 8px; padding: 12px 14px; color: #e2e8f0;
    font-size: 1rem; margin-bottom: 16px; outline: none;
    transition: border-color 0.2s;
  }}
  input:focus, textarea:focus {{ border-color: #6366f1; }}
  textarea {{ height: 80px; resize: vertical; }}
  button {{
    width: 100%; background: #6366f1; color: #fff; border: none;
    border-radius: 8px; padding: 14px; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }}
  button:hover {{ background: #4f46e5; }}
  .msg {{ margin-top: 20px; padding: 14px; border-radius: 8px;
         font-size: 0.9rem; text-align: center; }}
  .ok {{ background: #14532d; color: #86efac; }}
  .err {{ background: #450a0a; color: #fca5a5; }}
</style>
</head>
<body>
<div class="card">
  <h1>📌 Capture Job</h1>
  <p class="sub">Paste a job link from your phone — saved to JobPilot instantly</p>
  {msg}
  <form method="post" action="/capture">
    <label>Job URL *</label>
    <input type="url" name="url" placeholder="https://jobs.lever.co/..." required value="{url_val}">
    <label>Company (optional)</label>
    <input type="text" name="company" placeholder="Google" value="{company_val}">
    <label>Role / Title (optional)</label>
    <input type="text" name="title" placeholder="Data Analyst" value="{title_val}">
    <label>Notes (optional)</label>
    <textarea name="notes" placeholder="Found on LinkedIn, looks good...">{notes_val}</textarea>
    <button type="submit">Save to JobPilot ✓</button>
  </form>
</div>
</body>
</html>"""


def _render(msg: str = "", url: str = "", company: str = "", title: str = "", notes: str = "") -> str:
    msg_html = f'<div class="msg {{"ok" if "Saved" in msg else "err"}}">{msg}</div>' if msg else ""
    return _FORM_HTML.format(
        msg=msg_html,
        url_val=url,
        company_val=company,
        title_val=title,
        notes_val=notes,
    )


@router.get("", response_class=HTMLResponse)
async def capture_form(url: str = Query("", description="Pre-fill URL from Share shortcut")) -> str:
    """Serve the mobile-friendly job capture form.

    Supports ?url=<job_url> so phone Share Sheet can open /capture?url=... directly.
    """
    return _render(url=url)


@router.post("", response_class=HTMLResponse)
async def capture_job(
    url: str = Form(...),
    company: str = Form(""),
    title: str = Form(""),
    notes: str = Form(""),
) -> str:
    """Store a job URL captured from mobile or any browser."""
    url = url.strip()
    if not url.startswith("http"):
        return _render("URL must start with http/https", url, company, title, notes)

    try:
        init_db()
        existing_urls = get_all_urls()
        if url in existing_urls:
            return _render(f"Already tracked: {url}", "", company, title, notes)

        prefs = JobPreferences.from_config()
        job: dict = {
            "url": url,
            "title": title or "Job from Mobile Capture",
            "company": company or "Unknown",
            "description": notes or f"Captured from phone. URL: {url}",
            "source_name": "Mobile Capture",
            "location": "",
            "salary_raw": "",
            "job_type": "",
            "experience_level": "",
            "remote_type": "",
            "skills": [],
            "is_backfill": 0,
        }
        job["score"] = score_job(job, prefs)
        job_id = insert_job(job)
        if job_id:
            logger.info(f"Mobile capture stored job_id={job_id} url={url}")
            return _render(f"Saved! Score: {job['score']:.0%} | ID: {job_id}", "", "", "", "")
        else:
            return _render("Already exists in database.", "", company, title, notes)
    except Exception as exc:
        logger.error(f"Capture error: {exc}", exc_info=True)
        return _render(f"Error: {exc}", url, company, title, notes)
