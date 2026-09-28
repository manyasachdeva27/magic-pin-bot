"""
language_resolver.py — Resolves output language from merchant + message.

No hardcoded Hindi. Follows merchant.identity.languages preference.
Detects language of incoming message where relevant.
"""
from __future__ import annotations

import re
from typing import Any, Optional


# Hindi/Hinglish character and word indicators
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_HINGLISH_WORDS = {
    "hai", "hain", "kya", "nahi", "nahin", "aap", "hum", "tum", "mein", "yeh",
    "woh", "karo", "karna", "kar", "se", "ko", "ka", "ki", "ke", "mujhe",
    "aapka", "aapke", "aapki", "bhi", "aur", "lekin", "toh", "abhi", "jaldi",
    "kal", "aaj", "bahut", "accha", "theek", "haan", "ji", "kaise", "kitna",
    "kab", "kahan", "kyun", "chahiye", "chahte", "sakte", "sakta", "sakti",
    "dena", "lena", "batao", "bataye", "dekhte", "chalo", "aao",
    "dhanyavaad", "shukriya", "namaste",
}

# Tamil indicators
_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")

# Telugu indicators
_TELUGU_RE = re.compile(r"[\u0C00-\u0C7F]")

# Kannada indicators
_KANNADA_RE = re.compile(r"[\u0C80-\u0CFF]")


def resolve_language(
    merchant: dict[str, Any],
    message: Optional[str] = None,
    customer: Optional[dict[str, Any]] = None,
) -> str:
    """
    Resolve the output language for a message.

    Priority:
    1. Customer language_pref (if customer-scoped)
    2. Merchant identity.languages
    3. Detected language from incoming message
    4. Default: "english"

    Returns a language hint string for the composer prompt:
    "english", "hindi", "hi-en mix", "te-en mix", etc.
    """
    # Customer preference (if available)
    if customer:
        lang_pref = customer.get("identity", {}).get("language_pref", "")
        if lang_pref:
            return lang_pref

    # Merchant languages
    merchant_langs = merchant.get("identity", {}).get("languages", ["en"])

    # Detect from incoming message
    msg_lang = None
    if message:
        msg_lang = _detect_language(message)

    # If merchant supports Hindi and message is Hindi/Hinglish, use mix
    if msg_lang in ("hi", "hi-en mix") and "hi" in merchant_langs:
        return "hi-en mix"

    # If merchant supports multiple languages
    if len(merchant_langs) == 1:
        lang = merchant_langs[0]
        return _code_to_label(lang)

    # Multi-language merchant: prefer English with local mix
    if "hi" in merchant_langs and "en" in merchant_langs:
        return "hi-en mix"
    if "ta" in merchant_langs and "en" in merchant_langs:
        return "ta-en mix"
    if "te" in merchant_langs and "en" in merchant_langs:
        return "te-en mix"
    if "kn" in merchant_langs and "en" in merchant_langs:
        return "kn-en mix"

    return "english"


def _detect_language(text: str) -> Optional[str]:
    """Quick heuristic language detection from message text."""
    if not text:
        return None

    # Check for script-based detection
    if _DEVANAGARI_RE.search(text):
        return "hi"
    if _TAMIL_RE.search(text):
        return "ta"
    if _TELUGU_RE.search(text):
        return "te"
    if _KANNADA_RE.search(text):
        return "kn"

    # Check for Hinglish (romanized Hindi)
    words = set(text.lower().split())
    hinglish_count = len(words & _HINGLISH_WORDS)
    if hinglish_count >= 2:
        return "hi-en mix"

    return "en"


def _code_to_label(code: str) -> str:
    """Convert ISO language code to a composer-friendly label."""
    return {
        "en": "english",
        "hi": "hindi",
        "ta": "tamil",
        "te": "telugu",
        "kn": "kannada",
    }.get(code, "english")
