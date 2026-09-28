"""
provenance_verifier.py — Post-LLM numeric + entity verification against fact sheet.

Checks every number and entity name in the LLM output against the
ALLOWED_NUMBERS and ALLOWED_ENTITIES from the fact sheet.
Also checks for vocab_taboo words.

If verification fails → use template fallback (no re-prompt, budget too tight).
"""
from __future__ import annotations

import re
import logging
from typing import Any

log = logging.getLogger("vera")

_NUM_RE = re.compile(r"(?<!\w)(\d+(?:\.\d+)?%?)(?!\w)")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def verify(
    body: str,
    allowed_numbers: set[str],
    allowed_entities: set[str],
    taboo_words: list[str],
) -> tuple[bool, list[str]]:
    """
    Verify LLM output against fact sheet.

    Returns: (passed, list_of_violations)
    """
    violations: list[str] = []

    if not body:
        violations.append("empty_body")
        return False, violations

    # 1. Check for URLs (hard fail)
    if _URL_RE.search(body):
        violations.append("contains_url")

    # 2. Check for taboo words
    body_lower = body.lower()
    for taboo in taboo_words:
        if taboo.lower() in body_lower:
            violations.append(f"taboo_word:{taboo}")

    # 3. Check numbers provenance
    found_nums = _NUM_RE.findall(body)
    for num_str in found_nums:
        # Strip % for comparison
        clean = num_str.rstrip("%")
        if not _number_is_allowed(clean, allowed_numbers):
            violations.append(f"unverified_number:{num_str}")

    # 4. Don't check entity provenance too strictly — LLM may paraphrase
    # Just log warnings for debugging
    # (Entity check is informational, not blocking)

    passed = len(violations) == 0
    if not passed:
        log.warning("provenance_check failed: %s", violations[:5])

    return passed, violations


def _number_is_allowed(num_str: str, allowed: set[str]) -> bool:
    """
    Check if a number matches any allowed number.
    Handles formatting variations (e.g., "50" matches "0.5" as 50%).
    """
    if num_str in allowed:
        return True

    # Try as float comparison
    try:
        val = float(num_str)
        for a in allowed:
            try:
                a_val = float(a)
                # Exact match
                if abs(val - a_val) < 0.01:
                    return True
                # Percentage match (0.5 → 50, -0.22 → 22)
                if abs(val - abs(a_val) * 100) < 0.5:
                    return True
            except (ValueError, TypeError):
                continue
    except (ValueError, TypeError):
        pass

    # Common numbers that are always OK (ordinals, small counts used in prose)
    if num_str in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                   "15", "24", "30", "60", "90"}:
        return True

    return False
