"""Curator — the model picks tour stops by candidate ID; unknown IDs get one retry."""

from __future__ import annotations

import logging

from city_guide.backends import LLMBackend
from city_guide.config import LlmConfig
from city_guide.prompts import build_curator_messages
from city_guide.types import Candidate, CuratorResponse

logger = logging.getLogger(__name__)


async def curate(
    candidates: list[Candidate], interest: str, backend: LLMBackend, *, min_stops: int, max_stops: int
) -> CuratorResponse:
    """Pick stops for the interest. Selection is by ID — a place cannot be invented.

    min/max stops come from the route-length budget, not a fixed constant.
    Unknown IDs → one retry with the error spelled out, then the bad picks are dropped.
    """
    known_ids = {c.id for c in candidates}
    messages = build_curator_messages(candidates, interest, min_stops, max_stops)
    response = await backend.generate(messages, CuratorResponse, temperature=LlmConfig.curator_temperature)

    bad = [p.candidate_id for p in response.stops if p.candidate_id not in known_ids]
    if bad:
        logger.warning("Curator picked unknown ids %s, retrying once", bad)
        retry = [
            *messages,
            {"role": "assistant", "content": response.model_dump_json()},
            {
                "role": "user",
                "content": f"Ids {bad} are not in the candidate list. Answer again using ONLY listed ids.",
            },
        ]
        response = await backend.generate(retry, CuratorResponse, temperature=LlmConfig.curator_temperature)
        response.stops = [p for p in response.stops if p.candidate_id in known_ids]

    # Dedup picks — keep first mention of each id
    seen: set[int] = set()
    unique = []
    for pick in response.stops:
        if pick.candidate_id in seen:
            continue
        seen.add(pick.candidate_id)
        unique.append(pick)
    response.stops = unique
    return response
