"""
suppression.py — Global suppression + per-merchant fatigue caps.

Suppression is by suppression_key (global) AND per merchant with fatigue caps.
NOT per conversation — the simulator uses new conv_ids per turn.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import MAX_SENDS_PER_MERCHANT_PER_DAY, MIN_SECONDS_BETWEEN_SENDS

log = logging.getLogger("vera")


class SuppressionStore:
    """Global suppression keys + per-merchant fatigue."""

    def __init__(self):
        self._sent_keys: set[str] = set()
        self._merchant_sends_today: dict[str, int] = {}         # merchant_id -> count
        self._merchant_last_send: dict[str, datetime] = {}      # merchant_id -> last send time
        self._merchant_opted_out: set[str] = set()               # permanently suppressed merchants
        self._today: str = ""                                     # day string for daily reset

    def _maybe_reset_day(self):
        """Reset daily counters at midnight."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today:
            self._today = today
            self._merchant_sends_today.clear()

    def can_send(self, merchant_id: str, suppression_key: str) -> tuple[bool, str]:
        """
        Check if we can send. Returns (allowed, reason).
        reason is "" if allowed, otherwise explains why blocked.
        """
        self._maybe_reset_day()

        # 1. Merchant opted out?
        if merchant_id in self._merchant_opted_out:
            return False, "merchant_opted_out"

        # 2. Global suppression key already sent?
        if suppression_key and suppression_key in self._sent_keys:
            return False, f"suppression_key_sent:{suppression_key}"

        # 3. Per-merchant daily fatigue cap
        sends = self._merchant_sends_today.get(merchant_id, 0)
        if sends >= MAX_SENDS_PER_MERCHANT_PER_DAY:
            return False, f"fatigue_cap:{sends}/{MAX_SENDS_PER_MERCHANT_PER_DAY}"

        # 4. Per-merchant cooldown
        last = self._merchant_last_send.get(merchant_id)
        if last:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < MIN_SECONDS_BETWEEN_SENDS:
                return False, f"cooldown:{int(elapsed)}s/{MIN_SECONDS_BETWEEN_SENDS}s"

        return True, ""

    def record_send(self, merchant_id: str, suppression_key: str):
        """Record that we sent a message."""
        self._maybe_reset_day()
        if suppression_key:
            self._sent_keys.add(suppression_key)
        self._merchant_sends_today[merchant_id] = self._merchant_sends_today.get(merchant_id, 0) + 1
        self._merchant_last_send[merchant_id] = datetime.now(timezone.utc)
        log.info("suppression_record merchant=%s key=%s", merchant_id, suppression_key)

    def opt_out_merchant(self, merchant_id: str):
        """Permanently suppress a merchant (hostile opt-out)."""
        self._merchant_opted_out.add(merchant_id)
        log.info("merchant_opted_out merchant=%s", merchant_id)

    def wipe(self):
        """Clear all state on teardown."""
        self._sent_keys.clear()
        self._merchant_sends_today.clear()
        self._merchant_last_send.clear()
        self._merchant_opted_out.clear()
        self._today = ""
