"""Point a hosted ElevenLabs agent at this deployment.

    ELEVENLABS_API_KEY=... ELEVENLABS_AGENT_ID=... python scripts/setup_convai_agent.py https://your-host

Creates the webhook tool and sets the agent's prompt so every user turn is routed to
/api/convai/turn. The base URL must be reachable from the public internet — ElevenLabs
calls it, so a localhost address will not work (use a tunnel while developing).

Needs an API key with the convai_read and convai_write permissions.
"""

from __future__ import annotations

import asyncio
import os
import sys

from app.convai import ConvAIClient, tool_definition


async def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    base_url = sys.argv[1]
    api_key, agent_id = os.getenv("ELEVENLABS_API_KEY"), os.getenv("ELEVENLABS_AGENT_ID")
    if not api_key or not agent_id:
        print("Set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID first.")
        return 2

    print(f"Installing {tool_definition(base_url)['api_schema']['url']} on {agent_id}")
    await ConvAIClient(api_key, agent_id).install_tool(base_url)
    print("Agent updated. Start a call and every turn will hit your engine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
