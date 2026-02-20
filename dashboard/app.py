"""Job Automation Dashboard — Streamlit + Plotly.

Full-featured dashboard with:
- KPI cards (total, applied, replied, interviews, offers, rejections)
- Status distribution, source breakdown, application timeline charts
- Response rate & conversion funnel
- Job table with filtering, sorting, inline status updates
- Bot Control Center — start/stop individual bots
- Email Classification Rules — view, add, modify rules
- Sites/Sources tracker

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
            "desc": f"Scans {30}+ job sources (RSS feeds, APIs, career pages) every {settings.discovery_bot_interval_minutes} min",
            "schedule": f"Every {settings.discovery_bot_interval_minutes} minutes",
            "command": "python -m bots.discovery_bot.run",
            "dry_run": "python -m bots.discovery_bot.run --dry-run",
        },
        {
            "name": "Tracker Bot",
            "desc": "CLI tool for manually adding/managing job applications",
            "schedule": "Manual (CLI only)",
            "command": "python -m bots.tracker_bot.run",
            "dry_run": "python -m bots.tracker_bot.run list",
        },
        {
            "name": "Orchestrator",
            "desc": "Central scheduler that runs all bots automatically",
            "schedule": "Continuous",
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


# --- Resume Tailor ---
def render_resume_tailor(df: pd.DataFrame, backend_url: str):
    """Render resume tailor UI."""
    st.subheader("Resume Tailor")
    st.caption("Paste your resume + a job description. AI will restructure your resume to maximize relevance and ATS score.")

    col1, col2 = st.columns([1, 1])

    with col1:
        # Select from tracked jobs or enter manually
        job_options = ["-- Enter manually --"] + [
            f"{row['company']} — {row['role']}" for _, row in df.iterrows()
            if row.get("company")
        ]
        selected_job = st.selectbox("Select a tracked job", options=job_options, key="rt_job")

        if selected_job != "-- Enter manually --":
            parts = selected_job.split(" — ", 1)
            company = parts[0] if len(parts) > 0 else ""
            role = parts[1] if len(parts) > 1 else ""
        else:
            company = ""
            role = ""

        company = st.text_input("Company", value=company, key="rt_company")
        role = st.text_input("Role", value=role, key="rt_role")
        job_description = st.text_area(
            "Job Description",
            height=200,
            placeholder="Paste the full job description...",
            key="rt_jd",
        )
        resume_text = st.text_area(
            "Your Current Resume (paste full text)",
            height=250,
            placeholder="Paste your entire resume here...",
            key="rt_resume",
        )
        focus_skills = st.text_input(
            "Priority skills to emphasize (comma-separated, optional)",
            placeholder="e.g., Python, AWS, machine learning, system design",
        )
        tailor_btn = st.button("Tailor Resume", type="primary")

    with col2:
        st.markdown("**Tailored Resume:**")
        if tailor_btn:
            if not company or not role:
                st.error("Company and Role are required.")
            elif not job_description:
                st.error("Job description is required.")
            elif not resume_text:
                st.error("Resume text is required.")
            else:
                with st.spinner("Tailoring your resume (this may take 15-30 seconds)..."):
                    try:
                        skills_list = [s.strip() for s in focus_skills.split(",") if s.strip()] if focus_skills else []
                        resp = httpx.post(
                            f"{backend_url}/tailor-resume",
                            json={
                                "company": company,
                                "role": role,
                                "job_description": job_description,
                                "resume_text": resume_text,
                                "focus_skills": skills_list,
                            },
                            timeout=120.0,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            st.text_area(
                                "Tailored Resume",
                                value=data["tailored_resume"],
                                height=400,
                                label_visibility="collapsed",
                            )
                            st.caption(f"Tokens used: {data.get('tokens_used', 0)}")
                            if data.get("changes_summary"):
                                st.markdown("**Changes made:**")
                                st.markdown(data["changes_summary"])
                            st.code(data["tailored_resume"], language=None)
                        else:
                            st.error(f"Error: {resp.status_code} — {resp.text}")
                    except httpx.ConnectError:
                        st.error("Backend not reachable. Start it: `uvicorn backend.main:app --reload`")
                    except Exception as e:
                        st.error(f"Error: {e}")


# --- Main ---
def main():
    backend_url = render_sidebar()
    jobs = fetch_jobs(backend_url)

    if not jobs:
        st.title("JobPilot Dashboard")
        st.info("No jobs tracked yet. Add your first job from the sidebar, Chrome extension, or CLI.")
        render_bot_controls()
        return

    df = pd.DataFrame(jobs)

    for col in ["status", "source", "date_applied", "company", "role", "notes", "app_id"]:
        if col not in df.columns:
            df[col] = ""

    st.title("JobPilot Dashboard")

    # Main tabs
    tab_overview, tab_table, tab_cover, tab_resume, tab_bots, tab_rules, tab_sites = st.tabs(
        ["Overview", "Applications", "Cover Letter", "Resume Tailor", "Bot Controls", "Email Rules", "Sites & Sources"]
    )

    with tab_overview:
        render_kpis(df)
        st.divider()
        render_charts(df)

    with tab_table:
        render_table(df, backend_url)

    with tab_cover:
        render_cover_letter(df, backend_url)

    with tab_resume:
        render_resume_tailor(df, backend_url)

    with tab_bots:
        render_bot_controls()

    with tab_rules:
        render_rules()

    with tab_sites:
        render_sites(df)


if __name__ == "__main__":
    main()
