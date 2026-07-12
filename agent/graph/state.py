"""
Shared state object that flows through the LangGraph pipeline:

    intake -> planner -> gather -> narrate -> verify -> reply

Every node receives the current `AgentState`, reads what it needs, and
returns a dict of the fields it's updating (LangGraph merges this into the
running state). Keeping this in one typed place means `build_graph.py` and
every node file agree on the same contract without importing each other.

Field types are intentionally loose (dict[str, Any]) for now. If the agent
shell grows real schemas, swap the annotations below for pydantic models
without changing any node signatures.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages

VerifyDecision = Literal["retry", "reply"]


class AgentState(TypedDict, total=False):
    # ---- raw input (set once, by the caller / intake) ----
    raw_text: str | None
    coords: dict[str, Any] | None  # {"lat": float, "lon": float}
    pin: dict[str, Any] | None  # dropped-pin payload, if distinct from coords
    user_id: str | None  # for future profile/memory lookup

    # ---- intake output ----
    # Normalized request: intent, location, freeform question, etc.
    # Will become `schemas.query.Query` once that schema exists.
    query: dict[str, Any] | None

    # ---- planner output ----
    # Which gather sources to call and with what sub-queries, e.g.
    # {"reverse_geocode": True, "web_search": {"query": "..."}, "guide_store": {...}}
    plan: dict[str, Any] | None

    # ---- gather output ----
    # Assembled evidence corpus (city_guide.narrator.build_evidence output) —
    # the storyteller's user message AND the judge's ground truth.
    evidence: str | None

    # ---- future: memory / personalization (read side) ----
    # Retrieved user preferences/topics, injected into the narrate prompt.
    # Will become `schemas.profile.UserProfile`.
    user_profile: dict[str, Any] | None

    # ---- gather output (continued) ----
    # Counts for logging/UX ("found 12 places, 3 web snippets, 2 baked stories")
    evidence_stats: dict[str, Any] | None

    # ---- narrate output ----
    narration: str | None
    # The exact prompt messages the story came from — verify feeds them back
    # to city_guide's regenerate step.
    narrator_messages: list[dict[str, Any]] | None

    # ---- verify output ----
    # Summary line of city_guide's claim report ("9 supported, 1 uncertain...");
    # retry + strip happen inside verify_and_repair, so no graph-level loop.
    verify_report: str | None
    verify_regenerated: bool
    decision: VerifyDecision | None

    # ---- reply output ----
    reply: str | None

    # ---- cross-cutting ----
    error: str | None
    # Running chat history, if the agent is used conversationally rather
    # than as single-shot turns. `add_messages` handles append-merge
    # semantics the way LangGraph expects.
    messages: Annotated[list[Any], add_messages]


def initial_state(
    raw_text: str | None = None,
    coords: dict[str, Any] | None = None,
    pin: dict[str, Any] | None = None,
    user_id: str | None = None,
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
        evidence_stats=None,
        user_profile=None,
        narration=None,
        narrator_messages=None,
        verify_report=None,
        verify_regenerated=False,
        decision=None,
        reply=None,
        error=None,
        messages=[],
    )
