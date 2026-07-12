"""Tests for collector module — merging, dedup, and enrichment."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from city_guide.collector import (
    CollectedData,
    CollectorSources,
    collect,
)
from city_guide.config import WikidataConfig
from city_guide.place import DisplayData, filter_by_radius
from city_guide.sources.overpass import OverpassPOI, deduplicate_pois
from city_guide.sources.tavily import TavilySnippet
from city_guide.sources.wikidata import WikidataItem
from city_guide.sources.wikipedia import WikiArticle
from city_guide.types import Theme


def _poi(name: str, lat: float = 51.5, lon: float = -0.1, **kwargs: Any) -> OverpassPOI:
    return OverpassPOI(
        name=name,
        type=kwargs.get("type", "Cafe"),
        lat=lat,
        lon=lon,
        **{k: v for k, v in kwargs.items() if k != "type"},
    )


def _raw_element(name: str, lat: float, lon: float, amenity: str = "cafe", **tags: str) -> dict[str, Any]:
    """Build a minimal raw Overpass API element dict for mock fetch returns."""
    t: dict[str, str] = {"name": name, "amenity": amenity, **tags}
    return {"type": "node", "lat": lat, "lon": lon, "tags": t}


# ---------------------------------------------------------------------------
# deduplicate_pois tests (function now lives in overpass.py)
# ---------------------------------------------------------------------------


def test_deduplicate_pois_removes_dupes() -> None:
    pois = [
        _poi("Test Cafe", lat=51.5, lon=-0.1),
        _poi("Test Cafe", lat=51.501, lon=-0.101),
        _poi("Other Place", lat=51.502, lon=-0.102),
    ]
    result = deduplicate_pois(pois)
    assert len(result) == 2
    # Keeps first occurrence
    cafe = next(r for r in result if r.name == "Test Cafe")
    assert cafe.lat == 51.5


def test_deduplicate_pois_case_insensitive() -> None:
    pois = [
        _poi("Test Cafe"),
        _poi("test cafe"),
    ]
    result = deduplicate_pois(pois)
    assert len(result) == 1


def test_deduplicate_pois_preserves_order() -> None:
    """Dedup preserves input order."""
    pois = [
        _poi("A Place"),
        _poi("B Place"),
        _poi("C Place"),
    ]
    result = deduplicate_pois(pois)
    assert [r.name for r in result] == ["A Place", "B Place", "C Place"]


def test_display_data_to_display_dict() -> None:
    from city_guide.place import Place
    from city_guide.types import Source

    data = DisplayData(
        lat=51.5,
        lon=-0.1,
        places=[
            Place(
                name="Cafe",
                lat=51.501,
                lon=-0.1,
                distance_m=50,
                bearing=None,
                source=Source.OVERPASS,
                maps_url="https://maps.example.com/cafe",
                type="Cafe",
            ),
        ],
    )
    d = data.to_display_dict()
    assert d["lat"] == 51.5
    assert len(d["places"]) == 1
    assert d["places"][0]["name"] == "Cafe"
    assert d["places"][0]["maps_url"] == "https://maps.example.com/cafe"


def _make_sources(
    overpass_return: list[dict[str, Any]] | None = None,
    wiki_return: list[WikiArticle] | None = None,
    wikidata_return: list[WikidataItem] | None = None,
    tavily_return: list[TavilySnippet] | None = None,
) -> CollectorSources:
    """Build a CollectorSources with AsyncMock callables."""
    return CollectorSources(
        fetch_raw_elements=AsyncMock(return_value=overpass_return if overpass_return is not None else []),
        fetch_nearby_articles=AsyncMock(return_value=wiki_return if wiki_return is not None else []),
        fetch_wikidata=AsyncMock(return_value=wikidata_return if wikidata_return is not None else []),
        tavily_search=AsyncMock(return_value=tavily_return if tavily_return is not None else []),
    )


async def test_collect_empty_results() -> None:
    sources = _make_sources()
    data = await collect(51.5, -0.1, sources=sources)
    assert isinstance(data, CollectedData)
    assert data.overpass_pois == []
    assert data.wikipedia_articles == []


async def test_collect_parses_overpass_pois() -> None:
    sources = _make_sources(
        overpass_return=[
            _raw_element("Cafe A", 51.501, -0.1),
            _raw_element("Cafe A", 51.502, -0.1),
            _raw_element("Bar B", 51.503, -0.1, amenity="bar"),
        ],
    )
    data = await collect(51.5, -0.1, sources=sources)
    # Parsed into OverpassPOI objects (no dedup/filtering at collect time)
    assert len(data.overpass_pois) == 3
    assert all(isinstance(poi, OverpassPOI) for poi in data.overpass_pois)
    assert data.overpass_pois[0].name == "Cafe A"


async def test_collect_radius_override() -> None:
    sources = _make_sources()
    await collect(51.5, -0.1, radius_override=500, sources=sources)
    sources.fetch_raw_elements.assert_called_once_with(51.5, -0.1, 500, tags=None)  # type: ignore[attr-defined]


async def test_collect_single_wiki_fetch() -> None:
    """Wiki should be fetched once (no more near/far layering)."""
    sources = _make_sources()
    await collect(51.5, -0.1, sources=sources)
    assert sources.fetch_nearby_articles.call_count == 1  # type: ignore[attr-defined]


async def test_collect_themed_passes_overpass_tags() -> None:
    """Themed search should pass overpass_tags to fetch_nearby."""
    sources = _make_sources()
    await collect(51.5, -0.1, theme=Theme.HISTORY, sources=sources)
    call_args = sources.fetch_raw_elements.call_args  # type: ignore[attr-defined]
    assert call_args[1]["tags"] == ["tourism", "historic"]


async def test_collect_default_passes_no_overpass_tags() -> None:
    """Default theme should pass tags=None to fetch_nearby."""
    sources = _make_sources()
    await collect(51.5, -0.1, theme=Theme.DEFAULT, sources=sources)
    call_args = sources.fetch_raw_elements.call_args  # type: ignore[attr-defined]
    assert call_args[1]["tags"] is None


async def test_collect_themed_uses_fetch_radius() -> None:
    """All themes fetch at fetch_radius (500) for all sources."""
    sources = _make_sources()
    await collect(51.5, -0.1, theme=Theme.FOOD, sources=sources)
    # Overpass should use fetch_radius (500)
    overpass_args = sources.fetch_raw_elements.call_args  # type: ignore[attr-defined]
    assert overpass_args[0][2] == 500
    # Wiki should use fetch_radius (500)
    wiki_args = sources.fetch_nearby_articles.call_args  # type: ignore[attr-defined]
    assert wiki_args[1]["radius"] == 500


# ---------------------------------------------------------------------------
# Tavily merge/dedup tests
# ---------------------------------------------------------------------------


async def test_collect_no_tavily_queries() -> None:
    """Without tavily_queries, tavily_search is not called and snippets stay None."""
    sources = _make_sources()
    data = await collect(51.5, -0.1, sources=sources)
    sources.tavily_search.assert_not_called()  # type: ignore[union-attr]
    assert data.tavily_snippets is None


async def test_collect_tavily_merges_and_dedupes_by_url() -> None:
    """Snippets from multiple queries are merged, deduped by URL, first occurrence kept."""
    snippet_a = TavilySnippet(title="A", url="https://a.example.com", content="a")
    snippet_a_dup = TavilySnippet(title="A again", url="https://a.example.com", content="a2")
    snippet_b = TavilySnippet(title="B", url="https://b.example.com", content="b")
    sources = _make_sources()
    sources.tavily_search = AsyncMock(side_effect=[[snippet_a], [snippet_a_dup, snippet_b]])

    data = await collect(51.5, -0.1, tavily_queries=["q1", "q2"], sources=sources)

    assert sources.tavily_search.call_count == 2
    assert data.tavily_snippets is not None
    assert [s.url for s in data.tavily_snippets] == ["https://a.example.com", "https://b.example.com"]
    assert data.tavily_snippets[0].title == "A"


async def test_overpass_poi_cache_roundtrip() -> None:
    """OverpassPOI objects should survive cache serialization roundtrip."""
    data = CollectedData(
        lat=51.5,
        lon=-0.1,
        overpass_pois=[OverpassPOI(name="Cafe", type="Cafe", lat=51.501, lon=-0.1, cuisine="italian")],
    )
    cache_dict = data.model_dump()
    restored = CollectedData.model_validate(cache_dict)
    assert len(restored.overpass_pois) == 1
    assert restored.overpass_pois[0].name == "Cafe"
    assert restored.overpass_pois[0].cuisine == "italian"


# ---------------------------------------------------------------------------
# filter_by_radius tests
# ---------------------------------------------------------------------------


def test_filter_by_radius_pois_within() -> None:
    """POIs within radius are kept, those outside are dropped."""
    data = CollectedData(
        lat=51.5,
        lon=-0.1,
        overpass_pois=[
            _poi("Near", lat=51.5001, lon=-0.1),
            _poi("Far", lat=51.51, lon=-0.1),
        ],
    )
    result = filter_by_radius(data, 51.5, -0.1, 200)
    overpass_places = [p for p in result.places if p.source == "overpass"]
    assert len(overpass_places) == 1
    assert overpass_places[0].name == "Near"


def test_filter_by_radius_returns_display_data() -> None:
    """filter_by_radius should return DisplayData, not CollectedData."""
    data = CollectedData(lat=51.5, lon=-0.1)
    result = filter_by_radius(data, 51.5, -0.1, 200)
    assert isinstance(result, DisplayData)


def test_filter_by_radius_wiki_trimmed() -> None:
    """Wiki articles are sorted by distance and trimmed to wiki_limit."""
    articles = [
        WikiArticle(title=f"Art{i}", extract="x", distance=float(i * 10), lat=51.5 + i * 0.0001, lon=-0.1, pageid=i)
        for i in range(1, 8)
    ]
    data = CollectedData(lat=51.5, lon=-0.1, wikipedia_articles=articles)
    result = filter_by_radius(data, 51.5, -0.1, 500, wiki_limit=3)
    wiki_places = [p for p in result.places if p.source == "wikipedia"]
    assert len(wiki_places) == 3
    # Sorted by distance from user
    assert wiki_places[0].name == "Art1"


def test_filter_by_radius_wiki_bearing_enriched() -> None:
    """Wiki articles get bearing computed from user position."""
    articles = [
        WikiArticle(title="North", extract="x", distance=100.0, lat=51.501, lon=-0.1, pageid=1),
    ]
    data = CollectedData(lat=51.5, lon=-0.1, wikipedia_articles=articles)
    result = filter_by_radius(data, 51.5, -0.1, 500)
    wiki_places = [p for p in result.places if p.source == "wikipedia"]
    assert len(wiki_places) == 1
    assert wiki_places[0].bearing is not None
    # Point is roughly north
    assert wiki_places[0].bearing < 5 or wiki_places[0].bearing > 355


def test_filter_by_radius_computes_distance() -> None:
    """Distances are computed from user's actual position."""
    data = CollectedData(
        lat=51.5,
        lon=-0.1,
        overpass_pois=[_poi("A", lat=51.5001, lon=-0.1)],
    )
    result = filter_by_radius(data, 51.5, -0.1, 200)
    overpass_places = [p for p in result.places if p.source == "overpass"]
    assert len(overpass_places) == 1
    assert overpass_places[0].distance_m < 20


# ---------------------------------------------------------------------------
# Wikidata integration tests
# ---------------------------------------------------------------------------


async def test_collect_calls_wikidata() -> None:
    """Wikidata fetch should be called during collect()."""
    wikidata_items = [
        WikidataItem(name="Tower", description="historic", distance=100.0, lat=51.501, lon=-0.1, item_type="tower")
    ]
    sources = _make_sources(wikidata_return=wikidata_items)
    data = await collect(51.5, -0.1, sources=sources)
    sources.fetch_wikidata.assert_called_once()  # type: ignore[union-attr]
    assert data.wikidata_items is not None
    assert len(data.wikidata_items) == 1
    assert data.wikidata_items[0].name == "Tower"


async def test_collect_wikidata_none_source() -> None:
    """When fetch_wikidata is None, wikidata_items should be None."""
    sources = _make_sources()
    sources.fetch_wikidata = None
    data = await collect(51.5, -0.1, sources=sources)
    assert data.wikidata_items is None


async def test_wikidata_cache_roundtrip() -> None:
    """WikidataItem should survive cache serialization roundtrip."""
    data = CollectedData(
        lat=51.5,
        lon=-0.1,
        wikidata_items=[
            WikidataItem(
                name="Tower",
                description="historic tower",
                distance=100.0,
                lat=51.501,
                lon=-0.1,
                item_type="tower",
                founded="1066-01-01",
            )
        ],
    )
    cache_dict = data.model_dump()
    restored = CollectedData.model_validate(cache_dict)
    assert restored.wikidata_items is not None
    assert len(restored.wikidata_items) == 1
    assert restored.wikidata_items[0].name == "Tower"
    assert restored.wikidata_items[0].founded == "1066-01-01"


async def test_wikidata_cache_roundtrip_none() -> None:
    """None wikidata_items should survive cache roundtrip."""
    data = CollectedData(lat=51.5, lon=-0.1, wikidata_items=None)
    cache_dict = data.model_dump()
    restored = CollectedData.model_validate(cache_dict)
    assert restored.wikidata_items is None


def test_filter_by_radius_wikidata() -> None:
    """Wikidata items within radius are kept, outside are dropped."""
    items = [
        WikidataItem(name="Near", description="", distance=50.0, lat=51.5001, lon=-0.1, item_type="building"),
        WikidataItem(name="Far", description="", distance=9999.0, lat=51.51, lon=-0.1, item_type="building"),
    ]
    data = CollectedData(lat=51.5, lon=-0.1, wikidata_items=items)
    result = filter_by_radius(data, 51.5, -0.1, 200)
    wikidata_places = [p for p in result.places if p.source == "wikidata"]
    assert len(wikidata_places) == 1
    assert wikidata_places[0].name == "Near"


def test_filter_by_radius_wikidata_display_limit() -> None:
    """Wikidata items are trimmed to WikidataConfig.display_limit."""
    items = [
        WikidataItem(
            name=f"Item{i}",
            description="",
            distance=float(i * 10),
            lat=51.5 + i * 0.00001,
            lon=-0.1,
            item_type="building",
        )
        for i in range(1, 20)
    ]
    data = CollectedData(lat=51.5, lon=-0.1, wikidata_items=items)
    result = filter_by_radius(data, 51.5, -0.1, 5000)
    wikidata_places = [p for p in result.places if p.source == "wikidata"]
    assert len(wikidata_places) == WikidataConfig.display_limit


def test_filter_by_radius_wikidata_preserves_optional_fields() -> None:
    """All optional fields (founded, architect, named_after, etc.) survive filter_by_radius."""
    items = [
        WikidataItem(
            name="Tower",
            description="historic tower",
            distance=50.0,
            lat=51.5001,
            lon=-0.1,
            item_type="tower",
            founded="1066-01-01",
            architect="William",
            notable_event="Great Fire",
            named_after="King",
            creator="Builder",
            arch_style="Gothic",
            opening_date="1067-01-01",
            heritage="Grade I",
            native_label="La Tour",
        ),
    ]
    data = CollectedData(lat=51.5, lon=-0.1, wikidata_items=items)
    result = filter_by_radius(data, 51.5, -0.1, 200)
    wikidata_places = [p for p in result.places if p.source == "wikidata"]
    assert len(wikidata_places) == 1
    p = wikidata_places[0]
    assert p.extras["founded"] == "1066-01-01"
    assert p.extras["architect"] == "William"
    assert p.extras["notable_event"] == "Great Fire"
    assert p.extras["named_after"] == "King"
    assert p.extras["creator"] == "Builder"
    assert p.extras["arch_style"] == "Gothic"
    assert p.extras["opening_date"] == "1067-01-01"
    assert p.extras["heritage"] == "Grade I"
    assert p.extras["native_label"] == "La Tour"


def test_filter_by_radius_wikidata_none() -> None:
    """When wikidata_items is None, no wikidata places in result."""
    data = CollectedData(lat=51.5, lon=-0.1, wikidata_items=None)
    result = filter_by_radius(data, 51.5, -0.1, 200)
    wikidata_places = [p for p in result.places if p.source == "wikidata"]
    assert len(wikidata_places) == 0


# ---------------------------------------------------------------------------
# places population tests
# ---------------------------------------------------------------------------


def test_filter_by_radius_populates_places() -> None:
    """filter_by_radius should populate the places list."""
    data = CollectedData(
        lat=51.5,
        lon=-0.1,
        overpass_pois=[_poi("Cafe", lat=51.5001, lon=-0.1)],
        wikipedia_articles=[
            WikiArticle(title="Big Ben", extract="x", distance=100.0, lat=51.5002, lon=-0.1, pageid=1),
        ],
    )
    result = filter_by_radius(data, 51.5, -0.1, 500)
    assert len(result.places) == 2
    sources = {p.source for p in result.places}
    assert "overpass" in sources
    assert "wikipedia" in sources


def test_filter_by_radius_places_have_urls() -> None:
    """Each place should have a maps_url, wikipedia places also get wiki_url."""
    data = CollectedData(
        lat=51.5,
        lon=-0.1,
        wikipedia_articles=[
            WikiArticle(title="Big Ben", extract="x", distance=100.0, lat=51.5002, lon=-0.1, pageid=1),
        ],
    )
    result = filter_by_radius(data, 51.5, -0.1, 500)
    assert len(result.places) == 1
    p = result.places[0]
    assert p.maps_url != ""
    assert p.wiki_url != ""
    assert "Big_Ben" in p.wiki_url
