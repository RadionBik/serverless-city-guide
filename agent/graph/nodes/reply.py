"""
Reply node -- last step in the pipeline. Turns the internal narration into
the actual text sent to the user.

Two responsibilities:
  1. Strip citation tags ([geo], [guideN], [webN]) out of the narration --
     they're an internal grounding mechanism for `verify`, not something a
     traveler should ever see.
  2. If `verify` finished with confirmed-unsupported claims still present
     (i.e. the retry budget was spent and the issue persisted, or a claim
     was ungrounded with nothing to retry against), append a short, honest
     caveat rather than presenting the narration as fully confirmed.

This node never fails the turn -- even on an upstream error, it produces a
safe, user-facing apology rather than surfacing internal error text.
"""

from __future__ import annotations

import logging
from typing import Any

from llm.prompts.citation import strip_citation_tags

from graph.state import AgentState

logger = logging.getLogger(__name__)

GENERIC_FAILURE_REPLY = "Sorry, I ran into a problem putting that together. Mind trying again?"

UNCERTAINTY_CAVEAT = (
    "\n\n(A couple of specific details above I couldn't fully confirm -- worth double-checking locally.)"
)


def _has_unresolved_unsupported_claims(verification: list[dict] | None) -> bool:
    """
    True if verify's final pass still contains a claim it positively
    determined was unsupported (`supported is False`). Inconclusive claims
    (`supported is None`, e.g. the judge call itself failed) are not treated
    as unresolved here -- that's infra flakiness, not a wrong narration, and
    caveating every judge hiccup would make the caveat meaningless noise.
    """
    if not verification:
        return False
    return any(claim.get("supported") is False for claim in verification)


def run(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node entry point. Synchronous -- this is pure text
    post-processing, no I/O.
    """
    if state.get("error"):
        logger.warning("reply: finalizing with upstream error: %s", state["error"])
        return {"reply": GENERIC_FAILURE_REPLY}

    narration = state.get("narration")
    if not narration:
        logger.warning("reply: no narration in state -- narrate must run first.")
        return {"reply": GENERIC_FAILURE_REPLY}

    clean_text = strip_citation_tags(narration)
    if not clean_text:
        return {"reply": GENERIC_FAILURE_REPLY}

    if _has_unresolved_unsupported_claims(state.get("verification")):
        clean_text += UNCERTAINTY_CAVEAT

    return {"reply": clean_text}
