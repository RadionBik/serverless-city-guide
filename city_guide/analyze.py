"""Analysis layer — deterministic signals, scoring, and highlights between collect and LLM."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from city_guide.config import (
    COMMON_TYPES,
    NOTABLE_WHEN_CLUSTERED,
    SIGNAL_GROUPS,
    AnalysisCapsConfig,
    AnalysisScoringConfig,
    AnalysisThresholdsConfig,
    GeoConfig,
)
from city_guide.place import WIKIDATA_EXTRAS, DisplayData, Place
from city_guide.types import Source

logger = logging.getLogger(__name__)


@dataclass
class Highlight:
    name: str
    type: str
    distance_m: int
    score: float
    source: Source
    sources: frozenset[Source] = field(default_factory=frozenset)
    maps_url: str = ""
    wiki_url: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    fingerprint: str  # "32× Restaurant + 24× Fast Food + 15× Cafe"
    notable_types: list[str]  # max 6: "6× Tattoo", "4× Nightclub"
    signals: list[str]  # max 4 with component breakdown
    absences: list[str]  # common types that are missing
    ghost_layer: list[str]  # max 5: "Palace Cinema (50m) → now: Happy Money"
    cross_refs: list[str]  # max 4: heritage count, same architect, type clusters
    investigation: list[str]  # max 3: "WHY?"
    highlights: list[Highlight] = field(default_factory=list)  # top 15 scored

    def format_for_prompt(self) -> str:
        """Format analysis + compact highlights for LLM prompt (~400-500 tokens).

        Empty sections are omitted.
        """
        parts: list[str] = ["## Analysis"]

        parts.append(f"Fingerprint: {self.fingerprint}")

        if self.notable_types:
            parts.append(f"Notable: {', '.join(self.notable_types)}")

        if self.signals:
            parts.append(f"Signals: {'; '.join(self.signals)}")

        if self.absences:
            parts.append(f"Absent: {', '.join(self.absences)}")

        if self.ghost_layer:
            parts.append("Ghosts: " + "; ".join(self.ghost_layer))

        if self.cross_refs:
            parts.append("Cross-refs: " + "; ".join(self.cross_refs))

        if self.investigation:
            parts.append("Investigation leads: " + " | ".join(self.investigation))

        if self.highlights:
            parts.append("")
            parts.append("## Top Highlights")
            for i, h in enumerate(self.highlights, 1):
                parts.append(_format_highlight(i, h))

        return "\n".join(parts)


def _format_highlight(index: int, h: Highlight) -> str:
    """Format a single highlight line for the LLM prompt."""
    extras_str = ""
    if h.extras:
        extras_str = " (" + ", ".join(f"{k}: {v}" for k, v in h.extras.items()) + ")"
    source_label = "+".join(sorted(str(s) for s in h.sources)) if len(h.sources) > 1 else str(h.source)
    links = ""
    if h.maps_url:
        links += f" [📍map]({h.maps_url})"
    if h.wiki_url:
        links += f" [📖wiki]({h.wiki_url})"
    return f"{index}. {h.name} — {h.type}, {h.distance_m}m. {source_label}{extras_str}{links}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(data: DisplayData) -> AnalysisResult | None:
    """Pure deterministic analysis. Returns None if < AnalysisCapsConfig.min_pois POIs."""
    total_pois = len(data.places)

    if total_pois < AnalysisCapsConfig.min_pois:
        return None

    # Type counter from Overpass POIs only.
    # Wikidata item_type uses different namespace (lowercase SPARQL labels vs Title Case)
    # and risks double-counting same physical entities. Wikidata contributes via
    # ghost_layer and cross_references instead.
    types = Counter(p.type for p in data.places if Source.OVERPASS in p.sources)

    fingerprint = _build_fingerprint(types)
    notable = _find_notable_types(types)
    signals = _detect_signals(types)
    absences = _find_absences(types)

    wikidata_places = [p for p in data.places if Source.WIKIDATA in p.sources]
    overpass_places = [p for p in data.places if Source.OVERPASS in p.sources]

    ghosts = _build_ghost_layer(wikidata_places, overpass_places)
    cross_refs = _find_cross_references(wikidata_places)

    # Collect signal type sets for scoring
    signal_types: set[str] = set()
    for _name, (type_set, _thresh) in SIGNAL_GROUPS.items():
        total = sum(types.get(t, 0) for t in type_set)
        if total >= _thresh:
            signal_types |= type_set

    ghost_names: set[str] = set()
    for p in wikidata_places:
        if "former" in p.description.lower():
            ghost_names.add(p.name.lower())

    highlights = _score_highlights(data, signal_types, ghost_names)
    investigation = _generate_investigation_prompts(notable, signals, ghosts, cross_refs)

    return AnalysisResult(
        fingerprint=fingerprint,
        notable_types=notable,
        signals=signals,
        absences=absences,
        ghost_layer=ghosts,
        cross_refs=cross_refs,
        investigation=investigation,
        highlights=highlights,
    )


# ---------------------------------------------------------------------------
# Sub-functions
# ---------------------------------------------------------------------------


def _build_fingerprint(types: Counter[str]) -> str:
    """Top types with counts, e.g. '32× Restaurant + 24× Fast Food + 15× Cafe'."""
    if not types:
        return "no POIs"
    top = types.most_common(AnalysisCapsConfig.max_fingerprint_types)
    return " + ".join(f"{count}× {t}" for t, count in top)


def _find_notable_types(types: Counter[str]) -> list[str]:
    """Types interesting when clustered — check against NOTABLE_WHEN_CLUSTERED, top N."""
    results: list[tuple[int, str]] = []
    for t, min_count in NOTABLE_WHEN_CLUSTERED.items():
        actual = types.get(t, 0)
        if actual >= min_count:
            results.append((actual, t))
    results.sort(reverse=True)
    return [f"{count}× {t}" for count, t in results[: AnalysisCapsConfig.max_notable]]


def _detect_signals(types: Counter[str]) -> list[str]:
    """Signal groups with component breakdown, top N."""
    results: list[tuple[int, str]] = []
    for group_name, (type_set, threshold) in SIGNAL_GROUPS.items():
        components: list[tuple[int, str]] = []
        total = 0
        for t in type_set:
            count = types.get(t, 0)
            if count > 0:
                components.append((count, t))
                total += count
        if total >= threshold:
            components.sort(reverse=True)
            label = group_name.replace("_", " ")
            breakdown = " + ".join(f"{c}× {t}" for c, t in components)
            results.append((total, f"{label} ({total}): {breakdown}"))
    results.sort(reverse=True)
    return [s for _, s in results[: AnalysisCapsConfig.max_signals]]


def _find_absences(types: Counter[str]) -> list[str]:
    """Common types that are missing — signals unusual area character."""
    absent = [t for t in sorted(COMMON_TYPES) if types.get(t, 0) == 0]
    return absent[: AnalysisCapsConfig.max_absences]


def _build_ghost_layer(wikidata_places: list[Place], overpass_places: list[Place]) -> list[str]:
    """Former items from Wikidata matched to nearest current POI, max N."""
    if not wikidata_places:
        return []

    ghosts: list[tuple[float, str]] = []
    for w in wikidata_places:
        # Skip merged places that also have an active Overpass POI — not ghosts
        if Source.OVERPASS in w.sources:
            continue
        desc_lower = w.description.lower()
        if "former" not in desc_lower:
            continue

        # Find nearest current POI to this ghost location
        nearest_poi: str | None = None
        nearest_dist = float("inf")
        for poi in overpass_places:
            # Simple Euclidean approximation — good enough for <500m
            dlat = (w.lat - poi.lat) * GeoConfig.meters_per_degree
            dlon = (w.lon - poi.lon) * GeoConfig.meters_per_degree * AnalysisThresholdsConfig.ghost_cos_lat
            d = (dlat**2 + dlon**2) ** 0.5
            if d < nearest_dist:
                nearest_dist = d
                nearest_poi = poi.name

        dist_m = w.distance_m
        if nearest_poi and nearest_dist < AnalysisThresholdsConfig.ghost_proximity:
            ghosts.append((w.distance_m, f"{w.name} ({dist_m}m) → now: {nearest_poi}"))
        else:
            ghosts.append((w.distance_m, f"{w.name} ({dist_m}m) — {w.description}"))

    ghosts.sort()
    return [g for _, g in ghosts[: AnalysisCapsConfig.max_ghosts]]


def _heritage_cross_ref(wikidata_places: list[Place]) -> str | None:
    """Heritage count + top Grade I items."""
    heritage_items = [p for p in wikidata_places if p.extras.get("heritage")]
    if len(heritage_items) < AnalysisThresholdsConfig.heritage_min:
        return None
    grade_i = [p.name for p in heritage_items if "Grade I" in (p.extras.get("heritage") or "")]
    line = f"{len(heritage_items)} heritage-listed items"
    if grade_i:
        line += f" (Grade I: {', '.join(grade_i[: AnalysisCapsConfig.max_grade_i_display])})"
    return line


def _find_cross_references(wikidata_places: list[Place]) -> list[str]:
    """Same architect, heritage counts, interesting type clusters."""
    if not wikidata_places:
        return []

    refs: list[str] = []

    heritage = _heritage_cross_ref(wikidata_places)
    if heritage:
        refs.append(heritage)

    # Same architect appearing 2+ times
    architect_counter: Counter[str] = Counter(
        p.extras["architect"] for p in wikidata_places if p.extras.get("architect")
    )
    for arch, count in architect_counter.most_common():
        if count >= AnalysisThresholdsConfig.architect_min:
            refs.append(f"{arch} designed {count} nearby buildings")

    # Type clusters (3+ items of same wikidata type)
    type_counter: Counter[str] = Counter(
        p.type for p in wikidata_places if p.type and p.type not in AnalysisThresholdsConfig.wikidata_trivial_types
    )
    for wtype, count in type_counter.most_common():
        if count >= AnalysisThresholdsConfig.type_cluster_min:
            refs.append(f"{count}× {wtype}")

    return refs[: AnalysisCapsConfig.max_cross_refs]


def _generate_investigation_prompts(
    notable: list[str],
    signals: list[str],
    ghosts: list[str],
    cross_refs: list[str],
) -> list[str]:
    """Generate 'WHY?' investigation prompts for top findings."""
    prompts: list[str] = []

    if ghosts:
        prompts.append(f"WHY did {ghosts[0].split(' (')[0]} close? What replaced it and why?")

    if signals:
        first_signal = signals[0].split(":")[0].strip()
        prompts.append(f"WHY is there a {first_signal} here? Historical or economic reasons?")

    if notable:
        first_notable = notable[0]
        prompts.append(f"WHY so many {first_notable.split('× ')[1] if '× ' in first_notable else first_notable}s here?")

    return prompts[: AnalysisCapsConfig.max_investigation]


def _source_bonus(place: Place, signal_types: set[str], ghost_names: set[str]) -> tuple[float, bool]:
    """Calculate source-specific scoring bonus for a Place.

    Returns (bonus, is_ghost) — is_ghost is True when a Wikidata place matches
    a name in *ghost_names*.

    Uses additive ``if`` checks (not ``elif``) so a merged place gets bonuses
    from ALL its contributing sources.
    """
    bonus = 0.0
    is_ghost = False
    if Source.OVERPASS in place.sources and place.type in signal_types:
        bonus += AnalysisScoringConfig.signal
    if Source.WIKIPEDIA in place.sources:
        bonus += float(AnalysisScoringConfig.wikipedia)
    if Source.WIKIDATA in place.sources:
        bonus += sum(
            AnalysisScoringConfig.wikidata_extra
            for key, value in place.extras.items()
            if value and key in WIKIDATA_EXTRAS
        )
        if place.name.lower() in ghost_names:
            bonus += AnalysisScoringConfig.ghost
            is_ghost = True
    return bonus, is_ghost


def _score_place(place: Place, signal_types: set[str], ghost_names: set[str]) -> Highlight:
    """Score a single Place and return a Highlight."""
    bonus, is_ghost = _source_bonus(place, signal_types, ghost_names)
    extras = dict(place.extras)
    if is_ghost:
        extras["ghost"] = True
    score = _distance_score(place.distance_m) + bonus
    return Highlight(
        name=place.name,
        type=place.type,
        distance_m=place.distance_m,
        score=score,
        source=place.source,
        sources=place.sources,
        maps_url=place.maps_url,
        wiki_url=place.wiki_url,
        extras=extras,
    )


def _dedupe_and_diversify(candidates: list[Highlight]) -> list[Highlight]:
    """Deduplicate by name, sort by score, enforce diversity cap."""
    seen: dict[str, Highlight] = {}
    for h in candidates:
        key = h.name.lower().strip()
        if key not in seen or h.score > seen[key].score:
            seen[key] = h
    deduped = sorted(seen.values(), key=lambda h: (-h.score, h.distance_m))

    type_counts: Counter[str] = Counter()
    result: list[Highlight] = []
    for h in deduped:
        if type_counts[h.type] >= AnalysisCapsConfig.highlight_max_per_type:
            continue
        type_counts[h.type] += 1
        result.append(h)
        if len(result) >= AnalysisCapsConfig.highlight_top_n:
            break
    return result


def _score_highlights(
    data: DisplayData,
    signal_types: set[str],
    ghost_names: set[str],
) -> list[Highlight]:
    """Score all objects across all sources, dedupe, diversify, return top N."""
    candidates = [_score_place(p, signal_types, ghost_names) for p in data.places]
    return _dedupe_and_diversify(candidates)


def _distance_score(dist: float) -> float:
    """Score bonus based on distance."""
    if dist <= AnalysisThresholdsConfig.dist_close:
        return AnalysisScoringConfig.dist_close
    if dist <= AnalysisThresholdsConfig.dist_medium:
        return AnalysisScoringConfig.dist_medium
    return 0.0
