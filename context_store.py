"""
context_store.py — In-memory versioned context store.

- Idempotent by (scope, context_id, version)
- Returns 409 for version <= current
- Tracks before/after deltas on version bumps for performance data
- Wipes all state on teardown
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("vera")

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}


class ContextEntry:
    """Single versioned context entry."""
    __slots__ = ("scope", "context_id", "version", "payload", "stored_at", "prev_payload")

    def __init__(self, scope: str, context_id: str, version: int,
                 payload: dict[str, Any], stored_at: str):
        self.scope = scope
        self.context_id = context_id
        self.version = version
        self.payload = payload
        self.stored_at = stored_at
        self.prev_payload: Optional[dict[str, Any]] = None  # for before/after deltas


class ContextStore:
    """Thread-safe (single-worker) in-memory context store."""

    def __init__(self):
        # (scope, context_id) -> ContextEntry
        self._store: dict[tuple[str, str], ContextEntry] = {}

    # ── Push ─────────────────────────────────────────────────────────────────

    def push(self, scope: str, context_id: str, version: int,
             payload: dict[str, Any]) -> tuple[str, Optional[str], Optional[int]]:
        """
        Push a context. Returns (status, ack_id_or_reason, current_version).
        status: "accepted" | "stale" | "invalid"
        """
        if scope not in VALID_SCOPES:
            return "invalid", f"invalid_scope: {scope}", None

        key = (scope, context_id)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        existing = self._store.get(key)
        if existing and existing.version >= version:
            return "stale", "stale_version", existing.version

        # Store before/after for merchant performance deltas
        entry = ContextEntry(scope, context_id, version, payload, now_iso)
        if existing:
            entry.prev_payload = existing.payload

        self._store[key] = entry
        ack_id = f"ack_{context_id}_v{version}"

        log.info("context_push scope=%s id=%s v=%d", scope, context_id, version)
        return "accepted", ack_id, None

    # ── Get ──────────────────────────────────────────────────────────────────

    def get(self, scope: str, context_id: str) -> Optional[dict[str, Any]]:
        """Get payload for a context. Returns None if not found."""
        entry = self._store.get((scope, context_id))
        return entry.payload if entry else None

    def get_entry(self, scope: str, context_id: str) -> Optional[ContextEntry]:
        """Get full entry (including prev_payload for deltas)."""
        return self._store.get((scope, context_id))

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        """Get current version. Returns None if not found."""
        entry = self._store.get((scope, context_id))
        return entry.version if entry else None

    # ── Query ────────────────────────────────────────────────────────────────

    def get_merchant(self, merchant_id: str) -> Optional[dict[str, Any]]:
        return self.get("merchant", merchant_id)

    def get_category(self, slug: str) -> Optional[dict[str, Any]]:
        return self.get("category", slug)

    def get_customer(self, customer_id: str) -> Optional[dict[str, Any]]:
        return self.get("customer", customer_id)

    def get_trigger(self, trigger_id: str) -> Optional[dict[str, Any]]:
        return self.get("trigger", trigger_id)

    def get_category_for_merchant(self, merchant_id: str) -> Optional[dict[str, Any]]:
        """Look up the category context for a merchant."""
        merchant = self.get_merchant(merchant_id)
        if not merchant:
            return None
        slug = merchant.get("category_slug", "")
        return self.get_category(slug) if slug else None

    def get_perf_delta(self, merchant_id: str) -> Optional[dict[str, Any]]:
        """Get before/after performance delta if a version bump happened."""
        entry = self.get_entry("merchant", merchant_id)
        if not entry or not entry.prev_payload:
            return None
        old_perf = entry.prev_payload.get("performance", {})
        new_perf = entry.payload.get("performance", {})
        if not old_perf or not new_perf:
            return None
        delta = {}
        for key in ("views", "calls", "directions", "ctr"):
            old_val = old_perf.get(key)
            new_val = new_perf.get(key)
            if old_val is not None and new_val is not None:
                delta[f"{key}_old"] = old_val
                delta[f"{key}_new"] = new_val
                delta[f"{key}_change"] = new_val - old_val
        return delta if delta else None

    # ── Counts ───────────────────────────────────────────────────────────────

    def counts(self) -> dict[str, int]:
        """Count entries per scope for /v1/healthz."""
        result = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _) in self._store:
            if scope in result:
                result[scope] += 1
        return result

    # ── Teardown ─────────────────────────────────────────────────────────────

    def wipe(self):
        """Clear all state. Called by POST /v1/teardown."""
        self._store.clear()
        log.info("context_store wiped")
