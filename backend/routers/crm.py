"""CRM API router — contacts, conversations, touchpoints, actions.

Endpoints:
  GET    /crm/contacts                  — List contacts (filterable)
  POST   /crm/contacts                  — Upsert contact
  GET    /crm/contacts/{id}             — Get contact details
  PATCH  /crm/contacts/{id}/status      — Update contact status
  DELETE /crm/contacts/{id}             — Archive contact (soft delete)
  GET    /crm/contacts/{id}/touchpoints — Get touchpoint history
  GET    /crm/conversations             — List conversations
  POST   /crm/conversations             — Create conversation
  PATCH  /crm/conversations/{id}/stage  — Update stage + next follow-up
  POST   /crm/touchpoints               — Log touchpoint manually
  GET    /crm/actions                   — Today's actions
  GET    /crm/stats                     — CRM stats
  POST   /crm/merge                     — Merge duplicate contacts
  GET    /crm/duplicates                — Scan for duplicates
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/crm", tags=["crm"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class ContactUpsertRequest(BaseModel):
    email: str
    name: str = ""
    company: str = ""
    role: str = "unknown"
    source: str = "manual"
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    linkedin_url: str = ""


class ContactStatusRequest(BaseModel):
    status: str  # active, cold, blocked, archived


class ConversationCreateRequest(BaseModel):
    contact_id: str
    subject: str = ""
    job_id: str | None = None
    stage: str = "initial"
    direction: str = "outbound"


class ConversationStageRequest(BaseModel):
    stage: str
    next_follow_up: str | None = None  # ISO date string


class TouchpointRequest(BaseModel):
    contact_id: str
    type: str  # email_sent, email_received, note, call, meeting
    subject: str = ""
    summary: str = ""
    raw_snippet: str = ""
    conversation_id: str | None = None
    gmail_thread_id: str = ""
    gmail_message_id: str = ""
    direction: str = "outbound"
    sentiment: str = "neutral"
    occurred_at: str | None = None


class MergeRequest(BaseModel):
    primary_id: str
    secondary_id: str


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@router.get("/contacts")
def list_contacts(
    status: str | None = Query(None),
    company: str | None = Query(None),
    role: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    from src.crm.database import list_contacts as _list
    contacts = _list(status=status, company=company, role=role, limit=limit, offset=offset)
    return {"contacts": contacts, "count": len(contacts)}


@router.post("/contacts")
def upsert_contact(req: ContactUpsertRequest):
    from src.crm.database import upsert_contact as _upsert
    contact = _upsert(
        email=req.email,
        name=req.name,
        company=req.company,
        role=req.role,
        source=req.source,
        tags=req.tags,
        notes=req.notes,
        linkedin_url=req.linkedin_url,
    )
    return contact


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: str):
    from src.crm.database import get_contact as _get, get_conversations, get_touchpoints
    contact = _get(contact_id)
    if not contact:
        raise HTTPException(404, f"Contact '{contact_id}' not found")
    conversations = get_conversations(contact_id=contact_id)
    touchpoints = get_touchpoints(contact_id=contact_id, limit=20)
    return {
        **contact,
        "conversations": conversations,
        "recent_touchpoints": touchpoints,
    }


@router.patch("/contacts/{contact_id}/status")
def update_status(contact_id: str, req: ContactStatusRequest):
    from src.crm.database import update_contact_status
    ok = update_contact_status(contact_id, req.status)
    if not ok:
        raise HTTPException(400, f"Invalid status '{req.status}' or contact not found")
    return {"contact_id": contact_id, "status": req.status}


@router.delete("/contacts/{contact_id}")
def archive_contact(contact_id: str):
    """Soft delete — archives the contact."""
    from src.crm.database import update_contact_status
    ok = update_contact_status(contact_id, "archived")
    if not ok:
        raise HTTPException(404, f"Contact '{contact_id}' not found")
    return {"archived": contact_id}


@router.get("/contacts/{contact_id}/touchpoints")
def get_touchpoints(
    contact_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    from src.crm.database import get_touchpoints as _get
    return {"touchpoints": _get(contact_id=contact_id, limit=limit)}


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@router.get("/conversations")
def list_conversations(
    contact_id: str | None = Query(None),
    stage: str | None = Query(None),
    active_only: bool = Query(True),
):
    from src.crm.database import get_conversations
    convs = get_conversations(contact_id=contact_id, stage=stage, active_only=active_only)
    return {"conversations": convs, "count": len(convs)}


@router.post("/conversations")
def create_conversation(req: ConversationCreateRequest):
    from src.crm.database import create_conversation as _create, get_contact
    contact = get_contact(req.contact_id)
    if not contact:
        raise HTTPException(404, f"Contact '{req.contact_id}' not found")
    conv = _create(
        contact_id=req.contact_id,
        subject=req.subject,
        job_id=req.job_id,
        stage=req.stage,
        direction=req.direction,
    )
    return conv


@router.patch("/conversations/{conv_id}/stage")
def update_stage(conv_id: str, req: ConversationStageRequest):
    from src.crm.database import update_conversation_stage
    ok = update_conversation_stage(conv_id, req.stage, req.next_follow_up)
    if not ok:
        raise HTTPException(400, f"Invalid stage '{req.stage}' or conversation not found")
    return {"conv_id": conv_id, "stage": req.stage, "next_follow_up": req.next_follow_up}


# ---------------------------------------------------------------------------
# Touchpoints
# ---------------------------------------------------------------------------

@router.post("/touchpoints")
def log_touchpoint(req: TouchpointRequest):
    from src.crm.database import log_touchpoint as _log, get_contact
    contact = get_contact(req.contact_id)
    if not contact:
        raise HTTPException(404, f"Contact '{req.contact_id}' not found")
    tp = _log(
        contact_id=req.contact_id,
        type=req.type,
        subject=req.subject,
        summary=req.summary,
        raw_snippet=req.raw_snippet,
        conversation_id=req.conversation_id,
        gmail_thread_id=req.gmail_thread_id,
        gmail_message_id=req.gmail_message_id,
        direction=req.direction,
        sentiment=req.sentiment,
        occurred_at=req.occurred_at,
    )
    return tp


# ---------------------------------------------------------------------------
# Today's actions
# ---------------------------------------------------------------------------

@router.get("/actions")
def get_actions():
    """Get today's follow-up actions with cooldown enforcement."""
    from bots.crm_bot.run import get_actions_summary
    actions = get_actions_summary()
    return {"actions": actions, "count": len(actions)}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats():
    from src.crm.database import get_crm_stats
    return get_crm_stats()


# ---------------------------------------------------------------------------
# Dedup + merge
# ---------------------------------------------------------------------------

@router.get("/duplicates")
def find_duplicates(contact_id: str | None = Query(None)):
    """Scan for duplicate contacts. If contact_id given, find dupes for that contact."""
    if contact_id:
        from src.crm.dedup import find_duplicates as _find
        return {"duplicates": _find(contact_id)}
    else:
        from src.crm.dedup import scan_all_duplicates
        return {"duplicates": scan_all_duplicates()}


@router.post("/merge")
def merge_contacts(req: MergeRequest):
    """Merge secondary contact into primary. Secondary is archived."""
    from src.crm.dedup import merge_contacts as _merge
    try:
        result = _merge(req.primary_id, req.secondary_id)
        return {"merged": result, "archived_secondary": req.secondary_id}
    except ValueError as e:
        raise HTTPException(400, str(e))
