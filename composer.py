"""
composer.py — Core composition engine.

Pipeline: fact_sheet → cache_check → LLM (with deadline) → provenance_verify → fallback
Circuit breaker: 3 consecutive LLM failures → all subsequent calls use template fallback.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from config import llm_complete, ACTION_DEADLINE_S, CB_FAILURE_THRESHOLD, LLM_PROVIDER
from fact_sheet import build_fact_sheet
from templates.fallback_templates import render_fallback
from trigger_router import (
    should_skip_trigger, get_send_as, get_composition_prompt,
    get_reply_prompt, SYSTEM_PROMPT, reality_check,
)
from provenance_verifier import verify as verify_provenance
from response_cache import ResponseCache
from consent_resolver import can_contact_customer, resolve_audience
from language_resolver import resolve_language

log = logging.getLogger("vera")


class CircuitBreaker:
    """Simple circuit breaker for LLM calls."""

    def __init__(self, threshold: int = CB_FAILURE_THRESHOLD):
        self.threshold = threshold
        self.consecutive_failures = 0
        self.is_open = False

    def record_success(self):
        self.consecutive_failures = 0
        self.is_open = False

    def record_failure(self):
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.is_open = True
            log.warning("circuit_breaker OPEN after %d failures", self.consecutive_failures)

    def reset(self):
        """Reset at the start of each tick."""
        self.consecutive_failures = 0
        self.is_open = False


# Module-level singletons
_cache = ResponseCache()
_circuit = CircuitBreaker()


def reset_for_tick():
    """Reset circuit breaker at the start of each tick."""
    _circuit.reset()


def compose_action(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    category: dict[str, Any],
    context_store: Any,
) -> Optional[dict[str, Any]]:
    """
    Compose a single tick action for a trigger.

    Returns: action dict ready for TickResponse, or None to skip.
    """
    trigger_id = trigger.get("id", "")
    trigger_kind = trigger.get("kind", "unknown")
    merchant_id = trigger.get("merchant_id", "")
    customer_id = trigger.get("customer_id")

    # ── 1. Should we skip? ───────────────────────────────────────────────
    skip, reason = should_skip_trigger(trigger, merchant)
    if skip:
        log.info("skip_trigger id=%s reason=%s", trigger_id, reason)
        return None

    # ── 2. Customer consent check (customer-scoped triggers) ─────────────
    customer = None
    audience = None
    if customer_id:
        customer = context_store.get_customer(customer_id)
        if not customer:
            log.info("skip_trigger id=%s reason=customer_not_found", trigger_id)
            return None
        ok, reason = can_contact_customer(customer, trigger_kind)
        if not ok:
            log.info("skip_trigger id=%s reason=%s", trigger_id, reason)
            return None
        audience = resolve_audience(customer)
        if not audience.can_contact:
            log.info("skip_trigger id=%s reason=%s", trigger_id, audience.block_reason)
            return None

    # ── 3. Build fact sheet ──────────────────────────────────────────────
    perf_delta = context_store.get_perf_delta(merchant_id)
    fact_sheet, allowed_numbers, allowed_entities = build_fact_sheet(
        trigger=trigger,
        merchant=merchant,
        category=category,
        customer=customer,
        perf_delta=perf_delta,
        audience_info=audience,
    )

    # ── 4. Resolve language ──────────────────────────────────────────────
    lang = resolve_language(merchant, customer=customer)

    # ── 5. Try cache ─────────────────────────────────────────────────────
    cached = _cache.get(fact_sheet)
    if cached:
        return _build_action(
            cached["body"], cached["cta"], cached.get("template_name", "cached"),
            trigger, merchant_id, customer_id,
            f"Cached response (deterministic)"
        )

    # ── 6. Check placeholder / circuit breaker / none mode ───────────────
    payload = trigger.get("payload", {})
    is_placeholder = payload.get("placeholder", False)

    use_template = (
        is_placeholder
        or _circuit.is_open
        or LLM_PROVIDER == "none"
    )

    if use_template:
        body, cta, template_name, rationale = render_fallback(
            trigger, merchant, category, customer, audience
        )
        _cache.put(fact_sheet, {"body": body, "cta": cta, "template_name": template_name})
        return _build_action(body, cta, template_name, trigger, merchant_id, customer_id, rationale)

    # ── 7. LLM composition with deadline ─────────────────────────────────
    start = time.time()
    prompt = get_composition_prompt(fact_sheet, trigger_kind, lang)

    try:
        llm_body = llm_complete(SYSTEM_PROMPT, prompt, role="compose")
        elapsed = time.time() - start

        if llm_body is None or elapsed > ACTION_DEADLINE_S:
            raise TimeoutError(f"LLM took {elapsed:.1f}s or returned None")

        _circuit.record_success()

        # Clean up LLM output
        llm_body = llm_body.strip().strip('"').strip("'")

        # ── 8. Provenance verify ─────────────────────────────────────────
        taboos = category.get("voice", {}).get("vocab_taboo",
                 category.get("voice", {}).get("taboos", []))
        passed, violations = verify_provenance(llm_body, allowed_numbers, allowed_entities, taboos)

        if passed:
            cta = _infer_cta(trigger_kind, llm_body)
            _cache.put(fact_sheet, {"body": llm_body, "cta": cta, "template_name": f"llm_{trigger_kind}_v1"})
            return _build_action(
                llm_body, cta, f"llm_{trigger_kind}_v1",
                trigger, merchant_id, customer_id,
                f"LLM composed ({elapsed:.1f}s). Provenance verified."
            )
        else:
            # Provenance failed → fallback
            log.warning("provenance_failed trigger=%s violations=%s", trigger_id, violations[:3])
            body, cta, template_name, rationale = render_fallback(
                trigger, merchant, category, customer, audience
            )
            _cache.put(fact_sheet, {"body": body, "cta": cta, "template_name": template_name})
            return _build_action(body, cta, template_name, trigger, merchant_id, customer_id,
                               rationale + " (LLM output failed provenance)")

    except Exception as e:
        _circuit.record_failure()
        log.warning("llm_failed trigger=%s error=%s", trigger_id, e)
        body, cta, template_name, rationale = render_fallback(
            trigger, merchant, category, customer, audience
        )
        return _build_action(body, cta, template_name, trigger, merchant_id, customer_id,
                           rationale + f" (LLM fallback: {e})")


def compose_reply(
    merchant: dict[str, Any],
    category: dict[str, Any],
    conversation_history: str,
    merchant_message: str,
    intent: str,
    trigger: Optional[dict[str, Any]] = None,
    customer: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    Compose a reply to a merchant/customer message using LLM.
    Returns the reply body text, or None if LLM unavailable.
    """
    if LLM_PROVIDER == "none" or _circuit.is_open:
        return None

    perf_delta = None  # No delta for replies
    audience = resolve_audience(customer) if customer else None
    fact_sheet, _, _ = build_fact_sheet(
        trigger=trigger or {},
        merchant=merchant,
        category=category,
        customer=customer,
        audience_info=audience,
    )
    lang = resolve_language(merchant, message=merchant_message, customer=customer)
    prompt = get_reply_prompt(fact_sheet, conversation_history, merchant_message, intent, lang)

    try:
        result = llm_complete(SYSTEM_PROMPT, prompt, role="compose")
        if result:
            _circuit.record_success()
            return result.strip().strip('"').strip("'")
    except Exception as e:
        _circuit.record_failure()
        log.warning("reply_llm_failed: %s", e)

    return None


def teardown():
    """Wipe caches on teardown."""
    _cache.wipe()
    _circuit.reset()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_action(
    body: str, cta: str, template_name: str,
    trigger: dict, merchant_id: str, customer_id: Optional[str],
    rationale: str,
) -> dict:
    """Build a TickAction-compatible dict."""
    trigger_id = trigger.get("id", "")
    suppression_key = trigger.get("suppression_key", "")
    send_as = get_send_as(trigger)
    conv_id = f"conv_{merchant_id}_{trigger_id}"

    return {
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "send_as": send_as,
        "trigger_id": trigger_id,
        "template_name": template_name,
        "template_params": [],
        "body": body,
        "cta": cta,
        "suppression_key": suppression_key,
        "rationale": rationale,
    }


def _infer_cta(trigger_kind: str, body: str) -> str:
    """Infer appropriate CTA type from trigger kind."""
    _BOOKING_KINDS = {"recall_due", "trial_followup", "chronic_refill_due"}
    _CONFIRM_KINDS = {"active_planning_intent"}
    _BINARY_KINDS = {"renewal_due", "winback_eligible", "cde_opportunity"}

    if trigger_kind in _BOOKING_KINDS:
        return "multi_choice_slot"
    if trigger_kind in _CONFIRM_KINDS:
        return "binary_yes_stop"
    if trigger_kind in _BINARY_KINDS:
        return "binary_yes_stop"
    return "open_ended"
