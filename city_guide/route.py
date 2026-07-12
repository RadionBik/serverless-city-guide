"""Route composition — pure geometry, no LLM. Greedy nearest-neighbor + 2-opt + length trim.

Routes are circular by default: the walk returns to the user's pin, and the
return leg counts toward the length target.
"""

from __future__ import annotations

from city_guide.bearing import bearing, haversine
from city_guide.config import TourConfig
from city_guide.types import Candidate, CuratedStop, TourStop

Point = tuple[float, float]


def _tour_length(origin: Point, points: list[Point], circular: bool) -> float:
    path = [origin, *points]
    if circular:
        path.append(origin)
    return sum(haversine(*path[i], *path[i + 1]) for i in range(len(path) - 1))


def _greedy_order(origin: Point, coords: list[Point]) -> list[int]:
    """Nearest-neighbor order starting from the origin. Returns indices into coords."""
    remaining = set(range(len(coords)))
    order: list[int] = []
    current = origin
    while remaining:
        nearest = min(remaining, key=lambda i: haversine(*current, *coords[i]))
        order.append(nearest)
        current = coords[nearest]
        remaining.remove(nearest)
    return order


def _two_opt(origin: Point, coords: list[Point], order: list[int], circular: bool) -> list[int]:
    """One 2-opt pass — untangle route crossings. Good enough for ≤12 stops."""
    improved = True
    while improved:
        improved = False
        path = [origin] + [coords[i] for i in order]
        if circular:
            path.append(origin)
        for a in range(1, len(path) - 2):
            for b in range(a + 1, len(path) - 1):
                before = haversine(*path[a - 1], *path[a]) + haversine(*path[b], *path[b + 1])
                after = haversine(*path[a - 1], *path[b]) + haversine(*path[a], *path[b + 1])
                if after < before - 1:  # 1 m tolerance avoids float churn
                    order[a - 1 : b] = reversed(order[a - 1 : b])
                    improved = True
                    break
            if improved:
                break
    return order


def _trim_to_length(
    origin: Point, coords: list[Point], order: list[int], max_length: float, circular: bool
) -> list[int]:
    """Drop the stop whose removal saves the most distance until the tour fits."""
    while len(order) > TourConfig.min_stops:
        if _tour_length(origin, [coords[i] for i in order], circular) <= max_length:
            break
        savings = []
        for pos in range(len(order)):
            without = order[:pos] + order[pos + 1 :]
            length = _tour_length(origin, [coords[i] for i in without], circular)
            savings.append((length, pos))
        _, worst_pos = min(savings)
        order.pop(worst_pos)
    return order


def compose_route(
    origin_lat: float,
    origin_lon: float,
    candidates: list[Candidate],
    picks: list[CuratedStop],
    *,
    max_length: int | None = None,
    circular: bool = True,
) -> tuple[list[TourStop], int]:
    """Curator picks (semantic) → ordered TourStops with legs (spatial).

    Returns (ordered stops, total length in meters — return leg included when
    circular). Deterministic.
    """
    target = max_length if max_length is not None else TourConfig.default_length_meters
    by_id = {c.id: c for c in candidates}
    chosen = [(by_id[p.candidate_id], p.reason) for p in picks if p.candidate_id in by_id]
    if not chosen:
        return [], 0

    origin = (origin_lat, origin_lon)
    coords = [(c.lat, c.lon) for c, _ in chosen]

    order = _greedy_order(origin, coords)
    order = _two_opt(origin, coords, order, circular)
    order = _trim_to_length(origin, coords, order, target, circular)

    stops: list[TourStop] = []
    prev = origin
    total = 0.0
    for idx in order:
        cand, reason = chosen[idx]
        dist = haversine(*prev, cand.lat, cand.lon)
        stops.append(
            TourStop(
                name=cand.name,
                lat=cand.lat,
                lon=cand.lon,
                reason=reason,
                leg_distance_m=round(dist),
                leg_bearing_deg=round(bearing(*prev, cand.lat, cand.lon)),
            )
        )
        total += dist
        prev = (cand.lat, cand.lon)

    if circular and stops:
        total += haversine(*prev, *origin)

    return stops, round(total)


def walking_maps_url(origin_lat: float, origin_lon: float, stops: list[TourStop], *, circular: bool = True) -> str:
    """Google Maps directions deep-link — real street routing, no API key.

    Circular routes end back at the origin; open routes end at the last stop.
    """
    if not stops:
        return ""
    origin = f"{origin_lat},{origin_lon}"
    if circular:
        destination = origin
        waypoint_stops = stops
    else:
        destination = f"{stops[-1].lat},{stops[-1].lon}"
        waypoint_stops = stops[:-1]
    url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode=walking"
    waypoints = "|".join(f"{s.lat},{s.lon}" for s in waypoint_stops)
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url
