"""Dialogue manager: decides whether to ask, search, or refine, and speaks back."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .extraction import apply_utterance
from .recommend import Recommendation, rank
from .search import Candidate, live_search
from .state import SLOT_QUESTIONS, ConversationState

ASK_ORDER = ["location", "free_time_hours", "budget_aed", "vibe", "environment"]

OPENERS = [
    "Let's fix that.",
    "Sure!",
    "Got it.",
    "Nice \u2014 let's find you something.",
    "Okay, on it.",
]


@dataclass
class Session:
    state: ConversationState = field(default_factory=ConversationState)
    last_prices: list[float] = field(default_factory=list)
    turns: int = 0
    searched_once: bool = False


class Assistant:
    """Voice-first conversation loop over the slot state and live search."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def session(self, session_id: str) -> Session:
        return self._sessions.setdefault(session_id, Session())

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def handle(self, session_id: str, utterance: str) -> dict[str, Any]:
        session = self.session(session_id)
        session.turns += 1
        state, changes = apply_utterance(session.state, utterance, session.last_prices)
        session.state = state

        missing = [slot for slot in ASK_ORDER if getattr(state, slot) in (None, "", [])]
        if not state.is_ready() and missing:
            return {
                "reply": self._ask(state, missing, changes, session),
                "state": state.to_dict(),
                "recommendations": [],
                "changed": changes,
                "searching": False,
            }

        candidates = await live_search(state)
        top, near = rank(candidates, state)
        session.searched_once = True
        session.last_prices = [r.candidate.price_aed for r in top if r.candidate.price_aed not in (None, 0)]

        return {
            "reply": self._present(state, top, near, changes, session),
            "state": state.to_dict(),
            "recommendations": [r.to_dict() for r in top],
            "alternatives": [r.to_dict() for r in near] if not top else [],
            "changed": changes,
            "searching": True,
            "queries_used": sorted({c.query for c in candidates}),
        }

    def _ask(
        self,
        state: ConversationState,
        missing: list[str],
        changes: list[str],
        session: Session,
    ) -> str:
        acknowledgement = ""
        if changes:
            acknowledgement = f"Got it \u2014 {state.summary()}. "
        elif session.turns == 1:
            acknowledgement = random.choice(OPENERS) + " "

        # Ask for at most two closely-related things so it stays conversational.
        first = missing[0]
        question = SLOT_QUESTIONS[first]
        if first == "location" and "budget_aed" in missing:
            question = "Where are you right now, and roughly how much do you want to spend?"
        elif first == "free_time_hours" and "budget_aed" in missing:
            question = "How much time have you got, and what's your budget?"
        return acknowledgement + question

    def _present(
        self,
        state: ConversationState,
        top: list[Recommendation],
        near: list[Recommendation],
        changes: list[str],
        session: Session,
    ) -> str:
        if changes and session.searched_once:
            kept = state.summary()
            lead = f"No problem \u2014 keeping {kept}, here's what I found. "
        else:
            lead = f"Looking for {state.summary()}\u2026 "

        if not top:
            if near:
                closest = near[0].candidate.title
                return (
                    lead + "I couldn't find anything that ticks every box right now \u2014 the live listings "
                    f"either go over your budget or hit something you ruled out. The closest is {closest}. "
                    "Want me to stretch the budget a little or drop one of the filters?"
                )
            return (
                lead + "I came up empty on live listings for that combination. Try widening the area or "
                "the budget and I'll search again."
            )

        lines = [lead + f"Here {'are' if len(top) > 1 else 'is'} my top {len(top)}:"]
        for index, rec in enumerate(top, start=1):
            reason = rec.reasons[0] if rec.reasons else "it lines up with what you asked for"
            price = _price_label(rec.candidate)
            lines.append(f"{index}. {rec.candidate.title}{price} \u2014 {reason}.")
        lines.append("Want something cheaper, closer, or a different vibe?")
        return " ".join(lines)


def _price_label(candidate: Candidate) -> str:
    if candidate.is_free or candidate.price_aed == 0:
        return " (free)"
    if candidate.price_aed is not None:
        return f" (~{candidate.price_aed:g} AED)"
    return ""


def make_state(payload: dict[str, Any] | None) -> ConversationState:
    return ConversationState.from_dict(payload or {})
