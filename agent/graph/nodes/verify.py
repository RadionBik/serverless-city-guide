"""
Verify node -- checks the narration against the evidence before it goes to
the user.

Delegates to city_guide's verifier: an LLM judge splits the story into
claims (supported / uncertain / unsupported), unsupported claims trigger
one regeneration with explicit feedback, and whatever still fails is
stripped from the text deterministically. Because retry + strip happen
inside `verify_and_repair`, the graph never needs to route back to
`gather` -- `route()` always answers "reply".

TODO(cost): the original two-tier design (deterministic citation-tag check
first, LLM judge only for risky untagged sentences) is a real cost
optimization over judging every story -- worth revisiting once citation
tags exist in the narrator prompt.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.graph.state import AgentState, VerifyDecision
from city_guide.backends import EndpointBackend
from city_guide.verifier import verify_and_repair

logger = logging.getLogger(__name__)


async def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.get("error"):
        return {}

    narration = state.get("narration")
    evidence = state.get("evidence")
    messages = state.get("narrator_messages")
    if not narration or not evidence or not messages:
        # Nothing checkable (fallback narration, empty pin) -- pass through.
        return {"verify_report": None, "decision": "reply"}

    try:
        story, report, regenerated = await verify_and_repair(narration, messages, evidence, EndpointBackend())
    except Exception as exc:  # noqa: BLE001 -- verification failing shouldn't eat the story
        logger.error("verify: judge call failed: %s", exc)
        return {"verify_report": None, "decision": "reply"}

    return {
        "narration": story,
        "verify_report": report.summary(),
        "verify_regenerated": regenerated,
        "decision": "reply",
    }


def route(state: AgentState) -> VerifyDecision:
    """Conditional-edge router; the retry loop lives inside verify_and_repair."""
    return state.get("decision") or "reply"
