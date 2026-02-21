"""Health check endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from backend.dependencies import get_sheets_client
from src.models import HealthResponse
from src.sheets.client import SheetsClient

router = APIRouter(tags=["health"])

_HEARTBEAT_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "bot_heartbeat.json"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Basic health check — always returns OK if the server is running."""
    return HealthResponse(status="ok")


@router.get("/bot-status")
async def bot_status() -> dict:
    """Return per-bot last-run time, status, and last error from heartbeat file."""
    if not _HEARTBEAT_FILE.exists():
        return {"bots": {}, "note": "No runs recorded yet — start the orchestrator"}
    try:
        data = json.loads(_HEARTBEAT_FILE.read_text(encoding="utf-8"))
        return {"bots": data}
    except Exception as exc:
        return {"bots": {}, "error": str(exc)}


@router.get("/ready", response_model=HealthResponse)
async def ready(
    sheets: SheetsClient = Depends(get_sheets_client),
) -> HealthResponse:
    """Readiness check — verifies Google Sheets connection."""
    connected = sheets.is_connected()
    return HealthResponse(
        status="ready" if connected else "not_ready",
        sheets_connected=connected,
    )
