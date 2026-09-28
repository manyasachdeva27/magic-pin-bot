"""
bot.py — FastAPI app for the Vera AI Challenge.

Pure compose() shim following the skeleton in testing-brief §7.
5 endpoints + teardown:
  GET  /v1/healthz
  GET  /v1/metadata
  POST /v1/context
  POST /v1/tick
  POST /v1/reply
  POST /v1/teardown
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import (
    TEAM_NAME, TEAM_MEMBERS, CONTACT_EMAIL, BOT_VERSION,
    LLM_PROVIDER, TICK_BUDGET_S, REPLY_BUDGET_S,
)
from config import _get_model
from models import (
    ContextPushRequest, TickRequest, ReplyRequest,
    HealthzResponse, MetadataResponse, TeardownResponse,
)
from context_store import ContextStore
from conversation_state import ConversationStateStore
from suppression import SuppressionStore
from composer import compose_action, reset_for_tick, teardown as composer_teardown
from conversation_handlers import handle_reply

# ── Setup ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("vera")

app = FastAPI(title="Vera Bot", version=BOT_VERSION)
START_TIME = time.time()

# Global stores (single-worker, in-memory)
ctx_store = ContextStore()
conv_store = ConversationStateStore()
sup_store = SuppressionStore()


# ── GET /v1/healthz ──────────────────────────────────────────────────────────

@app.get("/v1/healthz")
async def healthz():
    return HealthzResponse(
        status="ok",
        uptime_seconds=int(time.time() - START_TIME),
        contexts_loaded=ctx_store.counts(),
    )


# ── GET / ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Vera Bot is running! The API endpoints are at /v1/..."}


# ── GET /v1/metadata ─────────────────────────────────────────────────────────

@app.get("/v1/metadata")
async def metadata():
    model = _get_model("compose") or "template-only"
    return MetadataResponse(
        team_name=TEAM_NAME,
        team_members=TEAM_MEMBERS,
        model=f"{LLM_PROVIDER}/{model}",
        approach="trigger-anchored composer with fact-sheet provenance, "
                 "per-merchant state, circuit-breaker fallback templates",
        contact_email=CONTACT_EMAIL,
        version=BOT_VERSION,
        submitted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ── POST /v1/context ─────────────────────────────────────────────────────────

@app.post("/v1/context")
async def push_context(body: ContextPushRequest):
    status, detail, current_ver = ctx_store.push(
        body.scope, body.context_id, body.version, body.payload,
    )

    if status == "invalid":
        return JSONResponse(
            status_code=400,
            content={"accepted": False, "reason": detail, "details": f"scope must be one of: category, merchant, customer, trigger"},
        )

    if status == "stale":
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version", "current_version": current_ver},
        )

    # Accepted
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "accepted": True,
        "ack_id": detail,  # detail is the ack_id on success
        "stored_at": now_iso,
    }


# ── POST /v1/tick ────────────────────────────────────────────────────────────

@app.post("/v1/tick")
async def tick(body: TickRequest):
    tick_start = time.time()
    reset_for_tick()

    actions = []

    for trigger_id in body.available_triggers:
        # Budget check
        elapsed = time.time() - tick_start
        if elapsed > TICK_BUDGET_S:
            log.warning("tick_budget_exhausted after %.1fs, %d actions", elapsed, len(actions))
            break

        # Get trigger
        trigger = ctx_store.get_trigger(trigger_id)
        if not trigger:
            continue

        merchant_id = trigger.get("merchant_id")
        if not merchant_id:
            continue

        # Get merchant + category
        merchant = ctx_store.get_merchant(merchant_id)
        if not merchant:
            continue
        category_slug = merchant.get("category_slug", "")
        category = ctx_store.get_category(category_slug) if category_slug else None
        if not category:
            continue

        # Suppression check
        suppression_key = trigger.get("suppression_key", "")
        can_send, reason = sup_store.can_send(merchant_id, suppression_key)
        if not can_send:
            log.info("suppressed trigger=%s merchant=%s reason=%s", trigger_id, merchant_id, reason)
            continue

        # Compose
        action = compose_action(trigger, merchant, category, ctx_store)
        if action:
            actions.append(action)
            # Record send
            sup_store.record_send(merchant_id, suppression_key)
            conv_store.record_bot_send(
                merchant_id=merchant_id,
                conversation_id=action["conversation_id"],
                body=action["body"],
                trigger_id=trigger_id,
                trigger_kind=trigger.get("kind", "unknown"),
            )

    elapsed = time.time() - tick_start
    log.info("tick actions=%d elapsed=%.1fs triggers=%d",
             len(actions), elapsed, len(body.available_triggers))

    return {"actions": actions}


# ── POST /v1/reply ───────────────────────────────────────────────────────────

@app.post("/v1/reply")
async def reply(body: ReplyRequest):
    reply_start = time.time()

    # Resolve merchant_id from request or conversation mapping
    merchant_id = body.merchant_id
    if not merchant_id:
        merchant_id = conv_store.merchant_for_conv(body.conversation_id)
    if not merchant_id:
        # Unknown conversation_id with no merchant_id — handle gracefully
        log.warning("reply unknown conv=%s no merchant_id", body.conversation_id)
        return {"action": "end", "rationale": "Unknown conversation, no merchant context available."}

    result = handle_reply(
        conversation_id=body.conversation_id,
        merchant_id=merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role,
        message=body.message,
        turn_number=body.turn_number,
        context_store=ctx_store,
        conv_store=conv_store,
    )

    # If opt-out, also suppress in suppression store
    if result.get("action") == "end" or (
        result.get("action") == "send" and
        any(w in result.get("body", "").lower() for w in ["sorry", "won't", "apolog"])
    ):
        from intent_classifier import classify, Intent
        if classify(body.message) == Intent.OPT_OUT:
            sup_store.opt_out_merchant(merchant_id)

    elapsed = time.time() - reply_start
    log.info("reply action=%s conv=%s elapsed=%.1fs", result.get("action"), body.conversation_id, elapsed)

    return result


# ── POST /v1/teardown ────────────────────────────────────────────────────────

@app.post("/v1/teardown")
async def teardown():
    ctx_store.wipe()
    conv_store.wipe()
    sup_store.wipe()
    composer_teardown()
    log.info("teardown complete")
    return TeardownResponse(wiped=True)


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    log.info("vera bot starting provider=%s version=%s", LLM_PROVIDER, BOT_VERSION)
