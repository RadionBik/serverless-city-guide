"""Shared httpx async client — lazy initialization with cleanup."""

import asyncio

import httpx

from city_guide.config import HttpConfig

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """Return the shared httpx client, creating it if needed."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                headers={"User-Agent": HttpConfig.user_agent},
                timeout=HttpConfig.timeout,
            )
    return _client


async def close_client() -> None:
    """Gracefully close the shared client."""
    global _client
    async with _lock:
        if _client is not None and not _client.is_closed:
            await _client.aclose()
            _client = None
