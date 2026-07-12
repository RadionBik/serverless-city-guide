"""Tests for Wikidata SPARQL module — parsing, noise filtering, error handling."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from city_guide.sources.wikidata import WikidataItem, _is_allowed_type, _parse_bindings, _parse_coord, fetch_wikidata


def _make_binding(
    name: str = "Big Ben",
    description: str = "clock tower",
    coord: str = "Point(-0.1246 51.5007)",
    distance: str = "0.2",
    instance_of: str = "tower",
    founding_date: str | None = None,
    architect: str | None = None,
    notable_event: str | None = None,
    named_after: str | None = None,
    creator: str | None = None,
    arch_style: str | None = None,
    opening_date: str | None = None,
    heritage: str | None = None,
    native_label: str | None = None,
) -> dict[str, Any]:
    """Build a single SPARQL result binding row."""
    row: dict[str, Any] = {
        "itemLabel": {"value": name},
        "itemDescription": {"value": description},
        "coord": {"value": coord},
        "distance": {"value": distance},
        "instanceOfLabel": {"value": instance_of},
    }
    _optional = {
        "foundingDate": founding_date,
        "architectLabel": architect,
        "notableEventLabel": notable_event,
        "namedAfterLabel": named_after,
        "creatorLabel": creator,
        "archStyleLabel": arch_style,
        "openingDate": opening_date,
        "heritageLabel": heritage,
        "nativeLabel": native_label,
    }
    for key, val in _optional.items():
        if val is not None:
            row[key] = {"value": val}
    return row


def test_parse_coord() -> None:
    lat, lon = _parse_coord("Point(-0.1246 51.5007)")
    assert abs(lat - 51.5007) < 0.0001
    assert abs(lon - (-0.1246)) < 0.0001


def test_parse_bindings_basic() -> None:
    bindings = [_make_binding()]
    items = _parse_bindings(bindings)
    assert len(items) == 1
    assert items[0].name == "Big Ben"
    assert items[0].description == "clock tower"
    assert items[0].distance == 200.0  # 0.2 km * 1000
    assert abs(items[0].lat - 51.5007) < 0.001
    assert abs(items[0].lon - (-0.1246)) < 0.001


def test_parse_bindings_with_extras() -> None:
    bindings = [
        _make_binding(
            founding_date="1859-05-31T00:00:00Z",
            architect="Augustus Pugin",
            notable_event="Great Fire",
        )
    ]
    items = _parse_bindings(bindings)
    assert len(items) == 1
    assert items[0].founded == "1859-05-31"
    assert items[0].architect == "Augustus Pugin"
    assert items[0].notable_event == "Great Fire"


def test_parse_bindings_with_new_extras() -> None:
    bindings = [
        _make_binding(
            named_after="Benjamin Hall",
            arch_style="Gothic Revival",
            heritage="Grade I listed building",
            opening_date="1859-07-11T00:00:00Z",
            creator="Edmund Beckett Denison",
            native_label="Elizabeth Tower",
        )
    ]
    items = _parse_bindings(bindings)
    assert len(items) == 1
    assert items[0].named_after == "Benjamin Hall"
    assert items[0].arch_style == "Gothic Revival"
    assert items[0].heritage == "Grade I listed building"
    assert items[0].opening_date == "1859-07-11"
    assert items[0].creator == "Edmund Beckett Denison"
    assert items[0].native_label == "Elizabeth Tower"


def test_parse_bindings_filters_qcodes() -> None:
    bindings = [_make_binding(name="Q12345")]
    items = _parse_bindings(bindings)
    assert len(items) == 0


def test_parse_bindings_filters_empty_name() -> None:
    bindings = [_make_binding(name="")]
    items = _parse_bindings(bindings)
    assert len(items) == 0


def test_parse_bindings_whitelist_allows_known_types() -> None:
    bindings = [
        _make_binding(name="Cool Museum", instance_of="museum"),
        _make_binding(name="Nice Pub", instance_of="pub"),
        _make_binding(name="Old Castle", instance_of="castle"),
    ]
    items = _parse_bindings(bindings)
    assert len(items) == 3


def test_parse_bindings_whitelist_rejects_unknown_types() -> None:
    bindings = [
        _make_binding(name="Baker Street", instance_of="street"),
        _make_binding(name="Awards Ceremony", instance_of="group of awards"),
        _make_binding(name="Generic Corp", instance_of="organization"),
        _make_binding(name="Some Letter", instance_of="letter"),
        _make_binding(name="Cool Museum", instance_of="museum"),
    ]
    items = _parse_bindings(bindings)
    assert len(items) == 1
    assert items[0].name == "Cool Museum"


def test_parse_bindings_building_with_extras_kept() -> None:
    """Buildings with enrichment facts (founded/architect/event) should pass."""
    bindings = [
        _make_binding(name="Historic Hall", instance_of="building", founding_date="1850-01-01"),
        _make_binding(name="Famous Tower", instance_of="building", architect="Gaudi"),
    ]
    items = _parse_bindings(bindings)
    assert len(items) == 2


def test_parse_bindings_building_without_extras_filtered() -> None:
    """Generic buildings without enrichment facts should be filtered out."""
    bindings = [
        _make_binding(name="6 And 8 Greenland Road", instance_of="building"),
    ]
    items = _parse_bindings(bindings)
    assert len(items) == 0


def test_is_allowed_type() -> None:
    assert _is_allowed_type("museum", has_extras=False) is True
    assert _is_allowed_type("pub", has_extras=False) is True
    assert _is_allowed_type("building", has_extras=True) is True
    assert _is_allowed_type("building", has_extras=False) is False
    assert _is_allowed_type("street", has_extras=False) is False
    assert _is_allowed_type("group of awards", has_extras=True) is False


def test_parse_bindings_deduplicates_merges_facts() -> None:
    """Duplicate rows (from OPTIONAL joins) are merged, keeping extra facts."""
    bindings = [
        _make_binding(name="Tower", distance="0.1", founding_date="1066-01-01"),
        _make_binding(name="Tower", distance="0.1", architect="William the Conqueror"),
    ]
    items = _parse_bindings(bindings)
    assert len(items) == 1
    assert items[0].founded == "1066-01-01"
    assert items[0].architect == "William the Conqueror"


def test_cache_roundtrip() -> None:
    item = WikidataItem(
        name="Test",
        description="desc",
        distance=100.0,
        lat=51.5,
        lon=-0.1,
        item_type="building",
        founded="1900-01-01",
        architect="Someone",
        notable_event="Opening",
        named_after="A Person",
        arch_style="Baroque",
        heritage="UNESCO",
        opening_date="1901-06-15",
        creator="Builder",
        native_label="Тест",
    )
    d = item.model_dump()
    restored = WikidataItem.model_validate(d)
    assert restored.name == "Test"
    assert restored.founded == "1900-01-01"
    assert restored.architect == "Someone"
    assert restored.notable_event == "Opening"
    assert restored.named_after == "A Person"
    assert restored.arch_style == "Baroque"
    assert restored.heritage == "UNESCO"
    assert restored.opening_date == "1901-06-15"
    assert restored.creator == "Builder"
    assert restored.native_label == "Тест"


def test_cache_roundtrip_no_extras() -> None:
    item = WikidataItem(
        name="Simple",
        description="desc",
        distance=50.0,
        lat=51.5,
        lon=-0.1,
        item_type="building",
    )
    d = item.model_dump()
    restored = WikidataItem.model_validate(d)
    assert restored.founded is None
    assert restored.architect is None
    assert restored.named_after is None
    assert restored.arch_style is None


async def test_fetch_wikidata_success() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json.return_value = {"results": {"bindings": [_make_binding(founding_date="1859-05-31T00:00:00Z")]}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    async def _mock_get_client() -> AsyncMock:
        return mock_client

    with patch("city_guide.sources.wikidata.get_client", _mock_get_client):
        items = await fetch_wikidata(51.5, -0.1, 500)

    assert len(items) == 1
    assert items[0].name == "Big Ben"
    assert items[0].founded == "1859-05-31"


async def test_fetch_wikidata_error_returns_empty() -> None:
    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("Network error")

    async def _mock_get_client() -> AsyncMock:
        return mock_client

    with patch("city_guide.sources.wikidata.get_client", _mock_get_client):
        items = await fetch_wikidata(51.5, -0.1, 500)

    assert items == []
