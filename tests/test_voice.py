import httpx
import pytest
from fastapi.testclient import TestClient

import app.dialog as dialog
import app.main as main
from app.search import Candidate, enrich_from_text
from app.voice import ElevenLabsVoice


class FakeVoice(ElevenLabsVoice):
    def __init__(self):
        super().__init__(api_key="test-key")
        self.spoken: list[str] = []

    async def transcribe(self, audio, filename="speech.webm", content_type="audio/webm"):
        return "I'm in Dubai, two hours, 100 AED, chill and outdoors" if audio else ""

    async def synthesize(self, text):
        self.spoken.append(text)
        return b"ID3-fake-mp3"


@pytest.fixture()
def voice(monkeypatch):
    async def fake_live_search(state, **kwargs):
        hit = Candidate(title="Creek park stroll", url="https://a.ae/1", snippet="free outdoor park in Dubai")
        return [enrich_from_text(hit, hit.text())]

    engine = FakeVoice()
    monkeypatch.setattr(dialog, "live_search", fake_live_search)
    monkeypatch.setattr(main, "require_voice", lambda: engine)
    monkeypatch.setattr(main, "get_voice", lambda: engine)
    return engine


def test_voice_turn_drives_the_same_agent(voice):
    client = TestClient(main.app)
    response = client.post(
        "/api/voice",
        data={"session_id": "v1"},
        files={"audio": ("speech.webm", b"fake-audio", "audio/webm")},
    )
    data = response.json()
    assert data["transcript"].startswith("I'm in Dubai")
    assert data["searching"] is True
    # The spoken turn lands in the same conversation state the typed API exposes.
    assert client.get("/api/state", params={"session_id": "v1"}).json()["budget_aed"] == 100


def test_unusable_audio_keeps_state_and_does_not_crash(voice, monkeypatch):
    client = TestClient(main.app)
    client.post(
        "/api/voice",
        data={"session_id": "v2"},
        files={"audio": ("speech.webm", b"fake-audio", "audio/webm")},
    )

    async def reject(*args, **kwargs):
        request = httpx.Request("POST", "https://api.elevenlabs.io/v1/speech-to-text")
        raise httpx.HTTPStatusError("bad audio", request=request, response=httpx.Response(400, request=request))

    monkeypatch.setattr(voice, "transcribe", reject)
    response = client.post(
        "/api/voice",
        data={"session_id": "v2"},
        files={"audio": ("speech.webm", b"", "audio/webm")},
    )
    data = response.json()
    assert response.status_code == 200
    assert "didn't catch that" in data["reply"]
    # The earlier spoken turn is still there, so the UI has nothing to wipe.
    assert data["state"]["location"] == "Dubai"
    assert "recommendations" not in data


def test_speak_returns_audio(voice):
    client = TestClient(main.app)
    response = client.post("/api/speak", json={"text": "Here are three ideas"})
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3-fake-mp3"
    assert voice.spoken == ["Here are three ideas"]


def test_health_reports_voice_backend(voice):
    assert TestClient(main.app).get("/api/health").json()["voice_backend"] == "elevenlabs"


def test_voice_disabled_without_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    client = TestClient(main.app)
    assert client.get("/api/health").json()["voice_backend"] == "browser"
    assert client.post("/api/speak", json={"text": "hi"}).status_code == 503
