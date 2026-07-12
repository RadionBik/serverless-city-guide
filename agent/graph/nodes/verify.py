"""
Verify node -- checks the narration against the evidence bundle before it
goes to the user, and decides whether to retry gathering or accept the
reply.

Two tiers, deliberately weighted toward the cheap one:

  Tier 1 (deterministic, always runs): every [geo]/[guideN]/[webN] tag the
  narration actually cites is checked against which tags the evidence
  bundle could legitimately support. A citation to a source that failed,
  wasn't requested, or doesn't exist (e.g. the model wrote "[guide3]" when
  only one guide item was returned) is a clear-cut hallucinated citation --
  no LLM needed to catch this.

  Tier 2 (heuristic + optional LLM judge): sentences that look like they're
  stating a specific fact (a year, price, time, opening status) but carry
  no citation tag at all are flagged as risky. If the evidence bundle has
  at least one successful source, a single batched call to the utility
  model checks whether those specific sentences are actually grounded. If
  the evidence bundle has nothing successful in it at all, there's nothing
  for such a claim to be grounded in, so it's marked unsupported directly
  without spending a call on it.

The result feeds a bounded retry: on an unsupported claim, route back to
`gather` once (see MAX_VERIFY_RETRIES) before accepting the reply as-is.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from llm.nebius_client import get_nebius_client
from llm.prompts.citation import TAG_RE as _TAG_RE
from llm.prompts.citation import format_evidence as _format_evidence
from llm.prompts.verify_prompt import SYSTEM_PROMPT, build_user_prompt

from graph.state import AgentState, VerifyDecision

logger = logging.getLogger(__name__)

MAX_VERIFY_RETRIES = 1

# Heuristics for "this sentence looks like a specific, checkable claim":
# a four-digit year, a currency amount, a clock time, or opening/closing
# language paired with a digit (hours, days, etc.).
_RISKY_PATTERNS = [
    re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b"),  # years
    re.compile(r"[£$€]\s?\d"),  # currency
    re.compile(r"\b\d{1,2}(:\d{2})?\s?(am|pm|AM|PM)\b"),  # clock time
    re.compile(r"\b(open|close[ds]?|hours?)\b.{0,15}\d", re.I),  # hours-ish
]

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _extract_used_tags(narration: str) -> set[str]:
    return set(_TAG_RE.findall(narration))


def _valid_tags_from_evidence(evidence: dict | None) -> set[str]:
    """Which tags the narration would be entitled to cite, given what was
    actually and successfully gathered."""
    if not evidence:
        return set()

    valid: set[str] = set()

    geo = evidence.get("reverse_geocode")
    if geo and geo.get("ok"):
        valid.add("geo")

    guide = evidence.get("guide_store")
    if guide and guide.get("ok") and guide.get("data"):
        valid.update(f"guide{i}" for i in range(1, len(guide["data"]) + 1))

    web = evidence.get("web_search")
    if web and web.get("ok") and web.get("data"):
        valid.update(f"web{i}" for i in range(1, len(web["data"]) + 1))

    return valid


def _has_successful_evidence(evidence: dict | None) -> bool:
    if not evidence:
        return False
    return any(source and source.get("ok") and source.get("data") for source in evidence.values())


def _split_sentences(narration: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(narration) if s.strip()]


def _is_risky_untagged(sentence: str) -> bool:
    if _TAG_RE.search(sentence):
        return False  # already tagged -- tier 1 covers this
    return any(pattern.search(sentence) for pattern in _RISKY_PATTERNS)


async def _judge_risky_sentences(evidence: dict | None, sentences: list[str]) -> list[dict]:
    """
    Batched LLM judge for untagged-but-risky sentences. Returns a list of
    {"claim": sentence, "supported": bool | None, "reason": str}. A `None`
    supported value means "inconclusive" (judge call/parse failed) --
    deliberately not treated as a failure, to avoid retry storms caused by
    the judge itself being flaky rather than the narration being wrong.
    """
    client = get_nebius_client()
    evidence_block = _format_evidence(evidence)

    try:
        raw = await client.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(evidence_block, sentences)},
            ],
            role="utility",
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        results = {r["index"]: bool(r["grounded"]) for r in data.get("results", [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify: judge call/parse failed (%s); marking inconclusive", exc)
        return [{"claim": s, "supported": None, "reason": "judge_unavailable"} for s in sentences]

    out = []
    for i, s in enumerate(sentences, start=1):
        if i in results:
            supported = results[i]
            out.append(
                {
                    "claim": s,
                    "supported": supported,
                    "reason": "judged_grounded" if supported else "judged_ungrounded",
                }
            )
        else:
            out.append({"claim": s, "supported": None, "reason": "judge_incomplete"})
    return out


async def run(state: AgentState) -> dict[str, Any]:
    """LangGraph node entry point."""
    if state.get("error"):
        return {}

    narration = state.get("narration")
    if not narration:
        return {"error": "verify: no narration in state -- narrate must run first."}

    evidence = state.get("evidence")
    retry_count = state.get("retry_count", 0)

    # ---- Tier 1: citation validity (deterministic) ----
    used_tags = _extract_used_tags(narration)
    valid_tags = _valid_tags_from_evidence(evidence)
    invalid_tags = used_tags - valid_tags

    verification: list[dict] = [
        {
            "claim": f"[{tag}]",
            "supported": tag in valid_tags,
            "reason": "cited" if tag in valid_tags else "cites_unavailable_source",
        }
        for tag in used_tags
    ]

    # ---- Tier 2: risky untagged sentences ----
    sentences = _split_sentences(narration)
    risky = [s for s in sentences if _is_risky_untagged(s)]

    if risky:
        if _has_successful_evidence(evidence):
            verification.extend(await _judge_risky_sentences(evidence, risky))
        else:
            # Nothing was successfully gathered, so a specific-looking
            # untagged claim has nothing to be grounded in -- no need to
            # spend a call finding that out.
            verification.extend({"claim": s, "supported": False, "reason": "no_evidence_available"} for s in risky)

    # ---- Decide retry vs reply ----
    has_unsupported = any(c["supported"] is False for c in verification) or bool(invalid_tags)
    can_retry = retry_count < MAX_VERIFY_RETRIES

    decision: VerifyDecision = "retry" if (has_unsupported and can_retry) else "reply"

    return {
        "verification": verification,
        "verify_decision": decision,
        "retry_count": retry_count + 1 if decision == "retry" else retry_count,
    }


def route(state: AgentState) -> VerifyDecision:
    """Conditional-edge function for build_graph.py's add_conditional_edges."""
    return state.get("verify_decision", "reply")
