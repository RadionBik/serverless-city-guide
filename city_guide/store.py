"""Guide store — JSON files in a directory (local, or the bucket mounted into the job).

Layout:
    <store>/<guide_id>/manifest.json
    <store>/<guide_id>/stops/<index>.json

Retrieval is a haversine scan over manifests — proximity is the relevance function.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from city_guide.bearing import haversine
from city_guide.config import get_store_dir
from city_guide.types import GuideManifest, StopStory, TourPlan

logger = logging.getLogger(__name__)


class GuideStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_store_dir()

    def _guide_dir(self, guide_id: str) -> Path:
        return self.root / guide_id

    # --- write (job side) ---

    def save_manifest(self, manifest: GuideManifest) -> None:
        guide_dir = self._guide_dir(manifest.plan.guide_id)
        guide_dir.mkdir(parents=True, exist_ok=True)
        (guide_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def save_stop(self, guide_id: str, index: int, story: StopStory) -> None:
        stops_dir = self._guide_dir(guide_id) / "stops"
        stops_dir.mkdir(parents=True, exist_ok=True)
        (stops_dir / f"{index}.json").write_text(story.model_dump_json(indent=2), encoding="utf-8")

    def save_trace(self, guide_id: str, name: str, payload: dict[str, Any]) -> None:
        """Audit layer — write-only debug/proof artifacts, never read by the app."""
        trace_dir = self._guide_dir(guide_id) / "trace"
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    # --- read (CLI / live path) ---

    def load_manifest(self, guide_id: str) -> GuideManifest | None:
        path = self._guide_dir(guide_id) / "manifest.json"
        if not path.exists():
            return None
        return GuideManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def load_stops(self, guide_id: str) -> list[StopStory]:
        stops_dir = self._guide_dir(guide_id) / "stops"
        if not stops_dir.exists():
            return []
        stories = []
        for path in sorted(stops_dir.glob("*.json"), key=lambda p: int(p.stem)):
            try:
                stories.append(StopStory.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("Skipping unreadable stop file %s", path, exc_info=True)
        return stories

    def list_guides(self) -> list[GuideManifest]:
        if not self.root.exists():
            return []
        manifests = []
        for manifest_path in sorted(self.root.glob("*/manifest.json")):
            try:
                manifests.append(GuideManifest.model_validate_json(manifest_path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("Skipping unreadable manifest %s", manifest_path, exc_info=True)
        return manifests

    def nearby_stops(self, lat: float, lon: float, radius_m: float) -> list[StopStory]:
        """Baked stops within radius — extra evidence for live answers in warm areas."""
        hits: list[tuple[float, StopStory]] = []
        for manifest in self.list_guides():
            if manifest.status != "ready":
                continue
            for story in self.load_stops(manifest.plan.guide_id):
                dist = haversine(lat, lon, story.stop.lat, story.stop.lon)
                if dist <= radius_m:
                    hits.append((dist, story))
        hits.sort(key=lambda pair: pair[0])
        return [story for _, story in hits]


def read_tour_plan(path: Path) -> TourPlan:
    """Load tour.json — the job's input contract."""
    return TourPlan.model_validate(json.loads(path.read_text(encoding="utf-8")))
