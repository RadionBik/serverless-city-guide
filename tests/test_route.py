"""Route composition — deterministic geometry, no LLM."""

from city_guide.route import compose_route, walking_maps_url
from city_guide.types import Candidate, CuratedStop

# Four points along one street (Berlin-ish), plus one far outlier
BASE_LAT, BASE_LON = 52.5000, 13.4000


def _candidate(cid: int, dlat: float, dlon: float, name: str | None = None) -> Candidate:
    return Candidate(
        id=cid, name=name or f"place-{cid}", kind="poi", dist_m=0, lat=BASE_LAT + dlat, lon=BASE_LON + dlon
    )


def _picks(*ids: int) -> list[CuratedStop]:
    return [CuratedStop(candidate_id=i, reason=f"reason-{i}") for i in ids]


def test_orders_stops_by_walking_greed() -> None:
    # Candidates given in scrambled order; geometry runs west→east from the origin
    candidates = [
        _candidate(0, 0.0, 0.009),  # ~600 m east
        _candidate(1, 0.0, 0.003),  # ~200 m east
        _candidate(2, 0.0, 0.006),  # ~400 m east
    ]
    stops, total = compose_route(BASE_LAT, BASE_LON, candidates, _picks(0, 1, 2))
    assert [s.name for s in stops] == ["place-1", "place-2", "place-0"]
    assert 550 < total < 650  # ~600 m straight line, no backtracking


def test_legs_carry_distance_and_bearing() -> None:
    candidates = [_candidate(0, 0.0, 0.003)]  # ~200 m due east
    stops, _ = compose_route(BASE_LAT, BASE_LON, candidates, _picks(0))
    assert stops[0].leg_distance_m > 150
    assert 85 <= stops[0].leg_bearing_deg <= 95  # east
    assert stops[0].reason == "reason-0"


def test_unknown_pick_ids_are_dropped() -> None:
    candidates = [_candidate(0, 0.0, 0.003)]
    stops, _ = compose_route(BASE_LAT, BASE_LON, candidates, _picks(0, 99))
    assert len(stops) == 1


def test_empty_picks() -> None:
    stops, total = compose_route(BASE_LAT, BASE_LON, [_candidate(0, 0.0, 0.003)], [])
    assert stops == []
    assert total == 0


def test_over_length_tour_drops_worst_detour() -> None:
    # Cluster near origin + one stop ~5 km away → total exceeds max, outlier must go
    candidates = [
        _candidate(0, 0.0, 0.002),
        _candidate(1, 0.0, 0.004),
        _candidate(2, 0.001, 0.003),
        _candidate(3, 0.002, 0.002),
        _candidate(4, 0.045, 0.0, name="outlier"),  # ~5 km north
    ]
    stops, total = compose_route(BASE_LAT, BASE_LON, candidates, _picks(0, 1, 2, 3, 4))
    assert all(s.name != "outlier" for s in stops)
    assert total <= 4000


def test_walking_maps_url() -> None:
    candidates = [_candidate(0, 0.0, 0.003), _candidate(1, 0.0, 0.006)]
    stops, _ = compose_route(BASE_LAT, BASE_LON, candidates, _picks(0, 1))
    url = walking_maps_url(BASE_LAT, BASE_LON, stops)
    assert url.startswith("https://www.google.com/maps/dir/?api=1")
    assert "travelmode=walking" in url
    assert f"destination={stops[-1].lat},{stops[-1].lon}" in url
    assert "waypoints=" in url


def test_maps_url_empty_stops() -> None:
    assert walking_maps_url(BASE_LAT, BASE_LON, []) == ""
