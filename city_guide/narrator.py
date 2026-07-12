"""Narrator — build evidence text and generate stories through a backend."""

from __future__ import annotations

import json

from city_guide.analyze import AnalysisResult
from city_guide.backends import LLMBackend
from city_guide.config import LlmConfig
from city_guide.place import DisplayData
from city_guide.prompts import Message, build_story_messages, build_storyteller_system
from city_guide.sources.tavily import TavilySnippet
from city_guide.types import Language, StopStory, StoryResponse, Theme, Verbosity


def build_evidence(
    data: DisplayData,
    analysis: AnalysisResult | None,
    tavily_snippets: list[TavilySnippet] | None = None,
    baked_stops: list[StopStory] | None = None,
) -> str:
    """Assemble the full evidence corpus — the LLM user message AND the judge's ground truth."""
    parts: list[str] = []
    if analysis is not None:
        parts.append(analysis.format_for_prompt())
    else:
        parts.append(json.dumps(data.to_display_dict(), ensure_ascii=False, indent=2))

    if tavily_snippets:
        lines = [f"- {s.title} ({s.url}): {s.content}" for s in tavily_snippets]
        parts.append("## Web context (cite URLs when used)\n" + "\n".join(lines))

    if baked_stops:
        lines = [f"### {s.stop.name}\n{s.story}" for s in baked_stops]
        parts.append("## Pre-baked local stories (verified earlier — reuse freely)\n" + "\n\n".join(lines))

    return "\n\n".join(parts)


async def narrate(
    evidence: str,
    backend: LLMBackend,
    *,
    language: Language = Language.EN,
    theme: Theme = Theme.DEFAULT,
    verbosity: Verbosity = Verbosity.FULL,
) -> tuple[str, list[Message]]:
    """One live story. Returns (text, messages) — messages are kept for the regenerate path."""
    system = build_storyteller_system(language, theme=theme, verbosity=verbosity)
    messages = build_story_messages(system, evidence)
    response = await backend.generate(messages, StoryResponse, temperature=LlmConfig.story_temperature)
    return response.text, messages
