"""FastAPI app serving the Go-with-the-Flow voice assistant."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .convai import get_client
from .dialog import Assistant, make_state
from .search import get_backend
from .voice import VoiceUnavailable, get_voice, require_voice

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Go-with-the-Flow", version="1.0.0")
assistant = Assistant()


class TurnRequest(BaseModel):
    session_id: str = "default"
    utterance: str
    state: dict[str, Any] | None = None


class ResetRequest(BaseModel):
    session_id: str = "default"


class SpeakRequest(BaseModel):
    text: str


class ConvAITurnRequest(BaseModel):
    utterance: str
    session_id: str = "convai"


@app.post("/api/turn")
async def turn(request: TurnRequest) -> dict[str, Any]:
    if request.state is not None:
        assistant.session(request.session_id).state = make_state(request.state)
    return await assistant.handle(request.session_id, request.utterance)


@app.get("/api/state")
async def get_state(session_id: str = "default") -> dict[str, Any]:
    return assistant.session(session_id).state.to_dict()


@app.get("/api/session")
async def session_snapshot(session_id: str = "default") -> dict[str, Any]:
    """State plus the last results — how the UI follows along during a hosted voice call."""
    session = assistant.session(session_id)
    return {
        "state": session.state.to_dict(),
        "recommendations": session.last_results,
        "turns": session.turns,
    }


@app.post("/api/reset")
async def reset(request: ResetRequest) -> dict[str, str]:
    assistant.reset(request.session_id)
    return {"status": "reset"}


@app.post("/api/voice")
async def voice_turn(
    audio: Annotated[UploadFile, File()],
    session_id: Annotated[str, Form()] = "default",
) -> dict[str, Any]:
    """Speech in → the same agent as /api/turn → reply text (speak it via /api/speak)."""
    engine = _voice_or_503()
    try:
        transcript = await engine.transcribe(
            await audio.read(),
            filename=audio.filename or "speech.webm",
            content_type=audio.content_type or "audio/webm",
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code >= 500:
            raise
        transcript = ""  # unusable audio, e.g. an accidental tap on the mic button
    if not transcript:
        # No state change, so leave the panel and the previous recommendations alone.
        return {
            "transcript": "",
            "reply": "I didn't catch that — say it again?",
            "state": assistant.session(session_id).state.to_dict(),
        }
    result = await assistant.handle(session_id, transcript)
    return {"transcript": transcript, **result}


@app.post("/api/speak")
async def speak(request: SpeakRequest) -> Response:
    audio = await _voice_or_503().synthesize(request.text)
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/convai/turn")
async def convai_turn(request: ConvAITurnRequest) -> dict[str, Any]:
    """Webhook the hosted ElevenLabs agent calls on every user turn.

    It is a thin wrapper over the same assistant: the agent speaks `reply` and never
    holds any conversation state of its own.
    """
    result = await assistant.handle(request.session_id, request.utterance)
    return {
        "reply": result["reply"],
        "state": result["state"],
        "recommendations": [
            {
                "title": rec["title"],
                "why": rec["why"],
                "price_aed": rec["price_aed"],
                "is_free": rec["is_free"],
                "opening_hours": rec["opening_hours"],
                "url": rec["url"],
            }
            for rec in result.get("recommendations", [])
        ],
    }


@app.get("/api/convai/session")
async def convai_session() -> dict[str, Any]:
    """What the browser widget needs to open a call with the hosted agent."""
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="ELEVENLABS_AGENT_ID is not set")
    try:
        return {"agent_id": client.agent_id, "signed_url": await client.signed_url()}
    except httpx.HTTPStatusError as error:
        # A public agent needs no signed URL, and the key may lack convai_read.
        return {"agent_id": client.agent_id, "signed_url": None, "detail": error.response.text[:200]}


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "search_backend": get_backend().__class__.__name__,
        "voice_backend": "elevenlabs" if get_voice() else "browser",
        "convai_agent": (get_client().agent_id if get_client() else ""),
    }


def _voice_or_503():
    try:
        return require_voice()
    except VoiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
