"""LLM backends — same prompts and schemas, two ways to make tokens.

EndpointBackend: httpx → vLLM serverless endpoint (OpenAI-compatible), used by the live CLI.
OfflineBackend: in-process vllm.LLM with guided JSON decoding, used by the pre-bake job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from city_guide.config import (
    TOKEN_FACTORY_URL,
    HttpConfig,
    LlmConfig,
    get_llm_api_key,
    get_llm_base_url,
    get_llm_model,
)
from city_guide.http_client import get_client
from city_guide.prompts import Message

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMBackend(Protocol):
    async def generate(self, messages: list[Message], schema: type[T], *, temperature: float) -> T: ...

    async def generate_batch(self, batches: list[list[Message]], schema: type[T], *, temperature: float) -> list[T]: ...


def _openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON schema fully OpenAI-strict-compatible.

    Strict mode requires every object to list ALL properties in `required`.
    Recurses into $defs and nested items.
    """
    if schema.get("type") == "object" and "properties" in schema:
        schema["required"] = list(schema["properties"])
    for key in ("properties", "$defs"):
        for value in schema.get(key, {}).values():
            if isinstance(value, dict):
                _openai_strict_schema(value)
    if "items" in schema and isinstance(schema["items"], dict):
        _openai_strict_schema(schema["items"])
    return schema


def _repair_truncated_json(content: str) -> str:
    """Attempt to repair JSON truncated by max_tokens (finish_reason=length).

    Strategy: strip trailing repetition (repeated \\n, repeated chars), close any
    open JSON string, and append missing closing braces/brackets.
    """
    cleaned = re.sub(r"(\\n){5,}", "", content)
    cleaned = re.sub(r"(.)\1{20,}", "", cleaned)

    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    in_string = False
    for i, char in enumerate(cleaned):
        if char == "\\" and in_string:
            continue
        if i > 0 and cleaned[i - 1] == "\\":
            continue
        if char == '"':
            in_string = not in_string
    if in_string:
        cleaned = cleaned + '"'

    for suffix in ('"}', "}", "]}", '"}]}'):
        try:
            json.loads(cleaned + suffix)
            logger.warning("Repaired truncated JSON with suffix: %s", suffix)
            return cleaned + suffix
        except json.JSONDecodeError:
            continue

    logger.error("Failed to repair truncated JSON (len=%d)", len(content))
    return content


def _validate[T: BaseModel](content: str, schema: type[T], finish_reason: str) -> T:
    if finish_reason == "length":
        logger.warning("LLM response truncated (finish_reason=length, len=%d), attempting repair", len(content))
        content = _repair_truncated_json(content)
    try:
        return schema.model_validate_json(content)
    except (ValidationError, json.JSONDecodeError):
        logger.error("LLM response parse failed (finish=%s):\n%.500s", finish_reason, content)
        raise


class EndpointBackend:
    """OpenAI-compatible chat completions against the vLLM serverless endpoint."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or get_llm_base_url()).rstrip("/")
        self.api_key = api_key if api_key is not None else get_llm_api_key()
        self.model = model or get_llm_model()
        if self.base_url == TOKEN_FACTORY_URL:
            logger.info("No endpoint configured — using Nebius Token Factory (dev fallback), model=%s", self.model)

    async def generate(self, messages: list[Message], schema: type[T], *, temperature: float) -> T:
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": LlmConfig.max_tokens,
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": _openai_strict_schema(schema.model_json_schema()),
                },
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        client = await get_client()
        resp = await client.post(
            f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=HttpConfig.llm_timeout
        )
        if resp.status_code != 200:
            logger.error("LLM HTTP %d: %.500s", resp.status_code, resp.text)
            resp.raise_for_status()

        data = resp.json()
        choices = data.get("choices")
        if not choices:
            raise ValueError(f"LLM response has no choices: {json.dumps(data)[:500]}")
        content: str = choices[0].get("message", {}).get("content", "")
        if not content:
            raise ValueError("LLM response content is empty")
        return _validate(content, schema, choices[0].get("finish_reason", "stop"))

    async def generate_batch(self, batches: list[list[Message]], schema: type[T], *, temperature: float) -> list[T]:
        semaphore = asyncio.Semaphore(LlmConfig.batch_concurrency)

        async def _one(messages: list[Message]) -> T:
            async with semaphore:
                return await self.generate(messages, schema, temperature=temperature)

        return list(await asyncio.gather(*(_one(m) for m in batches)))


class OfflineBackend:
    """In-process vLLM with guided JSON decoding — true batching for the pre-bake job.

    Imports vllm lazily: it only exists inside the job container (or with the
    `job` extra installed).
    """

    def __init__(self, model: str | None = None) -> None:
        from vllm import LLM  # noqa: PLC0415 — heavyweight, job-only import

        self.model = model or get_llm_model()
        self.llm = LLM(model=self.model)

    def _generate_sync(self, batches: list[list[Message]], schema: type[T], temperature: float) -> list[T]:
        from vllm import SamplingParams
        from vllm.sampling_params import GuidedDecodingParams

        params = SamplingParams(
            max_tokens=LlmConfig.max_tokens,
            temperature=temperature,
            guided_decoding=GuidedDecodingParams(json=_openai_strict_schema(schema.model_json_schema())),
        )
        outputs = self.llm.chat(batches, params)
        results: list[T] = []
        for out in outputs:
            text = out.outputs[0].text
            finish = out.outputs[0].finish_reason or "stop"
            results.append(_validate(text, schema, finish))
        return results

    async def generate(self, messages: list[Message], schema: type[T], *, temperature: float) -> T:
        return (await self.generate_batch([messages], schema, temperature=temperature))[0]

    async def generate_batch(self, batches: list[list[Message]], schema: type[T], *, temperature: float) -> list[T]:
        # Blocking on purpose: the job is a linear batch script, not a server.
        return self._generate_sync(batches, schema, temperature)
