"""Outreach API router.

Endpoints:
  GET  /outreach/drafts                    — List pending drafts
  GET  /outreach/drafts/{id}               — Get draft
  POST /outreach/drafts/{id}/approve       — Approve draft
  POST /outreach/drafts/{id}/reject        — Reject draft
  PUT  /outreach/drafts/{id}               — Edit draft
  POST /outreach/sequences                 — Start a new sequence
  GET  /outreach/sequences                 — List sequences
  GET  /outreach/sequences/{id}            — Get sequence + drafts
  POST /outreach/sequences/{id}/replied    — Mark as replied
  POST /outreach/run                       — Trigger draft generation cycle
  GET  /outreach/variants                  — A/B variant stats
  POST /outreach/variants/reply            — Record a reply for variant
  GET  /outreach/stats                     — Overall stats
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/outreach", tags=["outreach"])


class StartSequenceRequest(BaseModel):
    contact_id: str
    contact_email: str
    contact_name: str = ""
    company: str = ""
    job_title: str = ""


class RejectDraftRequest(BaseModel):
    notes: str = ""


class EditDraftRequest(BaseModel):
    subject: str | None = None
    body: str | None = None


class RecordReplyRequest(BaseModel):
    variant_id: str
    stage: str


class RunCycleRequest(BaseModel):
    dry_run: bool = False
    use_llm: bool = False


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

@router.get("/drafts")
def list_drafts(
    status: str = Query("pending"),
    limit: int = Query(50, ge=1, le=200),
):
    from src.outreach.database import list_drafts as _list
    return {"drafts": _list(status=status, limit=limit)}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str):
    from src.outreach.database import get_draft as _get
    d = _get(draft_id)
    if not d:
        raise HTTPException(404, f"Draft '{draft_id}' not found")
    return d


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: str):
    from src.outreach.database import approve_draft as _approve
    d = _approve(draft_id)
    if not d:
        raise HTTPException(404, f"Draft '{draft_id}' not found")
    return d


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, req: RejectDraftRequest):
    from src.outreach.database import reject_draft as _reject, get_draft
    _reject(draft_id, notes=req.notes)
    return {"status": "rejected", "draft_id": draft_id}


@router.put("/drafts/{draft_id}")
def edit_draft(draft_id: str, req: EditDraftRequest):
    from src.outreach.database import edit_draft as _edit
    d = _edit(draft_id, subject=req.subject, body=req.body)
    if not d:
        raise HTTPException(404, f"Draft '{draft_id}' not found")
    return d


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

@router.post("/sequences")
def start_sequence(req: StartSequenceRequest):
    from src.outreach.database import start_sequence as _start
    return _start(
        contact_id=req.contact_id,
        contact_email=req.contact_email,
        contact_name=req.contact_name,
        company=req.company,
        job_title=req.job_title,
    )


@router.get("/sequences")
def list_sequences(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    from src.outreach.database import list_sequences as _list
    return {"sequences": _list(status=status, limit=limit)}


@router.get("/sequences/{seq_id}")
def get_sequence(seq_id: str):
    from src.outreach.database import get_sequence as _get, list_drafts
    seq = _get(seq_id)
    if not seq:
        raise HTTPException(404, f"Sequence '{seq_id}' not found")
    drafts = list_drafts(status="pending") + list_drafts(status="approved") + list_drafts(status="sent")
    seq_drafts = [d for d in drafts if d["sequence_id"] == seq_id]
    return {**seq, "drafts": seq_drafts}


@router.post("/sequences/{seq_id}/replied")
def mark_replied(seq_id: str):
    from src.outreach.database import mark_sequence_replied
    mark_sequence_replied(seq_id)
    return {"status": "replied", "sequence_id": seq_id}


# ---------------------------------------------------------------------------
# Run cycle
# ---------------------------------------------------------------------------

@router.post("/run")
def run_cycle(req: RunCycleRequest):
    from src.outreach.sequences import run_sequence_cycle
    stats = run_sequence_cycle(dry_run=req.dry_run, use_llm=req.use_llm)
    return {"status": "ok", "stats": stats}


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------

@router.get("/variants")
def get_variants():
    from src.outreach.database import get_variant_stats
    return {"variants": get_variant_stats()}


@router.post("/variants/reply")
def record_reply(req: RecordReplyRequest):
    from src.outreach.database import record_variant_reply
    record_variant_reply(variant_id=req.variant_id, stage=req.stage)
    return {"status": "recorded"}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats():
    from src.outreach.database import get_outreach_stats
    return get_outreach_stats()
