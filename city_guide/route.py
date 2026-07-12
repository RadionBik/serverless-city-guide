"""Route composition — pure geometry, no LLM. Greedy nearest-neighbor + 2-opt + length trim."""

from __future__ import annotations

from city_guide.bearing import bearing, haversine
from city_guide.config import TourConfig
from city_guide.types import Candidate, CuratedStop, TourStop


def _tour_length(points: list[tuple[float, float]]) -> float:
    return sum(haversine(*points[i], *points[i + 1]) for i in range(len(points) - 1))


def _greedy_order(origin: tuple[float, float], coords: list[tuple[float, float]]) -> list[int]:
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


def _two_opt(origin: tuple[float, float], coords: list[tuple[float, float]], order: list[int]) -> list[int]:
    """One 2-opt pass — untangle route crossings. Good enough for ≤10 stops."""
    improved = True
    while improved:
        improved = False
        path = [origin] + [coords[i] for i in order]
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
    origin: tuple[float, float], coords: list[tuple[float, float]], order: list[int], max_length: float
) -> list[int]:
    """Drop the stop whose removal saves the most distance until the tour fits."""
    while len(order) > TourConfig.min_stops:
        points = [origin] + [coords[i] for i in order]
        if _tour_length(points) <= max_length:
            break
        savings = []
        for pos in range(len(order)):
            without = order[:pos] + order[pos + 1 :]
            length = _tour_length([origin] + [coords[i] for i in without])
            savings.append((length, pos))
        _, worst_pos = min(savings)
        order.pop(worst_pos)
    return order


def compose_route(
    origin_lat: float,
    origin_lon: float,
    candidates: list[Candidate],
    picks: list[CuratedStop],
) -> tuple[list[TourStop], int]:
    """Curator picks (semantic) → ordered TourStops with legs (spatial).

    Returns (ordered stops, total length in meters). Deterministic.
    """
    by_id = {c.id: c for c in candidates}
    chosen = [(by_id[p.candidate_id], p.reason) for p in picks if p.candidate_id in by_id]
    if not chosen:
        return [], 0

    origin = (origin_lat, origin_lon)
    coords = [(c.lat, c.lon) for c, _ in chosen]

    order = _greedy_order(origin, coords)
    order = _two_opt(origin, coords, order)
    order = _trim_to_length(origin, coords, order, TourConfig.max_length_meters)

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

    return stops, round(total)


def walking_maps_url(origin_lat: float, origin_lon: float, stops: list[TourStop]) -> str:
    """Google Maps directions deep-link — real street routing, no API key."""
    if not stops:
        return ""
    waypoints = "|".join(f"{s.lat},{s.lon}" for s in stops[:-1])
    dest = stops[-1]
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin_lat},{origin_lon}"
        f"&destination={dest.lat},{dest.lon}"
        "&travelmode=walking"
    )
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url
