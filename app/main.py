"""FastAPI app serving the Go-with-the-Flow voice assistant."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .dialog import Assistant, make_state
from .search import get_backend

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Go-with-the-Flow", version="1.0.0")
assistant = Assistant()


class TurnRequest(BaseModel):
    session_id: str = "default"
    utterance: str
    state: dict[str, Any] | None = None


class ResetRequest(BaseModel):
    session_id: str = "default"


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


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "search_backend": get_backend().__class__.__name__}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
