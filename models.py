"""
models.py — Pydantic request/response schemas for all 6 endpoints.

Covers: /v1/context, /v1/tick, /v1/reply, /v1/healthz, /v1/metadata, /v1/teardown
Including 409 (stale_version) and 400 (invalid_scope) error shapes.
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── /v1/context ──────────────────────────────────────────────────────────────

class ContextPushRequest(BaseModel):
    scope: str                           # category | merchant | customer | trigger
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str

class ContextPushAccepted(BaseModel):
    accepted: bool = True
    ack_id: str
    stored_at: str

class ContextPushRejected(BaseModel):
    accepted: bool = False
    reason: str                          # stale_version | invalid_scope
    current_version: Optional[int] = None
    details: Optional[str] = None


# ── /v1/tick ─────────────────────────────────────────────────────────────────

class TickRequest(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)

class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: str                         # vera | merchant_on_behalf
    trigger_id: str
    template_name: str
    template_params: list[str] = Field(default_factory=list)
    body: str
    cta: str                             # open_ended | binary_yes_stop | multi_choice_slot | none
    suppression_key: str
    rationale: str

class TickResponse(BaseModel):
    actions: list[TickAction] = Field(default_factory=list)


# ── /v1/reply ────────────────────────────────────────────────────────────────

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str                       # merchant | customer
    message: str
    received_at: str
    turn_number: int

class ReplySend(BaseModel):
    action: str = "send"
    body: str
    cta: str = "open_ended"
    rationale: str = ""

class ReplyWait(BaseModel):
    action: str = "wait"
    wait_seconds: int
    rationale: str = ""

class ReplyEnd(BaseModel):
    action: str = "end"
    rationale: str = ""


# ── /v1/healthz ──────────────────────────────────────────────────────────────

class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: dict[str, int]


# ── /v1/metadata ─────────────────────────────────────────────────────────────

class MetadataResponse(BaseModel):
    team_name: str
    team_members: list[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str


# ── /v1/teardown ─────────────────────────────────────────────────────────────

class TeardownResponse(BaseModel):
    wiped: bool = True
