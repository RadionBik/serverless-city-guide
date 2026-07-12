"""Wikidata SPARQL — fetch structured facts (founding dates, architects, events) for nearby items."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel

from city_guide.config import HttpConfig, WikidataConfig
from city_guide.http_client import get_client
from city_guide.sources.wikidata_types import WIKIDATA_ALLOWED_TYPES, WIKIDATA_BUILDING_TYPE

logger = logging.getLogger(__name__)

_SPARQL_TEMPLATE = """\
SELECT ?item ?itemLabel ?itemDescription ?coord ?distance ?instanceOfLabel
       ?foundingDate ?architectLabel ?notableEventLabel
       ?namedAfterLabel ?creatorLabel ?archStyleLabel
       ?openingDate ?heritageLabel ?nativeLabel
WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?coord.
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral.
    bd:serviceParam wikibase:radius "{radius_km}".
    bd:serviceParam wikibase:distance ?distance.
  }}
  OPTIONAL {{ ?item wdt:P31 ?instanceOf. }}
  OPTIONAL {{ ?item wdt:P571 ?foundingDate. }}
  OPTIONAL {{ ?item wdt:P84 ?architect. }}
  OPTIONAL {{ ?item wdt:P793 ?notableEvent. }}
  OPTIONAL {{ ?item wdt:P138 ?namedAfter. }}
  OPTIONAL {{ ?item wdt:P170 ?creator. }}
  OPTIONAL {{ ?item wdt:P149 ?archStyle. }}
  OPTIONAL {{ ?item wdt:P1619 ?openingDate. }}
  OPTIONAL {{ ?item wdt:P1435 ?heritage. }}
  OPTIONAL {{ ?item wdt:P1705 ?nativeLabel. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,es,ru". }}
}}
ORDER BY ?distance
LIMIT {limit}"""

# Pattern: Q-code label like "Q12345" — means the item has no human-readable label
_QCODE_RE = re.compile(r"^Q\d+$")


class WikidataItem(BaseModel):
    """Wikidata item with structured facts — raw fields from SPARQL query."""

    name: str = ""
    description: str = ""
    distance: float = 0.0  # meters
    lat: float = 0.0
    lon: float = 0.0
    item_type: str = ""
    founded: str | None = None
    architect: str | None = None
    notable_event: str | None = None
    named_after: str | None = None
    creator: str | None = None
    arch_style: str | None = None
    opening_date: str | None = None
    heritage: str | None = None
    native_label: str | None = None


def _parse_coord(wkt_value: str) -> tuple[float, float]:
    """Parse 'Point(lon lat)' WKT literal into (lat, lon)."""
    # Format: "Point(12.345 56.789)"
    inner = wkt_value.replace("Point(", "").rstrip(")")
    lon_s, lat_s = inner.split()
    return float(lat_s), float(lon_s)


# Mapping: SPARQL variable name -> WikidataItem field name
# Date fields (foundingDate, openingDate) get truncated to 10 chars (YYYY-MM-DD)
_SPARQL_TO_FIELD: tuple[tuple[str, str, bool], ...] = (
    ("foundingDate", "founded", True),
    ("architectLabel", "architect", False),
    ("notableEventLabel", "notable_event", False),
    ("namedAfterLabel", "named_after", False),
    ("creatorLabel", "creator", False),
    ("archStyleLabel", "arch_style", False),
    ("openingDate", "opening_date", True),
    ("heritageLabel", "heritage", False),
    ("nativeLabel", "native_label", False),
)


def _extract_extras(row: dict[str, Any]) -> dict[str, str]:
    """Extract all optional fact fields from a SPARQL row."""
    extras: dict[str, str] = {}
    for sparql_key, field_name, is_date in _SPARQL_TO_FIELD:
        if sparql_key in row:
            val = row[sparql_key].get("value", "")
            if val:
                extras[field_name] = val[:10] if is_date else val
    return extras


def _is_allowed_type(item_type: str, has_extras: bool) -> bool:
    """Check if item type passes the whitelist filter.

    - Types in WIKIDATA_ALLOWED_TYPES always pass.
    - "building" passes only if the item has enrichment facts (founded/architect/event).
    - Everything else is filtered out.
    """
    lower = item_type.lower()
    if lower in WIKIDATA_ALLOWED_TYPES:
        return True
    return lower == WIKIDATA_BUILDING_TYPE and has_extras


def _parse_bindings(bindings: list[dict[str, Any]]) -> list[WikidataItem]:
    """Parse SPARQL result bindings into deduplicated WikidataItems with whitelist filtering."""
    seen: dict[str, WikidataItem] = {}

    for row in bindings:
        name = row.get("itemLabel", {}).get("value", "")
        if not name or _QCODE_RE.match(name):
            continue

        extras = _extract_extras(row)

        # Deduplicate: keep first occurrence (closest), but merge extra facts
        if name in seen:
            existing = seen[name]
            for field_name, val in extras.items():
                if val and not getattr(existing, field_name):
                    setattr(existing, field_name, val)
            continue

        item_type = row.get("instanceOfLabel", {}).get("value", "")
        if not _is_allowed_type(item_type, bool(extras)):
            continue

        coord_raw = row.get("coord", {}).get("value", "")
        try:
            lat, lon = _parse_coord(coord_raw)
        except (ValueError, IndexError):
            lat, lon = 0.0, 0.0

        distance_km = float(row.get("distance", {}).get("value", 0))
        distance_m = distance_km * 1000

        description = row.get("itemDescription", {}).get("value", "")

        seen[name] = WikidataItem(
            name=name,
            description=description,
            distance=distance_m,
            lat=lat,
            lon=lon,
            item_type=item_type,
            **{k: v or None for k, v in extras.items()},
        )

    return list(seen.values())


def _build_query(lat: float, lon: float, radius: int) -> str:
    """Build SPARQL query string for given coordinates and radius."""
    radius_km = radius / 1000
    return _SPARQL_TEMPLATE.format(lat=lat, lon=lon, radius_km=radius_km, limit=WikidataConfig.fetch_limit)


async def fetch_wikidata_raw(lat: float, lon: float, radius: int = 500) -> list[dict[str, Any]]:
    """Async raw SPARQL fetch — returns unparsed bindings.

    Used by dev tools (scan_wikidata_types.py) that need raw data before
    whitelist filtering, and internally by fetch_wikidata().
    """
    query = _build_query(lat, lon, radius)
    client = await get_client()
    resp = await client.post(
        WikidataConfig.sparql_url,
        data={"query": query, "format": "json"},
        headers={
            "User-Agent": HttpConfig.user_agent,
            "Accept": "application/sparql-results+json",
        },
        timeout=HttpConfig.timeout,
    )
    resp.raise_for_status()
    bindings: list[dict[str, Any]] = resp.json()["results"]["bindings"]
    return bindings


async def fetch_wikidata(lat: float, lon: float, radius: int) -> list[WikidataItem]:
    """Fetch nearby Wikidata items via SPARQL. Returns empty list on any error."""
    try:
        bindings = await fetch_wikidata_raw(lat, lon, radius)
        return _parse_bindings(bindings)
    except Exception:
        logger.warning("Wikidata SPARQL fetch failed", exc_info=True)
        return []
