"""Configuration — constants and settings loaded from .env and environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Frozen dataclass singletons
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GeoConfig:
    earth_radius_meters: int = 6_371_000
    meters_per_degree: int = 111_000
    min_cos_value: float = 0.01
    distance_rounding_meters: int = 10


GeoConfig = _GeoConfig()


@dataclass(frozen=True)
class _SearchConfig:
    fetch_radius: int = 500
    default_display_radius: int = 250
    max_display_radius: int = 500
    dedup_proximity_meters: int = 30
    dedup_min_name_length: int = 5


SearchConfig = _SearchConfig()


@dataclass(frozen=True)
class _TourConfig:
    candidate_radius: int = 2500  # hard cap on the curation gather radius (scaled from route length)
    stop_radius: int = 200  # deep gather around each baked stop
    max_candidates: int = 50  # cap for the curator prompt
    min_stops: int = 3
    max_stops: int = 12
    default_length_meters: int = 2000  # circular route target; CLI --length overrides
    meters_per_stop: int = 250  # stop budget heuristic: length / this, clamped to min/max


TourConfig = _TourConfig()


@dataclass(frozen=True)
class _OverpassConfig:
    urls: tuple[str, ...] = (
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    )
    # Server-side QL timeout; the HTTP read timeout is derived from it (+5 s)
    # because public mirrors regularly need more than the global 5 s budget.
    query_timeout: int = 10


OverpassConfig = _OverpassConfig()


@dataclass(frozen=True)
class _HttpConfig:
    # Wikimedia APIs require a UA with contact info — 403 without it
    user_agent: str = "ServerlessCityGuide/1.0 (https://github.com/RadionBik/serverless-city-guide)"
    timeout: int = 5
    llm_timeout: int = 120


HttpConfig = _HttpConfig()


@dataclass(frozen=True)
class _WikiConfig:
    api_template: str = "https://{lang}.wikipedia.org/w/api.php"
    page_url_template: str = "https://{lang}.wikipedia.org/wiki/{title}"
    max_radius: int = 10000
    fetch_limit: int = 30
    thumbnail_size: int = 1200


WikiConfig = _WikiConfig()


@dataclass(frozen=True)
class _WikidataConfig:
    sparql_url: str = "https://query.wikidata.org/sparql"
    fetch_limit: int = 200
    display_limit: int = 10


WikidataConfig = _WikidataConfig()


@dataclass(frozen=True)
class _TavilyConfig:
    url: str = "https://api.tavily.com/search"
    max_results: int = 5
    timeout: int = 10
    snippet_max_chars: int = 600


TavilyConfig = _TavilyConfig()


@dataclass(frozen=True)
class _LlmConfig:
    max_tokens: int = 4096
    # Qwen3-32B default seq len (40960) needs more KV cache than one H100 80GB has
    # left after weights; 16k matches the endpoint's --max-model-len.
    max_model_len: int = 16384
    story_temperature: float = 0.8
    judge_temperature: float = 0.1
    curator_temperature: float = 0.3
    batch_concurrency: int = 4  # parallel HTTP calls in EndpointBackend batches
    regen_attempts: int = 1  # verify → regenerate rounds; each round = 2 calls per failing story


LlmConfig = _LlmConfig()


@dataclass(frozen=True)
class _LogConfig:
    level: str = "INFO"
    file: str | None = None
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 3


LogConfig = _LogConfig()


@dataclass(frozen=True)
class _AnalysisScoringConfig:
    wikipedia: int = 5
    wikidata_extra: int = 3
    ghost: int = 4
    signal: int = 2
    dist_close: int = 2
    dist_medium: int = 1


AnalysisScoringConfig = _AnalysisScoringConfig()


@dataclass(frozen=True)
class _AnalysisCapsConfig:
    min_pois: int = 3
    max_notable: int = 6
    max_signals: int = 4
    max_absences: int = 3
    max_ghosts: int = 5
    max_cross_refs: int = 4
    max_investigation: int = 3
    max_grade_i_display: int = 2
    highlight_top_n: int = 15
    highlight_max_per_type: int = 3
    max_fingerprint_types: int = 6


AnalysisCapsConfig = _AnalysisCapsConfig()


@dataclass(frozen=True)
class _AnalysisThresholdsConfig:
    dist_close: int = 100  # meters — distance bonus "close"
    dist_medium: int = 200  # meters — distance bonus "medium"
    ghost_proximity: int = 100  # meters — match ghost to current POI
    ghost_cos_lat: float = 0.65  # cos(~50°) for Euclidean lon approximation
    heritage_min: int = 2  # min heritage items for cross-ref
    architect_min: int = 2  # min appearances for architect cross-ref
    type_cluster_min: int = 3  # min items for wikidata type cluster
    fallback_distance: int = 999  # meters — default when distance is missing
    wikidata_trivial_types: tuple[str, ...] = ("building", "place")


AnalysisThresholdsConfig = _AnalysisThresholdsConfig()

# ---------------------------------------------------------------------------
# Complex module-level structures
# ---------------------------------------------------------------------------

NOTABLE_WHEN_CLUSTERED: dict[str, int] = {
    # --- entertainment_district ---
    "Cinema": 2,
    "Theatre": 2,
    "Nightclub": 2,
    "Music Venue": 2,
    "Concert Hall": 2,
    "Events Venue": 3,
    "Casino": 2,
    # --- creative_district ---
    "Tattoo": 2,
    "Gallery": 3,
    "Art": 2,
    "Artwork": 8,
    "Studio": 3,
    "Arts Centre": 2,
    # --- market_district (Bakery is COMMON — only specialist food types are notable) ---
    "Butcher": 3,
    "Greengrocer": 3,
    "Seafood": 3,
    "Marketplace": 2,
    "Cheese": 2,
    "Deli": 3,
    # --- nightlife_district (Bar, Pub are COMMON — only Hookah Lounge is notable) ---
    "Hookah Lounge": 2,
    # --- red_light_district ---
    "Stripclub": 2,
    "Erotic": 2,
    "Love Hotel": 2,
    "Brothel": 2,
    # --- vintage_quarter ---
    "Antiques": 2,
    "Second Hand": 3,
    "Books": 2,
    "Charity": 4,
    # --- textile_cluster (Clothes is COMMON) ---
    "Fabric": 2,
    "Tailor": 2,
    # --- deprivation_signals (Fast Food is COMMON) ---
    "Bookmaker": 2,
    "Pawnbroker": 2,
    "Money Transfer": 3,
    # --- waterfront (Swimming Area only matters as group sum) ---
    "Ferry Terminal": 1,
    "Marina": 1,
    "Boat Rental": 2,
    # --- standalone (no signal group) ---
    "Wine": 3,
    "Memorial": 3,
    "Museum": 2,
    "Hostel": 2,
    "Hotel": 4,
    "Monastery": 1,
    "Anchor": 1,
    "Watchmaker": 1,
    "Cannon": 1,
}

SIGNAL_GROUPS: dict[str, tuple[frozenset[str], int]] = {
    "entertainment_district": (
        frozenset({"Cinema", "Theatre", "Nightclub", "Music Venue", "Concert Hall", "Events Venue", "Casino"}),
        3,
    ),
    "creative_district": (frozenset({"Tattoo", "Gallery", "Art", "Artwork", "Studio", "Arts Centre"}), 4),
    "market_district": (frozenset({"Butcher", "Greengrocer", "Seafood", "Marketplace", "Cheese", "Deli", "Bakery"}), 4),
    "nightlife_district": (frozenset({"Bar", "Nightclub", "Pub", "Hookah Lounge"}), 6),
    "red_light_district": (frozenset({"Stripclub", "Erotic", "Love Hotel", "Brothel"}), 3),
    "vintage_quarter": (frozenset({"Antiques", "Second Hand", "Books", "Charity"}), 4),
    "textile_cluster": (frozenset({"Fabric", "Tailor"}), 3),
    "food_hub": (frozenset({"Restaurant", "Fast Food", "Cafe", "Bakery", "Seafood", "Ice Cream"}), 20),
    "multi_faith": (frozenset({"Place Of Worship"}), 5),
    "waterfront": (frozenset({"Ferry Terminal", "Marina", "Boat Rental", "Swimming Area"}), 2),
    "deprivation_signals": (frozenset({"Bookmaker", "Pawnbroker", "Money Transfer"}), 4),
}

COMMON_TYPES: frozenset[str] = frozenset(
    {
        "Restaurant",
        "Cafe",
        "Pub",
        "Bar",
        "Fast Food",
        "Clothes",
        "Convenience",
    }
)

# --- Consistency guard: catch drift between SIGNAL_GROUPS and NOTABLE_WHEN_CLUSTERED ---
_SIGNAL_ONLY_TYPES: frozenset[str] = COMMON_TYPES | frozenset(
    {"Bakery", "Ice Cream", "Place Of Worship", "Swimming Area"}
)
_sg_all_types = frozenset(t for types, _ in SIGNAL_GROUPS.values() for t in types)
_unexpected = (_sg_all_types - frozenset(NOTABLE_WHEN_CLUSTERED)) - _SIGNAL_ONLY_TYPES
assert not _unexpected, f"Types in SIGNAL_GROUPS but not in NOTABLE or _SIGNAL_ONLY_TYPES: {_unexpected}"

# ---------------------------------------------------------------------------
# Environment-variable helpers
# ---------------------------------------------------------------------------


def get_log_level() -> str:
    """Return log level, overridable via LOG_LEVEL env var."""
    return os.environ.get("LOG_LEVEL", LogConfig.level)


def get_log_file() -> str | None:
    """Return log file path, overridable via LOG_FILE env var."""
    return os.environ.get("LOG_FILE", LogConfig.file)


# Dev fallback: Nebius Token Factory (hosted, per-token) when no endpoint is deployed.
TOKEN_FACTORY_URL = "https://api.tokenfactory.nebius.com/v1"
# ONE model everywhere — Token Factory, endpoint, and job must tell the same story.
# Qwen3-32B: hosted on Token Factory AND fits one H100 80 GB (bf16 ~65 GB + KV cache) for vLLM.
DEFAULT_MODEL = "Qwen/Qwen3-32B"


def using_token_factory() -> bool:
    """True when no LLM_BASE_URL is set — requests go to Token Factory."""
    return not os.environ.get("LLM_BASE_URL")


def get_llm_base_url() -> str:
    """OpenAI-compatible base URL — the deployed endpoint, or Token Factory as dev fallback."""
    return (os.environ.get("LLM_BASE_URL") or TOKEN_FACTORY_URL).rstrip("/")


def get_llm_api_key() -> str:
    """Bearer token — LLM_API_KEY, or NEBIUS_API_KEY (Token Factory); empty = no auth header."""
    return os.environ.get("LLM_API_KEY") or os.environ.get("NEBIUS_API_KEY", "")


def get_llm_model() -> str:
    """Model id — the same model on every surface."""
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL)


def get_tavily_api_key() -> str | None:
    """Tavily API key, or None — the web-search source is skipped without it."""
    return os.environ.get("TAVILY_API_KEY") or None


def get_store_dir() -> Path:
    """Guide store directory — local dir, or the bucket mount inside the job."""
    return Path(os.environ.get("GUIDE_STORE_DIR", "guides"))
