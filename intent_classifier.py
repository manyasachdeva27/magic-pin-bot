"""
intent_classifier.py — Precedence-based intent classification.

Order: opt_out > auto_reply > question > commitment > defer > neutral

Uses whole-word matching with \\b boundaries to prevent substring misfires:
- "no" matches "no" but NOT "noticed"
- "ha" does NOT match "happy"
- "kal" does NOT match "kalkaji"
- "yes, but what does it cost?" is a QUESTION (not commitment)
"""
from __future__ import annotations

import re
import logging
from enum import Enum
from typing import Optional

from auto_reply_detector import is_auto_reply

log = logging.getLogger("vera")


class Intent(str, Enum):
    OPT_OUT = "opt_out"
    AUTO_REPLY = "auto_reply"
    QUESTION = "question"
    COMMITMENT = "commitment"
    DEFER = "defer"
    OFF_TOPIC = "off_topic"
    NEUTRAL = "neutral"


# ── Pattern banks (compiled, whole-word) ─────────────────────────────────────

def _wb(patterns: list[str]) -> list[re.Pattern]:
    """Compile patterns with word boundaries and case-insensitive."""
    return [re.compile(r"(?:^|\b)" + p + r"(?:\b|$)", re.IGNORECASE) for p in patterns]


# 1. Opt-out: explicit stop / abuse
_OPT_OUT_PATTERNS = _wb([
    r"stop\s+messaging",
    r"stop\s+sending",
    r"stop\s+contacting",
    r"don'?t\s+(message|contact|send|bother)",
    r"not\s+interested",
    r"band\s+karo",
    r"mat\s+bhejo",
    r"rehne\s+do",
    r"unsubscribe",
    r"nahi\s+chahiye",
    r"nahin\s+chahiye",
    r"this\s+is\s+useless",
    r"useless\s+spam",
    r"spam",
    r"leave\s+me\s+alone",
    r"go\s+away",
    r"block",
]) + [
    # Abuse detection (no word boundary needed)
    re.compile(r"\b(fuck|shit|damn|idiot|stupid|chutiya|bakwas|bewakoof)\b", re.IGNORECASE),
]

# 3. Question markers
_QUESTION_PATTERNS = _wb([
    r"what",
    r"how\s+much",
    r"how\s+many",
    r"how\s+long",
    r"how\s+does",
    r"how\s+do",
    r"how\s+can",
    r"when",
    r"where",
    r"which",
    r"why",
    r"can\s+you",
    r"could\s+you",
    r"is\s+it",
    r"does\s+it",
    r"will\s+it",
    r"kya",
    r"kitna",
    r"kitne",
    r"kab",
    r"kaise",
    r"kahan",
    r"kidhar",
    r"cost",
    r"price",
    r"rate",
    r"charges?",
    r"fees?",
    r"daam",
])

# 4. Commitment (positive intent)
_COMMITMENT_PATTERNS = _wb([
    r"yes",
    r"yeah",
    r"yep",
    r"sure",
    r"ok",
    r"okay",
    r"lets?\s+do\s+it",
    r"let'?s\s+go",
    r"go\s+ahead",
    r"do\s+it",
    r"proceed",
    r"confirm",
    r"confirmed",
    r"done",
    r"book\s+it",
    r"send\s+it",
    r"schedule\s+it",
    r"haan",
    r"haa",
    r"theek\s+hai",
    r"thik\s+hai",
    r"kar\s+do",
    r"karo",
    r"bhej\s+do",
    r"bhejo",
    r"chalo",
    r"sahi\s+hai",
    r"bilkul",
    r"zaroor",
    r"agreed",
    r"sounds\s+good",
    r"perfect",
    r"great",
    r"whats?\s+next",
    r"what'?s\s+next",
    r"next\s+step",
])

# 5. Defer patterns
_DEFER_PATTERNS = _wb([
    r"later",
    r"not\s+now",
    r"baad\s+mein",
    r"abhi\s+nahi",
    r"next\s+week",
    r"kal",
    r"tomorrow",
    r"some\s+other\s+time",
    r"busy\s+right\s+now",
    r"busy\s+abhi",
    r"let\s+me\s+think",
    r"sochne\s+do",
    r"phir\s+batata",
    r"phir\s+bataata",
    r"phir\s+bataungi",
])

# 6. Off-topic indicators
_OFF_TOPIC_PATTERNS = _wb([
    r"gst",
    r"tax",
    r"income\s+tax",
    r"ca\s+",
    r"accountant",
    r"loan",
    r"emi",
    r"insurance",
    r"passport",
    r"visa",
    r"pan\s+card",
    r"aadhaar",
    r"aadhar",
    r"electricity\s+bill",
    r"water\s+bill",
])


def classify(message: str) -> Intent:
    """
    Classify a message into an intent using strict precedence.
    Whole-word matching prevents substring misfires.
    """
    if not message or not message.strip():
        return Intent.NEUTRAL

    text = message.strip()

    # 1. Opt-out? (highest priority)
    for p in _OPT_OUT_PATTERNS:
        if p.search(text):
            return Intent.OPT_OUT

    # 2. Auto-reply?
    if is_auto_reply(text):
        return Intent.AUTO_REPLY

    # 3. Off-topic? (check BEFORE question — "can you help with GST?" is off-topic, not a question)
    for p in _OFF_TOPIC_PATTERNS:
        if p.search(text):
            return Intent.OFF_TOPIC

    # 4. Question?
    has_question_mark = "?" in text
    has_question_word = any(p.search(text) for p in _QUESTION_PATTERNS)

    # 4. Commitment?
    has_commitment = any(p.search(text) for p in _COMMITMENT_PATTERNS)

    # KEY RULE: "yes, but what does it cost?" is a QUESTION, not a commitment
    # If message has BOTH commitment and question markers, classify as question
    if has_commitment and (has_question_mark or has_question_word):
        return Intent.QUESTION

    if has_question_mark or has_question_word:
        return Intent.QUESTION

    if has_commitment:
        return Intent.COMMITMENT

    # 5. Defer?
    for p in _DEFER_PATTERNS:
        if p.search(text):
            return Intent.DEFER

    # 6. Default
    return Intent.NEUTRAL
