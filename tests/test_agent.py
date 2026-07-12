"""Agent shell — intake normalization, settings fallback, full-graph smoke run."""

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("langgraph")

from agent import nodes  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from agent.state import GuideSettings, initial_state  # noqa: E402
from city_guide.types import StoryResponse, Theme, Verbosity, VerifyReport  # noqa: E402


def test_intake_normalizes_lng_alias_and_strings() -> None:
    out = nodes.intake(initial_state(coords={"lat": "51.5", "lng": "-0.12"}))
    assert out["query"]["location"] == {"lat": 51.5, "lon": -0.12}


def test_intake_rejects_out_of_range() -> None:
    out = nodes.intake(initial_state(coords={"lat": 91, "lon": 0}))
    assert out["error"]


def test_intake_pin_beats_coords() -> None:
    out = nodes.intake(initial_state(coords={"lat": 1.0, "lon": 1.0}, pin={"lat": 2.0, "lon": 2.0, "label": "Cafe"}))
    assert out["query"]["location"] == {"lat": 2.0, "lon": 2.0, "label": "Cafe"}


async def test_plan_defaults_without_text() -> None:
    out = await nodes.plan({"query": {"text": None, "has_location": True}})
    assert out["settings"] == GuideSettings()


async def test_plan_falls_back_on_llm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        async def generate(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("endpoint down")

    monkeypatch.setattr(nodes, "EndpointBackend", Boom)
    out = await nodes.plan({"query": {"text": "any food here?", "has_location": True}})
    assert out["settings"] == GuideSettings()


async def test_plan_clamps_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        async def generate(self, *args: Any, **kwargs: Any) -> GuideSettings:
            return GuideSettings(radius_m=5000)

    monkeypatch.setattr(nodes, "EndpointBackend", Fake)
    out = await nodes.plan({"query": {"text": "the whole city please", "has_location": True}})
    assert out["settings"].radius_m == 500


async def test_graph_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """One full turn: settings drive gather + narrate, verified reply comes out."""
    seen: dict[str, Any] = {}

    class FakeBackend:
        async def generate(self, messages: Any, schema: Any, *, temperature: float) -> Any:
            if schema is GuideSettings:
                return GuideSettings(theme=Theme.FOOD, verbosity=Verbosity.SHORT, with_web=False)
            if schema is StoryResponse:
                return StoryResponse(text="A tasty corner.")
            if schema is VerifyReport:
                return VerifyReport(claims=[])
            raise AssertionError(f"unexpected schema {schema}")

    async def fake_gather(lat: float, lon: float, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(places=[object()]), None, SimpleNamespace(tavily_snippets=None)

    monkeypatch.setattr(nodes, "EndpointBackend", FakeBackend)
    monkeypatch.setattr(nodes, "engine_gather", fake_gather)
    monkeypatch.setattr(nodes, "build_evidence", lambda *args: "EVIDENCE")
    monkeypatch.setattr(nodes, "warm_context", lambda *args: [])

    result = await build_graph().ainvoke(
        initial_state(raw_text="best food here? briefly", coords={"lat": 51.5, "lon": -0.12})
    )

    assert seen["theme"] == Theme.FOOD  # the planned settings actually reached the engine
    assert seen["with_web"] is False
    assert result["reply"].startswith("A tasty corner.")
    assert "_verification:" in result["reply"]


async def test_graph_error_turns_into_safe_reply() -> None:
    result = await build_graph().ainvoke(initial_state())
    assert result["reply"] == nodes.GENERIC_FAILURE_REPLY
