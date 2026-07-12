"""Verifier — the same model in judge mode, the regenerate loop, and the final strip.

Flow: verify → regenerate with feedback (LlmConfig.regen_attempts rounds) →
claims still unsupported → their sentences are deterministically removed from
the story. The report ships with the story and marks what was removed.
"""

from __future__ import annotations

import logging
import re

from city_guide.backends import LLMBackend
from city_guide.config import LlmConfig
from city_guide.prompts import Message, build_judge_messages, build_regenerate_messages
from city_guide.types import StoryResponse, VerifyReport

logger = logging.getLogger(__name__)

_REMOVED_MARK = "[removed from story]"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_MIN_WORD_LEN = 4
_MATCH_THRESHOLD = 0.5  # fraction of claim words that must appear in a sentence to strip it


async def verify(story: str, evidence: str, backend: LLMBackend) -> VerifyReport:
    """Check every factual claim in the story against the gathered evidence."""
    messages = build_judge_messages(evidence, story)
    return await backend.generate(messages, VerifyReport, temperature=LlmConfig.judge_temperature)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w']+", text.lower()) if len(w) >= _MIN_WORD_LEN}


def strip_unsupported(story: str, report: VerifyReport) -> tuple[str, int]:
    """Remove sentences carrying still-unsupported claims. Pure, deterministic.

    Matching is word-overlap based (the judge paraphrases claims, so exact
    substring search would miss). A claim with no confident sentence match is
    left in place — never strip on a guess. Returns (story, sentences removed);
    removed claims get a marker appended to their evidence field.
    """
    paragraphs = story.split("\n")
    removed = 0
    for claim in report.unsupported:
        claim_words = _words(claim.claim)
        if not claim_words:
            continue
        best: tuple[float, int, int] | None = None  # (score, paragraph idx, sentence idx)
        split_paragraphs = [_SENTENCE_SPLIT.split(p) for p in paragraphs]
        for pi, sentences in enumerate(split_paragraphs):
            for si, sentence in enumerate(sentences):
                score = len(claim_words & _words(sentence)) / len(claim_words)
                if best is None or score > best[0]:
                    best = (score, pi, si)
        if best is None or best[0] < _MATCH_THRESHOLD:
            continue
        _, pi, si = best
        sentences = split_paragraphs[pi]
        del sentences[si]
        paragraphs[pi] = " ".join(s for s in sentences if s.strip())
        removed += 1
        claim.evidence = f"{claim.evidence} {_REMOVED_MARK}".strip()

    if removed:
        story = "\n".join(p for i, p in enumerate(paragraphs) if p.strip() or not story.split("\n")[i].strip())
    return story, removed


async def verify_and_repair(
    story: str,
    story_messages: list[Message],
    evidence: str,
    backend: LLMBackend,
) -> tuple[str, VerifyReport, bool]:
    """Verify; regenerate with feedback while claims stay unsupported; then strip.

    Regenerate rounds are capped by LlmConfig.regen_attempts (each round = 2 extra
    calls). Claims still unsupported after the last round have their sentences
    removed deterministically. Returns (final story, final report, regenerated flag).
    """
    report = await verify(story, evidence, backend)
    regenerated = False
    for _ in range(LlmConfig.regen_attempts):
        violations = [c.claim for c in report.unsupported]
        if not violations:
            break
        logger.info("Story failed verification (%d unsupported claims), regenerating", len(violations))
        regenerated = True
        retry_messages = build_regenerate_messages(story_messages, story, violations)
        response = await backend.generate(retry_messages, StoryResponse, temperature=LlmConfig.story_temperature)
        story = response.text
        report = await verify(story, evidence, backend)

    if report.unsupported:
        story, removed = strip_unsupported(story, report)
        if removed:
            logger.info("Removed %d ungrounded sentences after failed regeneration", removed)
    return story, report, regenerated
