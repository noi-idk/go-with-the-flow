"""Natural-language slot extraction and conversational refinement.

Turns free-form (often voice-transcribed) utterances into updates on a
:class:`~app.state.ConversationState`. Refinements such as "too expensive" or
"somewhere closer" touch only the slot they refer to.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .state import ConversationState

WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "hundred": 100,
    "couple": 2,
    "few": 3,
    "half": 0.5,
}

VIBE_SYNONYMS = {
    "chill": [
        "chill",
        "relaxing",
        "relaxed",
        "calm",
        "quiet",
        "laid back",
        "laid-back",
        "peaceful",
        "mellow",
    ],
    "active": ["active", "sporty", "energetic", "workout", "moving", "physical"],
    "adventurous": ["adventurous", "adventure", "thrilling", "thrill", "extreme", "adrenaline", "wild"],
    "fun": ["fun", "exciting", "lively", "playful", "entertaining"],
    "romantic": ["romantic", "date night", "date-night", "romance"],
    "cultural": ["cultural", "culture", "artsy", "art", "museum", "historic", "heritage"],
    "social": ["social", "with friends", "meet people", "nightlife"],
}

# Vibes ordered from calmest to most intense, used by "more exciting"-style refinements.
VIBE_INTENSITY = ["chill", "cultural", "romantic", "social", "fun", "active", "adventurous"]

EXCLUSION_NOUNS = [
    "restaurants",
    "restaurant",
    "shopping",
    "malls",
    "mall",
    "beaches",
    "beach",
    "museums",
    "museum",
    "clubs",
    "clubbing",
    "bars",
    "cinema",
    "movies",
    "desert",
    "driving",
    "walking",
    "crowds",
    "crowded places",
    "water",
    "sports",
    "alcohol",
    "theme parks",
]

# Recognised places; keeps location detection reliable on lowercase voice transcripts.
KNOWN_PLACES = [
    "downtown dubai",
    "dubai marina",
    "business bay",
    "jumeirah beach residence",
    "jbr",
    "jumeirah",
    "deira",
    "bur dubai",
    "al barsha",
    "al quoz",
    "al karama",
    "karama",
    "silicon oasis",
    "dubai hills",
    "palm jumeirah",
    "city walk",
    "la mer",
    "dubai creek",
    "international city",
    "motor city",
    "jvc",
    "jumeirah village circle",
    "mirdif",
    "dubai",
    "abu dhabi",
    "yas island",
    "saadiyat island",
    "al ain",
    "sharjah",
    "ajman",
    "fujairah",
    "ras al khaimah",
    "umm al quwain",
]

_TIME_OF_DAY = ["morning", "afternoon", "evening", "tonight", "night", "midday", "noon", "sunset", "sunrise"]


def _num(token: str) -> float | None:
    token = token.strip().lower()
    if not token:
        return None
    try:
        return float(token)
    except ValueError:
        return WORD_NUMBERS.get(token)


def _search_any(text: str, patterns: Iterable[str]) -> re.Match | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match
    return None


def extract_free_time(text: str) -> float | None:
    if re.search(r"\bhalf an hour\b", text):
        return 0.5
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+)\s*(?:min|mins|minute|minutes)\b", text)
    if match:
        return round(int(match.group(1)) / 60, 2)
    match = re.search(
        r"\b(a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|couple|few)\s+"
        r"(?:of\s+)?(?:h|hr|hrs|hour|hours)\b",
        text,
    )
    if match:
        return _num(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*and\s*a\s*half\s*hours?\b", text)
    if match:
        return float(match.group(1)) + 0.5
    return None


def extract_budget(text: str) -> float | None:
    # "free" only counts when it is about money, not "three hours free" / "free time".
    if re.search(
        r"\b(for free|something free|free (?:activit|entry|option|stuff|thing)|no money|zero budget|"
        r"don'?t want to spend|spend nothing|without spending)",
        text,
    ):
        return 0.0
    match = _search_any(
        text,
        [
            r"(?:aed|dhs?|dirhams?)\s*(\d+(?:\.\d+)?)",
            r"(\d+(?:\.\d+)?)\s*(?:aed|dhs?|dirhams?|bucks)",
            r"(?:budget|spend|under|below|less than|max(?:imum)?|around|about|up to)\s*(?:of\s*)?(\d+(?:\.\d+)?)",
        ],
    )
    if match:
        return float(match.group(1))
    return None


def extract_location(text: str, raw: str) -> str | None:
    for place in KNOWN_PLACES:  # longest names first
        if re.search(rf"\b{re.escape(place)}\b", text):
            return _titlecase_place(place)
    match = re.search(
        r"\b(?:i'?m in|i am in|im in|i'?m at|currently in|staying in|based in|in|at|near|around)\s+"
        r"([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+){0,3})",
        raw,
    )
    if match:
        return match.group(1).strip()
    return None


def _titlecase_place(place: str) -> str:
    upper = {"jbr", "jvc"}
    return " ".join(w.upper() if w in upper else w.capitalize() for w in place.split())


def extract_vibe(text: str) -> str | None:
    for vibe, words in VIBE_SYNONYMS.items():
        for word in words:
            if re.search(rf"(?<!not )(?<!no ){re.escape(word)}\b", text):
                return vibe
    return None


def extract_environment(text: str) -> str | None:
    if re.search(r"\b(either|both|doesn'?t matter|don'?t mind|no preference|whatever)\b", text):
        return "either"
    negated_outdoor = re.search(r"\b(?:no|not|don'?t want|nothing|avoid)\b[^.!?]{0,20}\boutdoors?\b", text)
    negated_indoor = re.search(r"\b(?:no|not|don'?t want|nothing|avoid)\b[^.!?]{0,20}\bindoors?\b", text)
    if negated_outdoor:
        return "indoor"
    if negated_indoor:
        return "outdoor"
    if re.search(r"\b(outdoors?|outside|open air|fresh air)\b", text):
        return "outdoor"
    if re.search(r"\b(indoors?|inside|air conditioned|air-conditioned|aircon)\b", text):
        return "indoor"
    return None


def extract_exclusions(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(
        r"\b(?:no|not|don'?t want|do not want|nothing|without|avoid|skip|hate|except)\b\s+"
        r"(?:any\s+|the\s+|more\s+)?([a-z][a-z \-]{2,30})",
        text,
    ):
        phrase = match.group(1).strip()
        for noun in EXCLUSION_NOUNS:
            if re.match(rf"^{re.escape(noun)}\b", phrase):
                found.append(_singularish(noun))
                break
    return found


def _singularish(noun: str) -> str:
    mapping = {
        "restaurant": "restaurants",
        "mall": "malls",
        "beach": "beaches",
        "museum": "museums",
        "movies": "cinema",
        "clubbing": "clubs",
        "crowded places": "crowds",
    }
    return mapping.get(noun, noun)


def extract_party_size(text: str) -> int | None:
    match = re.search(
        r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten|couple|few)\s+"
        r"(?:of us|people|persons|friends|guests|adults)\b",
        text,
    )
    if match:
        value = _num(match.group(1))
        return int(value) if value else None
    if re.search(r"\b(just me|by myself|alone|solo)\b", text):
        return 1
    return None


def extract_time_of_day(text: str) -> str | None:
    for slot in _TIME_OF_DAY:
        if re.search(rf"\b{slot}\b", text):
            return slot
    return None


def extract_distance(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kilometers?|kilometres?)\b", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+)\s*(?:min|mins|minutes)\s*(?:away|drive|walk)", text)
    if match:  # rough conversion, ~1 km per driving minute in-city
        return float(match.group(1))
    return None


def extract_transport(text: str) -> str | None:
    if re.search(r"\b(walk|walking|on foot|walkable)\b", text):
        return "walking"
    if re.search(r"\b(metro|tram|bus|public transport)\b", text):
        return "public transport"
    if re.search(r"\b(driving|my car|i'?m driving|taxi|uber|careem)\b", text):
        return "car"
    return None


def extract_age_group(text: str) -> str | None:
    if re.search(r"\b(kids?|children|family|toddlers?|family-friendly)\b", text):
        return "family"
    if re.search(r"\b(teens?|teenagers?)\b", text):
        return "teens"
    if re.search(r"\b(adults? only|no kids)\b", text):
        return "adults"
    return None


def apply_utterance(
    state: ConversationState,
    utterance: str,
    last_prices: list[float] | None = None,
) -> tuple[ConversationState, list[str]]:
    """Update ``state`` in place from one user turn; return it plus a change log."""
    raw = utterance.strip()
    text = raw.lower()
    changes: list[str] = []

    def set_slot(name: str, value: object, note: str) -> None:
        if value is None:
            return
        if getattr(state, name) != value:
            setattr(state, name, value)
            changes.append(note)

    changes += _apply_refinements(state, text, last_prices)

    set_slot("free_time_hours", extract_free_time(text), "time")
    budget = extract_budget(text)
    if budget is not None and not _is_pure_refinement(text):
        set_slot("budget_aed", budget, "budget")
    set_slot("location", extract_location(text, raw), "location")
    set_slot("vibe", extract_vibe(text), "vibe")
    set_slot("environment", extract_environment(text), "environment")
    set_slot("party_size", extract_party_size(text), "group size")
    set_slot("time_of_day", extract_time_of_day(text), "time of day")
    set_slot("max_distance_km", extract_distance(text), "distance")
    set_slot("transport", extract_transport(text), "transport")
    set_slot("age_group", extract_age_group(text), "age group")

    for exclusion in extract_exclusions(text):
        before = list(state.exclusions)
        state.add_exclusion(exclusion)
        if state.exclusions != before:
            changes.append(f"excluding {exclusion}")

    if re.search(r"\bopen (?:right )?now\b|\bopen at the moment\b|\bcurrently open\b", text):
        state.open_now = True
        changes.append("open now")

    return state, list(dict.fromkeys(changes))


def _is_pure_refinement(text: str) -> bool:
    """True for phrases like "cheaper" that imply a budget change without a number."""
    return bool(re.search(r"\b(cheaper|too expensive|less expensive|lower budget)\b", text)) and not re.search(
        r"\d", text
    )


def _apply_refinements(state: ConversationState, text: str, last_prices: list[float] | None) -> list[str]:
    changes: list[str] = []

    if re.search(r"\b(too expensive|cheaper|less expensive|lower the budget|too pricey|too much money)\b", text):
        # Anchor on what the user is reacting to: the price of the top option they just heard.
        anchor = next((p for p in (last_prices or []) if p > 0), None)
        current = state.budget_aed
        reference = min([v for v in (anchor, current) if v], default=50.0)
        new_budget = 0.6 * reference
        if current:  # never collapse the budget to something absurdly small
            new_budget = min(max(new_budget, 0.25 * current), current)
        state.budget_aed = float(round(new_budget))
        changes.append("budget")

    if re.search(r"\b(spend more|higher budget|money is no|splurge|treat myself)\b", text):
        state.budget_aed = round((state.budget_aed or 100) * 1.75)
        changes.append("budget")

    if re.search(r"\b(closer|nearby|near me|around here|walking distance|not far)\b", text):
        current = state.max_distance_km or 15.0
        state.max_distance_km = max(1.0, round(current / 2, 1))
        changes.append("distance")

    if re.search(r"\b(more exciting|more active|more fun|something wilder|more adventurous|less boring)\b", text):
        state.vibe = _shift_vibe(state.vibe, +2)
        changes.append("vibe")

    if re.search(r"\b(calmer|more chill|more relaxing|less intense|quieter|slower)\b", text):
        state.vibe = _shift_vibe(state.vibe, -2)
        changes.append("vibe")

    if re.search(r"\b(less time|shorter|quicker|faster|only have)\b", text) and not re.search(
        r"\d+\s*(?:h|hr|hour|min)", text
    ):
        if state.free_time_hours:
            state.free_time_hours = max(0.5, round(state.free_time_hours / 2, 2))
            changes.append("time")

    return changes


def _shift_vibe(vibe: str | None, delta: int) -> str:
    if vibe not in VIBE_INTENSITY:
        return "active" if delta > 0 else "chill"
    index = VIBE_INTENSITY.index(vibe)
    return VIBE_INTENSITY[max(0, min(len(VIBE_INTENSITY) - 1, index + delta))]
