"""Shared enums, theme definitions, and LLM response / store schemas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Language(StrEnum):
    EN = "en"
    ES = "es"
    RU = "ru"


class OutputMode(StrEnum):
    RAW = "raw"
    PROMPT = "prompt"
    STORY = "story"


class Source(StrEnum):
    OVERPASS = "overpass"
    WIKIPEDIA = "wikipedia"
    WIKIDATA = "wikidata"
    TAVILY = "tavily"


class Theme(StrEnum):
    DEFAULT = "default"
    HISTORY = "history"
    FOOD = "food"
    NIGHTLIFE = "nightlife"


class Verbosity(StrEnum):
    SHORT = "short"
    FULL = "full"


@dataclass(frozen=True)
class ThemeConfig:
    prompt_hint: str
    wiki_limit: int = 5
    overpass_tags: tuple[str, ...] | None = None


THEME_CONFIGS: dict[Theme, ThemeConfig] = {
    Theme.DEFAULT: ThemeConfig(prompt_hint=""),
    Theme.HISTORY: ThemeConfig(
        overpass_tags=("tourism", "historic"),
        wiki_limit=8,
        prompt_hint=(
            "Focus ONLY on HISTORY: ancient origins, forgotten events, architectural evolution, "
            "historical scandals, and how the past shaped this place. "
            "SKIP places with no historical significance (bowling, chain restaurants, generic shops). "
            "Dig into the layers of time — what happened here centuries ago?"
        ),
    ),
    Theme.FOOD: ThemeConfig(
        overpass_tags=("amenity", "shop"),
        prompt_hint=(
            "Focus ONLY on FOOD & DRINK places: restaurants, cafes, bakeries, street food, markets. "
            "SKIP any non-food POIs (parks, mosques, bowling, shops) — they don't exist for this story. "
            "Be a passionate food critic: legendary dishes, hidden gems, chef stories, "
            "food scandals, and the weirdest menu items."
        ),
    ),
    Theme.NIGHTLIFE: ThemeConfig(
        overpass_tags=("amenity",),
        prompt_hint=(
            "Focus ONLY on NIGHTLIFE: bars, clubs, pubs, live music, late-night culture, "
            "legendary parties, bouncer stories, and the vibe after dark. "
            "SKIP daytime-only places (cafes, shops, offices) — only what matters after dark."
        ),
    ),
}

DEFAULT_THEME = Theme.DEFAULT
DEFAULT_LANGUAGE = Language.EN
DEFAULT_VERBOSITY = Verbosity.FULL
WIKI_LANGUAGE = Language.EN

DEFAULT_INTEREST = "the most surprising, story-rich mix of places"

# ---------------------------------------------------------------------------
# LLM response schemas (strict JSON output)
# ---------------------------------------------------------------------------


class StoryResponse(BaseModel):
    """Storyteller output — one narrative text."""

    model_config = ConfigDict(extra="forbid")

    text: str


class CuratedStop(BaseModel):
    """One curator pick — by candidate ID, so a place can't be invented."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: int
    reason: str


class CuratorResponse(BaseModel):
    """Curator output — picked stops plus an honest note when the interest is poorly served."""

    model_config = ConfigDict(extra="forbid")

    stops: list[CuratedStop] = []
    note: str = ""


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"


class Claim(BaseModel):
    """One checked claim from the judge."""

    model_config = ConfigDict(extra="forbid")

    claim: str
    status: ClaimStatus
    evidence: str = ""


class VerifyReport(BaseModel):
    """Judge output — every factual claim in the story, checked against evidence."""

    model_config = ConfigDict(extra="forbid")

    claims: list[Claim] = []

    @property
    def unsupported(self) -> list[Claim]:
        return [c for c in self.claims if c.status == ClaimStatus.UNSUPPORTED]

    def summary(self) -> str:
        total = len(self.claims)
        bad = len(self.unsupported)
        uncertain = sum(1 for c in self.claims if c.status == ClaimStatus.UNCERTAIN)
        return f"{total} claims: {total - bad - uncertain} supported, {uncertain} uncertain, {bad} unsupported"


# ---------------------------------------------------------------------------
# Tour / guide store schemas
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    """One curation candidate — a place with an ID the curator picks by."""

    id: int
    name: str
    kind: str = ""
    dist_m: int = 0
    hint: str = ""  # short wiki/wikidata hint, keeps the curator prompt small
    lat: float
    lon: float


class TourStop(BaseModel):
    """One routed stop — leg fields describe the walk FROM the previous point."""

    name: str
    lat: float
    lon: float
    reason: str = ""
    leg_distance_m: int = 0
    leg_bearing_deg: int = 0


class TourPlan(BaseModel):
    """Everything the job needs — written as tour.json at submit time."""

    guide_id: str
    origin_lat: float
    origin_lon: float
    interest: str = DEFAULT_INTEREST
    language: Language = Language.EN
    note: str = ""
    stops: list[TourStop] = []
    total_length_m: int = 0
    maps_url: str = ""


class StopStory(BaseModel):
    """One baked stop — story plus its verification report."""

    stop: TourStop
    story: str
    verify: VerifyReport | None = None


class GuideManifest(BaseModel):
    """Guide store manifest — plan, status, and the tour intro/outro."""

    plan: TourPlan
    status: str = "baking"  # baking | ready | failed
    intro: str = ""
    outro: str = ""
    created_at: str = ""
