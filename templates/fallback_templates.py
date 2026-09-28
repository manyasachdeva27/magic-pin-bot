"""
fallback_templates.py — Deterministic template for every trigger kind.

Used when:
1. LLM_PROVIDER=none (template-only mode)
2. Circuit breaker is open (3+ consecutive LLM failures)
3. Action deadline exceeded
4. Placeholder trigger (payload.placeholder=True)

Every template produces a valid message using ONLY fact sheet data.
No fabricated numbers. No URLs. Matches category voice tone.
"""
from __future__ import annotations

from typing import Any, Optional


def render_fallback(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    category: dict[str, Any],
    customer: Optional[dict[str, Any]] = None,
    audience_info: Optional[Any] = None,
) -> tuple[str, str, str, str]:
    """
    Render a deterministic fallback message.

    Returns: (body, cta, template_name, rationale)
    """
    kind = trigger.get("kind", "unknown")
    payload = trigger.get("payload", {})
    identity = merchant.get("identity", {})
    owner = identity.get("owner_first_name", identity.get("name", "there"))
    m_name = identity.get("name", "your business")
    is_placeholder = payload.get("placeholder", False)

    renderer = _TEMPLATES.get(kind, _generic)
    body, cta = renderer(payload, merchant, category, customer, owner, m_name, audience_info)
    template_name = f"fallback_{kind}_v1"
    rationale = f"Deterministic template for {kind}"
    if is_placeholder:
        rationale += " (placeholder trigger, no LLM call)"

    return body, cta, template_name, rationale


# ── Per-kind template functions ──────────────────────────────────────────────

def _research_digest(p, m, c, cust, owner, name, aud):
    digest = c.get("digest", [])
    item_id = p.get("top_item_id", "")
    item = next((d for d in digest if d.get("id") == item_id), None)
    if item:
        title = item.get("title", "a new finding")
        source = item.get("source", "recent research")
        return (
            f"{owner}, {source} has a finding relevant to your practice: \"{title}\". "
            f"Want me to pull the key takeaway and draft something you can share with patients?",
            "open_ended"
        )
    return (
        f"{owner}, this week's research digest has items relevant to your practice. "
        f"Want me to highlight what matters most?",
        "open_ended"
    )

def _regulation_change(p, m, c, cust, owner, name, aud):
    digest = c.get("digest", [])
    item_id = p.get("top_item_id", "")
    item = next((d for d in digest if d.get("id") == item_id), None)
    deadline = p.get("deadline_iso", "")
    if item:
        title = item.get("title", "a new regulation")
        source = item.get("source", "regulatory update")
        body = f"{owner}, heads up — {title} ({source})."
        if deadline:
            body += f" Deadline: {deadline[:10]}."
        body += " Want me to summarize what you need to do?"
        return body, "open_ended"
    return f"{owner}, there's a regulatory update affecting your practice. Want me to pull the details?", "open_ended"

def _perf_dip(p, m, c, cust, owner, name, aud):
    metric = p.get("metric", "performance")
    delta = p.get("delta_pct")
    window = p.get("window", "7d")
    baseline = p.get("vs_baseline")
    body = f"{owner}, your {metric} "
    if delta is not None:
        body += f"dropped {abs(delta)*100:.0f}% "
    body += f"over the last {window}"
    if baseline is not None:
        body += f" (was {baseline})"
    body += ". Want me to look at what might be causing it and suggest a quick fix?"
    return body, "open_ended"

def _seasonal_perf_dip(p, m, c, cust, owner, name, aud):
    metric = p.get("metric", "traffic")
    delta = p.get("delta_pct")
    is_seasonal = p.get("is_expected_seasonal", False)
    note = p.get("season_note", "")
    body = f"{owner}, your {metric} is "
    if delta is not None:
        body += f"down {abs(delta)*100:.0f}% this week"
    else:
        body += "dipping"
    if is_seasonal:
        body += f" — this is normal for the season ({note.replace('_', ' ')}). "
        body += "Good time to prep for the next uptick. Want me to outline what high performers do during this window?"
    else:
        body += ". Want me to look into it?"
    return body, "open_ended"

def _perf_spike(p, m, c, cust, owner, name, aud):
    metric = p.get("metric", "traffic")
    delta = p.get("delta_pct")
    driver = p.get("likely_driver", "")
    body = f"{owner}, nice — your {metric} "
    if delta is not None:
        body += f"is up {abs(delta)*100:.0f}%"
    else:
        body += "spiked"
    if driver:
        body += f" (likely from your {driver.replace('_', ' ')} post)"
    body += ". Want me to help you keep the momentum going?"
    return body, "open_ended"

def _renewal_due(p, m, c, cust, owner, name, aud):
    days = p.get("days_remaining", "?")
    plan = p.get("plan", "")
    amount = p.get("renewal_amount")
    body = f"{owner}, your {plan} plan renews in {days} days"
    if amount:
        body += f" (₹{amount})"
    body += ". Everything running smoothly, or anything you'd like adjusted before renewal?"
    return body, "open_ended"

def _festival_upcoming(p, m, c, cust, owner, name, aud):
    festival = p.get("festival", "upcoming festival")
    days = p.get("days_until")
    body = f"{owner}, {festival} is "
    if days and days < 30:
        body += f"{days} days away. "
    else:
        body += "coming up. "
    body += f"Want me to draft a festive campaign for {name}?"
    return body, "open_ended"

def _ipl_match_today(p, m, c, cust, owner, name, aud):
    match = p.get("match", "today's match")
    venue = p.get("venue", "")
    body = f"{owner}, {match} is on today"
    if venue:
        body += f" at {venue}"
    body += f". Good night for a match-day push from {name}. Want me to draft a quick offer?"
    return body, "open_ended"

def _review_theme_emerged(p, m, c, cust, owner, name, aud):
    theme = p.get("theme", "").replace("_", " ")
    count = p.get("occurrences_30d")
    quote = p.get("common_quote", "")
    body = f"{owner}, a pattern in your recent reviews — "
    if count:
        body += f"{count} mentions of \"{theme}\" in the last 30 days"
    else:
        body += f"\"{theme}\" is coming up"
    if quote:
        body += f" (e.g., \"{quote}\")"
    body += ". Want me to suggest how to address it?"
    return body, "open_ended"

def _milestone_reached(p, m, c, cust, owner, name, aud):
    metric = p.get("metric", "milestone").replace("_", " ")
    val = p.get("value_now")
    target = p.get("milestone_value")
    body = f"{owner}, {name} is at {val} {metric}"
    if target:
        body += f" — just {target - val} away from {target}"
    body += ". Want me to help you hit it this week?"
    return body, "open_ended"

def _competitor_opened(p, m, c, cust, owner, name, aud):
    comp = p.get("competitor_name", "a new competitor")
    dist = p.get("distance_km")
    offer = p.get("their_offer", "")
    body = f"{owner}, {comp} opened "
    if dist:
        body += f"{dist}km from you"
    if offer:
        body += f" (advertising: {offer})"
    body += f". Want me to review what {name} can do to stand out?"
    return body, "open_ended"

def _dormant_with_vera(p, m, c, cust, owner, name, aud):
    days = p.get("days_since_last_merchant_message")
    last_topic = p.get("last_topic", "").replace("_", " ")
    body = f"{owner}, it's been "
    if days:
        body += f"{days} days since we last spoke"
    else:
        body += "a while"
    if last_topic:
        body += f" (we were discussing {last_topic})"
    body += ". Anything I can help with?"
    return body, "open_ended"

def _winback_eligible(p, m, c, cust, owner, name, aud):
    days = p.get("days_since_expiry")
    dip = p.get("perf_dip_pct")
    body = f"{owner}, "
    if days:
        body += f"it's been {days} days since your plan ended. "
    if dip is not None:
        body += f"Your visibility has dipped {abs(dip)*100:.0f}% since then. "
    body += f"Want to explore what getting back on would do for {name}?"
    return body, "open_ended"

def _gbp_unverified(p, m, c, cust, owner, name, aud):
    uplift = p.get("estimated_uplift_pct")
    path = p.get("verification_path", "verification")
    body = f"{owner}, {name}'s Google profile isn't verified yet. "
    if uplift:
        body += f"Verified businesses typically see {uplift*100:.0f}% more visibility. "
    body += f"The process is quick ({path.replace('_', ' ')}). Want me to walk you through it?"
    return body, "open_ended"

def _supply_alert(p, m, c, cust, owner, name, aud):
    molecule = p.get("molecule", "a product")
    batches = p.get("affected_batches", [])
    body = f"{owner}, urgent — {molecule} recall alert"
    if batches:
        body += f" (batches: {', '.join(batches[:2])})"
    body += ". Check your stock and pull affected units. Want details on the alternative supply?"
    return body, "open_ended"

def _category_seasonal(p, m, c, cust, owner, name, aud):
    season = p.get("season", "this season").replace("_", " ")
    trends = p.get("trends", [])
    body = f"{owner}, {season} trends for your category: "
    if trends:
        body += "; ".join(t.replace("_", " ") for t in trends[:3])
    body += ". Want me to suggest shelf/menu adjustments?"
    return body, "open_ended"

def _cde_opportunity(p, m, c, cust, owner, name, aud):
    credits = p.get("credits", "")
    fee = p.get("fee", "")
    digest = c.get("digest", [])
    item_id = p.get("digest_item_id", "")
    item = next((d for d in digest if d.get("id") == item_id), None)
    body = f"{owner}, "
    if item:
        body += f"there's a CDE opportunity: \"{item.get('title', 'upcoming webinar')}\""
    else:
        body += "a CDE webinar is coming up"
    if credits:
        body += f" ({credits} credits"
    if fee:
        body += f", {fee}"
    body += "). Interested?"
    return body, "open_ended"

def _curious_ask_due(p, m, c, cust, owner, name, aud):
    template = p.get("ask_template", "").replace("_", " ")
    return f"{owner}, quick question — {template}? Would love to know what you're seeing.", "open_ended"

def _active_planning_intent(p, m, c, cust, owner, name, aud):
    topic = p.get("intent_topic", "").replace("_", " ")
    last_msg = p.get("merchant_last_message", "")
    body = f"{owner}, picking up on the {topic} discussion"
    if last_msg:
        body += f" — you said \"{last_msg[:60]}\""
    body += ". Here's a rough outline to get started. Want me to flesh it out?"
    return body, "open_ended"

# ── Customer-scoped templates ────────────────────────────────────────────────

def _recall_due(p, m, c, cust, owner, name, aud):
    address = aud.address_as if aud else (cust or {}).get("identity", {}).get("name", "there")
    service = p.get("service_due", "checkup").replace("_", " ")
    slots = p.get("available_slots", [])
    m_name = m.get("identity", {}).get("name", "us")
    body = f"Hi {address}, {m_name} here — your {service} is due. "
    if slots:
        slot_text = " or ".join(s.get("label", "") for s in slots[:2])
        body += f"We have slots: {slot_text}. "
    body += "Reply to book or suggest a time."
    return body, "multi_choice_slot"

def _chronic_refill_due(p, m, c, cust, owner, name, aud):
    address = aud.address_as if aud else "there"
    molecules = p.get("molecule_list", [])
    runs_out = p.get("stock_runs_out_iso", "")
    m_name = m.get("identity", {}).get("name", "us")
    body = f"Hi {address}, {m_name} here — "
    if molecules:
        body += f"time for your {', '.join(molecules[:2])} refill"
    else:
        body += "your refill is due"
    if runs_out:
        body += f" (current stock runs out around {runs_out[:10]})"
    if p.get("delivery_address_saved"):
        body += ". We can deliver to your saved address"
    body += ". Confirm to place the order."
    return body, "binary_yes_stop"

def _customer_lapsed_hard(p, m, c, cust, owner, name, aud):
    address = aud.address_as if aud else "there"
    days = p.get("days_since_last_visit")
    focus = p.get("previous_focus", "").replace("_", " ")
    m_name = m.get("identity", {}).get("name", "us")
    body = f"Hi {address}, {m_name} here — "
    if days:
        body += f"it's been {days} days since your last visit"
    else:
        body += "we haven't seen you in a while"
    if focus:
        body += f" (your {focus} program)"
    body += ". Would you like to pick up where you left off?"
    return body, "open_ended"

def _trial_followup(p, m, c, cust, owner, name, aud):
    address = aud.address_as if aud else "there"
    m_name = m.get("identity", {}).get("name", "us")
    sessions = p.get("next_session_options", [])
    body = f"Hi {address}, {m_name} here — hope the trial session went well! "
    if sessions:
        slot = sessions[0].get("label", "")
        body += f"Next session available: {slot}. "
    body += "Want to continue?"
    return body, "binary_yes_stop"

def _wedding_package_followup(p, m, c, cust, owner, name, aud):
    address = aud.address_as if aud else "there"
    m_name = m.get("identity", {}).get("name", "us")
    wedding = p.get("wedding_date", "")
    days = p.get("days_to_wedding")
    next_step = p.get("next_step_window_open", "").replace("_", " ")
    body = f"Hi {address}, {m_name} here — "
    if days:
        body += f"{days} days to the big day! "
    if next_step:
        body += f"Time to start your {next_step}. "
    body += "Want me to set up the schedule?"
    return body, "open_ended"


def _generic(p, m, c, cust, owner, name, aud):
    kind = p.get("metric_or_topic", "update").replace("_", " ")
    return f"{owner}, I have an update about {kind} for {name}. Want me to share the details?", "open_ended"


# ── Template registry ────────────────────────────────────────────────────────
_TEMPLATES = {
    "research_digest": _research_digest,
    "regulation_change": _regulation_change,
    "perf_dip": _perf_dip,
    "seasonal_perf_dip": _seasonal_perf_dip,
    "perf_spike": _perf_spike,
    "renewal_due": _renewal_due,
    "festival_upcoming": _festival_upcoming,
    "ipl_match_today": _ipl_match_today,
    "review_theme_emerged": _review_theme_emerged,
    "milestone_reached": _milestone_reached,
    "competitor_opened": _competitor_opened,
    "dormant_with_vera": _dormant_with_vera,
    "winback_eligible": _winback_eligible,
    "gbp_unverified": _gbp_unverified,
    "supply_alert": _supply_alert,
    "category_seasonal": _category_seasonal,
    "cde_opportunity": _cde_opportunity,
    "curious_ask_due": _curious_ask_due,
    "active_planning_intent": _active_planning_intent,
    "recall_due": _recall_due,
    "chronic_refill_due": _chronic_refill_due,
    "customer_lapsed_hard": _customer_lapsed_hard,
    "trial_followup": _trial_followup,
    "wedding_package_followup": _wedding_package_followup,
}
