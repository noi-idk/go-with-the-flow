import pytest
from fastapi.testclient import TestClient

import app.dialog as dialog
from app.main import app as fastapi_app
from app.search import Candidate, enrich_from_text

FAKE_HITS = [
    (
        "Sunset kayak at Al Qudra",
        "relaxing outdoor paddle in Dubai, AED 60, open 8 am - 7 pm",
        "https://a.ae/1",
    ),
    ("Dubai Water Canal walk", "free outdoor promenade in Dubai, open 24 hours", "https://b.ae/2"),
    ("Luxury desert safari", "premium outdoor tour in Dubai AED 450", "https://c.ae/3"),
    ("Marina brunch buffet", "best restaurant dining in Dubai AED 199", "https://d.ae/4"),
]


@pytest.fixture()
def client(monkeypatch):
    async def fake_live_search(state, **kwargs):
        hits = []
        for title, snippet, url in FAKE_HITS:
            hit = Candidate(title=title, url=url, snippet=snippet, query="fake")
            hits.append(enrich_from_text(hit, hit.text()))
        return hits

    monkeypatch.setattr(dialog, "live_search", fake_live_search)
    return TestClient(fastapi_app)


def say(client, text, session_id="t1"):
    response = client.post("/api/turn", json={"session_id": session_id, "utterance": text})
    assert response.status_code == 200
    return response.json()


def test_asks_for_missing_info_before_searching(client):
    data = say(client, "I have two hours and I'm bored")
    assert data["searching"] is False
    assert "where" in data["reply"].lower()
    assert data["state"]["free_time_hours"] == 2


def test_searches_once_enough_slots_known(client):
    say(client, "I have three hours free")
    data = say(client, "I'm in Dubai and maybe around 100 AED, chill and outdoors")
    assert data["searching"] is True
    assert 1 <= len(data["recommendations"]) <= 5
    assert all(rec["why"] for rec in data["recommendations"])
    assert all(rec["price_aed"] is None or rec["price_aed"] <= 100 for rec in data["recommendations"])


def test_refinement_preserves_other_slots(client):
    say(client, "Find me something fun in Dubai for three hours, 150 AED, no shopping", session_id="t2")
    before = client.get("/api/state", params={"session_id": "t2"}).json()
    data = say(client, "That's too expensive. Give me something cheaper.", session_id="t2")
    after = data["state"]
    assert after["budget_aed"] < before["budget_aed"]
    assert after["location"] == before["location"]
    assert after["free_time_hours"] == before["free_time_hours"]
    assert after["exclusions"] == before["exclusions"]
    assert data["searching"] is True


def test_exclusions_never_recommended(client):
    data = say(client, "Dubai, two hours, 300 AED, no restaurants, chill", session_id="t3")
    titles = " ".join(rec["title"].lower() for rec in data["recommendations"])
    assert "brunch" not in titles


def test_reset_clears_state(client):
    say(client, "Dubai, two hours, 100 AED, chill outdoors", session_id="t4")
    client.post("/api/reset", json={"session_id": "t4"})
    assert client.get("/api/state", params={"session_id": "t4"}).json()["location"] is None


def test_health_reports_backend(client):
    assert client.get("/api/health").json()["status"] == "ok"
