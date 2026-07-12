"""Tests for city_guide.place — Place dataclass, normalize(), and deduplication."""

from __future__ import annotations

from city_guide.maps_url import build_maps_url, build_wiki_url
from city_guide.place import (
    Place,
    _merge_places,
    _names_match,
    deduplicate_places,
    normalize,
)
from city_guide.sources.overpass import OverpassPOI
from city_guide.sources.wikidata import WikidataItem
from city_guide.sources.wikipedia import WikiArticle
from city_guide.types import Source


def test_normalize_overpass() -> None:
    pois = [
        OverpassPOI(name="Test Cafe", type="Cafe", lat=51.5, lon=-0.1),
    ]
    places = normalize(overpass_pois=pois)
    assert len(places) == 1
    p = places[0]
    assert p.name == "Test Cafe"
    assert p.source == Source.OVERPASS
    assert p.sources == frozenset({Source.OVERPASS})
    assert p.type == "Cafe"
    assert p.distance_m == 0  # placeholder — computed by filter_by_radius
    assert p.bearing is None
    assert p.maps_url == build_maps_url("Test Cafe", 51.5, -0.1)
    assert p.wiki_url == ""


def test_normalize_wikipedia() -> None:
    articles = [
        WikiArticle(
            title="Big Ben",
            extract="A clock.",
            distance=200.0,
            lat=51.5007,
            lon=-0.1246,
            pageid=1,
            thumbnail_url="https://example.com/bb.jpg",
        ),
    ]
    places = normalize(wikipedia_articles=articles)
    assert len(places) == 1
    p = places[0]
    assert p.name == "Big Ben"
    assert p.source == Source.WIKIPEDIA
    assert p.sources == frozenset({Source.WIKIPEDIA})
    assert p.maps_url == build_maps_url("Big Ben", 51.5007, -0.1246)
    assert p.wiki_url == build_wiki_url("Big Ben")
    assert "en.wikipedia.org" in p.wiki_url
    assert "Big_Ben" in p.wiki_url
    assert p.description == "A clock."
    assert p.photo_url == "https://example.com/bb.jpg"


def test_normalize_wikipedia_no_thumbnail() -> None:
    articles = [
        WikiArticle(title="No Photo", extract="x", distance=100.0, lat=51.5, lon=-0.1, pageid=2),
    ]
    places = normalize(wikipedia_articles=articles)
    assert places[0].photo_url == ""
    assert places[0].description == "x"


def test_normalize_wikidata() -> None:
    items = [
        WikidataItem(
            name="Tower",
            description="historic tower",
            distance=150.0,
            lat=51.501,
            lon=-0.1,
            item_type="tower",
            founded="1066-01-01",
            architect="William",
        ),
    ]
    places = normalize(wikidata_items=items)
    assert len(places) == 1
    p = places[0]
    assert p.name == "Tower"
    assert p.source == Source.WIKIDATA
    assert p.sources == frozenset({Source.WIKIDATA})
    assert p.type == "tower"
    assert p.maps_url == build_maps_url("Tower", 51.501, -0.1)
    assert p.wiki_url == ""
    assert p.description == "historic tower"
    assert p.extras["founded"] == "1066-01-01"
    assert p.extras["architect"] == "William"


def test_normalize_all_sources() -> None:
    pois = [OverpassPOI(name="Cafe", type="Cafe", lat=51.5, lon=-0.1)]
    articles = [WikiArticle(title="Art", extract="x", distance=100.0, lat=51.501, lon=-0.1, pageid=1)]
    wikidata = [WikidataItem(name="Tower", description="t", distance=150.0, lat=51.502, lon=-0.1, item_type="tower")]

    places = normalize(
        overpass_pois=pois,
        wikipedia_articles=articles,
        wikidata_items=wikidata,
    )
    assert len(places) == 3
    sources = {p.source for p in places}
    assert sources == {Source.OVERPASS, Source.WIKIPEDIA, Source.WIKIDATA}


def test_normalize_empty() -> None:
    places = normalize()
    assert places == []


def test_normalize_wiki_url_spaces_encoded() -> None:
    articles = [
        WikiArticle(title="Tower of London", extract="x", distance=100.0, lat=51.5, lon=-0.1, pageid=1),
    ]
    places = normalize(wikipedia_articles=articles)
    assert "Tower_of_London" in places[0].wiki_url


def test_place_dataclass_defaults() -> None:
    p = Place(
        name="Test",
        lat=51.5,
        lon=-0.1,
        distance_m=100,
        bearing=None,
        source=Source.OVERPASS,
        maps_url="https://example.com",
    )
    assert p.wiki_url == ""
    assert p.type == ""
    assert p.description == ""
    assert p.photo_url == ""
    assert p.extras == {}


def test_place_to_display_dict_basic() -> None:
    p = Place(
        name="Big Ben",
        lat=51.5007,
        lon=-0.1246,
        distance_m=200,
        bearing=180,
        source=Source.WIKIPEDIA,
        maps_url="https://maps.example.com/bigben",
        wiki_url="https://en.wikipedia.org/wiki/Big_Ben",
        type="Wikipedia article",
        description="A clock tower.",
        photo_url="https://example.com/bb.jpg",
    )
    d = p.to_display_dict()
    assert d["name"] == "Big Ben"
    assert d["distance_m"] == 200
    assert d["bearing_deg"] == 180
    assert d["wiki_url"] == "https://en.wikipedia.org/wiki/Big_Ben"
    assert d["description"] == "A clock tower."
    assert d["photo_url"] == "https://example.com/bb.jpg"


def test_place_to_display_dict_inlines_extras() -> None:
    p = Place(
        name="Bar",
        lat=51.5,
        lon=-0.1,
        distance_m=50,
        bearing=None,
        source=Source.OVERPASS,
        maps_url="https://maps.example.com/bar",
        extras={"cuisine": "italian", "phone": "+44123"},
    )
    d = p.to_display_dict()
    assert d["cuisine"] == "italian"
    assert d["phone"] == "+44123"
    assert "bearing_deg" not in d
    assert "wiki_url" not in d


def test_place_to_display_dict_omits_empty_fields() -> None:
    p = Place(
        name="Cafe",
        lat=51.5,
        lon=-0.1,
        distance_m=30,
        bearing=None,
        source=Source.OVERPASS,
        maps_url="https://maps.example.com/cafe",
    )
    d = p.to_display_dict()
    assert "wiki_url" not in d
    assert "description" not in d
    assert "photo_url" not in d
    assert "bearing_deg" not in d


def test_normalize_overpass_extras() -> None:
    """Overpass POIs with extra fields get them in extras."""
    pois = [
        OverpassPOI(
            name="Pizza Place",
            type="Restaurant",
            lat=51.5,
            lon=-0.1,
            cuisine="italian",
            phone="+44123",
            website="https://pizza.com",
        ),
    ]
    places = normalize(overpass_pois=pois)
    p = places[0]
    assert p.extras["cuisine"] == "italian"
    assert p.extras["phone"] == "+44123"
    assert p.extras["website"] == "https://pizza.com"


def test_place_to_display_dict_multi_source() -> None:
    """Multi-source places include sources list in display dict."""
    p = Place(
        name="Test",
        lat=51.5,
        lon=-0.1,
        distance_m=100,
        bearing=None,
        source=Source.OVERPASS,
        sources=frozenset({Source.OVERPASS, Source.WIKIPEDIA}),
        maps_url="https://example.com",
    )
    d = p.to_display_dict()
    assert "sources" in d
    assert sorted(d["sources"]) == ["overpass", "wikipedia"]


def test_place_to_display_dict_single_source_no_sources_key() -> None:
    """Single-source places omit sources list from display dict."""
    p = Place(
        name="Test",
        lat=51.5,
        lon=-0.1,
        distance_m=100,
        bearing=None,
        source=Source.OVERPASS,
        sources=frozenset({Source.OVERPASS}),
        maps_url="https://example.com",
    )
    d = p.to_display_dict()
    assert "sources" not in d


# ---------------------------------------------------------------------------
# _names_match
# ---------------------------------------------------------------------------


class TestNamesMatch:
    def test_exact_case_insensitive(self) -> None:
        assert _names_match("Nando's", "nando's")

    def test_substring_match(self) -> None:
        assert _names_match("Nando's", "Nando's Finsbury Park")

    def test_substring_reversed(self) -> None:
        assert _names_match("Tollingtons Fish Bar", "Tollingtons")

    def test_too_short_substring(self) -> None:
        """Substrings shorter than dedup_min_name_length are rejected."""
        assert not _names_match("The", "The Big Pub")

    def test_no_match(self) -> None:
        """Neither name is a substring of the other."""
        assert not _names_match("Brothers Supermarket", "Elkins Brothers")

    def test_exact_empty_rejected(self) -> None:
        """Empty strings match each other but are too short for substring."""
        assert _names_match("", "")

    def test_whitespace_handling(self) -> None:
        assert _names_match("  Nando's  ", "Nando's")


# ---------------------------------------------------------------------------
# _merge_places
# ---------------------------------------------------------------------------


class TestMergePlaces:
    def test_two_sources_overpass_wikidata(self) -> None:
        """Overpass + Wikidata merge: type from Overpass, extras merged."""
        overpass = Place(
            name="Nando's",
            lat=51.57,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://maps.example.com/overpass",
            type="Restaurant",
            extras={"phone": "+44123", "cuisine": "chicken"},
        )
        wikidata = Place(
            name="Nando's Finsbury Park",
            lat=51.5701,
            lon=-0.1081,
            distance_m=55,
            bearing=91,
            source=Source.WIKIDATA,
            sources=frozenset({Source.WIKIDATA}),
            maps_url="https://maps.example.com/wikidata",
            type="restaurant",
            extras={"founded": "1992"},
        )
        merged = _merge_places([overpass, wikidata])
        # Primary is Overpass (highest priority)
        assert merged.source == Source.OVERPASS
        assert merged.sources == frozenset({Source.OVERPASS, Source.WIKIDATA})
        assert merged.name == "Nando's"
        assert merged.lat == 51.57
        # Type from Overpass
        assert merged.type == "Restaurant"
        # maps_url from primary
        assert merged.maps_url == "https://maps.example.com/overpass"
        # Extras merged
        assert merged.extras["phone"] == "+44123"
        assert merged.extras["founded"] == "1992"

    def test_three_sources(self) -> None:
        """Overpass + Wikipedia + Wikidata merge."""
        overpass = Place(
            name="New Beacon Books",
            lat=51.57,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://maps.example.com/overpass",
            type="Books",
        )
        wiki = Place(
            name="New Beacon Books",
            lat=51.5701,
            lon=-0.1081,
            distance_m=52,
            bearing=91,
            source=Source.WIKIPEDIA,
            sources=frozenset({Source.WIKIPEDIA}),
            maps_url="https://maps.example.com/wiki",
            wiki_url="https://en.wikipedia.org/wiki/New_Beacon_Books",
            description="A Black British bookshop founded in 1966.",
            photo_url="https://example.com/nbb.jpg",
        )
        wikidata = Place(
            name="New Beacon Books",
            lat=51.5702,
            lon=-0.1082,
            distance_m=53,
            bearing=92,
            source=Source.WIKIDATA,
            sources=frozenset({Source.WIKIDATA}),
            maps_url="https://maps.example.com/wikidata",
            type="bookshop",
            description="bookshop",
            extras={"founded": "1966", "heritage": "Grade II"},
        )
        merged = _merge_places([overpass, wiki, wikidata])
        assert merged.sources == frozenset({Source.OVERPASS, Source.WIKIPEDIA, Source.WIKIDATA})
        assert merged.source == Source.OVERPASS
        assert merged.type == "Books"
        assert merged.wiki_url == "https://en.wikipedia.org/wiki/New_Beacon_Books"
        assert merged.description == "A Black British bookshop founded in 1966."
        assert merged.photo_url == "https://example.com/nbb.jpg"
        assert merged.extras["founded"] == "1966"
        assert merged.extras["heritage"] == "Grade II"

    def test_extras_primary_precedence(self) -> None:
        """Primary source extras take precedence on key collision."""
        overpass = Place(
            name="Place",
            lat=51.5,
            lon=-0.1,
            distance_m=50,
            bearing=0,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com",
            extras={"website": "https://overpass.example.com"},
        )
        wikidata = Place(
            name="Place",
            lat=51.5,
            lon=-0.1,
            distance_m=50,
            bearing=0,
            source=Source.WIKIDATA,
            sources=frozenset({Source.WIKIDATA}),
            maps_url="https://example.com",
            extras={"website": "https://wikidata.example.com", "founded": "1900"},
        )
        merged = _merge_places([overpass, wikidata])
        assert merged.extras["website"] == "https://overpass.example.com"
        assert merged.extras["founded"] == "1900"

    def test_single_place_passthrough(self) -> None:
        """Single-item group returns the same place unchanged."""
        place = Place(
            name="Solo",
            lat=51.5,
            lon=-0.1,
            distance_m=50,
            bearing=0,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com",
        )
        result = _merge_places([place])
        assert result.name == "Solo"
        assert result.sources == frozenset({Source.OVERPASS})


# ---------------------------------------------------------------------------
# deduplicate_places
# ---------------------------------------------------------------------------


class TestDeduplicatePlaces:
    def test_no_duplicates(self) -> None:
        """Distinct places remain separate."""
        places = [
            Place(
                name="Place A",
                lat=51.5,
                lon=-0.1,
                distance_m=50,
                bearing=0,
                source=Source.OVERPASS,
                sources=frozenset({Source.OVERPASS}),
                maps_url="https://example.com/a",
            ),
            Place(
                name="Place B",
                lat=51.6,
                lon=-0.2,
                distance_m=100,
                bearing=180,
                source=Source.WIKIPEDIA,
                sources=frozenset({Source.WIKIPEDIA}),
                maps_url="https://example.com/b",
            ),
        ]
        result = deduplicate_places(places)
        assert len(result) == 2

    def test_overpass_wikipedia_merge(self) -> None:
        """Same-name places from different sources within proximity are merged."""
        overpass = Place(
            name="Nando's",
            lat=51.5695,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com/overpass",
            type="Restaurant",
        )
        wiki = Place(
            name="Nando's",
            lat=51.5696,
            lon=-0.1081,
            distance_m=52,
            bearing=91,
            source=Source.WIKIPEDIA,
            sources=frozenset({Source.WIKIPEDIA}),
            maps_url="https://example.com/wiki",
            type="restaurant",
        )
        result = deduplicate_places([overpass, wiki])
        assert len(result) == 1
        assert result[0].sources == frozenset({Source.OVERPASS, Source.WIKIPEDIA})

    def test_same_source_not_merged(self) -> None:
        """Two places from the same source at same location are NOT merged."""
        place_a = Place(
            name="Nando's",
            lat=51.5695,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com/a",
        )
        place_b = Place(
            name="Nando's",
            lat=51.5695,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com/b",
        )
        result = deduplicate_places([place_a, place_b])
        assert len(result) == 2

    def test_beyond_threshold_not_merged(self) -> None:
        """Places beyond proximity threshold are not merged despite same name."""
        overpass = Place(
            name="Nando's",
            lat=51.5695,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com/overpass",
        )
        wiki = Place(
            name="Nando's",
            lat=51.5705,  # ~110m away
            lon=-0.108,
            distance_m=80,
            bearing=0,
            source=Source.WIKIPEDIA,
            sources=frozenset({Source.WIKIPEDIA}),
            maps_url="https://example.com/wiki",
        )
        result = deduplicate_places([overpass, wiki])
        assert len(result) == 2

    def test_transitive_merge(self) -> None:
        """A↔B and B↔C leads to three-way merge."""
        overpass = Place(
            name="New Beacon Books",
            lat=51.5695,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com/overpass",
            type="Books",
        )
        wiki = Place(
            name="New Beacon Books",
            lat=51.5696,
            lon=-0.1081,
            distance_m=52,
            bearing=91,
            source=Source.WIKIPEDIA,
            sources=frozenset({Source.WIKIPEDIA}),
            maps_url="https://example.com/wiki",
            wiki_url="https://en.wikipedia.org/wiki/New_Beacon_Books",
            description="A bookshop.",
        )
        wikidata = Place(
            name="New Beacon Books",
            lat=51.5697,
            lon=-0.1082,
            distance_m=53,
            bearing=92,
            source=Source.WIKIDATA,
            sources=frozenset({Source.WIKIDATA}),
            maps_url="https://example.com/wikidata",
            type="bookshop",
            extras={"founded": "1966"},
        )
        result = deduplicate_places([overpass, wiki, wikidata])
        assert len(result) == 1
        merged = result[0]
        assert merged.sources == frozenset({Source.OVERPASS, Source.WIKIPEDIA, Source.WIKIDATA})
        assert merged.extras["founded"] == "1966"
        assert merged.wiki_url != ""

    def test_false_positive_avoidance(self) -> None:
        """Different names nearby are not merged."""
        overpass = Place(
            name="The Pub",
            lat=51.5695,
            lon=-0.108,
            distance_m=50,
            bearing=90,
            source=Source.OVERPASS,
            sources=frozenset({Source.OVERPASS}),
            maps_url="https://example.com/pub",
        )
        wiki = Place(
            name="Pizza Express",
            lat=51.5696,
            lon=-0.1081,
            distance_m=52,
            bearing=91,
            source=Source.WIKIPEDIA,
            sources=frozenset({Source.WIKIPEDIA}),
            maps_url="https://example.com/pizza",
        )
        result = deduplicate_places([overpass, wiki])
        assert len(result) == 2

    def test_empty_list(self) -> None:
        assert deduplicate_places([]) == []
