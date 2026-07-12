"""
Gather node -- fans out to whatever sources `planner` decided are needed
(reverse_geocode, guide_store, web_search), runs them concurrently, and
merges the results into a single provenance-tagged evidence bundle for
`narrate` to draw on.

Each source call is wrapped individually so one failing source (a flaky
API, a timeout) degrades that one entry rather than failing the whole
turn -- `narrate` can still work with partial evidence, and `verify` will
naturally catch any claim that outruns what was actually gathered.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tools.geo.reverse_geocode import reverse_geocode
from tools.guide_store import query_guides
from tools.web_search import search as web_search

from graph.state import AgentState

logger = logging.getLogger(__name__)


async def _call_reverse_geocode(lat: float, lon: float) -> dict:
    try:
        data = await reverse_geocode(lat, lon)
        return {"ok": True, "data": data, "error": None}
    except Exception as exc:  # noqa: BLE001 -- any source failure should degrade, not propagate
        logger.warning("gather: reverse_geocode failed: %s", exc)
        return {"ok": False, "data": None, "error": str(exc)}


async def _call_guide_store(lat: float, lon: float, query: str | None, radius_m: int) -> dict:
    try:
        data = await query_guides(lat, lon, query=query, radius_m=radius_m)
        return {"ok": True, "data": data, "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("gather: guide_store failed: %s", exc)
        return {"ok": False, "data": None, "error": str(exc)}


async def _call_web_search(query: str) -> dict:
    try:
        data = await web_search(query)
        return {"ok": True, "data": data, "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("gather: web_search failed: %s", exc)
        return {"ok": False, "data": None, "error": str(exc)}


async def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.get("error"):
        return {}

    plan = state.get("plan")
    query = state.get("query")

    if plan is None or query is None:
        return {"error": "gather: missing plan or query in state -- planner must run first."}

    location = query.get("location")

    # Build the set of concurrent calls based on the plan. Each entry pairs
    # a source name with its coroutine, so results can be matched back up
    # after asyncio.gather regardless of completion order.
    tasks: list[tuple[str, Any]] = []

    if plan.get("reverse_geocode") and location:
        tasks.append(("reverse_geocode", _call_reverse_geocode(location["lat"], location["lon"])))

    guide_store_plan = plan.get("guide_store")
    if guide_store_plan and location:
        tasks.append(
            (
                "guide_store",
                _call_guide_store(
                    location["lat"],
                    location["lon"],
                    query=guide_store_plan.get("query"),
                    radius_m=guide_store_plan.get("radius_m", 750),
                ),
            )
        )

    web_search_plan = plan.get("web_search")
    if web_search_plan and web_search_plan.get("query"):
        tasks.append(("web_search", _call_web_search(web_search_plan["query"])))

    if not tasks:
        # Nothing to gather (e.g. no location and no text worth searching).
        # Not an error -- narrate can still respond from the query alone,
        # though it will have very little to work with.
        return {"evidence": {"reverse_geocode": None, "guide_store": None, "web_search": None}}

    names, coros = zip(*tasks, strict=True)
    results = await asyncio.gather(*coros)

    evidence: dict[str, dict | None] = {
        "reverse_geocode": None,
        "guide_store": None,
        "web_search": None,
    }
    for name, result in zip(names, results, strict=True):
        evidence[name] = result

    return {"evidence": evidence}
