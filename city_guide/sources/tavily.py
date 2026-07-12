"""Tavily web search — templated queries, snippets + URLs join the evidence corpus."""

import logging

from pydantic import BaseModel

from city_guide.config import TavilyConfig, get_tavily_api_key
from city_guide.http_client import get_client

logger = logging.getLogger(__name__)


class TavilySnippet(BaseModel):
    """One web-search result — snippet text plus its source URL."""

    title: str
    url: str
    content: str


async def search(query: str, *, max_results: int | None = None) -> list[TavilySnippet]:
    """Run one Tavily search. Returns [] when no API key is set or on any error."""
    api_key = get_tavily_api_key()
    if not api_key:
        return []

    client = await get_client()
    try:
        resp = await client.post(
            TavilyConfig.url,
            json={
                "query": query,
                "max_results": max_results or TavilyConfig.max_results,
                "search_depth": "basic",
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TavilyConfig.timeout,
        )
        resp.raise_for_status()
    except Exception:
        logger.warning("Tavily search failed for %r", query, exc_info=True)
        return []

    results = resp.json().get("results", [])
    snippets = []
    for item in results:
        content = (item.get("content") or "")[: TavilyConfig.snippet_max_chars]
        if not content:
            continue
        snippets.append(TavilySnippet(title=item.get("title", ""), url=item.get("url", ""), content=content))
    return snippets
