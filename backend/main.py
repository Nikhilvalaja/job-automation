"""FastAPI application entry point.

Central API hub for the entire job automation ecosystem.
All bots, extension, and dashboard communicate through this backend.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure project root is on sys.path for imports
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.middleware import RequestLoggingMiddleware
from backend.routers import health, jobs
from src.utils.logging import get_logger

logger = get_logger("backend.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Job Automation Backend starting up...")
    yield
    logger.info("Job Automation Backend shutting down...")


app = FastAPI(
    title="Job Automation API",
    description="Central API for the job application automation ecosystem",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow extension, dashboard, and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging
app.add_middleware(RequestLoggingMiddleware)

# Routers
app.include_router(health.router)
app.include_router(jobs.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all error handler to prevent 500 crashes from leaking details."""
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."},
    )
