"""
fact_sheet.py — Builds a verifiable, human-readable fact sheet from contexts.

The LLM sees THIS, not a raw JSON dump.
Signal selection happens here in code — the LLM only composes prose from selected facts.
Also produces ALLOWED_NUMBERS and ALLOWED_ENTITIES for provenance verification.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("vera")


def build_fact_sheet(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    category: dict[str, Any],
    customer: Optional[dict[str, Any]] = None,
    perf_delta: Optional[dict[str, Any]] = None,
    audience_info: Optional[Any] = None,
) -> tuple[str, set[str], set[str]]:
    """
    Build a fact sheet for composition.

    Returns:
        (fact_sheet_text, allowed_numbers, allowed_entities)
    """
    lines: list[str] = []
    allowed_numbers: set[str] = set()
    allowed_entities: set[str] = set()

    # ── Trigger Section ──────────────────────────────────────────────────
    trg_kind = trigger.get("kind", "unknown")
    trg_payload = trigger.get("payload", {})
    trg_urgency = trigger.get("urgency", 0)
    trg_scope = trigger.get("scope", "merchant")
    trg_suppression = trigger.get("suppression_key", "")

    lines.append("=== TRIGGER (WHY NOW — this is the message anchor) ===")
    lines.append(f"Kind: {trg_kind}")
    lines.append(f"Scope: {trg_scope}")
    lines.append(f"Urgency: {trg_urgency}/5")
    _add_number(allowed_numbers, str(trg_urgency))

    is_placeholder = trg_payload.get("placeholder", False)
    if is_placeholder:
        lines.append("⚠ PLACEHOLDER TRIGGER — no specifics available, use template fallback")
        lines.append(f"Topic: {trg_payload.get('metric_or_topic', trg_kind)}")
    else:
        for key, val in trg_payload.items():
            if key in ("placeholder", "metric_or_topic"):
                continue
            lines.append(f"  {key}: {val}")
            _extract_numbers_from_value(allowed_numbers, val)
            _extract_entities_from_value(allowed_entities, val)

    lines.append("")

    # ── Merchant Section ─────────────────────────────────────────────────
    identity = merchant.get("identity", {})
    m_name = identity.get("name", "Merchant")
    owner = identity.get("owner_first_name", "")
    city = identity.get("city", "")
    locality = identity.get("locality", "")
    languages = identity.get("languages", ["en"])
    verified = identity.get("verified", True)

    allowed_entities.add(m_name)
    if owner:
        allowed_entities.add(owner)
    if locality:
        allowed_entities.add(locality)
    if city:
        allowed_entities.add(city)

    lines.append("=== MERCHANT ===")
    lines.append(f"Name: {m_name}")
    if owner:
        lines.append(f"Owner first name: {owner}")
    lines.append(f"Location: {locality}, {city}")
    lines.append(f"Languages: {', '.join(languages)}")
    lines.append(f"Verified: {verified}")

    # Subscription
    sub = merchant.get("subscription", {})
    sub_status = sub.get("status", "unknown")
    lines.append(f"Subscription: {sub_status}")
    if sub.get("plan"):
        lines.append(f"  Plan: {sub['plan']}")
    if sub.get("days_remaining") is not None:
        lines.append(f"  Days remaining: {sub['days_remaining']}")
        _add_number(allowed_numbers, str(sub["days_remaining"]))
    if sub.get("days_since_expiry") is not None:
        lines.append(f"  Days since expiry: {sub['days_since_expiry']}")
        _add_number(allowed_numbers, str(sub["days_since_expiry"]))

    # Performance
    perf = merchant.get("performance", {})
    if perf:
        lines.append("Performance (30d):")
        for key in ("views", "calls", "directions", "ctr"):
            val = perf.get(key)
            if val is not None:
                lines.append(f"  {key}: {val}")
                _add_number(allowed_numbers, str(val))
        delta = perf.get("delta_7d", {})
        if delta:
            lines.append("  7-day delta:")
            for key, val in delta.items():
                lines.append(f"    {key}: {val:+.0%}" if isinstance(val, float) else f"    {key}: {val}")
                _add_number(allowed_numbers, str(val))
                if isinstance(val, float):
                    _add_number(allowed_numbers, f"{abs(val)*100:.0f}")
                    _add_number(allowed_numbers, f"{val*100:+.0f}")

    # Signals
    signals = merchant.get("signals", [])
    if signals:
        lines.append(f"Signals: {', '.join(signals)}")

    # Active offers
    offers = merchant.get("offers", [])
    active_offers = [o for o in offers if o.get("status") == "active"]
    if active_offers:
        lines.append("Active offers:")
        for o in active_offers:
            title = o.get("title", "")
            lines.append(f"  - {title}")
            allowed_entities.add(title)
            _extract_numbers_from_value(allowed_numbers, title)
    else:
        lines.append("Active offers: NONE")

    # Customer aggregate
    cust_agg = merchant.get("customer_aggregate", {})
    if cust_agg:
        lines.append("Customer aggregate:")
        for key, val in cust_agg.items():
            lines.append(f"  {key}: {val}")
            _add_number(allowed_numbers, str(val))

    # Performance delta (from context version bump)
    if perf_delta:
        lines.append("Performance delta (since last context update):")
        for key, val in perf_delta.items():
            lines.append(f"  {key}: {val}")
            _add_number(allowed_numbers, str(val))

    lines.append("")

    # ── Category Section ─────────────────────────────────────────────────
    cat_slug = category.get("slug", "")
    voice = category.get("voice", {})
    tone = voice.get("tone", "professional")
    taboos = voice.get("vocab_taboo", voice.get("taboos", []))

    lines.append("=== CATEGORY ===")
    lines.append(f"Slug: {cat_slug}")
    lines.append(f"Voice tone: {tone}")
    if taboos:
        lines.append(f"TABOO words (DO NOT USE): {', '.join(taboos)}")

    # Peer stats
    peer = category.get("peer_stats", {})
    if peer:
        lines.append("Peer benchmarks:")
        for key, val in peer.items():
            if key != "scope":
                lines.append(f"  {key}: {val}")
                _add_number(allowed_numbers, str(val))

    # Relevant digest items (only those matching trigger payload)
    digest = category.get("digest", [])
    top_item_id = trg_payload.get("top_item_id") or trg_payload.get("digest_item_id") or trg_payload.get("alert_id")
    if top_item_id and digest:
        matching = [d for d in digest if d.get("id") == top_item_id]
        if matching:
            item = matching[0]
            lines.append(f"Relevant digest item:")
            lines.append(f"  Title: {item.get('title', '')}")
            lines.append(f"  Source: {item.get('source', '')}")
            if item.get("summary"):
                lines.append(f"  Summary: {item['summary']}")
            if item.get("trial_n"):
                lines.append(f"  Trial N: {item['trial_n']}")
                _add_number(allowed_numbers, str(item["trial_n"]))
            allowed_entities.add(item.get("title", ""))
            allowed_entities.add(item.get("source", ""))
            _extract_numbers_from_value(allowed_numbers, item.get("title", ""))

    # Trend signals
    trends = category.get("trend_signals", [])
    if trends:
        lines.append("Trend signals:")
        for t in trends[:3]:
            lines.append(f"  - {t.get('query', '')}: {t.get('delta_yoy', 0):+.0%} YoY")
            _add_number(allowed_numbers, str(t.get("delta_yoy", 0)))

    lines.append("")

    # ── Customer Section (if customer-scoped) ────────────────────────────
    if customer:
        cust_identity = customer.get("identity", {})
        cust_name = cust_identity.get("name", "Customer")
        rel = customer.get("relationship", {})
        state = customer.get("state", "unknown")
        prefs = customer.get("preferences", {})

        lines.append("=== CUSTOMER ===")

        # Use resolved audience info if available
        if audience_info and audience_info.is_proxy:
            lines.append(f"Address as: {audience_info.address_as}")
            lines.append(f"About: {audience_info.about}")
            lines.append(f"Proxy: {audience_info.proxy_note}")
            allowed_entities.add(audience_info.address_as)
            allowed_entities.add(audience_info.about)
        else:
            lines.append(f"Name: {cust_name}")
            allowed_entities.add(cust_name)

        lines.append(f"State: {state}")
        lines.append(f"Language pref: {cust_identity.get('language_pref', 'english')}")

        if rel:
            lines.append(f"Visits: {rel.get('visits_total', 0)}")
            _add_number(allowed_numbers, str(rel.get("visits_total", 0)))
            lines.append(f"Last visit: {rel.get('last_visit', '?')}")
            services = rel.get("services_received", [])
            if services:
                lines.append(f"Services: {', '.join(services[-3:])}")
            if rel.get("lifetime_value") is not None:
                lines.append(f"Lifetime value: ₹{rel['lifetime_value']}")
                _add_number(allowed_numbers, str(rel["lifetime_value"]))

        if prefs.get("preferred_slots"):
            lines.append(f"Preferred slots: {prefs['preferred_slots']}")
        if prefs.get("preferred_stylist"):
            lines.append(f"Preferred stylist: {prefs['preferred_stylist']}")
            allowed_entities.add(prefs["preferred_stylist"])
        if prefs.get("wedding_date"):
            lines.append(f"Wedding date: {prefs['wedding_date']}")

        lines.append("")

    # ── Allowed values summary ───────────────────────────────────────────
    lines.append("=== COMPOSITION RULES ===")
    lines.append("1. The TRIGGER section above is your message anchor ('why now').")
    lines.append("2. Use merchant/category facts only as supporting evidence.")
    lines.append("3. Every number in your message MUST appear in this fact sheet.")
    lines.append("4. Do NOT invent percentages, counts, dates, or names.")
    lines.append("5. Do NOT use any TABOO words listed above.")
    lines.append("6. Match the merchant's language preferences.")
    lines.append("7. Keep the message under 300 characters if possible.")
    lines.append("8. Do NOT include URLs.")

    fact_sheet_text = "\n".join(lines)
    return fact_sheet_text, allowed_numbers, allowed_entities


# ── Helpers ──────────────────────────────────────────────────────────────────

import re

_NUM_RE = re.compile(r"-?\d+\.?\d*")

def _add_number(nums: set[str], val: str):
    """Extract numeric strings from a value."""
    for m in _NUM_RE.findall(str(val)):
        nums.add(m)

def _extract_numbers_from_value(nums: set[str], val: Any):
    """Recursively extract numbers from a value."""
    if isinstance(val, (int, float)):
        nums.add(str(val))
        if isinstance(val, float):
            nums.add(f"{abs(val)*100:.0f}")
    elif isinstance(val, str):
        _add_number(nums, val)
    elif isinstance(val, list):
        for item in val:
            _extract_numbers_from_value(nums, item)
    elif isinstance(val, dict):
        for v in val.values():
            _extract_numbers_from_value(nums, v)

def _extract_entities_from_value(entities: set[str], val: Any):
    """Extract entity-like strings."""
    if isinstance(val, str) and len(val) > 2 and not val.isdigit():
        entities.add(val)
    elif isinstance(val, list):
        for item in val:
            _extract_entities_from_value(entities, item)
    elif isinstance(val, dict):
        for v in val.values():
            _extract_entities_from_value(entities, v)
