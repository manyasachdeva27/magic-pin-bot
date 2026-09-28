"""
trigger_router.py — Maps trigger.kind → prompt template + reality check.

The trigger is ALWAYS the anchor ("why now"). Merchant/category facts are
supporting evidence only. The only exception: if the Reality Check finds
the trigger's claim contradicted by data, reframe or skip.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("vera")


def reality_check(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
) -> tuple[bool, str]:
    """
    Check if the trigger's claim is contradicted by the merchant's data.

    Returns: (proceed, reason)
    - proceed=True: trigger claim is valid or uncontradicted
    - proceed=False: trigger claim is contradicted → skip or reframe
    """
    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})
    perf = merchant.get("performance", {})
    delta = perf.get("delta_7d", {})

    if kind == "perf_dip":
        metric = payload.get("metric", "")
        claimed_delta = payload.get("delta_pct")
        if claimed_delta is not None and metric:
            actual_delta = delta.get(f"{metric}_pct")
            # If trigger says dip but actual data shows growth → contradicted
            if actual_delta is not None and actual_delta > 0 and claimed_delta < 0:
                return False, f"trigger claims {metric} dip ({claimed_delta}) but actual delta is positive ({actual_delta})"

    if kind == "perf_spike":
        metric = payload.get("metric", "")
        claimed_delta = payload.get("delta_pct")
        if claimed_delta is not None and metric:
            actual_delta = delta.get(f"{metric}_pct")
            if actual_delta is not None and actual_delta < 0 and claimed_delta > 0:
                return False, f"trigger claims {metric} spike ({claimed_delta}) but actual delta is negative ({actual_delta})"

    if kind == "gbp_unverified":
        if merchant.get("identity", {}).get("verified", False):
            return False, "trigger says unverified but merchant is verified"

    if kind == "renewal_due":
        sub = merchant.get("subscription", {})
        if sub.get("status") == "expired":
            return False, "trigger says renewal due but subscription already expired"

    if kind == "dormant_with_vera":
        # Check: is the trigger valid? Don't anchor on CTR gap.
        # The trigger IS the anchor: "merchant hasn't talked to Vera in N days"
        # Just proceed — the trigger's claim is about dormancy, not performance.
        pass

    return True, "ok"


def should_skip_trigger(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
) -> tuple[bool, str]:
    """
    Higher-level check: should we skip this trigger entirely?
    """
    payload = trigger.get("payload", {})
    kind = trigger.get("kind", "")
    urgency = trigger.get("urgency", 0)

    # Skip expired triggers
    expires = trigger.get("expires_at")
    # (In production, compare against `now` from tick; here just flag for awareness)

    # Skip if trigger is way too early (e.g., Diwali 188 days out with urgency 1)
    if kind == "festival_upcoming":
        days_until = payload.get("days_until")
        if days_until and days_until > 60 and urgency <= 1:
            return True, f"festival {days_until} days out with urgency {urgency} — too early"

    # Reality check
    proceed, reason = reality_check(trigger, merchant)
    if not proceed:
        return True, f"reality_check_failed: {reason}"

    return False, "ok"


def get_send_as(trigger: dict[str, Any]) -> str:
    """Determine send_as based on trigger scope."""
    scope = trigger.get("scope", "merchant")
    customer_id = trigger.get("customer_id")
    if customer_id and scope == "customer":
        return "merchant_on_behalf"
    return "vera"


# ── LLM Prompt Templates ────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Vera, magicpin's AI assistant for local merchants.
You compose WhatsApp messages that are:
- Specific (use real numbers from the fact sheet, never invent)
- Category-appropriate (match the voice tone)
- Trigger-anchored (the trigger is your "why now" — don't replace it)
- Concise (under 300 chars preferred, never over 500)
- No URLs ever
- No taboo words (listed in the fact sheet)

Output ONLY the message body. No markdown, no quotes, no explanation.
Match the language preference specified in the fact sheet."""


def get_composition_prompt(
    fact_sheet: str,
    trigger_kind: str,
    language: str,
) -> str:
    """Build the user prompt for composition."""
    return f"""Compose a WhatsApp message based on this fact sheet.

{fact_sheet}

LANGUAGE: {language}
TRIGGER KIND: {trigger_kind}

Rules:
1. The TRIGGER section is your anchor — this is WHY NOW.
2. Use merchant/category facts as supporting evidence only.
3. Every number MUST come from the fact sheet. Do NOT invent.
4. Do NOT include any URL.
5. Keep under 300 characters if possible.
6. End with a natural next step or question.

Output ONLY the message body, nothing else."""


def get_reply_prompt(
    fact_sheet: str,
    conversation_history: str,
    merchant_message: str,
    intent: str,
    language: str,
) -> str:
    """Build the user prompt for reply composition."""
    return f"""You are in an ongoing WhatsApp conversation with a merchant.

{fact_sheet}

CONVERSATION SO FAR:
{conversation_history}

MERCHANT'S LATEST MESSAGE: "{merchant_message}"
DETECTED INTENT: {intent}
LANGUAGE: {language}

Rules:
1. Respond naturally to what they said.
2. If they committed ("yes", "let's do it"), deliver the artifact INLINE — include the actual content, don't just say "draft ready, say go".
3. If they asked a question, answer it using fact sheet data.
4. If off-topic, decline in one line and redirect to the live topic.
5. Every number MUST come from the fact sheet.
6. Keep under 300 characters if possible.
7. No URLs.

Output ONLY the reply message body, nothing else."""
