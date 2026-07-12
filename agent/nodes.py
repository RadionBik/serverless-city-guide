"""All graph nodes. Heavy lifting delegates to the city_guide engine; nodes
only adapt state to engine calls and keep failures from killing the turn.

intake  — normalize raw input (free text, coords, pin) into one query dict
plan    — LLM picks GuideSettings from the free text (defaults as fallback)
gather  — engine gather + guide store, driven by the settings
narrate — engine storyteller with the settings' language/theme/verbosity
verify  — engine verify → regenerate → strip loop
reply   — final text + verification summary
"""

from __future__ import annotations

import logging
from typing import Any

from agent.prompts import build_settings_messages
from agent.state import AgentState, GuideSettings, VerifyDecision
from city_guide.backends import EndpointBackend
from city_guide.config import SearchConfig
from city_guide.narrator import build_evidence
from city_guide.narrator import narrate as engine_narrate
from city_guide.pipeline import gather as engine_gather
from city_guide.pipeline import warm_context
from city_guide.store import GuideStore
from city_guide.verifier import verify_and_repair

logger = logging.getLogger(__name__)

FALLBACK_NARRATION = "I'm having trouble putting that together right now -- mind trying again in a moment?"
GENERIC_FAILURE_REPLY = "Sorry, I ran into a problem putting that together. Mind trying again?"

# Sanity bounds -- catches obviously malformed payloads (e.g. swapped
# lat/lon, stray (0, 0) defaults) before they propagate downstream.
_LAT_RANGE = (-90.0, 90.0)
_LON_RANGE = (-180.0, 180.0)


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------


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
    """Pins may carry richer context than raw coords (e.g. a place label
    the client already resolved), so keep the label alongside the coords."""
    if not pin:
        return None

    coords = _normalize_coords(pin)
    if coords is None:
        return None

    label = pin.get("label") or pin.get("name")
    return {**coords, "label": label} if label else coords


def intake(state: AgentState) -> dict[str, Any]:
    """Normalize whatever the caller sent into one query dict. Pure code, no LLM."""
    raw = state.get("raw_text")
    text = raw.strip() or None if raw else None
    coords = _normalize_coords(state.get("coords"))
    pin = _normalize_pin(state.get("pin"))

    # A pin implies a location; prefer it over raw coords if both are
    # present (the client likely resolved the pin from a map tap, whereas
    # `coords` might just be a stale device GPS fix).
    location = pin or coords

    if text is None and location is None:
        return {"error": "intake: no usable input -- need at least one of raw_text, coords, or pin."}

    query = {
        "text": text,
        "location": location,  # {"lat", "lon", "label"?} or None
        "has_text": text is not None,
        "has_location": location is not None,
        "user_id": state.get("user_id"),
    }
    return {"query": query, "error": None}


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


async def plan(state: AgentState) -> dict[str, Any]:
    """Pick engine settings from the free text. No text → defaults, no LLM call.
    Any LLM failure degrades to defaults rather than failing the turn."""
    if state.get("error"):
        return {}

    query = state.get("query")
    if not query:
        return {"error": "plan: no query in state -- intake must run first."}

    text = query.get("text")
    if not text:
        return {"settings": GuideSettings()}

    messages = build_settings_messages(text, bool(query.get("has_location")))
    try:
        settings = await EndpointBackend().generate(messages, GuideSettings, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 -- planning wrong is recoverable, planning nothing is not
        logger.error("plan: LLM call failed (%s); using default settings", exc)
        return {"settings": GuideSettings()}

    if settings.radius_m is not None:
        # Clamp whatever the model said to the engine's sane display range.
        settings.radius_m = max(50, min(settings.radius_m, SearchConfig.max_display_radius))
    return {"settings": settings}


# ---------------------------------------------------------------------------
# gather
# ---------------------------------------------------------------------------


async def gather(state: AgentState) -> dict[str, Any]:
    """Engine gather + baked guide store, driven by the planned settings."""
    if state.get("error"):
        return {}

    query = state.get("query")
    if query is None:
        return {"error": "gather: no query in state -- intake must run first."}
    settings = state.get("settings") or GuideSettings()

    location = query.get("location")
    if not location:
        # No pin -> nothing geo to gather; narrate answers from the query alone.
        return {"evidence": None}

    lat, lon = location["lat"], location["lon"]
    display, analysis, data = await engine_gather(
        lat,
        lon,
        radius=settings.radius_m,
        theme=settings.theme,
        interest=settings.interest or query.get("text"),
        with_web=settings.with_web,
    )
    baked = warm_context(GuideStore(), lat, lon, settings.radius_m or SearchConfig.default_display_radius)

    evidence = build_evidence(display, analysis, data.tavily_snippets, baked)
    return {
        "evidence": evidence,
        "evidence_stats": {
            "places": len(display.places),
            "web_snippets": len(data.tavily_snippets or []),
            "baked_stories": len(baked),
        },
    }


# ---------------------------------------------------------------------------
# narrate
# ---------------------------------------------------------------------------


async def narrate(state: AgentState) -> dict[str, Any]:
    """The single storyteller call, with the settings' language/theme/verbosity."""
    if state.get("error"):
        return {}

    query = state.get("query")
    if not query:
        return {"error": "narrate: no query in state -- intake must run first."}
    settings = state.get("settings") or GuideSettings()

    evidence = state.get("evidence")
    if not evidence:
        # Empty pin: honest no-story answer, zero LLM calls (mirrors the CLI guard).
        no_data = "I don't have any data about this exact spot -- try another pin."
        return {"narration": no_data, "narrator_messages": None}

    try:
        story, messages = await engine_narrate(
            evidence,
            EndpointBackend(),
            language=settings.language,
            theme=settings.theme,
            verbosity=settings.verbosity,
        )
    except Exception as exc:  # noqa: BLE001 -- a narration failure shouldn't crash the turn
        logger.error("narrate: storyteller call failed: %s", exc)
        return {"narration": FALLBACK_NARRATION, "narrator_messages": None}

    return {"narration": story or FALLBACK_NARRATION, "narrator_messages": messages}


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


async def verify(state: AgentState) -> dict[str, Any]:
    """Engine verify → regenerate → strip. Retry happens inside verify_and_repair,
    so route() always answers "reply"."""
    if state.get("error"):
        return {}

    narration = state.get("narration")
    evidence = state.get("evidence")
    messages = state.get("narrator_messages")
    if not narration or not evidence or not messages:
        # Nothing checkable (fallback narration, empty pin) -- pass through.
        return {"verify_report": None, "decision": "reply"}

    try:
        story, report, regenerated = await verify_and_repair(narration, messages, evidence, EndpointBackend())
    except Exception as exc:  # noqa: BLE001 -- verification failing shouldn't eat the story
        logger.error("verify: judge call failed: %s", exc)
        return {"verify_report": None, "decision": "reply"}

    return {
        "narration": story,
        "verify_report": report.summary(),
        "verify_regenerated": regenerated,
        "decision": "reply",
    }


def route(state: AgentState) -> VerifyDecision:
    """Conditional-edge router; the retry loop lives inside verify_and_repair."""
    return state.get("decision") or "reply"


# ---------------------------------------------------------------------------
# reply
# ---------------------------------------------------------------------------


def reply(state: AgentState) -> dict[str, Any]:
    """Final text. Never fails the turn -- upstream errors become a safe apology."""
    if state.get("error"):
        logger.warning("reply: finalizing with upstream error: %s", state["error"])
        return {"reply": GENERIC_FAILURE_REPLY}

    narration = state.get("narration")
    if not narration:
        logger.warning("reply: no narration in state -- narrate must run first.")
        return {"reply": GENERIC_FAILURE_REPLY}

    text = narration
    report = state.get("verify_report")
    if report:
        text += f"\n\n_verification: {report}_"
    return {"reply": text}
