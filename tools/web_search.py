"""
Web search tool -- general-purpose search for time-sensitive information
(opening hours, events, prices, recent closures) that the guide store
won't have.

Not yet implemented against a real provider (see WEB_SEARCH_API_KEY /
WEB_SEARCH_PROVIDER in .env). This defines the contract `gather` calls
against, so the graph can be wired and tested before a provider is chosen.
"""

from __future__ import annotations


async def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Run a web search and return normalized results.

    Expected return shape once implemented:
        [
            {"title": "...", "url": "...", "snippet": "..."},
            ...
        ]
    """
    raise NotImplementedError("web_search: no provider wired up yet")