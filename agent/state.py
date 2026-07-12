"""Agent state — flows through intake → plan → gather → narrate → verify → reply.

Every node returns a dict of the fields it updates; LangGraph merges it into
the running state.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel

from city_guide.types import DEFAULT_THEME, DEFAULT_VERBOSITY, Theme, Verbosity

VerifyDecision = Literal["retry", "reply"]


class GuideSettings(BaseModel):
    """Engine knobs the agent picks from the user's free text.

    Also the LLM response schema for the plan node (strict JSON decoding).
    Structured fields gate retrieval and need code-level validation; wording
    wishes (tone, language, length nuance) ride in free-form `style` instead —
    the storyteller reads them directly. Web search is always on: extra
    evidence only tightens verification, and the engine skips Tavily without
    an API key anyway.
    """

    interest: str | None = None  # distilled focus phrase → Tavily / curator
    theme: Theme = DEFAULT_THEME  # retrieval preset derived from interest (OSM tags, wiki limit)
    verbosity: Verbosity = DEFAULT_VERBOSITY  # enum keeps the proven hard-length prompt block
    radius_m: int | None = None  # only spatial dial; None → engine default, clamped in plan()
    style: str | None = None  # free-form writing wishes, forwarded to the storyteller


class AgentState(TypedDict, total=False):
    # ---- raw input (set once, by the caller) ----
    raw_text: str | None
    coords: dict[str, Any] | None  # {"lat": float, "lon": float}
    pin: dict[str, Any] | None  # dropped-pin payload, if distinct from coords
    user_id: str | None  # for future profile/memory lookup

    # ---- intake output: normalized request ----
    query: dict[str, Any] | None

    # ---- plan output: engine settings decided from the free text ----
    settings: GuideSettings | None

    # ---- gather output ----
    # Evidence corpus (city_guide.narrator.build_evidence output) — the
    # storyteller's user message AND the judge's ground truth.
    evidence: str | None
    evidence_stats: dict[str, Any] | None

    # ---- narrate output ----
    narration: str | None
    # Exact prompt messages the story came from — verify feeds them back
    # to city_guide's regenerate step.
    narrator_messages: list[dict[str, Any]] | None

    # ---- verify output ----
    verify_report: str | None
    verify_regenerated: bool
    decision: VerifyDecision | None

    # ---- reply output ----
    reply: str | None

    # ---- cross-cutting ----
    error: str | None
    # Chat history for conversational use; add_messages = append-merge.
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
        settings=None,
        evidence=None,
        evidence_stats=None,
        narration=None,
        narrator_messages=None,
        verify_report=None,
        verify_regenerated=False,
        decision=None,
        reply=None,
        error=None,
        messages=[],
    )
