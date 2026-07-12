"""Collector — orchestrate all data sources and merge results."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from city_guide.config import SearchConfig, WikiConfig
from city_guide.sources.overpass import OverpassPOI, parse_raw_elements
from city_guide.sources.tavily import TavilySnippet
from city_guide.sources.wikidata import WikidataItem
from city_guide.sources.wikipedia import WikiArticle
from city_guide.types import THEME_CONFIGS, WIKI_LANGUAGE, Theme

logger = logging.getLogger(__name__)


class CollectedData(BaseModel):
    """Raw per-source data from ``collect()``."""

    lat: float = 0.0
    lon: float = 0.0
    overpass_pois: list[OverpassPOI] = []
    wikipedia_articles: list[WikiArticle] = []
    wikidata_items: list[WikidataItem] | None = None
    tavily_snippets: list[TavilySnippet] | None = None


class FetchRawElementsProto(Protocol):
    async def __call__(
        self, lat: float, lon: float, radius: int, tags: list[str] | None = None
    ) -> list[dict[str, Any]]: ...


class FetchArticlesProto(Protocol):
    async def __call__(
        self, lat: float, lon: float, *, radius: int, limit: int, language: str, with_images: bool
    ) -> list[WikiArticle]: ...


class FetchWikidataProto(Protocol):
    async def __call__(self, lat: float, lon: float, radius: int) -> list[WikidataItem]: ...


class TavilySearchProto(Protocol):
    async def __call__(self, query: str, *, max_results: int | None = None) -> list[TavilySnippet]: ...


@dataclass
class CollectorSources:
    """Pluggable data-source callables for ``collect()``."""

    fetch_raw_elements: FetchRawElementsProto
    fetch_nearby_articles: FetchArticlesProto
    fetch_wikidata: FetchWikidataProto | None = None
    tavily_search: TavilySearchProto | None = None

    @classmethod
    def default(cls) -> CollectorSources:
        """Return sources wired to the real API functions."""
        from city_guide.sources.overpass import fetch_raw_elements as _overpass_raw
        from city_guide.sources.tavily import search as _tavily
        from city_guide.sources.wikidata import fetch_wikidata as _wikidata
        from city_guide.sources.wikipedia import fetch_nearby_articles as _wiki

        return cls(
            fetch_raw_elements=_overpass_raw,
            fetch_nearby_articles=_wiki,
            fetch_wikidata=_wikidata,
            tavily_search=_tavily,
        )


async def _safe_fetch(label: str, coro: Awaitable[list[Any]]) -> list[Any]:
    """Run *coro* and return its result, returning ``[]`` on any exception."""
    try:
        return await coro
    except Exception as exc:
        logger.warning("%s fetch failed: %r", label, exc)
        logger.debug("%s fetch traceback", label, exc_info=True)
        return []


async def collect(
    lat: float,
    lon: float,
    *,
    radius_override: int | None = None,
    theme: Theme = Theme.DEFAULT,
    tavily_queries: list[str] | None = None,
    with_wikidata: bool = True,
    with_geo: bool = True,
    sources: CollectorSources | None = None,
) -> CollectedData:
    """Collect data from all sources in parallel — no display filtering.

    tavily_queries: templated web-search queries; skipped when empty or no API key.
    with_geo: False skips Overpass/Wikipedia — for a Tavily-only second pass.
    """
    if sources is None:
        sources = CollectorSources.default()

    theme_config = THEME_CONFIGS[theme]
    radius = radius_override if radius_override is not None else SearchConfig.fetch_radius
    overpass_tags = list(theme_config.overpass_tags) if theme_config.overpass_tags is not None else None

    coros: dict[str, Any] = {}
    if with_geo:
        coros["overpass"] = _safe_fetch("Overpass", sources.fetch_raw_elements(lat, lon, radius, tags=overpass_tags))
        coros["wikipedia"] = _safe_fetch(
            "Wikipedia",
            sources.fetch_nearby_articles(
                lat, lon, radius=radius, limit=WikiConfig.fetch_limit, language=WIKI_LANGUAGE, with_images=False
            ),
        )
    if with_wikidata and sources.fetch_wikidata is not None:
        coros["wikidata"] = _safe_fetch("Wikidata", sources.fetch_wikidata(lat, lon, radius))
    if tavily_queries and sources.tavily_search is not None:
        for i, query in enumerate(tavily_queries):
            coros[f"tavily_{i}"] = _safe_fetch("Tavily", sources.tavily_search(query))

    keys = list(coros.keys())
    values = await asyncio.gather(*coros.values())
    results = dict(zip(keys, values, strict=True))

    tavily_snippets: list[TavilySnippet] = []
    seen_urls: set[str] = set()
    for key in keys:
        if not key.startswith("tavily_"):
            continue
        for snippet in results[key]:
            if snippet.url in seen_urls:
                continue
            seen_urls.add(snippet.url)
            tavily_snippets.append(snippet)

    return CollectedData(
        lat=lat,
        lon=lon,
        overpass_pois=parse_raw_elements(results.get("overpass", [])),
        wikipedia_articles=results.get("wikipedia", []),
        wikidata_items=results.get("wikidata"),
        tavily_snippets=tavily_snippets or None,
    )
