"""Job Automation Dashboard — Streamlit + Plotly.

Full-featured dashboard with:
- KPI cards (total, applied, replied, interviews, offers, rejections)
- Status distribution, source breakdown, application timeline charts
- Response rate & conversion funnel
- Job table with filtering, sorting, inline status updates
- Job Discovery with score colors, skill gaps, JD analysis, resume suggestion
- My Resumes — upload, parse, view skill inventory
- Bot Control Center — start/stop individual bots
- Email Classification Rules — view, add, modify rules
- Sites/Sources tracker
- DB Health widget in sidebar

Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.config import get_settings

# --- Page Config ---
st.set_page_config(
    page_title="JobPilot Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

STATUSES = [
    "To Apply", "Applied", "Assessment", "Interview",
    "Offer", "Rejected", "No Reply", "Withdrawn", "Archived",
]

STATUS_COLORS = {
    "To Apply": "#94a3b8",
    "Applied": "#3b82f6",
    "Assessment": "#a855f7",
    "Interview": "#f59e0b",
    "Offer": "#22c55e",
    "Rejected": "#ef4444",
    "No Reply": "#6b7280",
    "Withdrawn": "#78716c",
    "Archived": "#d1d5db",
}


def score_color(score: float) -> str:
    """Return color based on match score: green >= 0.7, yellow >= 0.4, red < 0.4."""
    if score >= 0.7:
        return "#22c55e"
    elif score >= 0.4:
        return "#f59e0b"
    return "#ef4444"


def score_badge(score: float) -> str:
    """Return an HTML badge string for a match score."""
    color = score_color(score)
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-weight:bold">{score:.0%}</span>'


def confidence_badge(confidence: float) -> str:
    """Return an HTML badge for JD confidence level."""
    if confidence >= 0.7:
        label, color = "High", "#22c55e"
    elif confidence >= 0.4:
        label, color = "Medium", "#f59e0b"
    else:
        label, color = "Low", "#ef4444"
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.8em">{label} ({confidence:.0%})</span>'


def skill_tags_html(skills: list[str], color: str = "#3b82f6") -> str:
    """Return HTML for skill tags."""
    if not skills:
        return ""
    tags = " ".join(
        f'<span style="background:{color};color:#fff;padding:1px 6px;border-radius:3px;font-size:0.8em;margin:1px">{s}</span>'
        for s in skills
    )
    return tags


# --- Data Fetching ---
@st.cache_data(ttl=30)
def fetch_jobs(backend_url: str) -> list[dict]:
    """Fetch all jobs from the backend API."""
    try:
        resp = httpx.get(f"{backend_url}/jobs", timeout=10.0)
        if resp.status_code == 200:
            return resp.json().get("jobs", [])
    except httpx.ConnectError:
        pass
    return []


def check_backend(backend_url: str) -> bool:
    """Check if backend is reachable."""
    try:
        resp = httpx.get(f"{backend_url}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


def update_job_status(backend_url: str, app_id: str, new_status: str) -> bool:
    """Update a job's status via the backend API."""
    try:
        resp = httpx.patch(
            f"{backend_url}/jobs/{app_id}",
            json={"status": new_status},
            timeout=10.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def add_job(backend_url: str, payload: dict) -> dict | None:
    """Add a new job via the backend API."""
    try:
        resp = httpx.post(
            f"{backend_url}/jobs",
            json=payload,
            timeout=10.0,
        )
        if resp.status_code == 201:
            return resp.json()
    except Exception:
        pass
    return None


# --- Sidebar ---
def render_sidebar():
    """Render sidebar with settings and add job form."""
    settings = get_settings()

    st.sidebar.title("JobPilot")

    # Backend connection
    backend_url = st.sidebar.text_input("Backend URL", value=settings.backend_url)
    connected = check_backend(backend_url)
    if connected:
        st.sidebar.success("Backend connected")
    else:
        st.sidebar.error("Backend unreachable")
        st.sidebar.caption("Start it: `uvicorn backend.main:app --reload`")

    st.sidebar.divider()

    # Add Job Form
    st.sidebar.subheader("Add New Job")
    with st.sidebar.form("add_job_form"):
        company = st.text_input("Company *")
        role = st.text_input("Role *")
        source = st.text_input("Source", placeholder="LinkedIn, Indeed, etc.")
        job_url = st.text_input("Job URL")
        status = st.selectbox("Status", STATUSES, index=1)
        notes = st.text_area("Notes", height=68)
        submitted = st.form_submit_button("Add Job")

        if submitted:
            if not company or not role:
                st.error("Company and Role are required.")
            else:
                result = add_job(backend_url, {
                    "company": company,
                    "role": role,
                    "source": source,
                    "job_url": job_url,
                    "status": status,
                    "notes": notes,
                })
                if result:
                    st.success(f"Added: {company} / {role}")
                    st.cache_data.clear()
                else:
                    st.error("Failed to add job.")

    st.sidebar.divider()

    if st.sidebar.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    # DB Health Widget
    st.sidebar.divider()
    st.sidebar.subheader("System Health")
    try:
        health_resp = httpx.get(f"{backend_url}/analysis/health", timeout=5.0)
        if health_resp.status_code == 200:
            health = health_resp.json()

            # Discovery DB
            disc_db = health.get("discovery_db", {})
            if disc_db.get("exists"):
                st.sidebar.caption(f"Discovery DB: {disc_db.get('size_mb', 0):.1f} MB")
            else:
                st.sidebar.caption("Discovery DB: not created yet")

            # Resume count
            st.sidebar.caption(f"Resumes stored: {health.get('resume_count', 0)}")

            # Backup status
            backup = health.get("backup", {})
            backup_status = backup.get("status", "unknown")
            if backup_status == "ok":
                st.sidebar.success(f"Backup: OK ({backup.get('backup_count', 0)} backups)")
            elif backup_status == "warning":
                st.sidebar.warning(f"Backup: {backup.get('hours_since_backup', '?')}h ago")
            elif backup_status == "critical":
                st.sidebar.error("Backup: No backups found!")
            else:
                st.sidebar.caption("Backup: unknown")

            # Retention stats
            retention = health.get("retention", {})
            if retention:
                active = retention.get("total_active", 0)
                archived = retention.get("total_archived", 0)
                st.sidebar.caption(f"Active jobs: {active:,} | Archived: {archived:,}")
        else:
            st.sidebar.caption("Health check unavailable")
    except Exception:
        st.sidebar.caption("Health: backend unreachable")

    return backend_url


# --- KPI Cards ---
def render_kpis(df: pd.DataFrame):
    """Render KPI metric cards with response rate."""
    total = len(df)
    applied = len(df[df["status"] == "Applied"])
    interviews = len(df[df["status"] == "Interview"])
    offers = len(df[df["status"] == "Offer"])
    rejected = len(df[df["status"] == "Rejected"])
    no_reply = len(df[df["status"] == "No Reply"])
    assessment = len(df[df["status"] == "Assessment"])

    # Response rate = (interview + offer + rejected + assessment) / (applied + interview + offer + rejected + no_reply + assessment)
    sent_out = applied + interviews + offers + rejected + no_reply + assessment
    got_reply = interviews + offers + rejected + assessment
    response_rate = (got_reply / sent_out * 100) if sent_out > 0 else 0
    sources_count = df["source"].nunique() if "source" in df.columns else 0

    cols = st.columns(8)
    cols[0].metric("Total", total)
    cols[1].metric("Applied", applied)
    cols[2].metric("Replied", got_reply)
    cols[3].metric("Interviews", interviews)
    cols[4].metric("Offers", offers)
    cols[5].metric("Rejected", rejected)
    cols[6].metric("Response Rate", f"{response_rate:.0f}%")
    cols[7].metric("Sources", sources_count)


# --- Charts ---
def render_charts(df: pd.DataFrame):
    """Render Plotly charts."""
    col1, col2 = st.columns(2)

    # Status Distribution Pie Chart
    with col1:
        st.subheader("Status Distribution")
        if len(df) > 0:
            status_counts = df["status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]

            fig = px.pie(
                status_counts,
                values="count",
                names="status",
                color="status",
                color_discrete_map=STATUS_COLORS,
                hole=0.4,
            )
            fig.update_layout(
                margin=dict(t=20, b=20, l=20, r=20),
                height=300,
                showlegend=True,
                legend=dict(orientation="h", y=-0.1),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No data yet.")

    # Source Breakdown Bar Chart
    with col2:
        st.subheader("Applications by Source")
        if len(df) > 0 and "source" in df.columns:
            source_df = df[df["source"] != ""].groupby("source").size().reset_index(name="count")
            source_df = source_df.sort_values("count", ascending=True)

            if len(source_df) > 0:
                fig = px.bar(
                    source_df,
                    x="count",
                    y="source",
                    orientation="h",
                    color_discrete_sequence=["#3b82f6"],
                )
                fig.update_layout(
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=300,
                    xaxis_title="Count",
                    yaxis_title="",
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("No source data.")
        else:
            st.caption("No data yet.")

    # Row 2: Timeline + Funnel
    col3, col4 = st.columns(2)

    # Timeline Chart
    with col3:
        st.subheader("Application Timeline")
        if len(df) > 0 and "date_applied" in df.columns:
            timeline_df = df[df["date_applied"] != ""].copy()
            if len(timeline_df) > 0:
                timeline_df["date"] = pd.to_datetime(timeline_df["date_applied"], errors="coerce")
                timeline_df = timeline_df.dropna(subset=["date"])

                if len(timeline_df) > 0:
                    daily = timeline_df.groupby(timeline_df["date"].dt.date).size().reset_index(name="count")
                    daily.columns = ["date", "count"]
                    daily["cumulative"] = daily["count"].cumsum()

                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=daily["date"], y=daily["count"],
                        name="Daily", marker_color="#93c5fd",
                    ))
                    fig.add_trace(go.Scatter(
                        x=daily["date"], y=daily["cumulative"],
                        name="Cumulative", line=dict(color="#2563eb", width=2),
                        yaxis="y2",
                    ))
                    fig.update_layout(
                        margin=dict(t=20, b=20, l=20, r=20),
                        height=280,
                        yaxis=dict(title="Daily"),
                        yaxis2=dict(title="Cumulative", overlaying="y", side="right"),
                        legend=dict(orientation="h", y=1.1),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.caption("No valid dates.")
            else:
                st.caption("No date data.")
        else:
            st.caption("No data yet.")

    # Conversion Funnel
    with col4:
        st.subheader("Conversion Funnel")
        if len(df) > 0:
            stages = ["Applied", "Assessment", "Interview", "Offer"]
            counts = []
            for stage in stages:
                # Count all jobs that reached this stage or beyond
                stage_idx = stages.index(stage)
                later_stages = stages[stage_idx:]
                count = len(df[df["status"].isin(later_stages)])
                counts.append(count)

            # Add total as top of funnel
            stages_full = ["Total Tracked"] + stages
            counts_full = [len(df)] + counts

            fig = go.Figure(go.Funnel(
                y=stages_full,
                x=counts_full,
                textinfo="value+percent initial",
                marker=dict(color=["#94a3b8", "#3b82f6", "#a855f7", "#f59e0b", "#22c55e"]),
            ))
            fig.update_layout(
                margin=dict(t=20, b=20, l=20, r=20),
                height=280,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No data yet.")


# --- Job Table ---
def render_table(df: pd.DataFrame, backend_url: str):
    """Render interactive job table with filters."""
    st.subheader("All Applications")

    # Filters
    filter_cols = st.columns(3)
    with filter_cols[0]:
        status_filter = st.multiselect(
            "Filter by Status",
            options=STATUSES,
            default=[],
            placeholder="All statuses",
        )
    with filter_cols[1]:
        source_options = sorted(df["source"].unique().tolist()) if "source" in df.columns else []
        source_filter = st.multiselect(
            "Filter by Source",
            options=[s for s in source_options if s],
            default=[],
            placeholder="All sources",
        )
    with filter_cols[2]:
        search = st.text_input("Search", placeholder="Company, role, notes...")

    # Apply filters
    filtered = df.copy()
    if status_filter:
        filtered = filtered[filtered["status"].isin(status_filter)]
    if source_filter:
        filtered = filtered[filtered["source"].isin(source_filter)]
    if search:
        mask = filtered.apply(
            lambda row: search.lower() in " ".join(str(v).lower() for v in row.values),
            axis=1,
        )
        filtered = filtered[mask]

    st.caption(f"Showing {len(filtered)} of {len(df)} applications")

    if len(filtered) == 0:
        st.info("No matching applications.")
        return

    # Display table
    display_cols = ["app_id", "company", "role", "status", "source", "date_applied", "notes"]
    available_cols = [c for c in display_cols if c in filtered.columns]
    st.dataframe(
        filtered[available_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "app_id": st.column_config.TextColumn("ID", width="small"),
            "company": st.column_config.TextColumn("Company", width="medium"),
            "role": st.column_config.TextColumn("Role", width="medium"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "source": st.column_config.TextColumn("Source", width="small"),
            "date_applied": st.column_config.TextColumn("Applied", width="small"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
        },
    )

    # Quick status update
    st.divider()
    st.subheader("Quick Update")
    update_cols = st.columns(3)
    with update_cols[0]:
        app_ids = filtered["app_id"].tolist() if "app_id" in filtered.columns else []
        selected_id = st.selectbox("Select Job", options=app_ids, index=None, placeholder="Pick a job...")
    with update_cols[1]:
        new_status = st.selectbox("New Status", options=STATUSES, key="update_status")
    with update_cols[2]:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Update Status") and selected_id:
            if update_job_status(backend_url, selected_id, new_status):
                st.success(f"Updated {selected_id} to {new_status}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Update failed.")


# --- Bot Control Center ---
def render_bot_controls():
    """Render bot control panel with status and actions."""
    st.subheader("Bot Control Center")
    st.caption(
        "All bots run automatically via the Orchestrator. "
        "Double-click **start.bat** in the project folder to launch everything at once."
    )

    settings = get_settings()

    bots_config = [
        {
            "name": "Email Bot",
            "desc": "Monitors Gmail for job application status updates",
            "schedule": f"Every {settings.email_bot_interval_minutes} minutes",
            "command": "python -m bots.email_bot.run",
            "dry_run": "python -m bots.email_bot.run --dry-run",
        },
        {
            "name": "Reminder Bot",
            "desc": f"Detects stale applications (>{settings.followup_threshold_days} days) and sends Telegram alerts",
            "schedule": f"Daily at {settings.reminder_bot_hour:02d}:{settings.reminder_bot_minute:02d}",
            "command": "python -m bots.reminder_bot.run",
            "dry_run": "python -m bots.reminder_bot.run --dry-run",
        },
        {
            "name": "Discovery Bot",
            "desc": f"Scans 700+ job sources (Greenhouse, Lever, Ashby, Workday, Adzuna grid, RSS) every {settings.discovery_bot_interval_minutes} min. Auto-scheduled by Orchestrator.",
            "schedule": f"Every {settings.discovery_bot_interval_minutes} minutes (auto)",
            "command": "python -m bots.discovery_bot.run",
            "dry_run": "python -m bots.discovery_bot.run --dry-run",
        },
        {
            "name": "Gmail Ingest Bot",
            "desc": "Scans Gmail (both accounts) every 30 min for job alert emails from iHire, Lensa, LinkedIn, Indeed, jobs2web, and ANY sender with job-related subject lines. Stores sender, URL, posted date, and source website. Auto-scheduled by Orchestrator.",
            "schedule": "Every 30 min (auto via Orchestrator)",
            "command": "python -m bots.gmail_ingest_bot.run --hours 168",
            "dry_run": "python -m bots.gmail_ingest_bot.run --hours 168 --dry-run",
        },
        {
            "name": "Tracker Bot",
            "desc": "CLI tool for manually adding/managing job applications",
            "schedule": "Manual (CLI only)",
            "command": "python -m bots.tracker_bot.run",
            "dry_run": "python -m bots.tracker_bot.run list",
        },
        {
            "name": "Orchestrator (Keep Running)",
            "desc": "Central scheduler — runs ALL bots automatically in the background. Start once, leave running. Includes: Email Bot, Reminder Bot, Discovery Bot, Gmail Ingest Bot.",
            "schedule": "Continuous background process",
            "command": "python -m bots.orchestrator.run",
            "dry_run": "python -m bots.orchestrator.run --status",
        },
    ]

    for bot in bots_config:
        with st.expander(f"**{bot['name']}** — {bot['schedule']}"):
            st.caption(bot["desc"])
            col1, col2 = st.columns(2)
            with col1:
                st.code(bot["command"], language="bash")
            with col2:
                st.code(bot["dry_run"], language="bash")

    # ── Launch Everything Box ────────────────────────────────────────────────
    st.divider()
    st.success(
        "### One-Click Start — Double-click this file:\n\n"
        "```\nC:\\Users\\valaj\\OneDrive\\Desktop\\job-automation\\start.bat\n```\n\n"
        "Starts **Backend API + Dashboard + All Bots** automatically.\n"
        "Bookmark **http://localhost:8501** in your browser — that's your permanent dashboard URL.\n\n"
        "**What the bots do automatically (no action needed):**\n"
        "| Bot | Schedule | What it does |\n"
        "|-----|----------|--------------|\n"
        "| Discovery Bot | Every 60 min | Scans 700+ sources, scores jobs, Telegram alert on new matches |\n"
        "| Gmail Ingest | Every 30 min | Captures job alert emails from iHire, Lensa, LinkedIn, etc. |\n"
        "| Email Bot | Every 5 min | Detects replies, interviews, rejections from applications |\n"
        "| Reminder Bot | Daily 9 AM | Flags stale applications, sends Telegram follow-up nudges |\n\n"
        "**Event-triggered (on your action):**\n"
        "- Google Sheets sync → happens when you click **Apply** on a job\n"
        "- Telegram job alert → fires when Discovery Bot finds high-score matches"
    )


# --- Email Classification Rules ---
def render_rules():
    """Render email classification rules editor."""
    st.subheader("Email Classification Rules")
    st.caption("These rules determine how incoming emails are classified. Higher priority wins on conflicts.")

    try:
        from src.gmail.rules import DEFAULT_RULES
        rules_data = []
        for rule in DEFAULT_RULES:
            rules_data.append({
                "Rule Name": rule.name,
                "Maps to Status": rule.status.value,
                "Priority": rule.priority,
                "Keywords (subject)": ", ".join(rule.subject_keywords[:5]) + ("..." if len(rule.subject_keywords) > 5 else ""),
                "Keywords (body)": ", ".join(rule.body_keywords[:5]) + ("..." if len(rule.body_keywords) > 5 else ""),
            })

        rules_df = pd.DataFrame(rules_data)
        st.dataframe(rules_df, use_container_width=True, hide_index=True)
    except ImportError:
        st.info("Email rules module not available.")

    # Custom rules builder
    st.divider()
    st.subheader("Add Custom Rule")
    st.caption("Add your own keywords to improve classification accuracy. Custom rules are saved locally.")

    custom_rules_path = Path(get_settings().log_path).parent / "custom_rules.json"

    # Load existing custom rules
    custom_rules = []
    if custom_rules_path.exists():
        try:
            custom_rules = json.loads(custom_rules_path.read_text())
        except Exception:
            custom_rules = []

    with st.form("custom_rule_form"):
        cr_col1, cr_col2 = st.columns(2)
        with cr_col1:
            rule_name = st.text_input("Rule Name", placeholder="e.g. My Company Reject Pattern")
            target_status = st.selectbox("Maps to Status", ["Rejected", "Interview", "Assessment", "Applied", "Offer"])
        with cr_col2:
            subject_kw = st.text_input("Subject Keywords (comma-separated)", placeholder="e.g. regret, sorry")
            body_kw = st.text_input("Body Keywords (comma-separated)", placeholder="e.g. not a fit, passed")

        if st.form_submit_button("Add Rule"):
            if rule_name and (subject_kw or body_kw):
                new_rule = {
                    "name": rule_name,
                    "status": target_status,
                    "subject_keywords": [k.strip() for k in subject_kw.split(",") if k.strip()],
                    "body_keywords": [k.strip() for k in body_kw.split(",") if k.strip()],
                }
                custom_rules.append(new_rule)
                custom_rules_path.write_text(json.dumps(custom_rules, indent=2))
                st.success(f"Rule '{rule_name}' saved!")
            else:
                st.error("Rule name and at least one keyword required.")

    # Display custom rules
    if custom_rules:
        st.caption(f"{len(custom_rules)} custom rule(s)")
        for i, rule in enumerate(custom_rules):
            with st.expander(f"{rule['name']} → {rule['status']}"):
                st.write(f"**Subject keywords:** {', '.join(rule.get('subject_keywords', []))}")
                st.write(f"**Body keywords:** {', '.join(rule.get('body_keywords', []))}")
                if st.button(f"Delete", key=f"del_rule_{i}"):
                    custom_rules.pop(i)
                    custom_rules_path.write_text(json.dumps(custom_rules, indent=2))
                    st.rerun()


# --- Sites Tracker ---
def render_sites(df: pd.DataFrame):
    """Show which job sites/sources are being tracked."""
    st.subheader("Sites & Sources Tracked")

    if len(df) == 0 or "source" not in df.columns:
        st.info("No source data yet.")
        return

    source_stats = df[df["source"] != ""].groupby("source").agg(
        total=("app_id", "count"),
        applied=("status", lambda x: (x == "Applied").sum()),
        replied=("status", lambda x: x.isin(["Interview", "Offer", "Rejected", "Assessment"]).sum()),
    ).reset_index()

    source_stats["response_rate"] = (
        source_stats["replied"] / source_stats["total"] * 100
    ).round(1)

    source_stats = source_stats.sort_values("total", ascending=False)

    st.dataframe(
        source_stats,
        use_container_width=True,
        hide_index=True,
        column_config={
            "source": st.column_config.TextColumn("Source", width="medium"),
            "total": st.column_config.NumberColumn("Total Jobs", width="small"),
            "applied": st.column_config.NumberColumn("Applied", width="small"),
            "replied": st.column_config.NumberColumn("Got Reply", width="small"),
            "response_rate": st.column_config.NumberColumn("Response %", format="%.1f%%", width="small"),
        },
    )


# --- Cover Letter Generator ---
def render_cover_letter(df: pd.DataFrame, backend_url: str):
    """Render cover letter generator UI with tone selection."""
    st.subheader("Cover Letter Generator")
    st.caption("Generate a tailored cover letter using AI (OpenAI GPT) or a basic template.")

    col1, col2 = st.columns([1, 1])

    with col1:
        # Select from tracked jobs or enter manually
        job_options = ["-- Enter manually --"] + [
            f"{row['company']} — {row['role']}" for _, row in df.iterrows()
            if row.get("company")
        ]
        selected_job = st.selectbox("Select a tracked job", options=job_options)

        if selected_job != "-- Enter manually --":
            parts = selected_job.split(" — ", 1)
            company = parts[0] if len(parts) > 0 else ""
            role = parts[1] if len(parts) > 1 else ""
        else:
            company = ""
            role = ""

        company = st.text_input("Company", value=company, key="cl_company")
        role = st.text_input("Role", value=role, key="cl_role")
        job_description = st.text_area(
            "Job Description (paste the full JD)",
            height=200,
            placeholder="Paste the job description here for a personalized cover letter...",
        )
        resume_text = st.text_area(
            "Your Resume/Background (optional)",
            height=150,
            placeholder="Paste your resume or key achievements to personalize further...",
        )

        tone_col, mode_col = st.columns(2)
        with tone_col:
            tone = st.selectbox("Tone", ["professional", "conversational", "technical", "executive"])
        with mode_col:
            mode = st.radio("Mode", ["llm", "template"], horizontal=True)

        extra_instructions = st.text_input(
            "Extra instructions (optional)",
            placeholder="e.g., mention my AWS certs, focus on ML experience...",
        )
        generate_btn = st.button("Generate Cover Letter", type="primary")

    with col2:
        st.markdown("**Generated Cover Letter:**")
        if generate_btn:
            if not company or not role:
                st.error("Company and Role are required.")
            elif mode == "llm" and not job_description:
                st.error("Job description is required for AI mode.")
            else:
                with st.spinner("Generating..."):
                    try:
                        resp = httpx.post(
                            f"{backend_url}/cover-letter",
                            json={
                                "company": company,
                                "role": role,
                                "job_description": job_description,
                                "resume_text": resume_text,
                                "tone": tone,
                                "extra_instructions": extra_instructions,
                                "mode": mode,
                            },
                            timeout=60.0,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            st.text_area(
                                "Cover Letter",
                                value=data["cover_letter"],
                                height=400,
                                label_visibility="collapsed",
                            )
                            st.caption(
                                f"Mode: {data['mode']} | Tone: {tone} | "
                                f"Tokens: {data.get('tokens_used', 0)}"
                            )
                            st.code(data["cover_letter"], language=None)
                        else:
                            st.error(f"Error: {resp.status_code} — {resp.text}")
                    except httpx.ConnectError:
                        st.error("Backend not reachable.")
                    except Exception as e:
                        st.error(f"Error: {e}")
        else:
            st.info("Fill in the details and click 'Generate Cover Letter' to get started.")


# --- Resume Studio ---
def render_resume_tailor(df: pd.DataFrame, backend_url: str):
    """Resume Studio — constrained bullet optimization with human-in-the-loop control.

    Features:
    - Select stored resume + JD
    - Deterministic or LLM-assisted rewrite
    - Side-by-side diff with word-level highlights
    - Per-bullet approve/reject/edit
    - Skill gap analysis with computed transfer scores
    - Variant management (draft → finalized → exported → applied)
    - Performance tracking (interview callbacks)
    """
    st.subheader("Resume Studio")
    st.caption(
        "Optimize resume bullets for a specific JD. "
        "Constrained rewrites — your skills, your metrics, your words. "
        "Review every change before it's applied."
    )

    # --- Studio sub-tabs ---
    studio_tab1, studio_tab2, studio_tab3 = st.tabs(
        ["Optimize Bullets", "My Variants", "Skill Transfer"]
    )

    with studio_tab1:
        _render_studio_optimize(df, backend_url)
    with studio_tab2:
        _render_studio_variants(backend_url)
    with studio_tab3:
        _render_studio_skill_transfer(backend_url)


def _render_studio_optimize(df: pd.DataFrame, backend_url: str):
    """Optimize bullets tab — select resume, enter JD, rewrite, review."""
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("**1. Select Resume**")
        # Fetch stored resumes
        try:
            resp = httpx.get(f"{backend_url}/analysis/resumes", timeout=5.0)
            resumes = resp.json().get("resumes", []) if resp.status_code == 200 else []
        except Exception:
            resumes = []

        if resumes:
            resume_options = {r["id"]: f"{r['name']} ({'default' if r.get('is_default') else r['id'][:6]})" for r in resumes}
            selected_resume_id = st.selectbox(
                "Choose a stored resume",
                options=list(resume_options.keys()),
                format_func=lambda x: resume_options.get(x, x),
                key="studio_resume",
            )
        else:
            st.info("No resumes stored yet. Upload one in the 'My Resumes' tab.")
            selected_resume_id = None

        st.markdown("**2. Job Description**")
        # Select from tracked jobs or enter manually
        job_options = ["-- Paste manually --"]
        if not df.empty:
            job_options += [
                f"{row['company']} — {row['role']}"
                for _, row in df.iterrows()
                if row.get("company")
            ]
        selected_job = st.selectbox("Select a tracked job", options=job_options, key="studio_job")

        if selected_job != "-- Paste manually --":
            parts = selected_job.split(" — ", 1)
            jd_company = parts[0] if parts else ""
            jd_title = parts[1] if len(parts) > 1 else ""
        else:
            jd_company = st.text_input("Company", key="studio_company")
            jd_title = st.text_input("Job Title", key="studio_title")

        jd_text = st.text_area(
            "Paste Full Job Description",
            height=200,
            placeholder="Paste the complete JD here...",
            key="studio_jd",
        )

        st.markdown("**3. Rewrite Method**")
        method = st.radio(
            "Method",
            ["Deterministic (keyword swaps only)", "LLM-Assisted (with strict guardrails)"],
            key="studio_method",
            horizontal=True,
        )

        optimize_btn = st.button("Optimize Bullets", type="primary", key="studio_optimize")

    with col_right:
        if optimize_btn:
            if not selected_resume_id:
                st.error("Please select a resume first.")
            elif not jd_text.strip():
                st.error("Job description is required.")
            else:
                endpoint = "/studio/rewrite" if "Deterministic" in method else "/studio/rewrite-llm"
                with st.spinner("Optimizing bullets..."):
                    try:
                        resp = httpx.post(
                            f"{backend_url}{endpoint}",
                            json={
                                "resume_id": selected_resume_id,
                                "jd_title": jd_title,
                                "jd_company": jd_company,
                                "jd_text": jd_text,
                            },
                            timeout=120.0,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            st.session_state["studio_result"] = data
                            st.success(
                                f"Optimized {data['rewrite_count']}/{data['total_bullets']} bullets. "
                                f"Variant saved: {data['variant']['id']}"
                            )
                        else:
                            st.error(f"Error: {resp.status_code} — {resp.text}")
                    except httpx.ConnectError:
                        st.error("Backend not reachable.")
                    except Exception as e:
                        st.error(f"Error: {e}")

        # Display results if available
        result = st.session_state.get("studio_result")
        if result:
            _render_studio_result(result, backend_url)
        else:
            st.markdown("**Optimized Results:**")
            st.info("Select a resume, paste a JD, and click 'Optimize Bullets' to get started.")


def _render_studio_result(data: dict, backend_url: str):
    """Render the optimization result — diff report + gap analysis."""
    variant = data.get("variant", {})
    diff_report = data.get("diff_report", {})
    gap_analysis = data.get("gap_analysis", {})

    # --- Score summary ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Weighted Score", f"{gap_analysis.get('weighted_score', 0):.0%}")
    m2.metric("Coverage", f"{gap_analysis.get('coverage_rate', 0):.0%}")
    m3.metric("Exact Matches", len(gap_analysis.get("exact_matches", [])))
    m4.metric("Skill Gaps", len(gap_analysis.get("gaps", [])))

    # --- Gap analysis detail ---
    with st.expander("Skill Gap Analysis", expanded=False):
        if gap_analysis.get("exact_matches"):
            st.markdown("**Exact Matches:** " + skill_tags_html(
                gap_analysis["exact_matches"], "#22c55e"
            ), unsafe_allow_html=True)
        if gap_analysis.get("transferable"):
            st.markdown("**Transferable Skills:**")
            for t in gap_analysis["transferable"]:
                score = t.get("score", 0)
                color = score_color(score)
                st.markdown(
                    f'<span style="color:{color}; font-weight:bold;">'
                    f'{t["best_resume_skill"]} &rarr; {t["jd_skill"]} ({score:.0%})</span>'
                    f' — {t.get("explanation", "")}',
                    unsafe_allow_html=True,
                )
        if gap_analysis.get("gaps"):
            st.markdown("**Gaps (no match):** " + skill_tags_html(
                gap_analysis["gaps"], "#ef4444"
            ), unsafe_allow_html=True)

    # --- Bullet-by-bullet diff ---
    st.markdown(f"**Bullet Review** — Variant `{variant.get('id', '?')}`")
    summary = diff_report.get("summary", {})
    st.caption(
        f"Total: {summary.get('total_bullets', 0)} | "
        f"Changed: {summary.get('changed_bullets', 0)} | "
        f"Validation: {summary.get('validation_pass_rate', 0):.0%}"
    )

    for bd in diff_report.get("bullet_diffs", []):
        idx = bd.get("index", 0)
        changed = bd.get("changed", False)

        if not changed:
            st.markdown(
                f"**Bullet {idx + 1}** — <span style='color:#94a3b8;'>UNCHANGED</span>",
                unsafe_allow_html=True,
            )
            st.text(bd.get("original_text", ""))
        else:
            valid = bd.get("validation", {})
            passed = valid.get("passed", True) if valid else True
            color = "#22c55e" if passed else "#ef4444"
            label = "VALID" if passed else "INVALID"

            st.markdown(
                f"**Bullet {idx + 1}** — <span style='color:{color};'>{label}</span>",
                unsafe_allow_html=True,
            )

            # Side-by-side diff
            dc1, dc2 = st.columns(2)
            with dc1:
                st.markdown("*Original:*")
                st.text(bd.get("original_text", ""))
            with dc2:
                st.markdown("*Rewritten:*")
                # Render word diffs with highlights
                diff_html = _render_word_diff_html(bd.get("word_diffs", []))
                if diff_html:
                    st.markdown(diff_html, unsafe_allow_html=True)
                else:
                    st.text(bd.get("rewritten_text", ""))

            # Changes list
            for c in bd.get("changes", []):
                st.caption(
                    f"  {c.get('original', '')} -> {c.get('replacement', '')} "
                    f"({c.get('reason', '')})"
                )

            # Approve/reject controls
            ac1, ac2, ac3 = st.columns([1, 1, 2])
            with ac1:
                if st.button("Approve", key=f"approve_{variant.get('id')}_{idx}"):
                    _approve_bullet(backend_url, variant.get("id"), idx, "approved")
            with ac2:
                if st.button("Reject", key=f"reject_{variant.get('id')}_{idx}"):
                    _approve_bullet(backend_url, variant.get("id"), idx, "rejected")
            with ac3:
                edit_text = st.text_input(
                    "Edit",
                    value=bd.get("rewritten_text", ""),
                    key=f"edit_{variant.get('id')}_{idx}",
                    label_visibility="collapsed",
                )
                if st.button("Save Edit", key=f"save_edit_{variant.get('id')}_{idx}"):
                    _approve_bullet(
                        backend_url, variant.get("id"), idx,
                        "approved", edit_text,
                    )

        st.divider()

    # Finalize button
    if st.button("Finalize Variant", type="primary", key="studio_finalize"):
        try:
            resp = httpx.post(
                f"{backend_url}/studio/variants/{variant.get('id')}/finalize",
                timeout=10.0,
            )
            if resp.status_code == 200:
                final = resp.json()
                if "error" in final:
                    st.warning(final["error"])
                else:
                    st.success(f"Variant {variant.get('id')} finalized!")
                    with st.expander("Final Bullets"):
                        for fb in final.get("final_bullets", []):
                            source_label = "REWRITTEN" if fb.get("source") == "rewritten" else "ORIGINAL"
                            st.markdown(f"**[{source_label}]** {fb.get('text', '')}")
            else:
                st.error(f"Error: {resp.text}")
        except Exception as e:
            st.error(f"Error: {e}")


def _approve_bullet(backend_url: str, variant_id: str, idx: int, approval: str, edited: str | None = None):
    """Send bullet approval to backend."""
    try:
        payload = {"approval": approval}
        if edited:
            payload["user_edited_text"] = edited
        resp = httpx.patch(
            f"{backend_url}/studio/variants/{variant_id}/bullet/{idx}",
            json=payload,
            timeout=5.0,
        )
        if resp.status_code == 200:
            st.toast(f"Bullet {idx + 1} {approval}")
        else:
            st.error(f"Failed: {resp.text}")
    except Exception as e:
        st.error(f"Error: {e}")


def _render_word_diff_html(word_diffs: list[dict]) -> str:
    """Render word-level diffs as HTML with color coding."""
    if not word_diffs:
        return ""
    parts = []
    for wd in word_diffs:
        t = wd.get("type", "equal")
        if t == "equal":
            parts.append(wd.get("value", ""))
        elif t == "delete":
            parts.append(
                f'<span style="background:#fecaca; text-decoration:line-through; padding:1px 3px;">'
                f'{wd.get("value", "")}</span>'
            )
        elif t == "insert":
            parts.append(
                f'<span style="background:#bbf7d0; font-weight:bold; padding:1px 3px;">'
                f'{wd.get("value", "")}</span>'
            )
        elif t == "replace":
            parts.append(
                f'<span style="background:#fecaca; text-decoration:line-through; padding:1px 3px;">'
                f'{wd.get("old", "")}</span>'
                f'<span style="background:#bbf7d0; font-weight:bold; padding:1px 3px;">'
                f'{wd.get("new", "")}</span>'
            )
    return " ".join(parts)


def _render_studio_variants(backend_url: str):
    """My Variants tab — list, view, manage variant lifecycle."""
    st.markdown("**All Resume Variants**")

    # Stats
    try:
        resp = httpx.get(f"{backend_url}/studio/stats", timeout=5.0)
        if resp.status_code == 200:
            stats = resp.json()
            s1, s2, s3, s4, s5 = st.columns(5)
            s1.metric("Total", stats.get("total_variants", 0))
            by_status = stats.get("by_status", {})
            s2.metric("Draft", by_status.get("draft", 0))
            s3.metric("Finalized", by_status.get("finalized", 0))
            s4.metric("Applied", by_status.get("applied", 0))
            s5.metric("Interviews", stats.get("interviews", 0))

            # Bullet analytics
            ba = stats.get("bullet_analytics", {})
            if ba.get("total", 0) > 0:
                with st.expander("Bullet Validation Analytics"):
                    st.metric("Validation Pass Rate", f"{ba.get('validation_pass_rate', 0):.0%}")
                    st.metric("Avg Similarity", f"{ba.get('avg_similarity', 0):.2f}")
                    failures = ba.get("top_failure_reasons", {})
                    if any(v > 0 for v in failures.values()):
                        st.markdown("**Top failure reasons:**")
                        for reason, count in failures.items():
                            if count > 0:
                                st.markdown(f"- {reason}: {count}")
    except Exception:
        pass

    # List variants
    try:
        resp = httpx.get(f"{backend_url}/studio/variants", timeout=5.0)
        if resp.status_code == 200:
            variants = resp.json().get("variants", [])
            if not variants:
                st.info("No variants yet. Optimize some bullets first!")
                return

            for v in variants:
                with st.expander(
                    f"{v.get('jd_company', '?')} — {v.get('jd_title', '?')} "
                    f"| {v.get('status', '?')} | Score: {v.get('weighted_score', 0):.0%} "
                    f"| {v.get('created_at', '')[:10]}"
                ):
                    vc1, vc2, vc3 = st.columns(3)
                    vc1.write(f"**ID:** {v['id']}")
                    vc2.write(f"**Method:** {v.get('method', '?')}")
                    vc3.write(f"**Status:** {v.get('status', '?')}")

                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Match", f"{v.get('match_score', 0):.0%}")
                    mc2.metric("Coverage", f"{v.get('coverage_rate', 0):.0%}")
                    mc3.metric("Exact", v.get("exact_match_count", 0))
                    mc4.metric("Gaps", v.get("gap_count", 0))

                    # Actions
                    ac1, ac2, ac3 = st.columns(3)
                    with ac1:
                        if v.get("status") == "applied" and not v.get("interview_callback"):
                            if st.button("Got Interview", key=f"interview_{v['id']}"):
                                try:
                                    httpx.post(
                                        f"{backend_url}/studio/variants/{v['id']}/interview",
                                        timeout=5.0,
                                    )
                                    st.toast("Interview marked!")
                                    st.rerun()
                                except Exception:
                                    pass
                    with ac2:
                        if v.get("status") in ("finalized", "exported"):
                            if st.button("Mark Applied", key=f"apply_{v['id']}"):
                                try:
                                    httpx.post(
                                        f"{backend_url}/studio/variants/{v['id']}/transition",
                                        json={"new_status": "applied"},
                                        timeout=5.0,
                                    )
                                    st.toast("Marked as applied!")
                                    st.rerun()
                                except Exception:
                                    pass
                    with ac3:
                        if st.button("Delete", key=f"del_variant_{v['id']}"):
                            try:
                                httpx.delete(
                                    f"{backend_url}/studio/variants/{v['id']}",
                                    timeout=5.0,
                                )
                                st.toast("Variant deleted")
                                st.rerun()
                            except Exception:
                                pass
    except Exception:
        st.warning("Could not load variants. Is the backend running?")


def _render_studio_skill_transfer(backend_url: str):
    """Skill Transfer checker — test any two skills."""
    st.markdown("**Skill Transferability Checker**")
    st.caption("Check if two skills are transferable. Computed per-skill, platform-aware, abstraction-aware.")

    tc1, tc2, tc3 = st.columns([2, 2, 1])
    with tc1:
        source = st.text_input("Resume Skill", placeholder="e.g., PostgreSQL", key="transfer_src")
    with tc2:
        target = st.text_input("JD Skill", placeholder="e.g., MySQL", key="transfer_tgt")
    with tc3:
        st.write("")  # spacer
        st.write("")
        check_btn = st.button("Check", key="transfer_check")

    if check_btn and source and target:
        try:
            resp = httpx.post(
                f"{backend_url}/studio/skill-transfer",
                json={"source_skill": source, "target_skill": target},
                timeout=5.0,
            )
            if resp.status_code == 200:
                r = resp.json()
                if r.get("transferable"):
                    st.success(
                        f"**Transferable!** Score: {r['score']:.0%}\n\n"
                        f"{r.get('explanation', '')}"
                    )
                else:
                    st.error(
                        f"**Not transferable.** Score: {r['score']:.0%}\n\n"
                        f"{r.get('explanation', '')}"
                    )

                # Show metadata
                if r.get("source_meta"):
                    with st.expander("Skill Metadata"):
                        sm, tm = st.columns(2)
                        with sm:
                            st.json(r.get("source_meta"))
                        with tm:
                            st.json(r.get("target_meta"))
            else:
                st.error(f"Error: {resp.text}")
        except httpx.ConnectError:
            st.error("Backend not reachable.")
        except Exception as e:
            st.error(f"Error: {e}")

    # Gap analysis
    st.divider()
    st.markdown("**Full Gap Analysis**")
    ga1, ga2 = st.columns(2)
    with ga1:
        resume_skills_input = st.text_area(
            "Resume Skills (one per line)",
            height=150,
            placeholder="Python\nPostgreSQL\nDocker\nAWS",
            key="gap_resume",
        )
    with ga2:
        jd_skills_input = st.text_area(
            "JD Required Skills (one per line)",
            height=150,
            placeholder="Java\nMySQL\nKubernetes\nGCP",
            key="gap_jd",
        )

    if st.button("Analyze Gaps", key="gap_analyze"):
        resume_skills = [s.strip() for s in resume_skills_input.strip().split("\n") if s.strip()]
        jd_skills = [s.strip() for s in jd_skills_input.strip().split("\n") if s.strip()]
        if resume_skills and jd_skills:
            try:
                resp = httpx.post(
                    f"{backend_url}/studio/gap-analysis",
                    json={"resume_skills": resume_skills, "jd_skills": jd_skills},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    ga = resp.json()
                    g1, g2, g3 = st.columns(3)
                    g1.metric("Weighted Score", f"{ga.get('weighted_score', 0):.0%}")
                    g2.metric("Coverage", f"{ga.get('coverage_rate', 0):.0%}")
                    g3.metric("Exact Match Rate", f"{ga.get('match_rate', 0):.0%}")

                    if ga.get("exact_matches"):
                        st.markdown("**Exact:** " + skill_tags_html(ga["exact_matches"], "#22c55e"), unsafe_allow_html=True)
                    if ga.get("transferable"):
                        st.markdown("**Transferable:**")
                        for t in ga["transferable"]:
                            sc = t.get("score", 0)
                            st.markdown(
                                f'<span style="color:{score_color(sc)}; font-weight:bold;">'
                                f'{t["best_resume_skill"]} &rarr; {t["jd_skill"]} ({sc:.0%})</span>'
                                f' — {t.get("explanation", "")}',
                                unsafe_allow_html=True,
                            )
                    if ga.get("gaps"):
                        st.markdown("**Gaps:** " + skill_tags_html(ga["gaps"], "#ef4444"), unsafe_allow_html=True)
                else:
                    st.error(f"Error: {resp.text}")
            except Exception as e:
                st.error(f"Error: {e}")
        else:
            st.warning("Enter skills in both fields.")


# --- Signals ---
def render_signals(backend_url: str):
    """Signals tab — hiring predictions, company scores, layoff alerts."""
    st.subheader("Hiring Signals")
    st.caption("Company hiring scores from public signals: funding, expansions, layoffs. Updated every 6 hours.")

    sig_tab0, sig_tab1, sig_tab2, sig_tab3 = st.tabs(["Priority Jobs", "Company Scores", "Signal Feed", "Classify Text"])

    # ---- Priority Jobs ----
    with sig_tab0:
        st.markdown("**Smart application filter** — jobs ranked by resume fit + company hiring signal + sector relevance + timing.")

        pf1, pf2, pf3 = st.columns(3)
        with pf1:
            target_role = st.selectbox(
                "Target Role",
                ["backend", "data", "ml", "devops", "healthcare_tech", "fullstack"],
                key="sig_target_role",
            )
        with pf2:
            min_match = st.slider("Min resume match score", 0.0, 1.0, 0.60, 0.05, key="sig_min_match")
        with pf3:
            windows = st.multiselect(
                "Hiring windows",
                ["warm", "peak", "cooling", "unknown"],
                default=["warm", "peak", "unknown"],
                key="sig_windows",
            )

        if st.button("Get Priority Jobs", key="sig_priority_btn"):
            try:
                pr = requests.get(
                    f"{backend_url}/signals/priority-filter",
                    params={
                        "target_role": target_role,
                        "min_match_score": min_match,
                        "hiring_windows": ",".join(windows),
                        "exclude_layoff": True,
                        "limit": 20,
                    },
                    timeout=15,
                )
                pr.raise_for_status()
                priority_jobs = pr.json().get("priority_jobs", [])
            except Exception as e:
                st.error(f"Error: {e}")
                priority_jobs = []

            if not priority_jobs:
                st.info("No priority jobs found. Make sure jobs are scored (run Discovery Bot) and signal data is populated.")
            else:
                st.success(f"Found {len(priority_jobs)} priority jobs")
                _WINDOW_LABELS = {"warm": "🟡 Warm", "peak": "🟢 Peak", "cooling": "🔵 Cooling", "unknown": "⚪ Unknown"}
                _TREND_ICONS = {"up": "↑", "down": "↓", "stable": "→"}
                for job in priority_jobs:
                    priority = job.get("priority_score", 0.0)
                    match = job.get("relevance_score", 0.0)
                    signal = job.get("signal_score", 0.5)
                    window = job.get("hiring_window", "unknown")
                    trend = job.get("signal_trend", "stable")
                    company = job.get("company", "")
                    title = job.get("title", "")
                    url = job.get("url", "")
                    sector_boost = job.get("sector_boost", 0.0)

                    header = f"**{title}** @ {company} — Priority: {priority:.0%}"
                    with st.expander(header, expanded=False):
                        col_a, col_b, col_c, col_d = st.columns(4)
                        col_a.metric("Resume Match", f"{match:.0%}")
                        col_b.metric("Signal Score", f"{signal:.0%}")
                        col_c.metric("Window", _WINDOW_LABELS.get(window, window))
                        col_d.metric("Sector Boost", f"+{sector_boost:.0%}" if sector_boost > 0 else "0%")
                        st.caption(f"Trend: {_TREND_ICONS.get(trend, '')} {trend} | Sector: {job.get('sector_boost', 0):.0%}")
                        if url:
                            st.markdown(f"[Open job posting →]({url})")

    # ---- Company Scores ----
    with sig_tab1:
        try:
            sr = requests.get(f"{backend_url}/signals/stats", timeout=10)
            sr.raise_for_status()
            stats = sr.json()
        except Exception:
            stats = {}

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Companies Tracked", stats.get("companies_tracked", 0))
        c2.metric("Total Signals", stats.get("total_signals", 0))
        c3.metric("High-Score Companies", stats.get("high_score_companies", 0))
        c4.metric("Layoff Alerts", stats.get("layoff_alerts", 0))

        st.divider()

        col_top, col_avoid = st.columns(2)

        with col_top:
            st.markdown("**Likely Hiring (score ≥ 0.65)**")
            try:
                tr = requests.get(f"{backend_url}/signals/top", params={"min_score": 0.65, "limit": 10}, timeout=10)
                tr.raise_for_status()
                top_companies = tr.json().get("companies", [])
            except Exception:
                top_companies = []

            if not top_companies:
                st.info("No high-score companies yet.")
            else:
                import pandas as pd
                df_top = pd.DataFrame([{
                    "Company": c["company"],
                    "Score": f"{c['hiring_score']:.0%}",
                    "Trend": {"up": "↑", "down": "↓", "stable": "→"}.get(c["trend"], "→"),
                    "Signals": c["signal_count"],
                    "Last Signal": (c.get("last_signal_at") or "")[:10],
                } for c in top_companies])
                st.dataframe(df_top, use_container_width=True, hide_index=True)

        with col_avoid:
            st.markdown("**Avoid — Layoff Signals (score < 0.30)**")
            try:
                ar = requests.get(f"{backend_url}/signals/avoid", params={"max_score": 0.30, "limit": 10}, timeout=10)
                ar.raise_for_status()
                avoid_companies = ar.json().get("companies", [])
            except Exception:
                avoid_companies = []

            if not avoid_companies:
                st.success("No layoff alerts.")
            else:
                import pandas as pd
                df_avoid = pd.DataFrame([{
                    "Company": c["company"],
                    "Score": f"{c['hiring_score']:.0%}",
                    "Neg. Signals": c.get("negative_signals", 0),
                } for c in avoid_companies])
                st.dataframe(df_avoid, use_container_width=True, hide_index=True)

        # All companies table
        st.divider()
        st.markdown("**All tracked companies**")
        min_score_filter = st.slider("Min score", 0.0, 1.0, 0.0, 0.05, key="sig_min_score")
        try:
            cr = requests.get(f"{backend_url}/signals/companies", params={"min_score": min_score_filter, "limit": 100}, timeout=10)
            cr.raise_for_status()
            all_companies = cr.json().get("companies", [])
        except Exception:
            all_companies = []

        if all_companies:
            import pandas as pd
            df_all = pd.DataFrame([{
                "Company": c["company"],
                "Hiring Score": round(c["hiring_score"], 2),
                "Trend": {"up": "↑", "down": "↓", "stable": "→"}.get(c["trend"], "→"),
                "Signals": c["signal_count"],
                "Positive": c.get("positive_signals", 0),
                "Negative": c.get("negative_signals", 0),
                "Last Signal": (c.get("last_signal_at") or "")[:10],
            } for c in all_companies])
            st.dataframe(df_all, use_container_width=True, hide_index=True, height=350)

    # ---- Signal Feed ----
    with sig_tab2:  # noqa: E501
        f1, f2 = st.columns(2)
        with f1:
            company_filter = st.text_input("Company", "", key="sig_company_filter")
        with f2:
            type_filter = st.selectbox(
                "Signal Type",
                ["", "funding", "expansion", "acquisition", "contract", "layoff", "leadership", "product"],
                key="sig_type_filter",
            )

        try:
            params = {"limit": 50}
            if company_filter:
                params["company"] = company_filter
            if type_filter:
                params["signal_type"] = type_filter
            fr = requests.get(f"{backend_url}/signals/signals", params=params, timeout=10)
            fr.raise_for_status()
            feed_signals = fr.json().get("signals", [])
        except Exception as e:
            st.error(f"Error: {e}")
            feed_signals = []

        if not feed_signals:
            st.info("No signals found. Run the Signal Bot to fetch latest data.")
        else:
            _TYPE_ICONS = {
                "funding": "💰", "expansion": "📈", "acquisition": "🤝",
                "contract": "📋", "layoff": "🔴", "leadership": "👔",
                "product": "🚀", "noise": "💤",
            }
            for sig in feed_signals:
                icon = _TYPE_ICONS.get(sig.get("signal_type", "noise"), "")
                company = sig.get("company", "Unknown")
                stype = sig.get("signal_type", "noise")
                conf = sig.get("confidence", 0.0)
                date = (sig.get("discovered_at") or "")[:10]
                text = sig.get("signal_text", "")[:120]
                source = sig.get("source_name", "")
                st.markdown(f"{icon} **{company}** — `{stype}` ({conf:.0%}) — {date}")
                if text:
                    st.caption(f"{text}  _{source}_")

    # ---- Classify Text ----
    with sig_tab3:  # noqa: E501
        st.markdown("Test the signal classifier on any news headline.")
        classify_text_input = st.text_area("Paste headline or news text", height=100, key="sig_classify_input")
        company_hint = st.text_input("Company name (optional)", key="sig_company_hint")
        if st.button("Classify", key="sig_classify_btn"):
            if not classify_text_input.strip():
                st.warning("Enter some text.")
            else:
                try:
                    cr = requests.post(
                        f"{backend_url}/signals/classify",
                        json={"text": classify_text_input, "company_hint": company_hint},
                        timeout=10,
                    )
                    cr.raise_for_status()
                    result = cr.json()
                    st.success(f"Signal type: **{result['signal_type']}** ({result['confidence']:.0%} confidence)")
                    if result.get("company"):
                        st.write(f"Company detected: **{result['company']}**")
                    if result.get("amount"):
                        st.write(f"Amount: **{result['amount']}**")
                    if result.get("matched_keywords"):
                        st.write(f"Keywords matched: {', '.join(result['matched_keywords'])}")
                except Exception as e:
                    st.error(f"Error: {e}")


# --- Referral ---
def render_referral(backend_url: str):
    """Referral tab — find warm intro paths using CRM contacts."""
    st.subheader("Referral Discovery")
    st.caption("For any company you're targeting, find the warmest intro path in your network.")

    ref_tab1, ref_tab2 = st.tabs(["Find Referral Paths", "Coverage Stats"])

    # ----------------------------------------------------------------
    # Tab 1: Find referral paths for a company
    # ----------------------------------------------------------------
    with ref_tab1:
        col1, col2 = st.columns([2, 1])
        with col1:
            target_company = st.text_input("Target Company:", placeholder="e.g. Stripe, Anthropic, Google")
        with col2:
            job_title = st.text_input("Role (optional):", placeholder="e.g. Backend Engineer")

        col3, col4 = st.columns(2)
        with col3:
            top_n = st.slider("Max results", 1, 10, 5, key="ref_top_n")
        with col4:
            min_score = st.slider("Min score", 0.0, 1.0, 0.2, 0.05, key="ref_min_score")

        if st.button("Find Paths", key="find_ref_btn") and target_company:
            try:
                r = requests.get(
                    f"{backend_url}/referral/paths",
                    params={"company": target_company, "job_title": job_title,
                            "top_n": top_n, "min_score": min_score},
                    timeout=15,
                )
                if r.ok:
                    data = r.json()
                    paths = data.get("paths", [])
                    if not paths:
                        st.info(f"No referral contacts found for **{target_company}** (min score: {min_score:.0%}).\nAdd contacts to your CRM to improve coverage.")
                    else:
                        st.success(f"Found **{len(paths)}** referral path(s) to **{target_company}**")
                        for p in paths:
                            tier_icon = {"direct": "🟢", "former": "🔵", "industry": "🟡", "none": "⚪"}.get(p["tier"], "⚪")
                            with st.expander(
                                f"{tier_icon} {p['name']} ({p.get('company','?')}) — {p['score']:.0%}",
                                expanded=p["score"] >= 0.7,
                            ):
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.write(f"**Email:** {p['email']}")
                                    st.write(f"**Tier:** {p['tier']}")
                                    st.write(f"**Reasons:** {', '.join(p['reasons'])}")
                                with c2:
                                    st.metric("Score", f"{p['score']:.0%}")
                                    st.write(f"**Last contacted:** {p.get('last_contacted') or 'never'}")
                                    st.write(f"**Touchpoints:** {p.get('touchpoint_count', 0)}")
                                st.markdown("**Suggested ask:**")
                                st.info(p.get("suggested_ask", ""))
                else:
                    st.error(f"Error: {r.text}")
            except Exception as e:
                st.error(f"Request failed: {e}")

    # ----------------------------------------------------------------
    # Tab 2: Coverage stats
    # ----------------------------------------------------------------
    with ref_tab2:
        st.markdown("#### Network Coverage")
        try:
            r = requests.get(f"{backend_url}/referral/stats", timeout=10)
            stats = r.json() if r.ok else {}
        except Exception:
            stats = {}

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Contacts", stats.get("total_contacts", 0))
        m2.metric("With Company", stats.get("contacts_with_company", 0))
        m3.metric("Spoke Before", stats.get("contacts_spoken_to", 0))
        m4.metric("Unique Companies", stats.get("unique_companies", 0))

        companies = stats.get("top_companies", [])
        if companies:
            st.markdown("**Companies in your network:**")
            st.write(", ".join(companies[:30]))

        st.markdown("---")
        st.caption("Tip: Add contacts to CRM (CRM tab → Add Contact) to improve referral coverage.")


# --- Outreach ---
def render_outreach(backend_url: str):
    """Outreach tab — draft approval, A/B stats, sequence status."""
    st.subheader("Outreach Copilot")
    st.caption("Bot drafts personalized emails. You approve before anything sends.")

    out_tab1, out_tab2, out_tab3, out_tab4 = st.tabs(
        ["Pending Drafts", "Sequences", "A/B Stats", "New Sequence"]
    )

    # ----------------------------------------------------------------
    # Tab 1: Pending Drafts
    # ----------------------------------------------------------------
    with out_tab1:
        st.markdown("#### Drafts Awaiting Your Approval")
        st.info("Review each draft below. Nothing sends until you click **Approve**.")

        try:
            r = requests.get(f"{backend_url}/outreach/drafts?status=pending&limit=50", timeout=10)
            drafts = r.json().get("drafts", []) if r.ok else []
        except Exception:
            drafts = []

        if not drafts:
            st.success("No pending drafts — inbox clean!")
        else:
            for draft in drafts:
                with st.expander(
                    f"[{draft['stage'].upper()}] {draft['contact_email']} @ {draft.get('company','?')} — {draft['subject'][:60]}",
                    expanded=False,
                ):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        new_subject = st.text_input("Subject", value=draft["subject"], key=f"subj_{draft['id']}")
                        new_body = st.text_area("Body", value=draft["body"], height=200, key=f"body_{draft['id']}")
                    with col2:
                        st.metric("Stage", draft["stage"])
                        st.metric("Variant", draft.get("variant_id", "A"))
                        st.metric("Words", len(draft["body"].split()))
                        st.caption(f"Drafted by: {draft.get('drafted_by','template')}")

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("✅ Approve", key=f"approve_{draft['id']}"):
                            # Save edits then approve
                            if new_subject != draft["subject"] or new_body != draft["body"]:
                                requests.put(
                                    f"{backend_url}/outreach/drafts/{draft['id']}",
                                    json={"subject": new_subject, "body": new_body},
                                    timeout=10,
                                )
                            requests.post(f"{backend_url}/outreach/drafts/{draft['id']}/approve", timeout=10)
                            st.success("Approved!")
                            st.rerun()
                    with c2:
                        if st.button("❌ Reject", key=f"reject_{draft['id']}"):
                            requests.post(
                                f"{backend_url}/outreach/drafts/{draft['id']}/reject",
                                json={"notes": "rejected via dashboard"},
                                timeout=10,
                            )
                            st.warning("Rejected.")
                            st.rerun()
                    with c3:
                        if st.button("💾 Save Edits", key=f"edit_{draft['id']}"):
                            requests.put(
                                f"{backend_url}/outreach/drafts/{draft['id']}",
                                json={"subject": new_subject, "body": new_body},
                                timeout=10,
                            )
                            st.info("Saved.")

    # ----------------------------------------------------------------
    # Tab 2: Sequences
    # ----------------------------------------------------------------
    with out_tab2:
        st.markdown("#### Active Sequences")

        status_filter = st.selectbox("Filter by status", ["all", "active", "replied", "cold", "completed"], key="seq_status")
        try:
            url = f"{backend_url}/outreach/sequences?limit=100"
            if status_filter != "all":
                url += f"&status={status_filter}"
            r = requests.get(url, timeout=10)
            seqs = r.json().get("sequences", []) if r.ok else []
        except Exception:
            seqs = []

        if not seqs:
            st.info("No sequences yet.")
        else:
            seq_data = [
                {
                    "Contact": s.get("contact_email", ""),
                    "Company": s.get("company", ""),
                    "Stage": s.get("current_stage", ""),
                    "Status": s.get("status", ""),
                    "Next Due": (s.get("next_due_at") or "")[:10],
                    "Last Sent": (s.get("last_sent_at") or "")[:10],
                    "Replied": "✅" if s.get("reply_received") else "—",
                    "ID": s.get("id", ""),
                }
                for s in seqs
            ]
            st.dataframe(seq_data, use_container_width=True)

            st.markdown("---")
            mark_replied_id = st.text_input("Mark sequence as replied (enter sequence ID):", key="mark_replied_id")
            if st.button("Mark Replied", key="btn_mark_replied") and mark_replied_id:
                r = requests.post(f"{backend_url}/outreach/sequences/{mark_replied_id}/replied", timeout=10)
                if r.ok:
                    st.success("Marked as replied!")
                    st.rerun()
                else:
                    st.error(f"Error: {r.text}")

    # ----------------------------------------------------------------
    # Tab 3: A/B Stats
    # ----------------------------------------------------------------
    with out_tab3:
        st.markdown("#### A/B Variant Performance")
        try:
            r = requests.get(f"{backend_url}/outreach/variants", timeout=10)
            variants = r.json().get("variants", []) if r.ok else []
        except Exception:
            variants = []

        try:
            r2 = requests.get(f"{backend_url}/outreach/stats", timeout=10)
            stats = r2.json() if r2.ok else {}
        except Exception:
            stats = {}

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Active Sequences", stats.get("active_sequences", 0))
        m2.metric("Replied", stats.get("replied", 0))
        m3.metric("Pending Drafts", stats.get("pending_drafts", 0))
        m4.metric("Reply Rate", f"{stats.get('reply_rate', 0):.0%}")

        st.markdown("---")
        if not variants:
            st.info("No A/B data yet — variants are tracked after sends.")
        else:
            vdf = pd.DataFrame([
                {
                    "Stage": v["stage"],
                    "Variant": v["variant_label"],
                    "Template": v.get("template_name", ""),
                    "Sends": v["sends"],
                    "Replies": v["replies"],
                    "Reply Rate": f"{v['reply_rate']:.0%}",
                }
                for v in variants
            ])
            st.dataframe(vdf, use_container_width=True)

    # ----------------------------------------------------------------
    # Tab 4: New Sequence
    # ----------------------------------------------------------------
    with out_tab4:
        st.markdown("#### Start a New Outreach Sequence")
        st.caption("Enter a contact's details to begin a 3-touch sequence (Day 0 / Day 3 / Day 7).")

        with st.form("new_sequence_form"):
            contact_id = st.text_input("Contact ID (from CRM, or enter email as ID):")
            contact_email = st.text_input("Contact Email *:")
            contact_name = st.text_input("Contact Name:")
            company = st.text_input("Company:")
            job_title = st.text_input("Target Role / Job Title:")
            submitted = st.form_submit_button("Start Sequence")

        if submitted:
            if not contact_email:
                st.error("Contact email is required.")
            else:
                if not contact_id:
                    contact_id = contact_email
                try:
                    r = requests.post(
                        f"{backend_url}/outreach/sequences",
                        json={
                            "contact_id": contact_id,
                            "contact_email": contact_email,
                            "contact_name": contact_name,
                            "company": company,
                            "job_title": job_title,
                        },
                        timeout=10,
                    )
                    if r.ok:
                        st.success(f"Sequence started for {contact_email}!")
                        st.json(r.json())
                    else:
                        st.error(f"Error: {r.text}")
                except Exception as e:
                    st.error(f"Request failed: {e}")

        st.markdown("---")
        st.markdown("#### Generate Drafts Now")
        st.caption("Run the drafting cycle manually (normally runs daily via bot).")
        col1, col2 = st.columns(2)
        with col1:
            use_llm = st.checkbox("Use LLM for drafting", value=False, key="run_use_llm")
        with col2:
            dry_run = st.checkbox("Dry run (no saves)", value=True, key="run_dry_run")
        if st.button("Run Cycle", key="run_cycle_btn"):
            try:
                r = requests.post(
                    f"{backend_url}/outreach/run",
                    json={"dry_run": dry_run, "use_llm": use_llm},
                    timeout=30,
                )
                if r.ok:
                    result = r.json()
                    st.success(f"Cycle complete! Drafts generated: {result['stats']['drafts_generated']}")
                    st.json(result["stats"])
                else:
                    st.error(f"Error: {r.text}")
            except Exception as e:
                st.error(f"Request failed: {e}")


# --- CRM ---
def render_crm(backend_url: str):
    """CRM tab — contacts table, Today's Actions, thread history."""
    st.subheader("CRM — Contacts & Outreach")
    st.caption("Track recruiters, hiring managers, and all outreach activity.")

    crm_tab1, crm_tab2, crm_tab3 = st.tabs(["Today's Actions", "Contacts", "Add Contact"])

    # ---- Today's Actions ----
    with crm_tab1:
        try:
            r = requests.get(f"{backend_url}/crm/actions", timeout=10)
            r.raise_for_status()
            data = r.json()
            actions = data.get("actions", [])
        except Exception as e:
            st.error(f"Failed to load actions: {e}")
            actions = []

        # Stats row
        try:
            sr = requests.get(f"{backend_url}/crm/stats", timeout=10)
            sr.raise_for_status()
            stats = sr.json()
        except Exception:
            stats = {}

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Contacts", stats.get("total_contacts", 0))
        c2.metric("Follow-ups Due", stats.get("follow_ups_due", 0))
        c3.metric("Replied", stats.get("replied_count", 0))
        reply_rate = stats.get("reply_rate", 0)
        c4.metric("Reply Rate", f"{reply_rate:.0%}")

        st.divider()

        if not actions:
            st.success("No follow-ups due today.")
        else:
            st.markdown(f"**{len(actions)} follow-up(s) due**")
            for action in actions:
                can = action.get("can_contact", True)
                block = action.get("block_reason", "")
                label = action.get("action_label", "Follow up")
                stage = action.get("stage", "")
                name = action.get("name", "Unknown")
                company = action.get("company", "")
                email = action.get("email", "")
                fu_count = action.get("follow_up_count", 0)

                color = "🟢" if can else "🔴"
                with st.expander(f"{color} {name} @ {company} — {label} (f/u #{fu_count})", expanded=False):
                    cols = st.columns(3)
                    cols[0].write(f"**Email:** {email}")
                    cols[1].write(f"**Stage:** {stage}")
                    cols[2].write(f"**Next stage:** {action.get('recommended_next_stage', '—')}")
                    if not can:
                        st.warning(f"Blocked: {block}")
                    else:
                        new_stage = action.get("recommended_next_stage")
                        suggested = action.get("suggested_followup_date", "")
                        btn_key = f"advance_{action.get('conv_id', name)}"
                        if new_stage and st.button(f"Mark as {new_stage}", key=btn_key):
                            try:
                                ur = requests.patch(
                                    f"{backend_url}/crm/conversations/{action['conv_id']}/stage",
                                    json={"stage": new_stage, "next_follow_up": suggested},
                                    timeout=10,
                                )
                                if ur.status_code == 200:
                                    st.success(f"Stage updated to {new_stage}")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {ur.text}")
                            except Exception as e:
                                st.error(str(e))

    # ---- Contacts Table ----
    with crm_tab2:
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            status_filter = st.selectbox("Status", ["", "active", "cold", "blocked", "archived"], index=0, key="crm_status_filter")
        with filter_col2:
            company_filter = st.text_input("Company", "", key="crm_company_filter")
        with filter_col3:
            role_filter = st.selectbox("Role", ["", "recruiter", "hiring_manager", "engineer", "unknown"], index=0, key="crm_role_filter")

        try:
            params = {}
            if status_filter:
                params["status"] = status_filter
            if company_filter:
                params["company"] = company_filter
            if role_filter:
                params["role"] = role_filter
            cr = requests.get(f"{backend_url}/crm/contacts", params=params, timeout=10)
            cr.raise_for_status()
            contacts = cr.json().get("contacts", [])
        except Exception as e:
            st.error(f"Failed to load contacts: {e}")
            contacts = []

        if not contacts:
            st.info("No contacts found. Add one below or run the CRM bot to scan Gmail.")
        else:
            import pandas as pd
            df_crm = pd.DataFrame([{
                "Name": c.get("name", ""),
                "Email": c.get("email", ""),
                "Company": c.get("company", ""),
                "Role": c.get("role", ""),
                "Status": c.get("status", ""),
                "Touchpoints": c.get("total_touchpoints", 0),
                "Last Contact": (c.get("last_contacted_at") or "")[:10],
                "ID": c.get("id", ""),
            } for c in contacts])

            st.dataframe(df_crm.drop(columns=["ID"]), use_container_width=True, height=400)

            # Thread history for selected contact
            st.markdown("**View thread history:**")
            contact_options = {f"{c.get('name', '')} ({c.get('email', '')})": c["id"] for c in contacts}
            selected_contact = st.selectbox("Select contact", list(contact_options.keys()), key="crm_contact_select")
            if selected_contact:
                sel_id = contact_options[selected_contact]
                try:
                    tr = requests.get(f"{backend_url}/crm/contacts/{sel_id}/touchpoints", timeout=10)
                    tr.raise_for_status()
                    touchpoints = tr.json().get("touchpoints", [])
                except Exception:
                    touchpoints = []

                if touchpoints:
                    for tp in touchpoints:
                        direction = tp.get("direction", "outbound")
                        icon = "→" if direction == "outbound" else "←"
                        date = (tp.get("occurred_at") or "")[:10]
                        ttype = tp.get("type", "")
                        subject = tp.get("subject", "No subject")
                        summary = tp.get("summary", "")
                        st.markdown(f"`{date}` {icon} **{ttype}** — {subject}")
                        if summary:
                            st.caption(summary)
                else:
                    st.info("No touchpoints recorded.")

                # Archive button
                if st.button("Archive this contact", key=f"archive_{sel_id}"):
                    try:
                        dr = requests.delete(f"{backend_url}/crm/contacts/{sel_id}", timeout=10)
                        if dr.status_code == 200:
                            st.success("Contact archived.")
                            st.rerun()
                    except Exception as e:
                        st.error(str(e))

    # ---- Add Contact ----
    with crm_tab3:
        with st.form("add_contact_form"):
            ac1, ac2 = st.columns(2)
            with ac1:
                add_name = st.text_input("Name")
                add_email = st.text_input("Email *")
                add_company = st.text_input("Company")
            with ac2:
                add_role = st.selectbox("Role", ["unknown", "recruiter", "hiring_manager", "engineer"])
                add_notes = st.text_area("Notes", height=80)
                add_linkedin = st.text_input("LinkedIn URL")

            submitted = st.form_submit_button("Add Contact")
            if submitted:
                if not add_email:
                    st.error("Email is required.")
                else:
                    try:
                        ar = requests.post(
                            f"{backend_url}/crm/contacts",
                            json={
                                "email": add_email, "name": add_name,
                                "company": add_company, "role": add_role,
                                "notes": add_notes, "linkedin_url": add_linkedin,
                                "source": "manual",
                            },
                            timeout=10,
                        )
                        ar.raise_for_status()
                        st.success(f"Contact '{add_name or add_email}' added.")
                    except Exception as e:
                        st.error(f"Error: {e}")


# --- Job Discovery ---
def render_discovery(backend_url: str):
    """Render job discovery browser with score colors, skill gaps, JD analysis, and resume suggestion."""
    st.subheader("Job Discovery")
    st.caption("Browse jobs discovered from 260+ sources. Color-coded scores, skill gap analysis, and resume suggestions.")

    # Filters row 1
    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        category = st.selectbox("Role Category", [
            "", "backend", "frontend", "fullstack", "data_science", "data_engineer",
            "ml_engineer", "devops", "cloud", "mobile", "security",
            "business_analyst", "product_manager", "qa", "other",
        ], format_func=lambda x: "All Categories" if x == "" else x.replace("_", " ").title())
    with f2:
        exp_level = st.selectbox("Experience Level", [
            "", "entry", "mid", "senior", "lead", "staff", "principal",
        ], format_func=lambda x: "All Levels" if x == "" else x.title())
    with f3:
        years_range = st.select_slider("Years of Experience", options=[0, 1, 2, 3, 5, 7, 10, 15, 20],
                                        value=(0, 20))
    with f4:
        job_type = st.selectbox("Job Type", [
            "", "full_time", "part_time", "contract", "internship",
        ], format_func=lambda x: "All Types" if x == "" else x.replace("_", " ").title())
    with f5:
        remote = st.selectbox("Work Mode", [
            "", "remote", "hybrid", "onsite",
        ], format_func=lambda x: "All" if x == "" else x.title())

    # Filters row 2: keyword, company, status, sort
    f6, f7, f8, f9 = st.columns([2, 2, 1, 1])
    with f6:
        keyword = st.text_input("Keyword Search", placeholder="python, machine learning, AWS...")
    with f7:
        company_filter = st.text_input("Company", placeholder="Google, Stripe, Anthropic...")
    with f8:
        status_filter = st.selectbox("Status", ["", "new", "saved", "applied", "dismissed"],
                                      format_func=lambda x: "All" if x == "" else x.title())
    with f9:
        sort_by = st.selectbox("Sort By", ["score", "newest", "oldest", "company", "title"],
                                format_func=lambda x: {
                                    "score": "Best Match", "newest": "Newest First",
                                    "oldest": "Oldest First", "company": "Company A-Z",
                                    "title": "Title A-Z",
                                }.get(x, x))

    # Pagination controls
    page_col1, page_col2 = st.columns([1, 5])
    with page_col1:
        page = st.number_input("Page", min_value=1, value=1, step=1, key="disc_page")
    per_page = 50

    # Fetch from discovery API
    try:
        params = {
            "category": category, "experience_level": exp_level,
            "years_min": years_range[0], "years_max": years_range[1],
            "job_type": job_type, "remote_type": remote,
            "keyword": keyword, "company": company_filter,
            "status": status_filter, "sort_by": sort_by,
            "page": page, "per_page": per_page,
        }
        params = {k: v for k, v in params.items() if v}  # Remove empty
        resp = httpx.get(f"{backend_url}/discovery/jobs", params=params, timeout=10.0)

        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total", 0)
            disc_jobs = data.get("jobs", [])
            total_pages = max(1, (total + per_page - 1) // per_page)

            st.caption(f"Showing {len(disc_jobs)} of {total:,} discovered jobs (page {page}/{total_pages})")

            if disc_jobs:
                disc_df = pd.DataFrame(disc_jobs)

                # Add score color column for display
                if "match_score" in disc_df.columns:
                    disc_df["score_display"] = disc_df["match_score"].apply(
                        lambda x: f"{'***' if x >= 0.7 else '**' if x >= 0.4 else '*'} {x:.0%}"
                    )

                # Main table with clickable URLs
                display_cols = ["title", "company", "url", "category", "experience_level",
                                "remote_type", "match_score", "skills", "status"]
                available = [c for c in display_cols if c in disc_df.columns]

                st.dataframe(
                    disc_df[available],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "title": st.column_config.TextColumn("Role", width="large"),
                        "company": st.column_config.TextColumn("Company", width="medium"),
                        "url": st.column_config.LinkColumn("Apply Link", display_text="Open", width="small"),
                        "category": st.column_config.TextColumn("Category", width="small"),
                        "experience_level": st.column_config.TextColumn("Level", width="small"),
                        "remote_type": st.column_config.TextColumn("Remote", width="small"),
                        "match_score": st.column_config.ProgressColumn(
                            "Score", min_value=0.0, max_value=1.0, format="%.0%%", width="small",
                        ),
                        "skills": st.column_config.TextColumn("Skills", width="large"),
                        "status": st.column_config.TextColumn("Status", width="small"),
                    },
                )

                # Pagination navigation
                nav_cols = st.columns(5)
                with nav_cols[1]:
                    if page > 1:
                        if st.button("Previous Page", key="disc_prev"):
                            st.session_state["disc_page"] = page - 1
                            st.rerun()
                with nav_cols[3]:
                    if page < total_pages:
                        if st.button("Next Page", key="disc_next"):
                            st.session_state["disc_page"] = page + 1
                            st.rerun()

                # --- Job Details + Apply Section ---
                st.divider()
                st.subheader("Job Actions")

                # Build readable job labels for the selector
                job_labels = {}
                if "id" in disc_df.columns:
                    for _, row in disc_df.iterrows():
                        score = row.get("match_score", 0)
                        indicator = "+" if score >= 0.7 else "~" if score >= 0.4 else "-"
                        label = f"[{indicator}{score:.0%}] {row.get('title', '?')} @ {row.get('company', '?')}"
                        job_labels[label] = row["id"]

                sel_col, act_col, parse_col = st.columns([3, 2, 1])
                with sel_col:
                    selected_label = st.selectbox(
                        "Select Job", list(job_labels.keys()),
                        index=None, placeholder="Pick a job to view details or apply...",
                        key="disc_sel",
                    )
                    selected = job_labels.get(selected_label) if selected_label else None

                with act_col:
                    btn_cols = st.columns(3)
                    with btn_cols[0]:
                        save_btn = st.button("Save", key="disc_save", disabled=not selected)
                    with btn_cols[1]:
                        apply_btn = st.button("Apply", key="disc_apply", type="primary", disabled=not selected)
                    with btn_cols[2]:
                        dismiss_btn = st.button("Dismiss", key="disc_dismiss", disabled=not selected)

                with parse_col:
                    if st.button("Parse Unparsed", key="disc_parse"):
                        try:
                            r = httpx.post(f"{backend_url}/discovery/parse?limit=50", timeout=30.0)
                            if r.status_code == 200:
                                st.success(f"Parsed {r.json().get('parsed', 0)} jobs")
                                st.rerun()
                        except Exception as e:
                            st.error(str(e))

                # Handle button actions
                if selected and save_btn:
                    try:
                        r = httpx.patch(f"{backend_url}/discovery/jobs/{selected}",
                                       json={"status": "saved"}, timeout=10.0)
                        if r.status_code == 200:
                            st.success("Saved!")
                            st.rerun()
                    except Exception as e:
                        st.error(str(e))

                if selected and apply_btn:
                    try:
                        r = httpx.post(f"{backend_url}/discovery/jobs/{selected}/apply", timeout=10.0)
                        if r.status_code == 200:
                            result = r.json()
                            job_url = result.get("url", "")
                            tracked = result.get("tracked", False)
                            st.success(
                                f"Applied to {result.get('title', '')} at {result.get('company', '')}! "
                                f"{'Also added to tracker.' if tracked else ''}"
                            )
                            if job_url:
                                st.markdown(f"**[Open Application Page]({job_url})**")

                            # Suggest best resume
                            _show_resume_suggestion(backend_url, result.get("title", ""), "")

                            st.rerun()
                    except Exception as e:
                        st.error(str(e))

                if selected and dismiss_btn:
                    try:
                        r = httpx.patch(f"{backend_url}/discovery/jobs/{selected}",
                                       json={"status": "dismissed"}, timeout=10.0)
                        if r.status_code == 200:
                            st.success("Dismissed.")
                            st.rerun()
                    except Exception as e:
                        st.error(str(e))

                # Show job details + JD analysis when selected
                if selected:
                    _render_job_detail(backend_url, selected)

            else:
                st.info("No discovered jobs match your filters. Run the Discovery Bot first.")
        else:
            st.warning(f"Discovery API returned {resp.status_code}")

        # Stats
        try:
            stats_resp = httpx.get(f"{backend_url}/discovery/stats", timeout=5.0)
            if stats_resp.status_code == 200:
                stats = stats_resp.json()
                st.divider()
                s1, s2, s3, s4, s5 = st.columns(5)
                s1.metric("Total Discovered", f"{stats.get('total', 0):,}")
                s2.metric("Parsed", f"{stats.get('parsed', 0):,}")
                s3.metric("Unparsed", f"{stats.get('unparsed', 0):,}")
                s4.metric("Categories", len(stats.get("by_category", {})))
                by_status = stats.get("by_status", {})
                s5.metric("Saved", by_status.get("saved", 0))
        except Exception:
            pass

    except httpx.ConnectError:
        st.error("Backend not reachable.")
    except Exception as e:
        st.error(f"Error: {e}")


def _render_job_detail(backend_url: str, job_id: str):
    """Render expanded job detail with JD analysis, skill gaps, and resume suggestion."""
    try:
        detail_resp = httpx.get(f"{backend_url}/discovery/jobs/{job_id}", timeout=5.0)
        if detail_resp.status_code != 200:
            return
        job = detail_resp.json()

        st.divider()
        st.subheader(f"{job.get('title', '')} — {job.get('company', '')}")

        # Row 1: metadata with score badge
        score = job.get("match_score", 0)
        detail_cols = st.columns(5)
        detail_cols[0].markdown(f"**Score:** {score_badge(score)}", unsafe_allow_html=True)
        detail_cols[1].markdown(f"**Category:** {job.get('category', 'N/A').replace('_', ' ').title()}")
        detail_cols[2].markdown(f"**Level:** {job.get('experience_level', 'N/A').title()}")
        detail_cols[3].markdown(f"**Type:** {job.get('job_type', 'N/A').replace('_', ' ').title()}")
        detail_cols[4].markdown(f"**Remote:** {job.get('remote_type', 'N/A').title()}")

        info_cols = st.columns(4)
        info_cols[0].markdown(f"**Location:** {job.get('location', 'N/A')}")
        info_cols[1].markdown(f"**Source:** {job.get('source_name', 'N/A')}")
        info_cols[2].markdown(f"**Status:** {job.get('status', 'new').title()}")
        info_cols[3].markdown(f"**First seen:** {job.get('first_seen_at', 'N/A')[:10]}")

        # Skills display
        skills_str = job.get("skills", "")
        if skills_str:
            skill_list = [s.strip() for s in skills_str.split(",") if s.strip()]
            st.markdown(f"**Skills:** {skill_tags_html(skill_list)}", unsafe_allow_html=True)

        # Apply link (always prominent)
        if job.get("url"):
            st.markdown(f"**[Open Job Posting]({job['url']})**")

        # JD Analysis panel
        description = job.get("description", "")
        if description:
            with st.expander("JD Analysis", expanded=False):
                _render_jd_analysis(backend_url, job.get("title", ""), description)

            with st.expander("Full Description", expanded=False):
                st.write(description[:5000])

        # Resume suggestion
        with st.expander("Best Resume for This Job", expanded=False):
            _show_resume_suggestion(backend_url, job.get("title", ""), description)

    except Exception:
        pass


def _render_jd_analysis(backend_url: str, title: str, description: str):
    """Render JD normalization analysis inside an expander."""
    try:
        resp = httpx.post(
            f"{backend_url}/analysis/normalize-jd",
            json={"title": title, "description": description},
            timeout=15.0,
        )
        if resp.status_code != 200:
            st.caption("JD analysis unavailable")
            return

        jd = resp.json()

        # Confidence badge
        st.markdown(
            f"**JD Confidence:** {confidence_badge(jd.get('confidence', 0))}",
            unsafe_allow_html=True,
        )

        # Title normalization
        col1, col2, col3 = st.columns(3)
        col1.markdown(f"**Normalized title:** {jd.get('title_norm', 'N/A').replace('_', ' ').title()}")
        col2.markdown(f"**Seniority:** {jd.get('seniority_level', 'N/A').title()}")
        col3.markdown(f"**Location type:** {jd.get('location_type', 'N/A').title()}")

        # Must-have vs nice-to-have skills
        must_have = jd.get("must_have_skills", [])
        nice_to_have = jd.get("nice_to_have_skills", [])

        if must_have:
            st.markdown(
                f"**Must-have skills:** {skill_tags_html(must_have, '#ef4444')}",
                unsafe_allow_html=True,
            )
        if nice_to_have:
            st.markdown(
                f"**Nice-to-have:** {skill_tags_html(nice_to_have, '#6b7280')}",
                unsafe_allow_html=True,
            )

        # Responsibilities
        responsibilities = jd.get("responsibilities", [])
        if responsibilities:
            st.markdown("**Key responsibilities:**")
            for r in responsibilities[:6]:
                st.markdown(f"- {r}")

        # Skill categories
        cats = jd.get("skill_categories", {})
        if cats:
            st.markdown("**Skill categories:**")
            cat_text = " | ".join(f"**{k}:** {', '.join(v)}" for k, v in cats.items() if v)
            st.markdown(cat_text)

    except Exception as e:
        st.caption(f"JD analysis error: {e}")


def _show_resume_suggestion(backend_url: str, title: str, description: str):
    """Show best resume suggestion for a job."""
    if not title:
        st.caption("No job title to score against.")
        return

    try:
        resp = httpx.post(
            f"{backend_url}/analysis/suggest-resume",
            json={"title": title, "description": description or title},
            timeout=20.0,
        )
        if resp.status_code != 200:
            st.caption("Resume suggestion unavailable")
            return

        data = resp.json()
        suggestion = data.get("suggestion")
        if not suggestion:
            st.info("No resumes uploaded yet. Go to 'My Resumes' tab to upload your first resume.")
            return

        st.markdown(
            f"**Best resume:** {suggestion['resume_name']} "
            f"— {score_badge(suggestion['match_score'])}",
            unsafe_allow_html=True,
        )

        if suggestion.get("missing_must_haves"):
            st.markdown(
                f"**Missing skills:** {skill_tags_html(suggestion['missing_must_haves'], '#ef4444')}",
                unsafe_allow_html=True,
            )

        if suggestion.get("matched_skills"):
            st.markdown(
                f"**Matched:** {skill_tags_html(suggestion['matched_skills'][:10], '#22c55e')}",
                unsafe_allow_html=True,
            )

        st.caption(f"Recommendation: {suggestion.get('recommended_emphasis', 'N/A').replace('_', ' ').title()}")

        # Show all resumes if more than one
        all_scores = data.get("all_scores", [])
        if len(all_scores) > 1:
            st.markdown("**All resumes ranked:**")
            for i, s in enumerate(all_scores):
                marker = " (best)" if i == 0 else ""
                st.markdown(
                    f"{i+1}. {s['resume_name']}: {score_badge(s['match_score'])}{marker}",
                    unsafe_allow_html=True,
                )

    except Exception:
        st.caption("Resume suggestion: backend unreachable")


# --- My Resumes ---
def render_my_resumes(backend_url: str):
    """Render resume management tab — upload, parse, view skill inventory, set default."""
    st.subheader("My Resumes")
    st.caption("Upload your resumes to get skill inventories, match scores, and personalized suggestions when applying.")

    # Upload section
    with st.expander("Upload New Resume", expanded=True):
        with st.form("upload_resume_form"):
            resume_name = st.text_input(
                "Resume Name *",
                placeholder="e.g., Backend Engineer Resume, ML Resume v2...",
            )
            resume_text = st.text_area(
                "Paste Resume Text *",
                height=300,
                placeholder="Paste the full text of your resume here...",
            )
            is_default = st.checkbox("Set as default resume", value=False)
            upload_btn = st.form_submit_button("Upload & Parse", type="primary")

        if upload_btn:
            if not resume_name or not resume_text.strip():
                st.error("Resume name and text are required.")
            else:
                with st.spinner("Parsing resume..."):
                    try:
                        resp = httpx.post(
                            f"{backend_url}/analysis/resumes/upload",
                            json={
                                "name": resume_name,
                                "raw_text": resume_text,
                                "is_default": is_default,
                            },
                            timeout=30.0,
                        )
                        if resp.status_code == 200:
                            st.success(f"Resume '{resume_name}' uploaded and parsed!")
                            st.rerun()
                        else:
                            st.error(f"Error: {resp.status_code} — {resp.text}")
                    except httpx.ConnectError:
                        st.error("Backend not reachable.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    st.divider()

    # List existing resumes
    try:
        resp = httpx.get(f"{backend_url}/analysis/resumes", timeout=10.0)
        if resp.status_code != 200:
            st.warning("Could not fetch resumes.")
            return

        resumes = resp.json().get("resumes", [])
        if not resumes:
            st.info("No resumes uploaded yet. Upload your first resume above.")
            return

        st.subheader(f"Stored Resumes ({len(resumes)})")

        for resume in resumes:
            default_marker = " (DEFAULT)" if resume.get("is_default") else ""
            with st.expander(f"**{resume['name']}**{default_marker} — {resume.get('total_bullets', 0)} bullets, {resume.get('total_metrics', 0)} metrics"):
                # Skill inventory
                skills = resume.get("skill_inventory", [])
                if skills:
                    st.markdown(
                        f"**Skill Inventory ({len(skills)}):** {skill_tags_html(skills)}",
                        unsafe_allow_html=True,
                    )

                # Skill categories
                categories = resume.get("skill_categories", {})
                if categories:
                    st.markdown("**Skills by Category:**")
                    for cat, cat_skills in sorted(categories.items()):
                        if cat_skills:
                            st.markdown(
                                f"- **{cat.replace('_', ' ').title()}:** {skill_tags_html(cat_skills, '#6b7280')}",
                                unsafe_allow_html=True,
                            )

                # Stats
                stat_cols = st.columns(4)
                stat_cols[0].metric("Skills", len(skills))
                stat_cols[1].metric("Bullets", resume.get("total_bullets", 0))
                stat_cols[2].metric("Metrics", resume.get("total_metrics", 0))
                stat_cols[3].metric("Categories", len(categories))

                # Actions
                action_cols = st.columns(3)
                with action_cols[0]:
                    if not resume.get("is_default"):
                        if st.button("Set as Default", key=f"def_{resume['id']}"):
                            try:
                                r = httpx.patch(
                                    f"{backend_url}/analysis/resumes/{resume['id']}/default",
                                    timeout=5.0,
                                )
                                if r.status_code == 200:
                                    st.success("Set as default!")
                                    st.rerun()
                            except Exception as e:
                                st.error(str(e))
                    else:
                        st.caption("This is your default resume")

                with action_cols[1]:
                    # View full parsed data
                    if st.button("View Full Parse", key=f"view_{resume['id']}"):
                        try:
                            detail = httpx.get(
                                f"{backend_url}/analysis/resumes/{resume['id']}",
                                timeout=5.0,
                            ).json()
                            parsed = detail.get("parsed_json", {})
                            if parsed:
                                st.json(parsed)
                        except Exception as e:
                            st.error(str(e))

                with action_cols[2]:
                    if st.button("Delete", key=f"del_{resume['id']}"):
                        try:
                            r = httpx.delete(
                                f"{backend_url}/analysis/resumes/{resume['id']}",
                                timeout=5.0,
                            )
                            if r.status_code == 200:
                                st.success("Deleted!")
                                st.rerun()
                        except Exception as e:
                            st.error(str(e))

                st.caption(f"Uploaded: {resume.get('created_at', 'N/A')[:10]}")

    except httpx.ConnectError:
        st.error("Backend not reachable.")
    except Exception as e:
        st.error(f"Error: {e}")


# --- Today (Supervisor) ---
def render_today(backend_url: str):
    """Unified command center — Today's priority actions from all systems."""
    st.subheader("Today's Actions")
    st.caption("Priority-ranked actions from all systems — outreach, jobs, CRM, signals, referrals.")

    # ----------------------------------------------------------------
    # System stats header
    # ----------------------------------------------------------------
    try:
        r = requests.get(f"{backend_url}/supervisor/stats", timeout=10)
        stats = r.json() if r.ok else {}
    except Exception:
        stats = {}

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("To Apply", stats.get("to_apply", 0))
    c2.metric("Applied", stats.get("applied", 0))
    c3.metric("Interviewing", stats.get("interviewing", 0))
    c4.metric("Hot Companies", stats.get("hot_companies", 0))
    c5.metric("Pending Drafts", stats.get("outreach_pending_drafts", 0))
    c6.metric("CRM Contacts", stats.get("crm_contacts", 0))

    st.divider()

    # ----------------------------------------------------------------
    # Today's actions
    # ----------------------------------------------------------------
    today_tab, funnel_tab, avoid_tab = st.tabs(["Priority Actions", "Pipeline Funnel", "Avoid List"])

    with today_tab:
        col_left, col_right = st.columns([3, 1])
        with col_right:
            max_actions = st.slider("Max actions", 5, 30, 15, key="today_max")
            inc_jobs     = st.checkbox("Jobs",     True, key="inc_jobs")
            inc_signals  = st.checkbox("Signals",  True, key="inc_signals")
            inc_refs     = st.checkbox("Referrals",True, key="inc_refs")
            if st.button("Refresh", key="today_refresh"):
                st.rerun()

        with col_left:
            try:
                r = requests.get(
                    f"{backend_url}/supervisor/today",
                    params={"max_total": max_actions, "include_jobs": inc_jobs,
                            "include_signals": inc_signals, "include_referrals": inc_refs},
                    timeout=15,
                )
                actions = r.json().get("actions", []) if r.ok else []
            except Exception:
                actions = []

            if not actions:
                st.info("No actions right now — everything is up to date!")
            else:
                # Color map per action type
                _TYPE_COLOR = {
                    "outreach_draft": "#7c3aed",
                    "crm_reply":      "#059669",
                    "crm_followup":   "#2563eb",
                    "job_apply":      "#d97706",
                    "signal_hot":     "#dc2626",
                    "referral_path":  "#0891b2",
                }
                _TYPE_ICON = {
                    "outreach_draft": "✉️",
                    "crm_reply":      "💬",
                    "crm_followup":   "🔁",
                    "job_apply":      "🎯",
                    "signal_hot":     "⚡",
                    "referral_path":  "🤝",
                }
                for i, action in enumerate(actions):
                    atype  = action.get("action_type", "")
                    icon   = _TYPE_ICON.get(atype, "•")
                    color  = _TYPE_COLOR.get(atype, "#6b7280")
                    pct    = int(action.get("priority", 0) * 100)
                    label  = action.get("action_label", "View")

                    with st.container():
                        cols = st.columns([0.05, 0.55, 0.20, 0.20])
                        with cols[0]:
                            st.markdown(f"<span style='font-size:1.4em'>{icon}</span>",
                                        unsafe_allow_html=True)
                        with cols[1]:
                            st.markdown(
                                f"**{action['title']}**  \n"
                                f"<span style='color:{color};font-size:0.85em'>{action['description']}</span>",
                                unsafe_allow_html=True,
                            )
                        with cols[2]:
                            st.progress(pct, text=f"{pct}%")
                        with cols[3]:
                            btn_key = f"action_{i}_{atype}"
                            if atype == "outreach_draft":
                                draft_id = action.get("data", {}).get("draft_id")
                                if draft_id and st.button(label, key=btn_key):
                                    requests.post(f"{backend_url}/outreach/drafts/{draft_id}/approve", timeout=10)
                                    st.success("Approved!")
                                    st.rerun()
                            elif atype == "job_apply":
                                url = action.get("data", {}).get("url", "")
                                if url:
                                    st.markdown(f"[{label}]({url})")
                                else:
                                    st.write(label)
                            else:
                                st.write(f"_{action.get('source','')}_")
                        st.markdown("---")

    with funnel_tab:
        st.markdown("#### Application Pipeline")
        try:
            r = requests.get(f"{backend_url}/supervisor/funnel", timeout=10)
            funnel = r.json() if r.ok else {}
        except Exception:
            funnel = {}

        if funnel:
            stages = ["discovered", "to_apply", "applied", "interviewing", "offer"]
            labels = ["Discovered", "To Apply", "Applied", "Interviewing", "Offer"]
            values = [funnel.get(s, 0) for s in stages]
            top = max(values) if values else 1
            cols = st.columns(len(stages))
            for col, label, val in zip(cols, labels, values):
                col.metric(label, val)
                col.progress(int(val / top * 100) if top > 0 else 0)

            # Conversion rates
            st.markdown("---")
            st.markdown("**Conversion rates:**")
            if funnel.get("discovered", 0) > 0:
                d = funnel["discovered"]
                apply_rate = funnel.get("to_apply", 0) / d
                applied_rate = funnel.get("applied", 0) / d
                interview_rate = funnel.get("applied", 1) and funnel.get("interviewing", 0) / max(funnel.get("applied", 1), 1)
                st.write(f"Shortlisted: {apply_rate:.0%} | Applied: {applied_rate:.0%} | "
                         f"Interview conversion: {interview_rate:.0%}")

    with avoid_tab:
        st.markdown("#### Companies to Avoid")
        st.caption("Companies with layoff signals or low hiring score — deprioritize these.")
        try:
            r = requests.get(f"{backend_url}/supervisor/avoid?limit=20", timeout=10)
            avoid = r.json().get("companies", []) if r.ok else []
        except Exception:
            avoid = []

        if not avoid:
            st.success("No layoff alerts — all tracked companies look healthy!")
        else:
            for co in avoid:
                st.markdown(
                    f"❌ **{co['company']}** — score {co.get('hiring_score',0):.0%} "
                    f"({co.get('signal_count',0)} signals, {co.get('negative_signals',0)} negative)"
                )


# --- Main ---
def main():
    backend_url = render_sidebar()
    jobs = fetch_jobs(backend_url)

    if not jobs:
        st.title("JobPilot Dashboard")
        st.info("No jobs tracked yet. Add your first job from the sidebar, Chrome extension, or CLI.")
        # Still show discovery, resumes, and bot controls even with no tracked jobs
        tab_disc, tab_resumes, tab_bots = st.tabs(["Job Discovery", "My Resumes", "Bot Controls"])
        with tab_disc:
            render_discovery(backend_url)
        with tab_resumes:
            render_my_resumes(backend_url)
        with tab_bots:
            render_bot_controls()
        return

    df = pd.DataFrame(jobs)

    for col in ["status", "source", "date_applied", "company", "role", "notes", "app_id"]:
        if col not in df.columns:
            df[col] = ""

    st.title("JobPilot Dashboard")

    # Main tabs — 14 tabs
    (tab_today, tab_overview, tab_disc, tab_table, tab_my_resumes,
     tab_cover, tab_resume, tab_crm, tab_referral, tab_signals, tab_outreach, tab_bots, tab_rules, tab_sites) = st.tabs(
        ["Today ★", "Overview", "Job Discovery", "Applications", "My Resumes",
         "Cover Letter", "Resume Studio", "CRM", "Referral", "Signals", "Outreach", "Bot Controls", "Email Rules", "Sites & Sources"]
    )

    with tab_today:
        render_today(backend_url)

    with tab_overview:
        render_kpis(df)
        st.divider()
        render_charts(df)

    with tab_disc:
        render_discovery(backend_url)

    with tab_table:
        render_table(df, backend_url)

    with tab_my_resumes:
        render_my_resumes(backend_url)

    with tab_cover:
        render_cover_letter(df, backend_url)

    with tab_resume:
        render_resume_tailor(df, backend_url)

    with tab_crm:
        render_crm(backend_url)

    with tab_referral:
        render_referral(backend_url)

    with tab_signals:
        render_signals(backend_url)

    with tab_outreach:
        render_outreach(backend_url)

    with tab_bots:
        render_bot_controls()

    with tab_rules:
        render_rules()

    with tab_sites:
        render_sites(df)


if __name__ == "__main__":
    main()
