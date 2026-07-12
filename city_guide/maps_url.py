"""Google Maps / Wikipedia URL builders for places."""

from urllib.parse import quote, quote_plus

from city_guide.config import WikiConfig
from city_guide.types import WIKI_LANGUAGE

MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1"
MAPS_BASE_URL = "https://www.google.com/maps/search"
MAPS_ZOOM = 17


def build_maps_url(
    name: str,
    lat: float | None = None,
    lon: float | None = None,
    address: str = "",
) -> str:
    """Build a Google Maps URL for a place.

    Priority: name+address+coords > coords-only > name-only search.
    address: street address (e.g. "9A Blackstock Road") — appended to name for
        better search accuracy.
    When only coordinates are available, links to the map point without a name search.
    """
    z = MAPS_ZOOM
    if lat is not None and lon is not None:
        if name.strip() and address.strip():
            query = quote_plus(f"{name}, {address}")
            return f"{MAPS_BASE_URL}/{query}/@{lat},{lon},{z}z/"
        if name.strip():
            return f"{MAPS_BASE_URL}/{quote_plus(name)}/@{lat},{lon},{z}z/"
        return f"{MAPS_BASE_URL}/@{lat},{lon},{z}z/"
    return f"{MAPS_SEARCH_URL}&query={quote_plus(name)}"


def build_wiki_url(title: str, language: str = "") -> str:
    """Build a Wikipedia article URL from title and language.

    Uses WikiConfig.page_url_template. Falls back to WIKI_LANGUAGE if not specified.
    Spaces are replaced with underscores per Wikipedia convention.
    """
    lang = language or WIKI_LANGUAGE
    encoded_title = quote(title.replace(" ", "_"), safe="/:@!$&'*+,;=-._~")
    return WikiConfig.page_url_template.format(lang=lang, title=encoded_title)
