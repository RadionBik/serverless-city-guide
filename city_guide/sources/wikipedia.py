"""Wikipedia geosearch — find nearby articles with extracts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel

from city_guide.config import WikiConfig
from city_guide.http_client import get_client

logger = logging.getLogger(__name__)


class WikiArticle(BaseModel):
    """Wikipedia article with geolocation — raw fields from geosearch + page details APIs."""

    title: str = ""
    extract: str = ""
    distance: float = 0.0  # from Wikipedia geosearch API
    lat: float = 0.0
    lon: float = 0.0
    pageid: int = 0
    thumbnail_url: str | None = None


def _api_url(lang: str) -> str:
    return WikiConfig.api_template.format(lang=lang)


async def _geosearch(lat: float, lon: float, radius: int, limit: int, lang: str) -> list[dict[str, Any]]:
    """Step 1: find nearby Wikipedia articles by coordinates."""
    params = {
        "action": "query",
        "list": "geosearch",
        "gscoord": f"{lat}|{lon}",
        "gsradius": str(min(radius, WikiConfig.max_radius)),
        "gslimit": str(limit),
        "format": "json",
    }
    url = f"{_api_url(lang)}?{urlencode(params)}"

    client = await get_client()
    resp = await client.get(url)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()

    return data.get("query", {}).get("geosearch", [])  # type: ignore[no-any-return]


@dataclass
class _PageDetails:
    extract: str = ""
    thumbnail_url: str | None = None


async def _fetch_page_details(pageids: list[int], lang: str, *, with_images: bool = False) -> dict[int, _PageDetails]:
    """Step 2: fetch intro extracts (and optionally thumbnails) for a batch of page IDs."""
    if not pageids:
        return {}

    prop = "extracts|pageimages" if with_images else "extracts"
    params: dict[str, str] = {
        "action": "query",
        "pageids": "|".join(str(pid) for pid in pageids),
        "prop": prop,
        "exintro": "1",
        "explaintext": "1",
        "format": "json",
    }
    if with_images:
        params["piprop"] = "thumbnail"
        params["pithumbsize"] = str(WikiConfig.thumbnail_size)

    url = f"{_api_url(lang)}?{urlencode(params)}"

    client = await get_client()
    resp = await client.get(url)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()

    pages = data.get("query", {}).get("pages", {})
    result: dict[int, _PageDetails] = {}
    for pid, page in pages.items():
        thumbnail = page.get("thumbnail", {})
        result[int(pid)] = _PageDetails(
            extract=page.get("extract", ""),
            thumbnail_url=thumbnail.get("source") if with_images else None,
        )
    return result


async def fetch_nearby_articles(
    lat: float,
    lon: float,
    radius: int = 500,
    limit: int = 5,
    *,
    language: str,
    with_images: bool = False,
) -> list[WikiArticle]:
    """Find Wikipedia articles near given coordinates with their extracts."""
    lang = language

    try:
        geo_results = await _geosearch(lat, lon, radius, limit, lang)
    except Exception:
        logger.warning("Wikipedia geosearch failed", exc_info=True)
        return []

    if not geo_results:
        return []

    pageids = [r["pageid"] for r in geo_results]

    try:
        details = await _fetch_page_details(pageids, lang, with_images=with_images)
    except Exception:
        logger.warning("Wikipedia page details fetch failed", exc_info=True)
        details = {}

    articles = []
    for r in geo_results:
        pid = r["pageid"]
        page = details.get(pid)
        articles.append(
            WikiArticle(
                title=r["title"],
                extract=page.extract if page else "",
                distance=r.get("dist", 0.0),
                lat=r["lat"],
                lon=r["lon"],
                pageid=pid,
                thumbnail_url=page.thumbnail_url if page else None,
            )
        )

    return articles
