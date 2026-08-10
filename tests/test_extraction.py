from app.extraction import apply_utterance
from app.state import ConversationState


def turn(state, text, last_prices=None):
    return apply_utterance(state, text, last_prices)[0]


def test_extracts_slots_from_one_dense_utterance():
    state = turn(
        ConversationState(),
        "I'm in Downtown Dubai, I've got two hours, 50 AED, and I don't want restaurants. Something relaxing.",
    )
    assert state.location == "Downtown Dubai"
    assert state.free_time_hours == 2
    assert state.budget_aed == 50
    assert state.exclusions == ["restaurants"]
    assert state.vibe == "chill"


def test_progressive_collection_across_turns():
    state = ConversationState()
    state = turn(state, "I have about three hours free and I don't know what to do.")
    assert state.free_time_hours == 3
    state = turn(state, "I'm in Dubai and maybe around 100 AED.")
    assert (state.location, state.budget_aed) == ("Dubai", 100)
    state = turn(state, "Chill, and preferably outdoors.")
    assert (state.vibe, state.environment) == ("chill", "outdoor")
    assert state.free_time_hours == 3 and state.budget_aed == 100


def test_too_expensive_lowers_only_budget():
    state = ConversationState(location="Dubai", free_time_hours=3, budget_aed=150, vibe="fun", exclusions=["shopping"])
    state = turn(state, "That's too expensive. Give me something cheaper.", last_prices=[140, 20])
    assert state.budget_aed == 84  # anchored on the 140 AED option the user reacted to
    assert (state.location, state.free_time_hours, state.vibe) == ("Dubai", 3, "fun")
    assert state.exclusions == ["shopping"]


def test_mood_change_keeps_other_slots():
    state = ConversationState(location="Dubai", free_time_hours=4, budget_aed=200, vibe="chill", environment="outdoor")
    state = turn(state, "Actually, I'm feeling more active now.")
    assert state.vibe in ("active", "adventurous")
    assert (state.free_time_hours, state.budget_aed, state.environment) == (4, 200, "outdoor")


def test_no_outdoors_flips_environment_only():
    state = ConversationState(location="Dubai", environment="outdoor", budget_aed=80, vibe="chill")
    state = turn(state, "I don't want anything outdoors.")
    assert state.environment == "indoor"
    assert state.budget_aed == 80


def test_closer_shrinks_distance():
    state = turn(ConversationState(location="Dubai", max_distance_km=20), "What about somewhere closer?")
    assert state.max_distance_km == 10


def test_only_one_hour():
    state = turn(ConversationState(free_time_hours=3), "Actually, I only have one hour.")
    assert state.free_time_hours == 1


def test_less_time_without_number_halves():
    state = turn(ConversationState(free_time_hours=4), "I have less time than I thought.")
    assert state.free_time_hours == 2


def test_open_now_and_extras():
    state = turn(ConversationState(), "Can you find something open right now for four of us tonight, we're driving")
    assert state.open_now is True
    assert state.party_size == 4
    assert state.time_of_day == "tonight"
    assert state.transport == "car"


def test_either_environment_and_free_budget():
    state = turn(ConversationState(), "Either is fine, and I'd rather find something free")
    assert state.environment == "either"
    assert state.budget_aed == 0


def test_free_time_is_not_a_zero_budget():
    state = turn(ConversationState(), "I have about three hours free and I don't know what to do")
    assert state.free_time_hours == 3
    assert state.budget_aed is None


def test_cheaper_does_not_collapse_budget_when_options_were_cheap():
    state = turn(ConversationState(budget_aed=100), "too expensive", last_prices=[10])
    assert state.budget_aed == 25


def test_minutes_and_family():
    state = turn(ConversationState(), "We have 90 minutes with the kids in Al Barsha")
    assert state.free_time_hours == 1.5
    assert state.age_group == "family"
    assert state.location == "Al Barsha"


def test_readiness_and_summary():
    state = ConversationState(location="Dubai", free_time_hours=2, budget_aed=100)
    assert state.is_ready()
    assert "Dubai" in state.summary() and "2 hours" in state.summary()
    assert not ConversationState(free_time_hours=2, budget_aed=100).is_ready()
