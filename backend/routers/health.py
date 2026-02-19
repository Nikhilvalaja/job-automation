"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.dependencies import get_sheets_client
from src.models import HealthResponse
from src.sheets.client import SheetsClient

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Basic health check — always returns OK if the server is running."""
    return HealthResponse(status="ok")


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
