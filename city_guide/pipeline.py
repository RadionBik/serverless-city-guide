"""Pipeline — gather → analyze → evidence, plus tour planning. Shared by CLI and job."""

from __future__ import annotations

import logging
import time

from city_guide.analyze import AnalysisResult, analyze
from city_guide.backends import LLMBackend
from city_guide.collector import CollectedData, collect
from city_guide.config import SearchConfig, TourConfig
from city_guide.curator import curate
from city_guide.place import DisplayData, filter_by_radius
from city_guide.route import compose_route, walking_maps_url
from city_guide.store import GuideStore
from city_guide.types import (
    THEME_CONFIGS,
    Candidate,
    Language,
    Source,
    StopStory,
    Theme,
    TourPlan,
)

logger = logging.getLogger(__name__)


def _tavily_queries(data: CollectedData, interest: str | None) -> list[str]:
    """Templated web queries — anchored on the closest named article/POI, no LLM."""
    anchor = ""
    if data.wikipedia_articles:
        anchor = data.wikipedia_articles[0].title
    elif data.overpass_pois:
        anchor = data.overpass_pois[0].name
    if not anchor:
        return []
    queries = [f"{anchor} history interesting facts"]
    if interest:
        queries.append(f"{interest} near {anchor}")
    return queries


async def gather(
    lat: float,
    lon: float,
    *,
    radius: int | None = None,
    theme: Theme = Theme.DEFAULT,
    interest: str | None = None,
    with_web: bool = True,
) -> tuple[DisplayData, AnalysisResult | None, CollectedData]:
    """Fixed parallel fan-out + deterministic analysis. Two passes when web search is on:
    geo sources first (they name the anchor), then Tavily with templated queries."""
    display_radius = radius or SearchConfig.default_display_radius
    fetch_radius = max(display_radius, SearchConfig.fetch_radius)

    data = await collect(lat, lon, radius_override=fetch_radius, theme=theme)
    if with_web:
        queries = _tavily_queries(data, interest)
        if queries:
            web = await collect(
                lat, lon, radius_override=fetch_radius, theme=theme, tavily_queries=queries, with_wikidata=False
            )
            data = data.model_copy(update={"tavily_snippets": web.tavily_snippets})

    wiki_limit = THEME_CONFIGS[theme].wiki_limit
    display = filter_by_radius(data, lat, lon, display_radius, wiki_limit=wiki_limit)
    return display, analyze(display), data


def build_candidates(display: DisplayData) -> list[Candidate]:
    """ID'd curation candidates — wiki-backed places first (pre-rank proxy), then by distance."""
    places = sorted(
        display.places,
        key=lambda p: (Source.WIKIPEDIA not in p.sources and p.source != Source.WIKIPEDIA, p.distance_m),
    )
    candidates = []
    for i, place in enumerate(places[: TourConfig.max_candidates]):
        candidates.append(
            Candidate(
                id=i,
                name=place.name,
                kind=place.type or str(place.source),
                dist_m=place.distance_m,
                hint=place.description[:150],
                lat=place.lat,
                lon=place.lon,
            )
        )
    return candidates


async def plan_tour(
    lat: float,
    lon: float,
    interest: str,
    backend: LLMBackend,
    *,
    language: Language = Language.EN,
    length_m: int | None = None,
    circular: bool = True,
    store: GuideStore | None = None,
) -> TourPlan:
    """Submit-time tour planning: gather wide → curate (LLM, by ID) → route (code).

    Route length is the one knob: it sets the gather radius (a circular route of
    length L reaches ~L/2 from the pin), the curator's stop budget, and the trim
    cap. Sparse areas may undershoot the target — never padded artificially.
    """
    target = length_m or TourConfig.default_length_meters
    radius = max(300, min(target // 2, TourConfig.candidate_radius))
    max_stops = max(TourConfig.min_stops, min(TourConfig.max_stops, target // TourConfig.meters_per_stop))

    display, _, _ = await gather(lat, lon, radius=radius, interest=interest, with_web=False)
    candidates = build_candidates(display)
    if not candidates:
        return TourPlan(
            guide_id=_guide_id(lat, lon),
            origin_lat=lat,
            origin_lon=lon,
            interest=interest,
            language=language,
            circular=circular,
            target_length_m=target,
            note="No candidate places found around this location.",
        )

    curated = await curate(candidates, interest, backend, min_stops=TourConfig.min_stops, max_stops=max_stops)
    stops, total = compose_route(lat, lon, candidates, curated.stops, max_length=target, circular=circular)
    guide_id = _guide_id(lat, lon)
    if store is not None:
        store.save_trace(
            guide_id,
            "curation",
            {
                "interest": interest,
                "candidates": [c.model_dump() for c in candidates],
                "picks": [p.model_dump() for p in curated.stops],
                "note": curated.note,
            },
        )
    return TourPlan(
        guide_id=guide_id,
        origin_lat=lat,
        origin_lon=lon,
        interest=interest,
        language=language,
        note=curated.note,
        stops=stops,
        circular=circular,
        target_length_m=target,
        total_length_m=total,
        maps_url=walking_maps_url(lat, lon, stops, circular=circular),
    )


def _guide_id(lat: float, lon: float) -> str:
    return f"tour-{lat:.4f}_{lon:.4f}-{int(time.time())}"


def warm_context(store: GuideStore, lat: float, lon: float, radius: int) -> list[StopStory]:
    """Baked stops near the pin — the guide-store read that makes warm areas richer."""
    try:
        return store.nearby_stops(lat, lon, radius)
    except Exception:
        logger.warning("Guide store lookup failed", exc_info=True)
        return []
