"""Overpass API — query OpenStreetMap for nearby POIs."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from city_guide.config import OverpassConfig
from city_guide.http_client import get_client
from city_guide.sources.overpass_types import CATEGORIES, OVERPASS_NOISE_TYPES

log = logging.getLogger(__name__)


class OverpassPOI(BaseModel):
    """Structured representation of an Overpass POI — raw parsed fields only.

    ``tags`` stores the full OSM tag dict from the API response, used by
    noise-filtering and analysis scripts after the model is created.
    """

    name: str = "?"
    type: str = ""
    lat: float = 0.0
    lon: float = 0.0
    cuisine: str = ""
    phone: str = ""
    website: str = ""
    address: str = ""
    housenumber: str = ""
    tags: dict[str, str] = {}


def is_poi_noise(tags: dict[str, Any]) -> bool:
    """Return True if the POI is purely utilitarian noise."""
    for category in CATEGORIES:
        value = tags.get(category)
        if value and (category, value) in OVERPASS_NOISE_TYPES:
            return True
    return False


def build_query(lat: float, lon: float, radius: int, tags: list[str] | None = None) -> str:
    """Build Overpass QL query for nearby POIs.

    If *tags* is provided, only those category keys are queried (e.g. ``["amenity", "shop"]``).
    Otherwise all categories are included.
    """
    tag_keys = tags if tags is not None else list(CATEGORIES.keys())
    parts = []
    for tag in tag_keys:
        parts.append(f'node(around:{radius},{lat},{lon})["{tag}"];')
        parts.append(f'way(around:{radius},{lat},{lon})["{tag}"];')
    query = f"[out:json][timeout:{OverpassConfig.query_timeout}];({' '.join(parts)});out center tags;"
    return query


def classify(tags: dict[str, Any]) -> str:
    """Human-readable type from tags."""
    for category in CATEGORIES:
        value = tags.get(category, "")
        if value:
            return str(value).replace("_", " ").title()
    return "Place"


async def fetch_raw_elements(
    lat: float, lon: float, radius: int = 100, tags: list[str] | None = None
) -> list[dict[str, Any]]:
    """Query Overpass mirrors, return raw JSON elements.

    Tries each mirror in ``OverpassConfig.urls`` until one succeeds.
    """
    query = build_query(lat, lon, radius, tags=tags)
    encoded = quote(query)
    client = await get_client()

    last_exc: Exception | None = None
    for base_url in OverpassConfig.urls:
        try:
            resp = await client.get(f"{base_url}?data={encoded}")
            resp.raise_for_status()
            data = resp.json()
            elements: list[dict[str, Any]] = data.get("elements", [])
            return elements
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            log.warning("Overpass mirror %s failed: %s", base_url, exc)
            last_exc = exc

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("No Overpass mirrors configured")


def parse_raw_elements(elements: list[dict[str, Any]]) -> list[OverpassPOI]:
    """Convert raw Overpass JSON dicts into OverpassPOI objects.

    Extracts coordinates (``center`` for ways, top-level for nodes) and skips
    elements that lack coordinates entirely. Does **not** filter unnamed or
    noise POIs — that is handled by :func:`filter_pois`.

    Args:
        elements: Raw ``elements`` list from the Overpass JSON response.
    """
    results: list[OverpassPOI] = []
    for el in elements:
        center = el.get("center", {})
        el_lat = center.get("lat") if center.get("lat") is not None else el.get("lat")
        el_lon = center.get("lon") if center.get("lon") is not None else el.get("lon")
        if el_lat is None or el_lon is None:
            continue

        tags = el.get("tags", {})
        results.append(
            OverpassPOI(
                name=tags.get("name", "?"),
                type=classify(tags),
                lat=el_lat,
                lon=el_lon,
                cuisine=tags.get("cuisine", ""),
                phone=tags.get("phone", ""),
                website=tags.get("website", ""),
                address=tags.get("addr:street", ""),
                housenumber=tags.get("addr:housenumber", ""),
                tags={k: str(v) for k, v in tags.items()},
            )
        )

    return results


def filter_pois(pois: list[OverpassPOI]) -> list[OverpassPOI]:
    """Remove unnamed and noise POIs from a parsed list.

    Args:
        pois: Already-parsed OverpassPOI objects (from :func:`parse_raw_elements`).
    """
    results: list[OverpassPOI] = []
    for poi in pois:
        if not poi.name or poi.name == "?":
            continue
        if is_poi_noise(poi.tags):
            continue
        results.append(poi)
    return results


def deduplicate_pois(pois: list[OverpassPOI]) -> list[OverpassPOI]:
    """Remove duplicate POIs by name, keeping first occurrence."""
    seen: set[str] = set()
    result: list[OverpassPOI] = []
    for poi in pois:
        key = poi.name.lower().strip()
        if key not in seen:
            seen.add(key)
            result.append(poi)
    return result
