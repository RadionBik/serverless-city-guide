"""
Planner node -- decides which gather sources to call and with what
sub-queries, so `gather` never has to make judgment calls of its own.

Design:
  - If the request is location-only (no free text), skip the LLM entirely
    and use a cheap heuristic plan -- there's no ambiguity to reason about
    ("where am I" doesn't need a model to decide it wants reverse_geocode
    + guide_store).
  - If there's free text, ask the "utility" Nebius model (falls back to the
    storyteller model if no separate utility model is configured) to
    choose sources and craft focused sub-queries.
  - Any failure to call or parse the model's response falls back to the
    same heuristic plan rather than failing the turn -- planning wrong is
    recoverable (verify/gather can compensate), planning nothing is not.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from graph.state import AgentState
from llm.nebius_client import get_nebius_client
from llm.prompts.planner_prompt import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

DEFAULT_GUIDE_RADIUS_M = 750


def _heuristic_plan(query: dict) -> dict:
    """
    Deterministic fallback plan, used when there's no free text to reason
    about, and as a safety net if the LLM call or parse fails.
    """
    has_text = bool(query.get("has_text"))
    has_location = bool(query.get("has_location"))

    return {
        "reverse_geocode": has_location,
        "guide_store": (
            {"query": query.get("text"), "radius_m": DEFAULT_GUIDE_RADIUS_M}
            if has_location
            else None
        ),
        "web_search": {"query": query["text"]} if has_text else None,
    }


def _parse_llm_plan(raw: str, query: dict) -> dict:
    """
    Parse the model's JSON plan, validating each field against what's
    actually possible given the query (e.g. never enable location-based
    sources if there's no location). Falls back field-by-field to the
    heuristic plan on anything malformed, rather than discarding the whole
    response over one bad field.
    """
    fallback = _heuristic_plan(query)
    has_location = bool(query.get("has_location"))

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("plan is not a JSON object")
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("planner: unparseable LLM plan, using heuristic fallback")
        return fallback

    plan = dict(fallback)

    if "reverse_geocode" in data:
        plan["reverse_geocode"] = bool(data["reverse_geocode"]) and has_location

    if "web_search" in data:
        ws = data["web_search"]
        if ws in (None, False):
            plan["web_search"] = None
        elif isinstance(ws, dict) and ws.get("query"):
            plan["web_search"] = {"query": str(ws["query"])}
        elif isinstance(ws, str) and ws.strip():
            plan["web_search"] = {"query": ws.strip()}
        # else: malformed -- keep fallback value for this field

    if "guide_store" in data:
        gs = data["guide_store"]
        if gs in (None, False) or not has_location:
            plan["guide_store"] = None
        elif isinstance(gs, dict):
            plan["guide_store"] = {
                "query": gs.get("query") or query.get("text"),
                "radius_m": gs.get("radius_m", DEFAULT_GUIDE_RADIUS_M),
            }
        # else: malformed -- keep fallback value for this field

    return plan


async def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.get("error"):
        return {}

    query: Optional[dict] = state.get("query")
    if not query:
        return {"error": "planner: no query in state -- intake must run first."}

    fallback = _heuristic_plan(query)

    if not query.get("has_text"):
        # Location-only request -- nothing for the model to disambiguate.
        return {"plan": fallback}

    client = get_nebius_client()
    try:
        raw = await client.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(query)},
            ],
            role="utility",
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001 -- any failure here should degrade, not crash the turn
        logger.error("planner: Nebius call failed (%s); using heuristic plan", exc)
        return {"plan": fallback}

    plan = _parse_llm_plan(raw, query)
    return {"plan": plan}