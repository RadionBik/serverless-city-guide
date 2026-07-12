"""Tests for overpass module — query building and response parsing."""

from typing import Any

from city_guide.sources.overpass import (
    OverpassPOI,
    build_query,
    classify,
    filter_pois,
    is_poi_noise,
    parse_raw_elements,
)


def test_build_query_contains_radius() -> None:
    query = build_query(51.5, -0.1, 200)
    assert "200" in query
    assert "51.5" in query
    assert "-0.1" in query


def test_build_query_has_all_categories() -> None:
    query = build_query(51.5, -0.1, 100)
    assert '"amenity"' in query
    assert '"shop"' in query
    assert '"tourism"' in query
    assert '"leisure"' in query
    assert '"historic"' in query


def test_build_query_with_tag_filter() -> None:
    query = build_query(51.5, -0.1, 300, tags=["amenity", "shop"])
    assert '"amenity"' in query
    assert '"shop"' in query
    assert '"tourism"' not in query
    assert '"leisure"' not in query
    assert '"historic"' not in query


def test_build_query_with_single_tag() -> None:
    query = build_query(51.5, -0.1, 500, tags=["historic"])
    assert '"historic"' in query
    assert '"amenity"' not in query


def test_build_query_format() -> None:
    query = build_query(51.5, -0.1, 100)
    assert query.startswith("[out:json]")
    assert query.endswith("out center tags;")


def test_classify_restaurant() -> None:
    assert classify({"amenity": "restaurant"}) == "Restaurant"


def test_classify_fast_food() -> None:
    assert classify({"amenity": "fast_food"}) == "Fast Food"


def test_classify_no_match() -> None:
    assert classify({"random": "tag"}) == "Place"


# -- Noise filter tests --


def test_noise_parking() -> None:
    assert is_poi_noise({"amenity": "parking"}) is True


def test_noise_atm() -> None:
    assert is_poi_noise({"amenity": "atm"}) is True


def test_noise_vending_machine() -> None:
    assert is_poi_noise({"amenity": "vending_machine"}) is True


def test_noise_information() -> None:
    assert is_poi_noise({"tourism": "information"}) is True


def test_noise_pitch() -> None:
    assert is_poi_noise({"leisure": "pitch"}) is True


def test_noise_hairdresser() -> None:
    assert is_poi_noise({"shop": "hairdresser"}) is True


def test_noise_pharmacy() -> None:
    assert is_poi_noise({"amenity": "pharmacy"}) is True


def test_not_noise_hotel() -> None:
    assert is_poi_noise({"tourism": "hotel"}) is False


def test_not_noise_cafe() -> None:
    assert is_poi_noise({"amenity": "cafe"}) is False


def test_overpass_poi_model_roundtrip() -> None:
    poi = OverpassPOI(name="Cafe", type="Cafe", lat=51.5, lon=-0.1, cuisine="italian")
    d = poi.model_dump()
    restored = OverpassPOI.model_validate(d)
    assert restored.name == "Cafe"
    assert restored.cuisine == "italian"
    assert restored.lat == 51.5


# -- parse_raw_elements tests --


def test_parse_raw_elements_keeps_unnamed() -> None:
    """parse_raw_elements does NOT filter unnamed — that's filter_pois' job."""
    elements: list[dict[str, Any]] = [
        {"type": "node", "id": 1, "lat": 51.5, "lon": -0.1, "tags": {"amenity": "bench"}},
        {"type": "node", "id": 2, "lat": 51.5, "lon": -0.1, "tags": {"name": "Cafe", "amenity": "cafe"}},
    ]
    results = parse_raw_elements(elements)
    assert len(results) == 2
    assert results[0].name == "?"
    assert results[1].name == "Cafe"


def test_parse_raw_elements_keeps_noise() -> None:
    """parse_raw_elements does NOT filter noise — that's filter_pois' job."""
    elements: list[dict[str, Any]] = [
        {"type": "node", "id": 1, "lat": 51.5, "lon": -0.1, "tags": {"name": "City Parking", "amenity": "parking"}},
    ]
    results = parse_raw_elements(elements)
    assert len(results) == 1
    assert results[0].name == "City Parking"


def test_parse_raw_elements_skips_no_coords() -> None:
    """Elements without lat/lon (and no center) are skipped."""
    elements: list[dict[str, Any]] = [
        {"type": "relation", "id": 1, "tags": {"name": "Ghost"}},
    ]
    results = parse_raw_elements(elements)
    assert len(results) == 0


def test_parse_raw_elements_way_uses_center() -> None:
    """Way elements get coords from center."""
    elements: list[dict[str, Any]] = [
        {"type": "way", "id": 1, "center": {"lat": 51.5, "lon": -0.1}, "tags": {"name": "Museum", "tourism": "museum"}},
    ]
    results = parse_raw_elements(elements)
    assert len(results) == 1
    assert results[0].lat == 51.5
    assert results[0].lon == -0.1


def test_parse_raw_elements_stores_tags() -> None:
    """The full tags dict is stored in the OverpassPOI."""
    elements: list[dict[str, Any]] = [
        {
            "type": "node",
            "id": 1,
            "lat": 51.5,
            "lon": -0.1,
            "tags": {"name": "Cafe", "amenity": "cafe", "cuisine": "italian"},
        },
    ]
    results = parse_raw_elements(elements)
    assert results[0].tags == {"name": "Cafe", "amenity": "cafe", "cuisine": "italian"}


def test_parse_raw_elements_tags_values_are_strings() -> None:
    """Non-string tag values are coerced to strings."""
    elements: list[dict[str, Any]] = [
        {"type": "node", "id": 1, "lat": 51.5, "lon": -0.1, "tags": {"name": "Place", "level": 3}},
    ]
    results = parse_raw_elements(elements)
    assert results[0].tags["level"] == "3"


# -- filter_pois tests --


def test_filter_pois_removes_unnamed() -> None:
    pois = [
        OverpassPOI(name="?", type="Place", lat=51.5, lon=-0.1),
        OverpassPOI(name="", type="Place", lat=51.5, lon=-0.1),
        OverpassPOI(name="Real Cafe", type="Cafe", lat=51.5, lon=-0.1),
    ]
    results = filter_pois(pois)
    assert len(results) == 1
    assert results[0].name == "Real Cafe"


def test_filter_pois_removes_noise() -> None:
    pois = [
        OverpassPOI(name="City Parking", type="Parking", lat=51.5, lon=-0.1, tags={"amenity": "parking"}),
        OverpassPOI(name="Nice Cafe", type="Cafe", lat=51.5, lon=-0.1, tags={"amenity": "cafe"}),
    ]
    results = filter_pois(pois)
    assert len(results) == 1
    assert results[0].name == "Nice Cafe"


def test_filter_pois_empty_tags_not_noise() -> None:
    """POI with empty tags dict is not considered noise."""
    pois = [OverpassPOI(name="Unknown Place", type="Place", lat=51.5, lon=-0.1, tags={})]
    results = filter_pois(pois)
    assert len(results) == 1
