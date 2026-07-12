"""
Planner node -- decides which gather sources to call and with what
sub-queries, so `gather` never has to make judgment calls of its own.

Design:
  - If the request is location-only (no free text), skip the LLM entirely
    and use a cheap heuristic plan -- there's no ambiguity to reason about.
  - If there's free text, ask the model to choose sources and craft focused
    sub-queries. The call goes through city_guide's EndpointBackend with a
    strict JSON schema, so the response is validated at the decoding layer
    instead of hand-parsed.
  - Any LLM failure falls back to the heuristic plan rather than failing
    the turn -- planning wrong is recoverable, planning nothing is not.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from agent.graph.state import AgentState
from agent.llm.prompts.planner_prompt import SYSTEM_PROMPT, build_user_prompt
from city_guide.backends import EndpointBackend

logger = logging.getLogger(__name__)

DEFAULT_GUIDE_RADIUS_M = 750


class _GuideStorePlan(BaseModel):
    query: str | None = None
    radius_m: int = DEFAULT_GUIDE_RADIUS_M


class _WebSearchPlan(BaseModel):
    query: str


class PlanResponse(BaseModel):
    """Schema-enforced plan — the backend's guided decoding guarantees the shape."""

    reverse_geocode: bool = False
    guide_store: _GuideStorePlan | None = None
    web_search: _WebSearchPlan | None = None


def _heuristic_plan(query: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback: location-only requests and LLM-failure safety net."""
    has_text = bool(query.get("has_text"))
    has_location = bool(query.get("has_location"))

    return {
        "reverse_geocode": has_location,
        "guide_store": ({"query": query.get("text"), "radius_m": DEFAULT_GUIDE_RADIUS_M} if has_location else None),
        "web_search": {"query": query["text"]} if has_text else None,
    }


async def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.get("error"):
        return {}

    query: dict[str, Any] | None = state.get("query")
    if not query:
        return {"error": "planner: no query in state -- intake must run first."}

    fallback = _heuristic_plan(query)

    if not query.get("has_text"):
        # Location-only request -- nothing for the model to disambiguate.
        return {"plan": fallback}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(query)},
    ]
    try:
        response = await EndpointBackend().generate(messages, PlanResponse, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 -- any failure here should degrade, not crash the turn
        logger.error("planner: LLM call failed (%s); using heuristic plan", exc)
        return {"plan": fallback}

    plan = response.model_dump()
    # Never enable location-based sources without a location, whatever the model said.
    if not query.get("has_location"):
        plan["reverse_geocode"] = False
        plan["guide_store"] = None
    return {"plan": plan}
