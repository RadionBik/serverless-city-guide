"""
Reply node -- last step in the pipeline. Turns the internal narration into
the actual text sent to the user.

The narration arrives already repaired: city_guide's verifier regenerated
failed claims and stripped whatever still failed, so there are no citation
tags to remove and no unsupported claims left in the text. What remains
here is honesty about the process -- surface the verification summary so
the traveler knows the story has receipts.

This node never fails the turn -- even on an upstream error, it produces a
safe, user-facing apology rather than surfacing internal error text.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.graph.state import AgentState

logger = logging.getLogger(__name__)

GENERIC_FAILURE_REPLY = "Sorry, I ran into a problem putting that together. Mind trying again?"


def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point. Synchronous -- pure text post-processing."""
    if state.get("error"):
        logger.warning("reply: finalizing with upstream error: %s", state["error"])
        return {"reply": GENERIC_FAILURE_REPLY}

    narration = state.get("narration")
    if not narration:
        logger.warning("reply: no narration in state -- narrate must run first.")
        return {"reply": GENERIC_FAILURE_REPLY}

    reply = narration
    report = state.get("verify_report")
    if report:
        reply += f"\n\n_verification: {report}_"

    return {"reply": reply}
