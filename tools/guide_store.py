"""
Geo-keyed guide store -- curated knowledge base of guide content (history,
things to do, local tips) retrieved by proximity to a location.

Not yet implemented against a real backend (see GUIDE_STORE_BACKEND /
GUIDE_STORE_CONNECTION_STRING in .env). This defines the contract `gather`
calls against, so the graph can be wired and tested before a backend is
chosen.
"""

from __future__ import annotations

from typing import Optional


async def query_guides(
    lat: float,
    lon: float,
    query: Optional[str] = None,
    radius_m: int = 750,
) -> list[dict]:
    """
    Retrieve guide entries near a location, optionally filtered/ranked by
    a topical query (e.g. "coffee", "history").

    Expected return shape once implemented:
        [
            {"title": "...", "text": "...", "distance_m": 120, "source": "..."},
            ...
        ]
    """
    raise NotImplementedError("guide_store: no backend wired up yet")