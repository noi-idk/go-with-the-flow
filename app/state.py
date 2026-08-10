"""Conversation state for the Go-with-the-Flow assistant."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Environment = Literal["indoor", "outdoor", "either"]

REQUIRED_SLOTS = ("location", "free_time_hours", "budget_aed", "vibe", "environment")

# Ordered by how naturally the assistant should ask for them.
SLOT_QUESTIONS = {
    "location": "Where are you right now?",
    "free_time_hours": "How much time have you got?",
    "budget_aed": "Roughly how much would you like to spend?",
    "vibe": "What kind of mood are you in \u2014 chill, active, or a bit adventurous?",
    "environment": "Indoor or outdoor \u2014 or doesn't it matter?",
}


@dataclass
class ConversationState:
    """Structured slots the assistant maintains across the whole conversation.

    Only the fields a user actually talks about are set; a refinement updates the
    single field it refers to and leaves everything else untouched.
    """

    location: str | None = None
    free_time_hours: float | None = None
    budget_aed: float | None = None
    exclusions: list[str] = field(default_factory=list)
    vibe: str | None = None
    environment: Environment | None = None

    # Optional extras
    party_size: int | None = None
    age_group: str | None = None
    transport: str | None = None
    max_distance_km: float | None = None
    interests: list[str] = field(default_factory=list)
    time_of_day: str | None = None
    open_now: bool = False

    def missing_required(self) -> list[str]:
        return [s for s in REQUIRED_SLOTS if getattr(self, s) in (None, [], "")]

    def is_ready(self) -> bool:
        """Enough to search: we always need a place, plus two other strong signals."""
        if not self.location:
            return False
        known = sum(1 for s in ("free_time_hours", "budget_aed", "vibe", "environment") if getattr(self, s) is not None)
        return known >= 2

    def add_exclusion(self, item: str) -> None:
        item = item.strip().lower()
        if item and item not in self.exclusions:
            self.exclusions.append(item)

    def add_interest(self, item: str) -> None:
        item = item.strip().lower()
        if item and item not in self.interests:
            self.interests.append(item)

    def summary(self) -> str:
        bits: list[str] = []
        if self.location:
            bits.append(self.location)
        if self.free_time_hours:
            hours = self.free_time_hours
            bits.append(f"{hours:g} hour{'s' if hours != 1 else ''}")
        if self.budget_aed is not None:
            bits.append(f"around {self.budget_aed:g} AED")
        if self.vibe:
            bits.append(f"{self.vibe} vibe")
        if self.environment and self.environment != "either":
            bits.append(self.environment)
        if self.time_of_day:
            bits.append(self.time_of_day)
        if self.party_size:
            bits.append(f"{self.party_size} people")
        if self.exclusions:
            bits.append("no " + ", no ".join(self.exclusions))
        if self.open_now:
            bits.append("open right now")
        return ", ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationState:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})
