"""Unified Place model — single representation for all data sources."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from city_guide.bearing import bearing as compute_bearing
from city_guide.bearing import haversine
from city_guide.config import GeoConfig, SearchConfig, WikidataConfig
from city_guide.maps_url import build_maps_url, build_wiki_url
from city_guide.sources.overpass import deduplicate_pois, filter_pois
from city_guide.types import Source

if TYPE_CHECKING:
    from city_guide.collector import CollectedData
    from city_guide.sources.overpass import OverpassPOI
    from city_guide.sources.wikidata import WikidataItem
    from city_guide.sources.wikipedia import WikiArticle

# Wikidata optional fact fields — used when converting WikidataItem → Place extras
WIKIDATA_EXTRAS: frozenset[str] = frozenset(
    {
        "founded",
        "architect",
        "notable_event",
        "named_after",
        "creator",
        "arch_style",
        "opening_date",
        "heritage",
        "native_label",
    }
)


def _round_distance(meters: float) -> int:
    """Round distance to nearest GeoConfig.distance_rounding_meters, clamping to at least one unit."""
    raw = round(meters / GeoConfig.distance_rounding_meters) * GeoConfig.distance_rounding_meters
    return raw or GeoConfig.distance_rounding_meters


class Place(BaseModel):
    """Unified place representation for display/LLM — all sources normalize to this.

    source: primary source (for display/sorting).
    sources: all contributing sources — includes primary; populated during normalize(),
    expanded during deduplicate_places() when cross-source duplicates are merged.
    """

    name: str
    lat: float
    lon: float
    distance_m: int
    bearing: int | None
    source: Source
    sources: frozenset[Source] = frozenset()
    maps_url: str
    wiki_url: str = ""
    type: str = ""
    description: str = ""
    photo_url: str = ""
    extras: dict[str, Any] = {}

    def to_display_dict(self) -> dict[str, Any]:
        """Serialize to a flat dict for display/LLM — inlines extras alongside top-level fields."""
        result: dict[str, Any] = {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "distance_m": self.distance_m,
            "source": str(self.source),
            "maps_url": self.maps_url,
        }
        if self.bearing is not None:
            result["bearing_deg"] = self.bearing
        if self.wiki_url:
            result["wiki_url"] = self.wiki_url
        if self.type:
            result["type"] = self.type
        if self.description:
            result["description"] = self.description
        if self.photo_url:
            result["photo_url"] = self.photo_url
        if len(self.sources) > 1:
            result["sources"] = sorted(str(s) for s in self.sources)
        # Inline extras at top level (skip reserved keys to avoid shadowing)
        for key, value in self.extras.items():
            if value and key not in result:
                result[key] = value
        return result


def normalize(
    *,
    overpass_pois: list[OverpassPOI] | None = None,
    wikipedia_articles: list[WikiArticle] | None = None,
    wikidata_items: list[WikidataItem] | None = None,
) -> list[Place]:
    """Convert all source lists into a unified list of Place objects."""
    places: list[Place] = []
    if overpass_pois:
        places.extend(_from_overpass(poi) for poi in overpass_pois)
    if wikipedia_articles:
        places.extend(_from_wikipedia(article) for article in wikipedia_articles)
    if wikidata_items:
        places.extend(_from_wikidata(item) for item in wikidata_items)
    return places


def _overpass_address(poi: OverpassPOI) -> str:
    """Build a street address string from Overpass POI fields.

    Combines housenumber and street name (e.g. "9A Blackstock Road").
    Returns empty string if no address info is available.
    """
    parts = []
    if poi.housenumber:
        parts.append(poi.housenumber)
    if poi.address:
        parts.append(poi.address)
    return " ".join(parts)


def _from_overpass(poi: OverpassPOI) -> Place:
    extras: dict[str, Any] = {}
    if poi.cuisine:
        extras["cuisine"] = poi.cuisine
    if poi.phone:
        extras["phone"] = poi.phone
    if poi.website:
        extras["website"] = poi.website
    if poi.address:
        extras["address"] = poi.address
    if poi.housenumber:
        extras["housenumber"] = poi.housenumber
    return Place(
        name=poi.name,
        lat=poi.lat,
        lon=poi.lon,
        distance_m=0,
        bearing=None,
        source=Source.OVERPASS,
        sources=frozenset({Source.OVERPASS}),
        maps_url=build_maps_url(poi.name, poi.lat, poi.lon, address=_overpass_address(poi)),
        type=poi.type,
        extras=extras,
    )


def _from_wikipedia(article: WikiArticle) -> Place:
    return Place(
        name=article.title,
        lat=article.lat,
        lon=article.lon,
        distance_m=0,
        bearing=None,
        source=Source.WIKIPEDIA,
        sources=frozenset({Source.WIKIPEDIA}),
        maps_url=build_maps_url(article.title, article.lat, article.lon),
        wiki_url=build_wiki_url(article.title),
        type="Wikipedia article",
        description=article.extract,
        photo_url=article.thumbnail_url or "",
    )


def _from_wikidata(item: WikidataItem) -> Place:
    extras: dict[str, Any] = {}
    for field_name in WIKIDATA_EXTRAS:
        value = getattr(item, field_name, None)
        if value:
            extras[field_name] = value
    return Place(
        name=item.name,
        lat=item.lat,
        lon=item.lon,
        distance_m=0,
        bearing=None,
        source=Source.WIKIDATA,
        sources=frozenset({Source.WIKIDATA}),
        maps_url=build_maps_url(item.name, item.lat, item.lon),
        type=item.item_type or "wikidata",
        description=item.description,
        extras=extras,
    )


# Source priority for merging — first = highest priority for primary source selection.
# OVERPASS first because its `type` field is critical for the analysis fingerprint.
_SOURCE_PRIORITY: list[Source] = [Source.OVERPASS, Source.WIKIPEDIA, Source.WIKIDATA]


def _names_match(name_a: str, name_b: str) -> bool:
    """Check if two place names refer to the same entity.

    Returns True when names match case-insensitively, or one name is a substring
    of the other (shorter name must be >= SearchConfig.dedup_min_name_length chars).
    """
    lower_a = name_a.strip().lower()
    lower_b = name_b.strip().lower()
    if lower_a == lower_b:
        return True
    shorter, longer = (lower_a, lower_b) if len(lower_a) <= len(lower_b) else (lower_b, lower_a)
    return len(shorter) >= SearchConfig.dedup_min_name_length and shorter in longer


def _pick_field(by_source: dict[Source, Place], group: list[Place], preferred: Source, getter: str) -> str:
    """Pick a string field from the preferred source, falling back to the first non-empty value.

    by_source: mapping from Source to Place for O(1) lookup.
    group: ordered list of Places (primary first).
    preferred: source whose value is preferred (e.g. OVERPASS for type).
    getter: attribute name to read from each Place.
    """
    if preferred in by_source:
        value = getattr(by_source[preferred], getter)
        if value:
            return str(value)
    for place in group:
        value = getattr(place, getter)
        if value:
            return str(value)
    return ""


def _merge_extras(group: list[Place], primary: Place) -> dict[str, Any]:
    """Merge extras dicts from all places — primary's keys take precedence."""
    merged: dict[str, Any] = {}
    for place in reversed(group):  # lower priority first, primary overwrites
        merged.update({key: value for key, value in place.extras.items() if value})
    merged.update({key: value for key, value in primary.extras.items() if value})
    return merged


def _merge_places(group: list[Place]) -> Place:
    """Merge a group of Places representing the same physical location.

    Merge strategy:
    - name/lat/lon/distance_m/bearing: from primary source (highest _SOURCE_PRIORITY)
    - type: from OVERPASS source (for fingerprint), else first available
    - maps_url: from primary source, else first available
    - wiki_url: from WIKIPEDIA source
    - description: from WIKIPEDIA (richest), else longest non-empty
    - photo_url: first non-empty
    - extras: merge all dicts (primary's keys take precedence)
    - sources: union of all
    """
    if len(group) == 1:
        return group[0]

    # Sort by source priority to pick the primary
    priority = {source: idx for idx, source in enumerate(_SOURCE_PRIORITY)}
    group.sort(key=lambda place: priority.get(place.source, len(_SOURCE_PRIORITY)))
    primary = group[0]

    by_source: dict[Source, Place] = {place.source: place for place in group}

    # Description: prefer WIKIPEDIA (richest), else longest non-empty
    merged_description = ""
    if Source.WIKIPEDIA in by_source and by_source[Source.WIKIPEDIA].description:
        merged_description = by_source[Source.WIKIPEDIA].description
    else:
        merged_description = max((place.description for place in group), key=len, default="")

    return Place(
        name=primary.name,
        lat=primary.lat,
        lon=primary.lon,
        distance_m=primary.distance_m,
        bearing=primary.bearing,
        source=primary.source,
        sources=frozenset().union(*(place.sources for place in group)),
        maps_url=_pick_field(by_source, group, primary.source, "maps_url"),
        wiki_url=_pick_field(by_source, group, Source.WIKIPEDIA, "wiki_url"),
        type=_pick_field(by_source, group, Source.OVERPASS, "type"),
        description=merged_description,
        photo_url=_pick_field(by_source, group, primary.source, "photo_url"),
        extras=_merge_extras(group, primary),
    )


def _should_merge(place_a: Place, place_b: Place) -> bool:
    """Check if two places should be merged — different sources, close proximity, matching names."""
    if place_a.source == place_b.source:
        return False
    dist = haversine(place_a.lat, place_a.lon, place_b.lat, place_b.lon)
    if dist > SearchConfig.dedup_proximity_meters:
        return False
    return _names_match(place_a.name, place_b.name)


class _UnionFind:
    """Lightweight union-find for grouping duplicate place indices."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, idx: int) -> int:
        """Find root with path compression."""
        while self._parent[idx] != idx:
            self._parent[idx] = self._parent[self._parent[idx]]
            idx = self._parent[idx]
        return idx

    def union(self, idx_a: int, idx_b: int) -> None:
        """Merge two sets."""
        root_a, root_b = self.find(idx_a), self.find(idx_b)
        if root_a != root_b:
            self._parent[root_b] = root_a


def deduplicate_places(places: list[Place]) -> list[Place]:
    """Merge cross-source duplicates into enriched Place objects.

    Uses O(n^2) pairwise proximity + name matching with union-find for transitive merges.
    Only places from *different* sources can be merged. N is small (~35-85 after per-source limits).
    """
    count = len(places)
    uf = _UnionFind(count)

    for i in range(count):
        for j in range(i + 1, count):
            if _should_merge(places[i], places[j]):
                uf.union(i, j)

    groups: dict[int, list[Place]] = {}
    for idx, place in enumerate(places):
        groups.setdefault(uf.find(idx), []).append(place)

    return [_merge_places(group) for group in groups.values()]


class DisplayData(BaseModel):
    """Post-filter data from ``filter_by_radius()`` — for analyze/LLM/display."""

    lat: float = 0.0
    lon: float = 0.0
    places: list[Place] = []

    def to_display_dict(self) -> dict[str, Any]:
        """Serialize for display/LLM — delegates to Place.to_display_dict()."""
        return {
            "lat": self.lat,
            "lon": self.lon,
            "places": [place.to_display_dict() for place in self.places],
        }


# Per-source display limits. Sources not listed here: no limit. All sorted by distance.
_SOURCE_LIMITS: dict[Source, int] = {
    Source.WIKIDATA: WikidataConfig.display_limit,
}


def filter_by_radius(
    data: CollectedData,
    lat: float,
    lon: float,
    radius: int,
    wiki_limit: int = 5,
) -> DisplayData:
    """Filter CollectedData down to a display radius using the user's actual position.

    Converts all source data to Place objects, recomputes distances from (lat, lon),
    filters by *radius*, applies per-source sorting and display limits.
    """
    overpass_pois = deduplicate_pois(filter_pois(data.overpass_pois))
    all_places = normalize(
        overpass_pois=overpass_pois,
        wikipedia_articles=data.wikipedia_articles,
        wikidata_items=data.wikidata_items,
    )

    # Recompute distance + bearing from user position, filter by radius
    filtered: list[Place] = []
    for place in all_places:
        dist = haversine(lat, lon, place.lat, place.lon)
        if dist <= radius:
            bearing_deg = round(compute_bearing(lat, lon, place.lat, place.lon))
            filtered.append(place.model_copy(update={"distance_m": _round_distance(dist), "bearing": bearing_deg}))

    # Apply per-source limits and sorting
    source_limits = dict(_SOURCE_LIMITS)
    source_limits[Source.WIKIPEDIA] = wiki_limit

    result: list[Place] = []
    for source in Source:
        group = [place for place in filtered if place.source == source]
        group.sort(key=lambda place: place.distance_m)
        result.extend(group[: source_limits.get(source)])

    result = deduplicate_places(result)

    return DisplayData(lat=lat, lon=lon, places=result)
