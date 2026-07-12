"""Guide store — JSON round-trips and haversine retrieval."""

from pathlib import Path

from city_guide.store import GuideStore, read_tour_plan
from city_guide.types import GuideManifest, StopStory, TourPlan, TourStop


def _plan(guide_id: str = "tour-test") -> TourPlan:
    return TourPlan(
        guide_id=guide_id,
        origin_lat=52.5,
        origin_lon=13.4,
        interest="street art",
        stops=[
            TourStop(name="Mural", lat=52.5010, lon=13.4010, leg_distance_m=120, leg_bearing_deg=45),
            TourStop(name="Gallery", lat=52.5020, lon=13.4020, leg_distance_m=150, leg_bearing_deg=50),
        ],
        total_length_m=270,
    )


def test_manifest_round_trip(tmp_path: Path) -> None:
    store = GuideStore(tmp_path)
    manifest = GuideManifest(plan=_plan(), status="ready", intro="hi", outro="bye")
    store.save_manifest(manifest)

    loaded = store.load_manifest("tour-test")
    assert loaded is not None
    assert loaded.status == "ready"
    assert loaded.plan.stops[0].name == "Mural"


def test_stops_round_trip_ordered(tmp_path: Path) -> None:
    store = GuideStore(tmp_path)
    plan = _plan()
    # Save out of order; 10 before 2 catches lexicographic-sort bugs
    for i in (10, 0, 2):
        store.save_stop("tour-test", i, StopStory(stop=plan.stops[0], story=f"story-{i}"))
    stories = store.load_stops("tour-test")
    assert [s.story for s in stories] == ["story-0", "story-2", "story-10"]


def test_missing_guide(tmp_path: Path) -> None:
    store = GuideStore(tmp_path)
    assert store.load_manifest("nope") is None
    assert store.load_stops("nope") == []
    assert store.list_guides() == []


def test_nearby_stops_only_ready_within_radius(tmp_path: Path) -> None:
    store = GuideStore(tmp_path)

    ready = GuideManifest(plan=_plan("ready-guide"), status="ready")
    store.save_manifest(ready)
    store.save_stop("ready-guide", 0, StopStory(stop=ready.plan.stops[0], story="near"))
    far_stop = TourStop(name="Far", lat=53.5, lon=14.4)  # ~130 km away
    store.save_stop("ready-guide", 1, StopStory(stop=far_stop, story="far"))

    baking = GuideManifest(plan=_plan("baking-guide"), status="baking")
    store.save_manifest(baking)
    store.save_stop("baking-guide", 0, StopStory(stop=baking.plan.stops[0], story="not-ready"))

    hits = store.nearby_stops(52.5, 13.4, radius_m=500)
    assert [s.story for s in hits] == ["near"]


def test_read_tour_plan(tmp_path: Path) -> None:
    path = tmp_path / "tour.json"
    path.write_text(_plan().model_dump_json(), encoding="utf-8")
    plan = read_tour_plan(path)
    assert plan.guide_id == "tour-test"
    assert len(plan.stops) == 2
