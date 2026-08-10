"""FastAPI app serving the Go-with-the-Flow voice assistant."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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


@app.post("/api/turn")
async def turn(request: TurnRequest) -> dict[str, Any]:
    if request.state is not None:
        assistant.session(request.session_id).state = make_state(request.state)
    return await assistant.handle(request.session_id, request.utterance)


@app.get("/api/state")
async def get_state(session_id: str = "default") -> dict[str, Any]:
    return assistant.session(session_id).state.to_dict()


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


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "search_backend": get_backend().__class__.__name__,
        "voice_backend": "elevenlabs" if get_voice() else "browser",
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
