"""Pre-bake job entrypoint — tour.json → batch gather / narrate / verify / package.

Runs inside the Nebius Serverless AI Job. All generation goes through one backend:
OfflineBackend (in-process vLLM, default) or EndpointBackend (BACKEND=endpoint —
CPU-only fallback that calls the live endpoint instead).

Env:
    TOUR_JSON        path to tour.json (default /input/tour.json)
    GUIDE_STORE_DIR  bucket mount to write the guide into
    BACKEND          offline (default) | endpoint
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from city_guide.backends import EndpointBackend, LLMBackend, OfflineBackend
from city_guide.config import LlmConfig, TourConfig, get_llm_model
from city_guide.logging_config import setup_logging
from city_guide.narrator import build_evidence
from city_guide.pipeline import gather
from city_guide.prompts import (
    Message,
    build_judge_messages,
    build_regenerate_messages,
    build_stop_messages,
    build_storyteller_system,
    build_tour_frame_messages,
)
from city_guide.store import GuideStore, read_tour_plan
from city_guide.types import GuideManifest, StopStory, StoryResponse, TourPlan, VerifyReport
from city_guide.verifier import strip_unsupported

logger = logging.getLogger(__name__)


async def bake(plan: TourPlan, backend: LLMBackend, store: GuideStore) -> GuideManifest:
    manifest = GuideManifest(plan=plan, status="baking", created_at=datetime.now(UTC).isoformat())
    store.save_manifest(manifest)

    # 1. Deep gather per stop — parallel, network-bound
    logger.info("Gathering evidence for %d stops", len(plan.stops))
    gathered = await asyncio.gather(
        *(gather(stop.lat, stop.lon, radius=TourConfig.stop_radius, interest=plan.interest) for stop in plan.stops)
    )
    evidences = [build_evidence(display, analysis, data.tavily_snippets) for display, analysis, data in gathered]

    # 2. Batch narrate — all chapters + intro + outro in ONE offline pass
    system = build_storyteller_system(plan.language)
    chapter_messages: list[list[Message]] = [
        build_stop_messages(system, evidences[i], plan, i) for i in range(len(plan.stops))
    ]
    frame_messages = [
        build_tour_frame_messages(system, plan, "intro"),
        build_tour_frame_messages(system, plan, "outro"),
    ]
    logger.info("Narrating %d chapters + intro/outro", len(chapter_messages))
    stories = await backend.generate_batch(
        chapter_messages + frame_messages, StoryResponse, temperature=LlmConfig.story_temperature
    )
    chapters = [s.text for s in stories[: len(plan.stops)]]
    intro, outro = stories[-2].text, stories[-1].text

    # 3. Batch verify
    logger.info("Verifying %d chapters", len(chapters))
    judge_batches = [build_judge_messages(evidences[i], chapters[i]) for i in range(len(chapters))]
    reports: list[VerifyReport] = await backend.generate_batch(
        judge_batches, VerifyReport, temperature=LlmConfig.judge_temperature
    )
    rounds: list[list[dict[str, object]]] = [
        [{"story": chapters[i], "verify": reports[i].model_dump()}] for i in range(len(chapters))
    ]

    # 4. Regenerate failures — batch retry rounds, then strip what still fails
    for _ in range(LlmConfig.regen_attempts):
        failed = [i for i, r in enumerate(reports) if r.unsupported]
        if not failed:
            break
        logger.info("Regenerating %d failed chapters: %s", len(failed), failed)
        retry_batches = [
            build_regenerate_messages(chapter_messages[i], chapters[i], [c.claim for c in reports[i].unsupported])
            for i in failed
        ]
        retried = await backend.generate_batch(retry_batches, StoryResponse, temperature=LlmConfig.story_temperature)
        recheck = await backend.generate_batch(
            [build_judge_messages(evidences[i], retried[k].text) for k, i in enumerate(failed)],
            VerifyReport,
            temperature=LlmConfig.judge_temperature,
        )
        for k, i in enumerate(failed):
            chapters[i] = retried[k].text
            reports[i] = recheck[k]
            rounds[i].append({"story": chapters[i], "verify": reports[i].model_dump()})

    stripped = [0] * len(chapters)
    for i, report in enumerate(reports):
        if report.unsupported:
            chapters[i], stripped[i] = strip_unsupported(chapters[i], report)
            if stripped[i]:
                logger.info("Stop %d: removed %d ungrounded sentences", i, stripped[i])

    # 5. Package + trace (audit layer: evidence, every verify round, strip count)
    for i, stop in enumerate(plan.stops):
        store.save_stop(plan.guide_id, i, StopStory(stop=stop, story=chapters[i], verify=reports[i]))
        store.save_trace(
            plan.guide_id, f"stop-{i}", {"evidence": evidences[i], "rounds": rounds[i], "stripped": stripped[i]}
        )
    store.save_trace(
        plan.guide_id,
        "meta",
        {
            "model": get_llm_model(),
            "story_temperature": LlmConfig.story_temperature,
            "judge_temperature": LlmConfig.judge_temperature,
            "started": manifest.created_at,
            "finished": datetime.now(UTC).isoformat(),
        },
    )
    manifest.intro = intro
    manifest.outro = outro
    manifest.status = "ready"
    store.save_manifest(manifest)
    logger.info("Guide %s ready: %d stops, %s", plan.guide_id, len(plan.stops), store.root)
    return manifest


def main() -> None:
    setup_logging()
    tour_path = Path(os.environ.get("TOUR_JSON", "/input/tour.json"))
    if not tour_path.exists():
        logger.error("tour.json not found at %s", tour_path)
        sys.exit(1)

    plan = read_tour_plan(tour_path)
    if not plan.stops:
        logger.error("Tour plan has no stops — nothing to bake. Note: %s", plan.note)
        sys.exit(1)

    use_endpoint = os.environ.get("BACKEND", "offline") == "endpoint"
    backend: LLMBackend = EndpointBackend() if use_endpoint else OfflineBackend()

    store = GuideStore()
    asyncio.run(bake(plan, backend, store))


if __name__ == "__main__":
    main()
