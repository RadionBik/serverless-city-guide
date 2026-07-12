"""
Narrate node -- the single storyteller call in the pipeline.

This is the one node that's genuinely expensive/slow, so it's the one node
built around streaming: tokens are forwarded to an optional `on_token`
callback as they arrive from Nebius, so a caller (e.g. a websocket handler
in main.py) can push them to the client immediately for perceived
real-time latency, while the full accumulated text still lands in state
for `verify` to check afterward.

Note on LangGraph streaming: because this calls the Nebius client directly
rather than a LangChain chat model, LangGraph's built-in `stream_mode="messages"`
token events won't fire automatically for this node. The explicit `on_token`
callback is the pragmatic way to get token-level output out of a plain
async function node. If this is later swapped for a LangChain-wrapped chat
model, the callback could be replaced with LangGraph's native event stream.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from llm.nebius_client import get_nebius_client
from llm.prompts.narrate_prompt import SYSTEM_PROMPT, build_user_prompt

from graph.state import AgentState

logger = logging.getLogger(__name__)

OnToken = Callable[[str], Awaitable[None]]

FALLBACK_NARRATION = "I'm having trouble putting that together right now -- mind trying again in a moment?"


async def run(state: AgentState, on_token: OnToken | None = None) -> dict[str, Any]:
    """
    LangGraph node entry point.

    `on_token` is not part of `AgentState` -- it's a transport-layer concern
    (how tokens reach the client), not pipeline state, so it's passed as an
    explicit argument by whatever invokes the graph rather than threaded
    through the shared state.
    """
    if state.get("error"):
        return {}

    query = state.get("query")
    if not query:
        return {"error": "narrate: no query in state -- intake must run first."}

    evidence = state.get("evidence")
    user_profile = state.get("user_profile")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(query, evidence, user_profile)},
    ]

    client = get_nebius_client()
    chunks: list[str] = []
    try:
        async for delta in client.stream(messages, role="storyteller", temperature=0.7):
            chunks.append(delta)
            if on_token is not None:
                await on_token(delta)
    except Exception as exc:  # noqa: BLE001 -- a narration failure shouldn't crash the turn
        logger.error("narrate: Nebius stream failed: %s", exc)
        return {"narration": FALLBACK_NARRATION, "error": None}

    narration = "".join(chunks).strip()
    if not narration:
        logger.warning("narrate: model returned empty narration")
        narration = FALLBACK_NARRATION

    return {"narration": narration}
