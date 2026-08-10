"""ElevenLabs Agents (ConvAI) wiring.

The hosted agent handles speech and turn-taking only. Every user turn is routed
back here through a webhook tool, so slot extraction, refinement and live search
stay in :mod:`app.dialog` and the agent never keeps its own idea of the state.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

API_ROOT = "https://api.elevenlabs.io/v1"
TOOL_NAME = "go_with_the_flow_turn"
TIMEOUT = 30.0

SYSTEM_PROMPT = f"""You are Go with the Flow, a spontaneous voice companion that helps people decide \
what to do right now.

You do not decide anything yourself. On every single user turn, call the `{TOOL_NAME}` tool with the \
user's words verbatim in `utterance`, then say the `reply` it returns, naturally and in your own \
rhythm. Never invent activities, prices or opening hours, and never answer from memory: the tool \
owns the conversation state and does the live search.

Keep it short and warm, like a friend who already knows the city."""


def tool_definition(base_url: str) -> dict[str, Any]:
    """The webhook tool the agent calls on every turn."""
    return {
        "type": "webhook",
        "name": TOOL_NAME,
        "description": (
            "Send the user's latest message to the Go with the Flow engine and get back the reply "
            "to speak. Call this on every user turn, including refinements like 'too expensive' or "
            "'somewhere closer'."
        ),
        "response_timeout_secs": 60,
        "api_schema": {
            "url": f"{base_url.rstrip('/')}/api/convai/turn",
            "method": "POST",
            "request_body_schema": {
                "type": "object",
                "required": ["utterance"],
                "properties": {
                    "utterance": {
                        "type": "string",
                        "description": "Exactly what the user just said, unedited.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "The conversation id, so the engine keeps the same slots across turns.",
                    },
                },
            },
        },
    }


class ConvAIClient:
    def __init__(self, api_key: str, agent_id: str) -> None:
        self.api_key = api_key
        self.agent_id = agent_id

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.request(method, f"{API_ROOT}{path}", headers={"xi-api-key": self.api_key}, **kwargs)
        response.raise_for_status()
        return response.json()

    async def signed_url(self) -> str:
        """A short-lived URL so the browser widget can talk to a private agent."""
        data = await self._request("GET", "/convai/conversation/get-signed-url", params={"agent_id": self.agent_id})
        return data["signed_url"]

    async def install_tool(self, base_url: str) -> dict[str, Any]:
        """Point the hosted agent at this deployment's webhook and prompt."""
        tool = await self._request("POST", "/convai/tools", json={"tool_config": tool_definition(base_url)})
        tool_id = tool.get("id") or tool["tool_config"]["id"]
        return await self._request(
            "PATCH",
            f"/convai/agents/{self.agent_id}",
            json={
                "conversation_config": {
                    "agent": {
                        "prompt": {"prompt": SYSTEM_PROMPT, "tool_ids": [tool_id]},
                        "first_message": "Hey! Got some free time? Tell me where you are and what you feel like.",
                    }
                }
            },
        )


def get_client() -> ConvAIClient | None:
    api_key = os.getenv("ELEVENLABS_API_KEY")
    agent_id = os.getenv("ELEVENLABS_AGENT_ID")
    return ConvAIClient(api_key, agent_id) if api_key and agent_id else None
