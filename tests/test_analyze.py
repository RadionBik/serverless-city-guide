"""Tests for city_guide.analyze — deterministic analysis layer."""

from __future__ import annotations

from collections import Counter
from typing import Any

from city_guide.analyze import (
    AnalysisResult,
    Highlight,
    _build_fingerprint,
    _build_ghost_layer,
    _detect_signals,
    _find_absences,
    _find_cross_references,
    _find_notable_types,
    _generate_investigation_prompts,
    _score_highlights,
    _source_bonus,
    analyze,
)
from city_guide.config import AnalysisCapsConfig
from city_guide.place import DisplayData, Place, normalize
from city_guide.sources.overpass import OverpassPOI
from city_guide.sources.wikidata import WikidataItem
from city_guide.sources.wikipedia import WikiArticle
from city_guide.types import Source

# ---------------------------------------------------------------------------
# Helpers — inline fixtures
# ---------------------------------------------------------------------------


def _poi(name: str, ptype: str = "Restaurant", lat: float = 51.47, lon: float = -0.02) -> OverpassPOI:
    return OverpassPOI(name=name, type=ptype, lat=lat, lon=lon)


def _wiki_article(title: str, distance: float = 100.0) -> WikiArticle:
    return WikiArticle(title=title, extract="Some text.", distance=distance, lat=51.47, lon=-0.02, pageid=1)


def _wikidata_item(
    name: str,
    description: str = "building",
    distance: float = 100.0,
    item_type: str = "building",
    **kwargs: Any,
) -> WikidataItem:
    return WikidataItem(
        name=name,
        description=description,
        distance=distance,
        lat=51.47,
        lon=-0.02,
        item_type=item_type,
        **kwargs,
    )


def _display_data(
    *,
    overpass_pois: list[OverpassPOI] | None = None,
    wikipedia_articles: list[WikiArticle] | None = None,
    wikidata_items: list[WikidataItem] | None = None,
) -> DisplayData:
    """Build DisplayData with places auto-populated via normalize()."""
    places = normalize(
        overpass_pois=overpass_pois,
        wikipedia_articles=wikipedia_articles,
        wikidata_items=wikidata_items,
    )
    return DisplayData(lat=51.47, lon=-0.02, places=places)


# ---------------------------------------------------------------------------
# _build_fingerprint
# ---------------------------------------------------------------------------


class TestBuildFingerprint:
    def test_empty(self) -> None:
        assert _build_fingerprint(Counter()) == "no POIs"

    def test_basic(self) -> None:
        types = Counter({"Restaurant": 10, "Cafe": 5, "Pub": 3})
        fp = _build_fingerprint(types)
        assert "10× Restaurant" in fp
        assert "5× Cafe" in fp
        assert "3× Pub" in fp

    def test_caps_at_max(self) -> None:
        types = Counter({f"Type{i}": 10 - i for i in range(10)})
        fp = _build_fingerprint(types)
        # Should only have AnalysisCapsConfig.max_fingerprint_types entries
        assert fp.count("×") == 6


# ---------------------------------------------------------------------------
# _find_notable_types
# ---------------------------------------------------------------------------


class TestFindNotableTypes:
    def test_tattoo_cluster(self) -> None:
        """Camden-like: 6 tattoo shops should trigger notable (threshold=2)."""
        types = Counter({"Tattoo": 6, "Restaurant": 20, "Cafe": 10})
        result = _find_notable_types(types)
        assert any("Tattoo" in r for r in result)
        assert any("6×" in r for r in result)

    def test_below_threshold(self) -> None:
        types = Counter({"Tattoo": 1, "Restaurant": 20})
        result = _find_notable_types(types)
        assert not any("Tattoo" in r for r in result)

    def test_caps_at_max(self) -> None:
        # Create many notable types all above threshold
        types = Counter(
            {
                "Cinema": 5,
                "Theatre": 5,
                "Nightclub": 5,
                "Museum": 5,
                "Tattoo": 5,
                "Gallery": 5,
                "Casino": 5,
                "Marketplace": 5,
            }
        )
        result = _find_notable_types(types)
        assert len(result) <= AnalysisCapsConfig.max_notable


# ---------------------------------------------------------------------------
# _detect_signals
# ---------------------------------------------------------------------------


class TestDetectSignals:
    def test_creative_district(self) -> None:
        """Camden-like creative district signal with breakdown."""
        types = Counter({"Tattoo": 6, "Gallery": 3, "Art": 1})
        result = _detect_signals(types)
        assert len(result) >= 1
        sig = result[0]
        assert "creative district" in sig
        assert "6× Tattoo" in sig
        assert "3× Gallery" in sig

    def test_nightlife_district(self) -> None:
        types = Counter({"Bar": 10, "Nightclub": 5, "Pub": 8})
        result = _detect_signals(types)
        assert any("nightlife district" in s for s in result)

    def test_below_threshold(self) -> None:
        types = Counter({"Bar": 1, "Nightclub": 1})
        result = _detect_signals(types)
        assert not any("nightlife" in s for s in result)

    def test_caps_at_max(self) -> None:
        # Trigger many signals
        types = Counter(
            {
                "Bar": 10,
                "Nightclub": 10,
                "Pub": 10,
                "Tattoo": 10,
                "Gallery": 10,
                "Art": 10,
                "Cinema": 10,
                "Theatre": 10,
                "Restaurant": 20,
                "Fast Food": 10,
                "Cafe": 10,
                "Bookmaker": 10,
                "Pawnbroker": 10,
            }
        )
        result = _detect_signals(types)
        assert len(result) <= AnalysisCapsConfig.max_signals


# ---------------------------------------------------------------------------
# _find_absences
# ---------------------------------------------------------------------------


class TestFindAbsences:
    def test_missing_types(self) -> None:
        types = Counter({"Theatre": 5, "Cinema": 3})
        result = _find_absences(types)
        # All 6 common types are missing, capped at AnalysisCapsConfig.max_absences (3)
        assert len(result) == 3
        # Sorted alphabetically, so first 3: Bar, Cafe, Convenience
        assert "Bar" in result
        assert "Cafe" in result

    def test_all_present(self) -> None:
        types = Counter(
            {"Restaurant": 5, "Cafe": 3, "Pub": 2, "Bar": 1, "Fast Food": 1, "Convenience": 1, "Clothes": 2}
        )
        result = _find_absences(types)
        assert result == []


# ---------------------------------------------------------------------------
# _build_ghost_layer
# ---------------------------------------------------------------------------


class TestBuildGhostLayer:
    def test_former_matched_to_poi(self) -> None:
        """Deptford-like: former cinema matched to nearest current POI."""
        wikidata_places = normalize(wikidata_items=[_wikidata_item("Palace Cinema", "former cinema", distance=50.0)])
        overpass_places = normalize(overpass_pois=[_poi("Happy Money", "Bureau De Change", lat=51.47, lon=-0.02)])
        result = _build_ghost_layer(wikidata_places, overpass_places)
        assert len(result) == 1
        assert "Palace Cinema" in result[0]
        assert "Happy Money" in result[0]

    def test_no_former(self) -> None:
        wikidata_places = normalize(wikidata_items=[_wikidata_item("Big Church", "church")])
        result = _build_ghost_layer(wikidata_places, [])
        assert result == []

    def test_caps_at_max(self) -> None:
        wikidata_places = normalize(
            wikidata_items=[
                _wikidata_item(f"Former Place {i}", "former building", distance=float(i * 10)) for i in range(10)
            ]
        )
        result = _build_ghost_layer(wikidata_places, [])
        assert len(result) <= AnalysisCapsConfig.max_ghosts

    def test_empty_list(self) -> None:
        assert _build_ghost_layer([], []) == []


# ---------------------------------------------------------------------------
# _find_cross_references
# ---------------------------------------------------------------------------


class TestFindCrossReferences:
    def test_heritage_count(self) -> None:
        places = normalize(
            wikidata_items=[
                _wikidata_item("A", heritage="Grade II"),
                _wikidata_item("B", heritage="Grade I"),
                _wikidata_item("C", heritage="Grade II"),
            ]
        )
        result = _find_cross_references(places)
        assert any("3 heritage" in r for r in result)
        assert any("Grade I" in r for r in result)

    def test_same_architect(self) -> None:
        places = normalize(
            wikidata_items=[
                _wikidata_item("A", architect="Wren"),
                _wikidata_item("B", architect="Wren"),
            ]
        )
        result = _find_cross_references(places)
        assert any("Wren" in r and "2" in r for r in result)

    def test_type_cluster(self) -> None:
        places = normalize(
            wikidata_items=[
                _wikidata_item("A", item_type="church"),
                _wikidata_item("B", item_type="church"),
                _wikidata_item("C", item_type="church"),
            ]
        )
        result = _find_cross_references(places)
        assert any("3× church" in r for r in result)

    def test_empty(self) -> None:
        assert _find_cross_references([]) == []


# ---------------------------------------------------------------------------
# _generate_investigation_prompts
# ---------------------------------------------------------------------------


class TestGenerateInvestigation:
    def test_ghost_prompt(self) -> None:
        ghosts = ["Palace Cinema (50m) → now: Happy Money"]
        result = _generate_investigation_prompts([], [], ghosts, [])
        assert len(result) == 1
        assert "Palace Cinema" in result[0]
        assert "WHY" in result[0]

    def test_signal_prompt(self) -> None:
        signals = ["creative district (10): 6× Tattoo + 3× Gallery"]
        result = _generate_investigation_prompts([], signals, [], [])
        assert any("creative district" in p for p in result)

    def test_notable_prompt(self) -> None:
        notable = ["6× Tattoo"]
        result = _generate_investigation_prompts(notable, [], [], [])
        assert any("Tattoo" in p for p in result)


# ---------------------------------------------------------------------------
# _score_highlights
# ---------------------------------------------------------------------------


class TestScoreHighlights:
    def test_wikipedia_beats_bare_overpass(self) -> None:
        """Wikipedia item should score higher than bare Overpass POI."""
        data = _display_data(
            overpass_pois=[_poi("Generic Cafe", "Cafe")],
            wikipedia_articles=[_wiki_article("Famous Place", distance=100.0)],
        )
        result = _score_highlights(data, set(), set())
        # Wikipedia item should be first (higher score)
        assert result[0].source == "wikipedia"

    def test_ghost_bonus(self) -> None:
        """Wikidata 'former' item gets ghost bonus."""
        data = _display_data(
            wikidata_items=[
                _wikidata_item("Palace Cinema", "former cinema", distance=50.0),
                _wikidata_item("Some Building", "office building", distance=50.0),
            ],
        )
        ghost_names = {"palace cinema"}
        result = _score_highlights(data, set(), ghost_names)
        palace = next(h for h in result if h.name == "Palace Cinema")
        building = next(h for h in result if h.name == "Some Building")
        assert palace.score > building.score

    def test_max_per_type_diversity(self) -> None:
        """Max 3 of same type in top-15."""
        data = _display_data(
            overpass_pois=[_poi(f"Restaurant {i}", "Restaurant") for i in range(1, 20)],
        )
        result = _score_highlights(data, {"Restaurant"}, set())
        restaurant_count = sum(1 for h in result if h.type == "Restaurant")
        assert restaurant_count <= AnalysisCapsConfig.highlight_max_per_type

    def test_top_n_limit(self) -> None:
        """Result capped at AnalysisCapsConfig.highlight_top_n."""
        data = _display_data(
            overpass_pois=[_poi(f"Place {i}", f"Type{i % 10}") for i in range(50)],
            wikipedia_articles=[_wiki_article(f"Article {i}", distance=float(i * 10)) for i in range(10)],
        )
        result = _score_highlights(data, set(), set())
        assert len(result) <= AnalysisCapsConfig.highlight_top_n

    def test_deduplication(self) -> None:
        """Same name from different sources — keep highest score."""
        data = _display_data(
            overpass_pois=[_poi("The Pub", "Pub")],
            wikipedia_articles=[_wiki_article("The Pub")],
        )
        result = _score_highlights(data, set(), set())
        pub_count = sum(1 for h in result if h.name.lower() == "the pub")
        assert pub_count == 1

    def test_highlights_carry_urls(self) -> None:
        """Highlights should carry maps_url and wiki_url from Place."""
        data = _display_data(
            wikipedia_articles=[_wiki_article("Big Ben", distance=100.0)],
        )
        result = _score_highlights(data, set(), set())
        assert len(result) == 1
        assert result[0].maps_url != ""
        assert result[0].wiki_url != ""
        assert "Big_Ben" in result[0].wiki_url


# ---------------------------------------------------------------------------
# analyze() — integration
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_sparse_returns_none(self) -> None:
        """Less than 3 total POIs — None."""
        data = _display_data(overpass_pois=[_poi("A"), _poi("B")])
        assert analyze(data) is None

    def test_deptford_like(self) -> None:
        """Deptford-like data: cinema ghost layer, movie theater cluster."""
        pois = [
            _poi("Happy Money", "Bureau De Change"),
            *[_poi(f"Restaurant {i}", "Restaurant") for i in range(10)],
            *[_poi(f"Fast Food {i}", "Fast Food") for i in range(5)],
            *[_poi(f"Cafe {i}", "Cafe") for i in range(5)],
        ]
        wikidata = [
            _wikidata_item("Palace Cinema", "former cinema", distance=50.0),
            _wikidata_item("Old Town Hall", "town hall", distance=100.0, heritage="Grade II", architect="John Smith"),
        ]
        data = _display_data(
            overpass_pois=pois,
            wikipedia_articles=[_wiki_article("Deptford")],
            wikidata_items=wikidata,
        )
        result = analyze(data)
        assert result is not None
        assert "Restaurant" in result.fingerprint
        assert len(result.ghost_layer) >= 1
        assert "Palace Cinema" in result.ghost_layer[0]
        assert len(result.highlights) > 0

    def test_camden_like(self) -> None:
        """Camden-like: Tattoo notable (6 >= 2), creative_district signal with breakdown."""
        pois = [
            *[_poi(f"Tattoo {i}", "Tattoo") for i in range(1, 7)],
            *[_poi(f"Gallery {i}", "Gallery") for i in range(1, 4)],
            _poi("Art Studio", "Art"),
            *[_poi(f"Pub {i}", "Pub") for i in range(1, 5)],
        ]
        data = _display_data(
            overpass_pois=pois,
            wikipedia_articles=[_wiki_article("Camden Town")],
        )
        result = analyze(data)
        assert result is not None
        assert any("Tattoo" in n for n in result.notable_types)
        assert any("creative district" in s for s in result.signals)
        # Breakdown should include component counts
        creative_sig = next(s for s in result.signals if "creative" in s)
        assert "6× Tattoo" in creative_sig

    def test_returns_analysis_result_type(self) -> None:
        data = _display_data(overpass_pois=[_poi(f"P{i}", f"Type{i}") for i in range(5)])
        result = analyze(data)
        assert result is not None
        assert isinstance(result, AnalysisResult)


# ---------------------------------------------------------------------------
# format_for_prompt
# ---------------------------------------------------------------------------


class TestFormatForPrompt:
    def test_basic_format(self) -> None:
        result = AnalysisResult(
            fingerprint="10× Restaurant + 5× Cafe",
            notable_types=["6× Tattoo"],
            signals=["creative district (10): 6× Tattoo + 3× Gallery"],
            absences=["Pub"],
            ghost_layer=["Palace Cinema (50m) → now: Happy Money"],
            cross_refs=["3 heritage-listed items"],
            investigation=["WHY did Palace Cinema close?"],
            highlights=[
                Highlight(
                    name="Palace Cinema",
                    type="cinema",
                    distance_m=50,
                    score=10.0,
                    source=Source.WIKIDATA,
                    maps_url="https://maps.example.com/palace",
                    extras={"ghost": True},
                ),
                Highlight(
                    name="Deptford",
                    type="Wikipedia article",
                    distance_m=100,
                    score=7.0,
                    source=Source.WIKIPEDIA,
                    maps_url="https://maps.example.com/deptford",
                    wiki_url="https://en.wikipedia.org/wiki/Deptford",
                ),
            ],
        )
        text = result.format_for_prompt()
        assert "## Analysis" in text
        assert "Fingerprint:" in text
        assert "Notable:" in text
        assert "Signals:" in text
        assert "Ghosts:" in text
        assert "Investigation leads:" in text
        assert "## Top Highlights" in text
        assert "1. Palace Cinema" in text
        assert "2. Deptford" in text
        assert "[📍map](https://maps.example.com/palace)" in text
        assert "[📖wiki](https://en.wikipedia.org/wiki/Deptford)" in text

    def test_empty_sections_omitted(self) -> None:
        result = AnalysisResult(
            fingerprint="5× Cafe",
            notable_types=[],
            signals=[],
            absences=[],
            ghost_layer=[],
            cross_refs=[],
            investigation=[],
            highlights=[],
        )
        text = result.format_for_prompt()
        assert "Notable:" not in text
        assert "Signals:" not in text
        assert "Ghosts:" not in text
        assert "Top Highlights" not in text

    def test_token_estimate(self) -> None:
        """Typical analysis should be ~500-700 tokens (~400-600 words) with URLs."""
        result = AnalysisResult(
            fingerprint="32× Restaurant + 24× Fast Food + 15× Cafe + 8× Bar + 5× Pub",
            notable_types=["6× Tattoo", "4× Nightclub", "3× Cinema"],
            signals=[
                "creative district (10): 6× Tattoo + 3× Gallery + 1× Art",
                "nightlife district (12): 4× Nightclub + 5× Bar + 3× Pub",
            ],
            absences=["Convenience"],
            ghost_layer=[
                "Palace Cinema (50m) → now: Happy Money (Bureau De Change)",
                "Old Theatre (120m) → now: Tesco Express",
            ],
            cross_refs=[
                "5 heritage-listed items (Grade I: St Paul's Church)",
                "John Smith designed 3 nearby buildings",
            ],
            investigation=[
                "WHY did Palace Cinema close? What replaced it and why?",
                "WHY is there a creative district here? Historical or economic reasons?",
            ],
            highlights=[
                Highlight(
                    name=f"Place {i}",
                    type=f"type{i % 5}",
                    distance_m=i * 20,
                    score=15.0 - i,
                    source=Source.WIKIDATA,
                    maps_url=f"https://maps.example.com/place{i}",
                    extras={"heritage": "Grade II"},
                )
                for i in range(15)
            ],
        )
        text = result.format_for_prompt()
        # Rough word count as proxy for tokens (1 token ~ 0.75 words)
        word_count = len(text.split())
        assert word_count < 800, f"Too many words: {word_count}"


# ---------------------------------------------------------------------------
# Config consistency guard
# ---------------------------------------------------------------------------


class TestMergedPlaceScoring:
    """Tests for _source_bonus with merged (multi-source) places."""

    def test_additive_overpass_wikipedia_signal(self) -> None:
        """Merged overpass+wikipedia place with a signal type gets both bonuses."""
        place = Place(
            name="Nando's",
            lat=51.57,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS, Source.WIKIPEDIA}),
            maps_url="https://example.com",
            type="Restaurant",
        )
        bonus, _is_ghost = _source_bonus(place, {"Restaurant"}, set())
        # Should get signal bonus (OVERPASS) + wikipedia bonus
        from city_guide.config import AnalysisScoringConfig

        assert bonus == AnalysisScoringConfig.signal + AnalysisScoringConfig.wikipedia

    def test_additive_overpass_wikipedia(self) -> None:
        """Merged overpass+wikipedia place gets both bonuses."""
        place = Place(
            name="New Beacon Books",
            lat=51.57,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS, Source.WIKIPEDIA}),
            maps_url="https://example.com",
            type="Books",
        )
        bonus, _is_ghost = _source_bonus(place, set(), set())
        from city_guide.config import AnalysisScoringConfig

        assert bonus == AnalysisScoringConfig.wikipedia

    def test_wikidata_bonus_only_counts_wikidata_extras(self) -> None:
        """Wikidata bonus counts only WIKIDATA_EXTRAS keys, not overpass extras like phone."""
        place = Place(
            name="Old Church",
            lat=51.57,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS, Source.WIKIDATA}),
            maps_url="https://example.com",
            type="Place Of Worship",
            extras={"phone": "+44123", "heritage": "Grade II", "founded": "1820"},
        )
        bonus, _is_ghost = _source_bonus(place, set(), set())
        from city_guide.config import AnalysisScoringConfig

        # Only heritage + founded count (2 wikidata extras), NOT phone
        assert bonus == 2 * AnalysisScoringConfig.wikidata_extra

    def test_ghost_layer_skips_merged_overpass_wikidata(self) -> None:
        """Ghost layer skips wikidata places that also have OVERPASS source."""
        merged_place = Place(
            name="Some Place",
            lat=51.57,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS, Source.WIKIDATA}),
            maps_url="https://example.com",
            description="former theatre",
        )
        pure_wikidata = Place(
            name="Old Cinema",
            lat=51.571,
            lon=-0.109,
            distance_m=60,
            bearing=180,
            source=Source.WIKIDATA,
            sources=frozenset({Source.WIKIDATA}),
            maps_url="https://example.com",
            description="former cinema",
        )
        ghosts = _build_ghost_layer([merged_place, pure_wikidata], [])
        # Only the pure wikidata place should appear as ghost
        assert len(ghosts) == 1
        assert "Old Cinema" in ghosts[0]


class TestHighlightSources:
    def test_highlight_carries_sources(self) -> None:
        """Highlight.sources propagated from Place.sources."""
        data = _display_data(
            overpass_pois=[_poi("Some Cafe", "Cafe")],
        )
        result = _score_highlights(data, set(), set())
        assert len(result) >= 1
        assert Source.OVERPASS in result[0].sources

    def test_highlight_format_multi_source(self) -> None:
        """Multi-source highlight shows combined source label."""
        from city_guide.analyze import _format_highlight

        h = Highlight(
            name="Place",
            type="Cafe",
            distance_m=50,
            score=5.0,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS, Source.WIKIPEDIA}),
        )
        text = _format_highlight(1, h)
        assert "overpass+wikipedia" in text


class TestConfigConsistency:
    def test_signal_groups_notable_consistency(self) -> None:
        """Importing config doesn't crash — consistency assertion passes."""
        from city_guide.config import _SIGNAL_ONLY_TYPES, NOTABLE_WHEN_CLUSTERED, SIGNAL_GROUPS

        all_signal_types = frozenset(t for types, _ in SIGNAL_GROUPS.values() for t in types)
        uncovered = (all_signal_types - frozenset(NOTABLE_WHEN_CLUSTERED)) - _SIGNAL_ONLY_TYPES
        assert not uncovered, f"Uncovered types: {uncovered}"
