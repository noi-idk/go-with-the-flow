from app.recommend import is_junk, rank, score_candidate, violates_exclusions
from app.search import Candidate, build_queries, enrich_from_text, expand_roundup
from app.state import ConversationState


def candidate(title, snippet, url="https://example.com/a", **kwargs):
    return Candidate(title=title, url=url, snippet=snippet, **kwargs)


def test_queries_reflect_state():
    state = ConversationState(
        location="Downtown Dubai", budget_aed=50, vibe="chill", environment="outdoor", free_time_hours=2
    )
    queries = build_queries(state)
    joined = " ".join(queries).lower()
    assert "downtown dubai" in joined
    assert "chill" in joined and "outdoor" in joined and "under 50 aed" in joined


def test_price_and_hours_extracted_from_live_text():
    hit = candidate("Kite Beach", "Entry from AED 45 per person, open 9:00 am - 11:00 pm daily")
    enrich_from_text(hit, hit.text())
    assert hit.price_aed == 45
    assert hit.opening_hours is not None


def test_free_entry_detected():
    hit = candidate("Al Seef promenade", "Free entry, open 24 hours")
    enrich_from_text(hit, hit.text())
    assert hit.is_free and hit.price_aed == 0 and hit.open_24h


def test_exclusions_filter_results():
    state = ConversationState(location="Dubai", budget_aed=100, exclusions=["restaurants"], vibe="chill")
    assert violates_exclusions(candidate("Top brunch", "best restaurant dining in Dubai"), state) == "restaurants"
    assert violates_exclusions(candidate("Kayaking", "paddle the creek"), state) is None


def test_ranking_prefers_in_budget_matching_vibe_outdoors():
    state = ConversationState(location="Dubai", budget_aed=100, vibe="chill", environment="outdoor", free_time_hours=3)
    good = candidate(
        "Chill sunset kayak at Hatta",
        "relaxing outdoor kayak in Dubai, AED 60, 2 hours, open 8 am - 6 pm",
        url="https://a.example/kayak",
    )
    pricey = candidate("Indoor skydiving", "adrenaline indoor experience AED 300", url="https://b.example/sky")
    enrich_from_text(good, good.text())
    enrich_from_text(pricey, pricey.text())
    top, near = rank([pricey, good], state)
    assert top[0].candidate.title == good.title
    assert top[0].reasons
    assert near and near[0].candidate.title == pricey.title


def test_over_budget_becomes_alternative_not_recommendation():
    state = ConversationState(location="Dubai", budget_aed=50)
    pricey = candidate("Desert safari", "AED 250 per person")
    enrich_from_text(pricey, pricey.text())
    top, near = rank([pricey], state)
    assert top == []
    assert len(near) == 1


def test_junk_results_dropped():
    assert is_junk(candidate("Jobs in Dubai", "hiring now", url="https://ae.indeed.com/x"))
    assert is_junk(candidate("Метро Дубая в 2026 году", "карта, цены", url="https://dzen.ru/x"))
    assert is_junk(candidate("Is Dubai safe in 2026?", "a travel safety explainer", url="https://blog.ae/x"))
    assert not is_junk(candidate("Kayak tour", "AED 60", url="https://visitdubai.com/x"))


def test_years_are_not_prices():
    hit = candidate("Dubai events calendar", "everything happening in Dubai 2026, tickets from AED 75")
    enrich_from_text(hit, hit.text())
    assert hit.price_aed == 75


def test_roundup_pages_expand_into_individual_options():
    parent = candidate("20 best outdoor things to do in Dubai", "round-up", url="https://x.ae/list")
    parent.details["headings"] = [
        ("1. 🏖️ Kite Beach", "Free entry, open 24 hours, great for a chill morning"),
        ("Pro Tips from Locals", "Bring AED 50 in cash"),
        ("Dubai Frame", "Tickets AED 50, open 9 am - 9 pm"),
        ("Table of contents", "jump to section"),
        ("Some heading", "no live details here at all"),
    ]
    children = expand_roundup(parent)
    assert [c.title for c in children] == ["Kite Beach", "Dubai Frame"]
    assert children[0].is_free and children[1].price_aed == 50
    assert children[1].opening_hours


def test_vibe_matches_whole_words_only():
    state = ConversationState(location="Dubai", vibe="chill", environment="indoor")
    lounge = candidate("Chillout Ice Lounge Dubai", "indoor ice bar experience")
    _, reasons = score_candidate(lounge, state)
    assert not any("chill mood" in reason for reason in reasons)


def test_duplicate_venues_appear_once():
    state = ConversationState(location="Dubai", budget_aed=100, vibe="chill")
    first = candidate("Chillout Ice Lounge Dubai tickets", "indoor experience", url="https://a.ae/1")
    second = candidate("Chillout Ice Lounge Dubai 2026 hours", "indoor experience", url="https://b.ae/2")
    top, near = rank([first, second], state)
    assert len(top) + len(near) == 1


def test_score_reasons_mention_budget_and_vibe():
    state = ConversationState(location="Dubai", budget_aed=100, vibe="chill", environment="outdoor")
    hit = candidate("Relaxing garden walk in Dubai", "calm outdoor park, AED 30 entry")
    enrich_from_text(hit, hit.text())
    score, reasons = score_candidate(hit, state)
    assert score > 0
    joined = " ".join(reasons)
    assert "budget" in joined and "chill" in joined and "outdoors" in joined
