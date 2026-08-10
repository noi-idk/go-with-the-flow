import pytest
from fastapi.testclient import TestClient

import app.dialog as dialog
import app.main as main
from app.convai import TOOL_NAME, tool_definition
from app.search import Candidate, enrich_from_text


@pytest.fixture(autouse=True)
def fake_search(monkeypatch):
    async def search(state, **kwargs):
        hit = Candidate(
            title="Kite Beach walk", url="https://x.ae/kite", snippet="free outdoor beach in Dubai, open 24 hours"
        )
        enrich_from_text(hit, hit.text())
        return [hit]

    monkeypatch.setattr(dialog, "live_search", search)
    main.assistant = dialog.Assistant()


def test_convai_webhook_uses_the_same_engine():
    client = TestClient(main.app)
    client.post(
        "/api/convai/turn",
        json={"session_id": "call-1", "utterance": "I'm in Dubai, two hours, 100 dirhams, something chill outdoors"},
    )
    # A refinement on the next agent turn keeps every other slot.
    reply = client.post("/api/convai/turn", json={"session_id": "call-1", "utterance": "that's too expensive"}).json()
    state = reply["state"]
    assert state["location"] == "Dubai"
    assert state["free_time_hours"] == 2
    assert state["vibe"] == "chill"
    assert state["budget_aed"] < 100
    assert reply["reply"]


def test_session_snapshot_lets_the_ui_follow_a_call():
    client = TestClient(main.app)
    client.post(
        "/api/convai/turn",
        json={"session_id": "convai", "utterance": "Dubai, two hours, 100 AED, chill, outdoors"},
    )
    snapshot = client.get("/api/session", params={"session_id": "convai"}).json()
    assert snapshot["state"]["location"] == "Dubai"
    assert snapshot["recommendations"][0]["title"] == "Kite Beach walk"


def test_tool_points_at_this_deployment():
    schema = tool_definition("https://example.com/")["api_schema"]
    assert schema["url"] == "https://example.com/api/convai/turn"
    assert schema["request_body_schema"]["required"] == ["utterance"]
    assert TOOL_NAME in tool_definition("https://example.com")["name"]
