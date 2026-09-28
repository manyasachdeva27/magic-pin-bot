"""
auto_reply_detector.py — Detects WhatsApp Business canned auto-replies.

State tracked per MERCHANT (not per conversation) because the simulator
sends different conversation_ids per turn.

Sequence: 1st → send (one owner-directed nudge)
          2nd → wait 86400
          3rd → end
"""
from __future__ import annotations

import re
import logging
from typing import Optional

log = logging.getLogger("vera")

# ── Auto-reply patterns (40+ patterns covering English + Hindi + mixed) ──────
_AUTO_REPLY_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        # English patterns
        r"thank\s*you\s+for\s+(contacting|reaching|messaging|writing)",
        r"thanks?\s+for\s+(contacting|reaching|messaging|writing)",
        r"our\s+team\s+will\s+(respond|get\s+back|reply)\s+(shortly|soon|asap)",
        r"we('ll|\s+will)\s+(get\s+back|respond|reply)\s+(to\s+you\s+)?(shortly|soon|within)",
        r"this\s+is\s+an?\s+(automated|auto)\s*([-\s])?reply",
        r"(auto|automated)\s*([-\s])?(response|reply|message)",
        r"we\s+have\s+received\s+your\s+(message|query|enquiry)",
        r"your\s+(message|query|enquiry)\s+(has\s+been|is)\s+received",
        r"we\s+are\s+(currently\s+)?(closed|unavailable|away|busy)",
        r"our\s+(business|office|working)\s+hours\s+are",
        r"(office|business|store)\s+hours?\s*:?\s*\d",
        r"please\s+(leave|send)\s+your\s+(details|message|query)",
        r"we('ll|\s+will)\s+(reach|contact|call)\s+(out\s+to\s+)?you",
        r"currently\s+(away|offline|out\s+of\s+office)",
        r"out\s+of\s+office",
        r"i('m|\s+am)\s+(away|not\s+available|out)",
        r"(hello|hi)\s*!?\s*(thank|welcome)\s*",
        r"welcome\s+to\s+.{3,50}!?\s*(our|we)",
        # Hindi patterns
        r"(humse|hamse)\s+(sampark|contact)\s+karne\s+ke\s+liye\s+(dhanyavaad|shukriya)",
        r"aapka\s+(sandesh|message)\s+(mil\s+gaya|prapt\s+hua)",
        r"hum\s+jald\s+(hi\s+)?(jawab|reply|uttar)\s+denge",
        r"hum\s+aapko\s+jald\s+se\s+jald\s+(contact|sampark)\s+karenge",
        r"(dhanyavaad|shukriya)\s+.{0,20}(sampark|contact|message)",
        r"abhi\s+(band|closed)\s+(hain|hai)",
    ]
]

# Quick substring checks (faster than regex for obvious cases)
_AUTO_REPLY_SUBSTRINGS = [
    "thank you for contacting",
    "thanks for contacting",
    "our team will respond",
    "team will get back",
    "automated reply",
    "auto-reply",
    "auto reply",
    "we have received your",
    "your message has been",
    "currently away",
    "out of office",
    "business hours",
    "office hours",
]


def is_auto_reply(message: str) -> bool:
    """
    Detect if a message is a WhatsApp Business canned auto-reply.
    Uses both fast substring checks and regex patterns.
    """
    if not message or len(message) < 10:
        return False

    lower = message.lower().strip()

    # Fast path: substring check
    for sub in _AUTO_REPLY_SUBSTRINGS:
        if sub in lower:
            return True

    # Slow path: regex
    for pattern in _AUTO_REPLY_PATTERNS:
        if pattern.search(lower):
            return True

    return False


def get_auto_reply_action(
    merchant_auto_count: int,
) -> tuple[str, Optional[int], str]:
    """
    Given the merchant's auto-reply count (BEFORE incrementing),
    return the action to take.

    Args:
        merchant_auto_count: how many auto-replies already seen from this merchant

    Returns:
        (action, wait_seconds_or_None, rationale)
        action: "send" | "wait" | "end"
    """
    if merchant_auto_count == 0:
        # 1st auto-reply: one owner-directed nudge
        return (
            "send",
            None,
            "Detected auto-reply (1st occurrence). Sending one nudge for the owner."
        )
    elif merchant_auto_count == 1:
        # 2nd auto-reply: wait 24h
        return (
            "wait",
            86400,
            "Same auto-reply pattern (2nd occurrence). Owner not at phone. Waiting 24h."
        )
    else:
        # 3rd+: end
        return (
            "end",
            None,
            f"Auto-reply {merchant_auto_count + 1}x — no real engagement. Closing conversation."
        )


def auto_reply_nudge_body(owner_name: str, original_topic: str) -> str:
    """Generate the owner-directed nudge message (1st auto-reply)."""
    body = f"Looks like an auto-reply — no worries! "
    if original_topic:
        topic = original_topic.replace("_", " ")
        body += f"When you see this, just reply about the {topic}."
    else:
        body += "When the owner sees this, just reply and I'll pick up."
    return body
