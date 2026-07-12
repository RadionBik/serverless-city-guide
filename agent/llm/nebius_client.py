"""
Thin wrapper around the Nebius AI Studio inference API (OpenAI-compatible).

All LLM calls in the agent -- planner, narrate (storyteller), verify, and the
future memory extractor -- should go through this module. It is the single
place that knows about:
  - which Nebius model to use for which role (storyteller vs utility)
  - how to authenticate
  - how to stream vs. get a single completion
  - basic error handling/logging

Usage:
    from llm.nebius_client import get_nebius_client

    client = get_nebius_client()

    # single-shot completion (planner / verify / memory extractor)
    text = await client.complete(
        messages=[{"role": "user", "content": "Hello"}],
        role="utility",
    )

    # streaming completion (narrate -- forward tokens to client as they arrive)
    async for delta in client.stream(
        messages=[{"role": "user", "content": "Tell me about this place"}],
        role="storyteller",
    ):
        print(delta, end="", flush=True)
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Iterable
from typing import Literal

from dotenv import load_dotenv
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI

load_dotenv()

logger = logging.getLogger(__name__)

Role = Literal["storyteller", "utility"]

DEFAULT_BASE_URL = "https://api.studio.nebius.com/v1"
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 2


class NebiusConfigError(RuntimeError):
    """Raised when required Nebius configuration is missing."""


class NebiusClient:
    """
    Async client for calling Nebius-hosted models.

    Two logical "roles" are exposed so callers don't need to know model
    names:
      - "storyteller": the single heavy generation model used by the
        narrate node. Optimized for quality; this is the model the whole
        pipeline is built around.
      - "utility": a cheaper/faster model used by planner, verify, and the
        (future) memory extractor. Falls back to the storyteller model if
        no utility model is configured, so the app runs fine with just one
        model to start.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        storyteller_model: str | None = None,
        utility_model: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.api_key = api_key or os.getenv("NEBIUS_API_KEY")
        if not self.api_key:
            raise NebiusConfigError("NEBIUS_API_KEY is not set. Add it to your .env file.")

        self.base_url = base_url or os.getenv("NEBIUS_BASE_URL", DEFAULT_BASE_URL)

        self.storyteller_model = storyteller_model or os.getenv("NEBIUS_STORYTELLER_MODEL")
        if not self.storyteller_model:
            raise NebiusConfigError("NEBIUS_STORYTELLER_MODEL is not set. Add it to your .env file.")

        # Utility model is optional -- fall back to the storyteller model
        # if unset, so planner/verify/memory-extraction work out of the box.
        self.utility_model = utility_model or os.getenv("NEBIUS_UTILITY_MODEL") or self.storyteller_model

        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout_s,
            max_retries=max_retries,
        )

    def _model_for(self, role: Role) -> str:
        return self.storyteller_model if role == "storyteller" else self.utility_model

    async def complete(
        self,
        messages: Iterable[dict],
        role: Role = "storyteller",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs,
    ) -> str:
        """
        Single-shot (non-streaming) chat completion. Returns the text of the
        first choice.

        Pass `response_format={"type": "json_object"}` for nodes that need
        structured output (planner's tool-selection, verify's claim list,
        the memory extractor's preference deltas), provided the underlying
        Nebius model supports it.
        """
        model = self._model_for(role)
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                **kwargs,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            logger.error("Nebius connection error (model=%s): %s", model, exc)
            raise
        except APIError as exc:
            logger.error("Nebius API error (model=%s): %s", model, exc)
            raise

        return response.choices[0].message.content or ""

    async def stream(
        self,
        messages: Iterable[dict],
        role: Role = "storyteller",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """
        Streaming chat completion. Yields text deltas as they arrive.

        Intended for the narrate node so tokens can be forwarded to the
        client as soon as they're generated, instead of waiting for the
        full response -- this is what makes the agent feel "real-time".
        """
        model = self._model_for(role)
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except (APIConnectionError, APITimeoutError) as exc:
            logger.error("Nebius streaming connection error (model=%s): %s", model, exc)
            raise
        except APIError as exc:
            logger.error("Nebius streaming API error (model=%s): %s", model, exc)
            raise

    async def close(self) -> None:
        """Release the underlying HTTP client / connection pool."""
        await self._client.close()

    async def __aenter__(self) -> NebiusClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()


_default_client: NebiusClient | None = None


def get_nebius_client() -> NebiusClient:
    """
    Module-level singleton accessor so graph nodes share one client (and one
    underlying connection pool) instead of each constructing their own.
    """
    global _default_client
    if _default_client is None:
        _default_client = NebiusClient()
    return _default_client
