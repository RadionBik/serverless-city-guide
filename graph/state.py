"""
Shared state object that flows through the LangGraph pipeline:

    intake -> planner -> gather -> narrate -> verify -> reply

Every node receives the current `AgentState`, reads what it needs, and
returns a dict of the fields it's updating (LangGraph merges this into the
running state). Keeping this in one typed place means `build_graph.py` and
every node file agree on the same contract without importing each other.

Field types are intentionally loose (dict/Any) for now, since `schemas/`
(query.py, evidence.py, profile.py) are not yet populated. Once those are
filled in, swap the annotations below for the real pydantic models -- e.g.
`query: Optional[Query]` instead of `query: Optional[dict]` -- without
changing any node signatures.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages

VerifyDecision = Literal["retry", "reply"]


class AgentState(TypedDict, total=False):
    # ---- raw input (set once, by the caller / intake) ----
    raw_text: Optional[str]
    coords: Optional[dict]       # {"lat": float, "lon": float}
    pin: Optional[dict]          # dropped-pin payload, if distinct from coords
    user_id: Optional[str]       # for future profile/memory lookup

    # ---- intake output ----
    # Normalized request: intent, location, freeform question, etc.
    # Will become `schemas.query.Query` once that schema exists.
    query: Optional[dict]

    # ---- planner output ----
    # Which gather sources to call and with what sub-queries, e.g.
    # {"reverse_geocode": True, "web_search": {"query": "..."}, "guide_store": {...}}
    plan: Optional[dict]

    # ---- gather output ----
    # Merged, provenance-tagged evidence bundle from geo sources, web search,
    # and the guide store. Will become `schemas.evidence.EvidenceBundle`.
    evidence: Optional[dict]

    # ---- future: memory / personalization (read side) ----
    # Retrieved user preferences/topics, injected into the narrate prompt.
    # Will become `schemas.profile.UserProfile`.
    user_profile: Optional[dict]

    # ---- narrate output ----
    narration: Optional[str]

    # ---- verify output ----
    # List of atomic claims extracted from `narration`, each checked against
    # `evidence`, e.g. [{"claim": "...", "supported": True, "source": "..."}]
    verification: Optional[list[dict]]
    verify_decision: Optional[VerifyDecision]
    retry_count: int

    # ---- reply output ----
    reply: Optional[str]

    # ---- cross-cutting ----
    error: Optional[str]
    # Running chat history, if the agent is used conversationally rather
    # than as single-shot turns. `add_messages` handles append-merge
    # semantics the way LangGraph expects.
    messages: Annotated[list[Any], add_messages]


def initial_state(
    raw_text: Optional[str] = None,
    coords: Optional[dict] = None,
    pin: Optional[dict] = None,
    user_id: Optional[str] = None,
) -> AgentState:
    """Construct a fresh state for a single turn."""
    return AgentState(
        raw_text=raw_text,
        coords=coords,
        pin=pin,
        user_id=user_id,
        query=None,
        plan=None,
        evidence=None,
        user_profile=None,
        narration=None,
        verification=None,
        verify_decision=None,
        retry_count=0,
        reply=None,
        error=None,
        messages=[],
    )