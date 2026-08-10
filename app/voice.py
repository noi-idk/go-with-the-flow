"""ElevenLabs voice layer.

Speech in, speech out. It only converts audio to text and text back to audio —
the conversation itself stays in :mod:`app.dialog`, so the voice path and the
typed path drive exactly the same agent and the same slot state.
"""

from __future__ import annotations

import os

import httpx

API_ROOT = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", a natural conversational voice
DEFAULT_STT_MODEL = "scribe_v1"
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"  # low latency, which matters in a live conversation
TIMEOUT = 60.0


class VoiceUnavailable(RuntimeError):
    """Raised when no ElevenLabs credentials are configured."""


class ElevenLabsVoice:
    def __init__(self, api_key: str, voice_id: str | None = None) -> None:
        self.api_key = api_key
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID)

    @property
    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self.api_key}

    async def transcribe(self, audio: bytes, filename: str = "speech.webm", content_type: str = "audio/webm") -> str:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                f"{API_ROOT}/speech-to-text",
                headers=self._headers,
                data={"model_id": os.getenv("ELEVENLABS_STT_MODEL", DEFAULT_STT_MODEL)},
                files={"file": (filename, audio, content_type)},
            )
        response.raise_for_status()
        return (response.json().get("text") or "").strip()

    async def synthesize(self, text: str) -> bytes:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                f"{API_ROOT}/text-to-speech/{self.voice_id}",
                headers={**self._headers, "Content-Type": "application/json"},
                params={"output_format": "mp3_44100_128"},
                json={
                    "text": text,
                    "model_id": os.getenv("ELEVENLABS_TTS_MODEL", DEFAULT_TTS_MODEL),
                    "voice_settings": {"stability": 0.4, "similarity_boost": 0.7, "speed": 1.05},
                },
            )
        response.raise_for_status()
        return response.content


def get_voice() -> ElevenLabsVoice | None:
    """The configured voice engine, or ``None`` when the browser should handle speech."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    return ElevenLabsVoice(api_key) if api_key else None


def require_voice() -> ElevenLabsVoice:
    voice = get_voice()
    if voice is None:
        raise VoiceUnavailable("ELEVENLABS_API_KEY is not set")
    return voice
