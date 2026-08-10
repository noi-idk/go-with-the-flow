"""Ranking layer: score live candidates against the conversation state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .extraction import VIBE_SYNONYMS
from .search import Candidate
from .state import ConversationState

OUTDOOR_WORDS = [
    "outdoor",
    "beach",
    "park",
    "garden",
    "kayak",
    "hike",
    "hiking",
    "cycling",
    "boardwalk",
    "promenade",
    "desert",
    "cruise",
    "waterfront",
    "rooftop",
    "trail",
]
INDOOR_WORDS = [
    "indoor",
    "museum",
    "gallery",
    "cinema",
    "aquarium",
    "arcade",
    "bowling",
    "spa",
    "escape room",
    "cafe",
    "lounge",
    "climbing wall",
    "trampoline",
    "ice rink",
    "library",
]
EXCLUSION_WORDS = {
    "restaurants": ["restaurant", "dining", "brunch", "eatery", "food hall", "buffet"],
    "shopping": ["shopping", "mall", "outlet", "boutique", "souk"],
    "malls": ["mall", "shopping centre", "shopping center"],
    "beaches": ["beach", "shore", "sand"],
    "museums": ["museum", "gallery", "exhibition"],
    "clubs": ["nightclub", "club night", "clubbing"],
    "bars": ["bar", "pub", "lounge", "happy hour"],
    "cinema": ["cinema", "movie", "film screening"],
    "desert": ["desert", "dune"],
    "crowds": ["crowded", "busy hotspot"],
    "sports": ["match", "stadium", "tournament"],
    "alcohol": ["bar", "pub", "brunch", "cocktail"],
    "theme parks": ["theme park", "waterpark", "water park"],
    "water": ["swim", "waterpark", "water park", "kayak", "diving"],
    "walking": ["walking tour", "hike", "trail"],
}
JUNK_HOSTS = (
    "indeed.",
    "linkedin.",
    "propertyfinder.",
    "dubizzle.",
    "bayut.",
    "wikipedia.",
    "tiktok.",
    "pinterest.",
    "quora.",
    "facebook.",
    "youtube.",
    "dzen.ru",
    "vk.com",
)
JUNK_WORDS = ("jobs", "for sale", "for rent", "hiring", "salary", "visa requirements")
# Booking / listings sites tend to carry the live price and availability we want.
TRUSTED_HOSTS = (
    "platinumlist",
    "visitdubai",
    "timeoutdubai",
    "getyourguide",
    "viator",
    "tripadvisor",
    "headout",
    "dubai.ae",
    "eventbrite",
    "virginmegastore",
    "coca-cola-arena",
)
# A result is only usable if it actually describes something you can go and do.
ACTIVITY_WORDS = (
    "activit",
    "attraction",
    "adventure",
    "aquarium",
    "arcade",
    "beach",
    "bowling",
    "boat",
    "cafe",
    "cinema",
    "class",
    "climb",
    "concert",
    "cruise",
    "cycl",
    "escape room",
    "event",
    "exhibition",
    "experience",
    "gallery",
    "garden",
    "hike",
    "karting",
    "kayak",
    "museum",
    "park",
    "rink",
    "ride",
    "safari",
    "show",
    "skydiv",
    "spa",
    "things to do",
    "ticket",
    "tour",
    "trail",
    "visit",
    "walk",
    "workshop",
)
# Round-up articles are useful context but a poor "go here now" answer.
_PLURALS = r"things|places|activities|attractions|spots|experiences|ideas|adventures"
LISTICLE_RE = re.compile(
    r"^\s*(?:top\s*)?\d{1,3}[\s+]|"  # "15 Amazing …"
    rf"\b\d{{1,3}}\s+(?:\w+\s+){{0,2}}(?:{_PLURALS})\b|"  # "the 10 best outdoor activities"
    rf"\b(?:top|best)\b(?:\s+\w+){{0,3}}\s+(?:{_PLURALS})\b|"  # "best cheap places"
    rf"\b(?:{_PLURALS})\s+(?:in|under|near|to do)\b|"  # "attractions under AED 100"
    r"\b(?:things to do|travel guide|places to visit|guide to)\b",
    re.I,
)
# A tight budget rules out anything whose price we could not confirm.
TIGHT_BUDGET_AED = 60.0
MAX_PER_HOST = 2

# Only genuinely matching options get recommended; a few strong picks beat a long list.
MIN_SCORE = 1.0
# Below this many named places, round-up articles are allowed to fill the remaining slots.
MIN_SPECIFIC = 3

DURATION_HINTS = [
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:-|to)?\s*hours?\b"), lambda m: float(m.group(1))),
    (re.compile(r"\b(\d+)\s*minutes?\b"), lambda m: int(m.group(1)) / 60),
]


@dataclass
class Recommendation:
    candidate: Candidate
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = self.candidate.to_dict()
        data["score"] = round(self.score, 2)
        data["reasons"] = self.reasons
        data["why"] = "; ".join(self.reasons)
        return data


def _matches(text: str, words: list[str]) -> str | None:
    for word in words:
        if word in text:
            return word
    return None


def _matches_word(text: str, words: list[str]) -> str | None:
    """Whole-word match, so "chill" doesn't fire on a venue called "Chillout Lounge"."""
    for word in words:
        if re.search(rf"\b{re.escape(word)}\b", text):
            return word
    return None


def estimated_duration(text: str) -> float | None:
    for pattern, convert in DURATION_HINTS:
        match = pattern.search(text)
        if match:
            return convert(match)
    return None


def violates_exclusions(candidate: Candidate, state: ConversationState) -> str | None:
    text = candidate.text()
    for exclusion in state.exclusions:
        words = EXCLUSION_WORDS.get(exclusion, [exclusion.rstrip("s")])
        hit = _matches(text, words)
        if hit:
            return exclusion
    return None


def is_junk(candidate: Candidate) -> bool:
    host = urlparse(candidate.url).netloc.lower()
    if not candidate.url or not candidate.title:
        return True
    if any(bad in host for bad in JUNK_HOSTS):
        return True
    if not _mostly_english(candidate.title):
        return True
    if not any(word in candidate.text() for word in ACTIVITY_WORDS):
        return True
    return any(bad in candidate.text() for bad in JUNK_WORDS)


def _mostly_english(title: str) -> bool:
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    return sum(c.isascii() for c in letters) / len(letters) >= 0.7


def score_candidate(candidate: Candidate, state: ConversationState) -> tuple[float, list[str]]:
    text = candidate.text()
    score = 0.0
    reasons: list[str] = []

    # Budget
    if state.budget_aed is not None:
        if candidate.is_free or candidate.price_aed == 0:
            score += 3.0
            reasons.append("it's free, so it's well inside your budget")
        elif candidate.price_aed is not None:
            if candidate.price_aed <= state.budget_aed:
                score += 2.5
                reasons.append(f"costs about {candidate.price_aed:g} AED, within your {state.budget_aed:g} AED budget")
            else:
                score -= 2.5 + min(2.0, (candidate.price_aed - state.budget_aed) / max(state.budget_aed, 1))
                reasons.append(f"pricier at ~{candidate.price_aed:g} AED")
        else:
            # An unconfirmed price is a weak answer, and worse the tighter the budget.
            score -= 1.2 if state.budget_aed <= TIGHT_BUDGET_AED else 0.4

    # Environment
    if state.environment in ("outdoor", "indoor"):
        wanted, other = (
            (OUTDOOR_WORDS, INDOOR_WORDS) if state.environment == "outdoor" else (INDOOR_WORDS, OUTDOOR_WORDS)
        )
        hit = _matches(text, wanted)
        if hit:
            score += 2.0
            detail = "" if hit == state.environment else f" ({hit})"
            reasons.append(f"it's {state.environment}s{detail}")
        elif _matches(text, other):
            score -= 2.5
        else:  # nothing says it is the environment they asked for
            score -= 0.8

    # Vibe
    if state.vibe:
        hit = _matches_word(text, VIBE_SYNONYMS.get(state.vibe, [state.vibe]))
        if hit:
            score += 1.8
            reasons.append(f"matches your {state.vibe} mood")

    # Time
    if state.free_time_hours:
        duration = estimated_duration(text)
        if duration is not None:
            if duration <= state.free_time_hours:
                score += 1.2
                reasons.append(f"takes about {duration:g}h, fits your {state.free_time_hours:g}h window")
            else:
                score -= 1.2

    # Location
    if state.location:
        head = state.location.split()[0].lower()
        if head in text:
            score += 1.0
            reasons.append(f"it's in {state.location}")

    # Live info quality
    if candidate.opening_hours or candidate.open_24h:
        score += 0.8
        reasons.append(f"opening hours checked ({candidate.opening_hours})")
    if candidate.verified_at:
        score += 0.4
    if state.open_now and (candidate.open_24h or candidate.opening_hours):
        score += 0.6

    # Interests / group
    for interest in state.interests:
        if interest in text:
            score += 0.8
            reasons.append(f"covers your interest in {interest}")
    if state.age_group == "family" and _matches(text, ["family", "kids", "children"]):
        score += 0.7
        reasons.append("family-friendly")

    if re.search(r"\b(2025|2026|this week|today|tonight|now open)\b", text):
        score += 0.5

    # Prefer a bookable place or event over a round-up article.
    if any(host in candidate.url.lower() for host in TRUSTED_HOSTS):
        score += 0.6
    if len(urlparse(candidate.url).path.strip("/")) < 3:  # a site homepage, not a thing to do
        score -= 1.5
    if re.search(r"\bhotels?\b", candidate.title.lower()):  # somewhere to sleep, not to spend an afternoon
        score -= 1.5

    if LISTICLE_RE.search(candidate.title):
        score -= 1.6
    elif candidate.price_aed is not None or candidate.opening_hours:
        score += 0.8
        reasons.append("it's a specific spot with live details listed")

    return score, reasons


def has_verified_price(candidate: Candidate) -> bool:
    """True when we actually read a price (or "free") off the live listing."""
    return candidate.is_free or candidate.price_aed is not None


def _dedupe_key(candidate: Candidate) -> str:
    words = re.findall(r"[a-z0-9]+", candidate.title.lower())
    return " ".join(words[:4])


def rank(
    candidates: list[Candidate], state: ConversationState, top_n: int = 5
) -> tuple[list[Recommendation], list[Recommendation]]:
    """Return (top recommendations, near-miss fallbacks)."""
    kept: list[Recommendation] = []
    near_misses: list[Recommendation] = []
    seen: set[str] = set()
    per_host: dict[str, int] = {}

    for candidate in candidates:
        if is_junk(candidate):
            continue
        key = _dedupe_key(candidate)
        if key in seen:  # the same venue surfaced by several queries
            continue
        host = urlparse(candidate.url).netloc.lower()
        if per_host.get(host, 0) >= MAX_PER_HOST:  # don't hand back one site's article five times
            continue
        seen.add(key)
        per_host[host] = per_host.get(host, 0) + 1
        excluded = violates_exclusions(candidate, state)
        score, reasons = score_candidate(candidate, state)
        if excluded:
            near_misses.append(
                Recommendation(candidate, score - 5, [f"but it involves {excluded}, which you ruled out"] + reasons)
            )
            continue
        over_budget = (
            state.budget_aed is not None and candidate.price_aed is not None and candidate.price_aed > state.budget_aed
        )
        if state.budget_aed is not None and not has_verified_price(candidate):
            reasons.insert(0, f"price not available, so I can't promise it fits your {state.budget_aed:g} AED budget")
        (near_misses if over_budget else kept).append(Recommendation(candidate, score, reasons))

    # An unconfirmed price never outranks one we checked, and a round-up article never outranks a
    # named place: sort by those two tiers first, score second.
    ranked = sorted(
        (r for r in kept if r.score >= MIN_SCORE),
        key=lambda r: (
            0 if has_verified_price(r.candidate) else 1,
            1 if LISTICLE_RE.search(r.candidate.title) else 0,
            -r.score,
        ),
    )
    specific = [r for r in ranked if not LISTICLE_RE.search(r.candidate.title)]
    strong = ranked[:top_n] if len(specific) < MIN_SPECIFIC else specific[:top_n]

    leftovers = [r for r in ranked if r not in strong]
    fallbacks = sorted(
        near_misses + leftovers + [r for r in kept if r.score < MIN_SCORE], key=lambda r: r.score, reverse=True
    )
    return strong, fallbacks[:3]
