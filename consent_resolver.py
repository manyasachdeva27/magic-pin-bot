"""
consent_resolver.py — Gates outbound messages on consent scope + audience resolution.

Data traps handled:
- 186 of 200 customers have promo-only consent
- Parent-proxy names: "Aanya (parent: Sneha)" → address Sneha
- Senior via son: "Mr. Sharma", channel=whatsapp_via_son
- Unreachable: c_015 has phone=null, consent=[], opt_in=false
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("vera")


# ── Trigger kind → required consent scope mapping ────────────────────────────
REQUIRED_CONSENT: dict[str, str] = {
    "recall_due": "recall_reminders",
    "chronic_refill_due": "refill_reminders",
    "appointment_tomorrow": "appointment_reminders",
    "trial_followup": "promotional_offers",
    "customer_lapsed_soft": "winback_offers",
    "customer_lapsed_hard": "winback_offers",
    "wedding_package_followup": "bridal_package_followup",
    # All other customer-scoped triggers default to "promotional_offers"
}


@dataclass
class AudienceInfo:
    """Resolved addressing info for a customer message."""
    address_as: str        # Who to greet in the message
    about: str             # Who the message is about (may differ from address_as)
    is_proxy: bool         # True if message goes via a parent/son
    proxy_note: str        # e.g., "via parent" or "via son"
    can_contact: bool      # False if unreachable
    block_reason: str      # Why blocked (empty if can_contact)


def can_contact_customer(
    customer: dict[str, Any],
    trigger_kind: str,
) -> tuple[bool, str]:
    """
    Check if we have consent to contact this customer for this trigger kind.
    Returns (allowed, reason).
    """
    consent = customer.get("consent", {})
    scope = consent.get("scope", [])
    prefs = customer.get("preferences", {})

    # Unreachable: no phone, no channel, no opt-in
    phone = customer.get("identity", {}).get("phone_redacted")
    if phone is None:
        return False, "no_phone"
    if prefs.get("channel") == "none_recorded":
        return False, "no_channel"
    if not prefs.get("reminder_opt_in", True):
        return False, "reminder_opt_in_false"
    if not scope:
        return False, "consent_scope_empty"

    # Check specific consent
    required = REQUIRED_CONSENT.get(trigger_kind, "promotional_offers")
    if required not in scope:
        return False, f"consent_missing:{required}"

    return True, "ok"


def resolve_audience(customer: dict[str, Any]) -> AudienceInfo:
    """
    Parse parent-proxy names and proxy channels.
    Returns who to address and how to frame the message.
    """
    identity = customer.get("identity", {})
    name = identity.get("name", "Customer")
    channel = customer.get("preferences", {}).get("channel", "whatsapp")

    # Check for parent proxy pattern: "Aanya (parent: Sneha)"
    parent_match = re.match(r"(.+?)\s*\(parent:\s*(.+?)\)", name)
    if parent_match:
        child_name = parent_match.group(1).strip()
        parent_name = parent_match.group(2).strip()
        return AudienceInfo(
            address_as=parent_name,
            about=child_name,
            is_proxy=True,
            proxy_note=f"Message about {child_name}, sent to parent {parent_name}",
            can_contact=True,
            block_reason="",
        )

    # Check for via_son / via_parent channel
    if "via_son" in channel:
        return AudienceInfo(
            address_as=name,
            about=name,
            is_proxy=True,
            proxy_note=f"Message for {name}, delivered via son's phone",
            can_contact=True,
            block_reason="",
        )
    if "via_parent" in channel:
        return AudienceInfo(
            address_as=name,
            about=name,
            is_proxy=True,
            proxy_note=f"Message for {name}, delivered via parent's phone",
            can_contact=True,
            block_reason="",
        )

    # Normal direct contact
    return AudienceInfo(
        address_as=name,
        about=name,
        is_proxy=False,
        proxy_note="",
        can_contact=True,
        block_reason="",
    )
