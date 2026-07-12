"""
Gather node -- fans out to the sources `planner` decided are needed and
merges the results into one evidence bundle for `narrate`.

All heavy lifting is done by the city_guide engine (Overpass, Wikipedia,
Wikidata, Tavily, guide store); this node only adapts the plan to engine
calls and keeps per-source failures from killing the turn.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.graph.state import AgentState
from city_guide.narrator import build_evidence
from city_guide.pipeline import gather as engine_gather
from city_guide.pipeline import warm_context
from city_guide.store import GuideStore

logger = logging.getLogger(__name__)

DEFAULT_GUIDE_RADIUS_M = 750


async def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.get("error"):
        return {}

    plan = state.get("plan")
    query = state.get("query")
    if plan is None or query is None:
        return {"error": "gather: missing plan or query in state -- planner must run first."}

    location = query.get("location")
    if not location:
        # No pin -> nothing geo to gather; narrate answers from the query alone.
        return {"evidence": None}

    lat, lon = location["lat"], location["lon"]
    interest = query.get("text")

    # reverse_geocode: no provider wired yet -- the wiki/overpass data names the area anyway
    display, analysis, data = await engine_gather(lat, lon, interest=interest, with_web=bool(plan.get("web_search")))

    baked = []
    guide_plan = plan.get("guide_store")
    if guide_plan:
        baked = warm_context(GuideStore(), lat, lon, guide_plan.get("radius_m", DEFAULT_GUIDE_RADIUS_M))

    evidence = build_evidence(display, analysis, data.tavily_snippets, baked)
    return {
        "evidence": evidence,
        "evidence_stats": {
            "places": len(display.places),
            "web_snippets": len(data.tavily_snippets or []),
            "baked_stories": len(baked),
        },
    }
