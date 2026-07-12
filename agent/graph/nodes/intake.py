"""
Intake node -- first step in the pipeline.

Takes whatever the caller sent (freeform text, coordinates, a dropped pin,
some combination) and turns it into a single normalized `query` dict that
every downstream node can rely on, without needing to know which input
channel the request came in on.

This is deliberately a plain Python/validation step, not an LLM call --
normalizing shape and units is cheap and deterministic, so there's no
reason to spend a Nebius call on it. Intent interpretation (what the user
actually wants gathered) belongs to the `planner` node, which does have
reason to reach for the model.

Returns a partial state update: `{"query": {...}}` on success, or
`{"error": "..."}` if the input can't be normalized at all.
"""

from __future__ import annotations

from typing import Any

from agent.graph.state import AgentState

# Sanity bounds -- catches obviously malformed payloads (e.g. swapped
# lat/lon, stray (0, 0) defaults) before they propagate downstream.
_LAT_RANGE = (-90.0, 90.0)
_LON_RANGE = (-180.0, 180.0)


def _normalize_coords(coords: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate and coerce a {"lat": ..., "lon": ...} payload."""
    if not coords:
        return None

    raw_lon = coords.get("lon", coords.get("lng"))
    if raw_lon is None:
        return None
    try:
        lat = float(coords["lat"])
        lon = float(raw_lon)
    except (KeyError, TypeError, ValueError):
        return None

    if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
        return None
    if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
        return None

    return {"lat": lat, "lon": lon}


def _normalize_pin(pin: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Normalize a dropped-pin payload. Pins may carry richer context than raw
    coords (e.g. a place label the client already resolved), so we keep
    both the coordinate and any label rather than collapsing it into coords.
    """
    if not pin:
        return None

    coords = _normalize_coords(pin)
    if coords is None:
        return None

    label = pin.get("label") or pin.get("name")
    return {**coords, "label": label} if label else coords


def _normalize_text(raw_text: str | None) -> str | None:
    if raw_text is None:
        return None
    text = raw_text.strip()
    return text or None


def run(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node entry point. Synchronous -- normalization here is pure
    computation with no I/O, so there's no need for an async signature.
    """
    text = _normalize_text(state.get("raw_text"))
    coords = _normalize_coords(state.get("coords"))
    pin = _normalize_pin(state.get("pin"))

    # A pin implies a location; prefer it over raw coords if both are
    # present (the client likely resolved the pin from a map tap, whereas
    # `coords` might just be a stale device GPS fix).
    location = pin or coords

    if text is None and location is None:
        return {"error": ("intake: no usable input -- need at least one of raw_text, coords, or pin.")}

    query = {
        "text": text,
        "location": location,  # {"lat", "lon", "label"?} or None
        "has_text": text is not None,
        "has_location": location is not None,
        "user_id": state.get("user_id"),
    }

    return {"query": query, "error": None}
