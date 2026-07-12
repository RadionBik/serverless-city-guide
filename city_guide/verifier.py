"""Verifier — the same model in judge mode, plus the regenerate-once loop."""

from __future__ import annotations

import logging

from city_guide.backends import LLMBackend
from city_guide.config import LlmConfig
from city_guide.prompts import Message, build_judge_messages, build_regenerate_messages
from city_guide.types import StoryResponse, VerifyReport

logger = logging.getLogger(__name__)


async def verify(story: str, evidence: str, backend: LLMBackend) -> VerifyReport:
    """Check every factual claim in the story against the gathered evidence."""
    messages = build_judge_messages(evidence, story)
    return await backend.generate(messages, VerifyReport, temperature=LlmConfig.judge_temperature)


async def verify_and_repair(
    story: str,
    story_messages: list[Message],
    evidence: str,
    backend: LLMBackend,
) -> tuple[str, VerifyReport, bool]:
    """Verify; on unsupported claims regenerate ONCE with explicit feedback, then verify again.

    Returns (final story, final report, regenerated flag). The final report always
    describes the final story — it ships with the output, failures included.
    """
    report = await verify(story, evidence, backend)
    violations = [c.claim for c in report.unsupported]
    if not violations:
        return story, report, False

    logger.info("Story failed verification (%d unsupported claims), regenerating once", len(violations))
    retry_messages = build_regenerate_messages(story_messages, story, violations)
    response = await backend.generate(retry_messages, StoryResponse, temperature=LlmConfig.story_temperature)
    final_report = await verify(response.text, evidence, backend)
    return response.text, final_report, True
