"""
Narrate node -- the single storyteller call in the pipeline.

Delegates to the city_guide narrator (strict-JSON storyteller on the
Nebius endpoint / Token Factory). The original messages are kept in state
so `verify` can regenerate with feedback.

TODO(streaming): the original design streamed tokens via an `on_token`
callback for perceived latency; city_guide's EndpointBackend returns full
responses. Add a streaming method to EndpointBackend and thread the
callback back through here.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.graph.state import AgentState
from city_guide.backends import EndpointBackend
from city_guide.narrator import narrate

logger = logging.getLogger(__name__)

FALLBACK_NARRATION = "I'm having trouble putting that together right now -- mind trying again in a moment?"


async def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.get("error"):
        return {}

    query = state.get("query")
    if not query:
        return {"error": "narrate: no query in state -- intake must run first."}

    evidence = state.get("evidence")
    if not evidence:
        # Empty pin: honest no-story answer, zero LLM calls (mirrors the CLI guard).
        no_data = "I don't have any data about this exact spot -- try another pin."
        return {"narration": no_data, "narrator_messages": None}

    try:
        story, messages = await narrate(evidence, EndpointBackend())
    except Exception as exc:  # noqa: BLE001 -- a narration failure shouldn't crash the turn
        logger.error("narrate: storyteller call failed: %s", exc)
        return {"narration": FALLBACK_NARRATION, "narrator_messages": None}

    return {"narration": story or FALLBACK_NARRATION, "narrator_messages": messages}
