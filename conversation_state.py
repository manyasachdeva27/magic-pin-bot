"""
conversation_state.py — Per-MERCHANT conversation state (not per-conversation).

The simulator uses a new conversation_id every turn, so tracking state
per conversation_id is useless. We track per merchant_id instead.

Also maintains conversation history for reply context.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("vera")


@dataclass
class ConversationTurn:
    """A single turn in any conversation."""
    conversation_id: str
    from_role: str          # "vera" | "merchant" | "customer"
    body: str
    timestamp: str
    turn_number: int = 0
    trigger_id: Optional[str] = None


@dataclass
class MerchantState:
    """Aggregated state for a merchant across ALL conversation_ids."""
    merchant_id: str
    auto_reply_count: int = 0              # across all conv_ids
    last_auto_reply_at: Optional[datetime] = None
    last_topic: str = ""                    # trigger kind of last message
    last_trigger_id: str = ""               # for reply context
    turns: list[ConversationTurn] = field(default_factory=list)
    active_conv_id: Optional[str] = None    # most recent conv_id

    def record_auto_reply(self):
        self.auto_reply_count += 1
        self.last_auto_reply_at = datetime.now(timezone.utc)

    def reset_auto_reply(self):
        """Reset when a real (non-auto) reply arrives."""
        self.auto_reply_count = 0

    def add_turn(self, turn: ConversationTurn):
        self.turns.append(turn)
        self.active_conv_id = turn.conversation_id

    def recent_turns(self, n: int = 6) -> list[ConversationTurn]:
        """Last N turns for prompt context."""
        return self.turns[-n:]


class ConversationStateStore:
    """Manages per-merchant state across all conversations."""

    def __init__(self):
        self._merchants: dict[str, MerchantState] = {}
        # conv_id -> merchant_id mapping for reply routing
        self._conv_to_merchant: dict[str, str] = {}

    def get_or_create(self, merchant_id: str) -> MerchantState:
        if merchant_id not in self._merchants:
            self._merchants[merchant_id] = MerchantState(merchant_id=merchant_id)
        return self._merchants[merchant_id]

    def register_conv(self, conversation_id: str, merchant_id: str):
        """Map a conversation_id to a merchant_id."""
        self._conv_to_merchant[conversation_id] = merchant_id

    def merchant_for_conv(self, conversation_id: str) -> Optional[str]:
        """Look up merchant_id for a conversation_id."""
        return self._conv_to_merchant.get(conversation_id)

    def record_bot_send(self, merchant_id: str, conversation_id: str,
                        body: str, trigger_id: str, trigger_kind: str):
        """Record that the bot sent a proactive message."""
        state = self.get_or_create(merchant_id)
        state.last_topic = trigger_kind
        state.last_trigger_id = trigger_id
        state.add_turn(ConversationTurn(
            conversation_id=conversation_id,
            from_role="vera",
            body=body,
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            trigger_id=trigger_id,
        ))
        self.register_conv(conversation_id, merchant_id)

    def record_reply(self, merchant_id: str, conversation_id: str,
                     from_role: str, message: str, turn_number: int):
        """Record an incoming reply."""
        state = self.get_or_create(merchant_id)
        state.add_turn(ConversationTurn(
            conversation_id=conversation_id,
            from_role=from_role,
            body=message,
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            turn_number=turn_number,
        ))
        self.register_conv(conversation_id, merchant_id)

    def wipe(self):
        """Clear all state on teardown."""
        self._merchants.clear()
        self._conv_to_merchant.clear()
