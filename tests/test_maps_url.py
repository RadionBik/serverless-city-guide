"""Tests for maps_url module — Google Maps and Wikipedia URL builders."""

from city_guide.maps_url import MAPS_BASE_URL, MAPS_SEARCH_URL, MAPS_ZOOM, build_maps_url, build_wiki_url


def test_build_maps_url_with_name_and_coords() -> None:
    url = build_maps_url("Test Place", lat=51.5, lon=-0.1)
    assert url == f"{MAPS_BASE_URL}/Test+Place/@51.5,-0.1,{MAPS_ZOOM}z/"


def test_build_maps_url_with_coords_no_name() -> None:
    url = build_maps_url("", lat=51.5, lon=-0.1)
    assert url == f"{MAPS_BASE_URL}/@51.5,-0.1,{MAPS_ZOOM}z/"


def test_build_maps_url_without_coords() -> None:
    url = build_maps_url("Big Ben London")
    assert url == f"{MAPS_SEARCH_URL}&query=Big+Ben+London"


def test_build_maps_url_name_with_special_chars() -> None:
    url = build_maps_url("Café & Bar", lat=51.5, lon=-0.1)
    assert "Caf%C3%A9+%26+Bar" in url


def test_build_maps_url_lat_none_lon_none() -> None:
    url = build_maps_url("Test", lat=None, lon=None)
    assert "&query=Test" in url


def test_build_maps_url_partial_coords_falls_back_to_name() -> None:
    url = build_maps_url("Test", lat=51.5, lon=None)
    assert "&query=Test" in url


# ---------------------------------------------------------------------------
# build_wiki_url
# ---------------------------------------------------------------------------


def test_build_wiki_url_basic() -> None:
    url = build_wiki_url("Big Ben")
    assert url == "https://en.wikipedia.org/wiki/Big_Ben"


def test_build_wiki_url_with_language() -> None:
    url = build_wiki_url("Big Ben", language="ru")
    assert url == "https://ru.wikipedia.org/wiki/Big_Ben"


def test_build_wiki_url_spaces_to_underscores() -> None:
    url = build_wiki_url("Tower of London")
    assert "Tower_of_London" in url


def test_build_wiki_url_special_chars() -> None:
    url = build_wiki_url("Café")
    assert "Caf%C3%A9" in url


def test_build_wiki_url_default_language() -> None:
    url = build_wiki_url("Test")
    assert "en.wikipedia.org" in url
