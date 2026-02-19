"""Job Automation Dashboard — Streamlit + Plotly.

Provides a visual overview of all tracked job applications:
- KPI cards (total, applied, interviews, offers, rejections)
- Status distribution pie chart
- Applications timeline
- Source breakdown bar chart
- Full job table with filtering, sorting, and inline status updates

Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.config import get_settings

# --- Page Config ---
st.set_page_config(
    page_title="Job Tracker Dashboard",
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

    st.sidebar.title("Job Tracker")

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
        notes = st.text_area("Notes", height=60)
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

    # Refresh button
    if st.sidebar.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    return backend_url


# --- KPI Cards ---
def render_kpis(df: pd.DataFrame):
    """Render KPI metric cards."""
    total = len(df)
    applied = len(df[df["status"] == "Applied"])
    interviews = len(df[df["status"] == "Interview"])
    offers = len(df[df["status"] == "Offer"])
    rejected = len(df[df["status"] == "Rejected"])
    no_reply = len(df[df["status"] == "No Reply"])

    cols = st.columns(6)
    cols[0].metric("Total", total)
    cols[1].metric("Applied", applied)
    cols[2].metric("Interviews", interviews)
    cols[3].metric("Offers", offers)
    cols[4].metric("Rejected", rejected)
    cols[5].metric("No Reply", no_reply)


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
            colors = [STATUS_COLORS.get(s, "#94a3b8") for s in status_counts["status"]]

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

    # Timeline Chart
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
                    height=250,
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


# --- Main ---
def main():
    backend_url = render_sidebar()
    jobs = fetch_jobs(backend_url)

    if not jobs:
        st.title("Job Tracker Dashboard")
        st.info("No jobs tracked yet. Add your first job from the sidebar, Chrome extension, or CLI.")
        return

    df = pd.DataFrame(jobs)

    # Fill missing columns with empty strings
    for col in ["status", "source", "date_applied", "company", "role", "notes", "app_id"]:
        if col not in df.columns:
            df[col] = ""

    st.title("Job Tracker Dashboard")
    render_kpis(df)
    st.divider()
    render_charts(df)
    st.divider()
    render_table(df, backend_url)


if __name__ == "__main__":
    main()
