#!/usr/bin/env python3
"""Serverless city guide — grounded, verified local stories.

Commands:
    intro LAT LON   live story about what's around the pin (endpoint)
    tour  LAT LON   curate + route a walking tour, then bake it (job or --local)
    status ID       job-side guide status from the store
    show   ID       print a baked guide
"""

import argparse
import asyncio
import json
import sys

from city_guide.backends import EndpointBackend
from city_guide.config import SearchConfig
from city_guide.http_client import close_client
from city_guide.logging_config import setup_logging
from city_guide.narrator import build_evidence, narrate
from city_guide.pipeline import gather, plan_tour, warm_context
from city_guide.store import GuideStore
from city_guide.types import (
    DEFAULT_INTEREST,
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    DEFAULT_VERBOSITY,
    Language,
    OutputMode,
    Theme,
    Verbosity,
)
from city_guide.verifier import verify_and_repair


def _print_report(report, regenerated: bool) -> None:
    print(f"\n--- verification: {report.summary()}" + (" (regenerated once)" if regenerated else " ---"))
    for claim in report.claims:
        mark = {"supported": "✓", "unsupported": "✗", "uncertain": "?"}[claim.status]
        line = f"  {mark} {claim.claim}"
        if claim.evidence:
            line += f"  [{claim.evidence}]"
        print(line)


async def cmd_intro(args: argparse.Namespace) -> None:
    backend = EndpointBackend()
    store = GuideStore()
    display, analysis, data = await gather(
        args.lat, args.lon, radius=args.radius, theme=args.focus, with_web=not args.no_web
    )
    baked = warm_context(store, args.lat, args.lon, args.radius or SearchConfig.default_display_radius)
    evidence = build_evidence(display, analysis, data.tavily_snippets, baked)

    if args.output == OutputMode.RAW:
        print(json.dumps(display.to_display_dict(), ensure_ascii=False, indent=2))
        return
    if args.output == OutputMode.PROMPT:
        print(evidence)
        return

    story, messages = await narrate(
        evidence, backend, language=args.lang, theme=args.focus, verbosity=args.detail
    )
    if args.no_verify:
        print(story)
    else:
        story, report, regenerated = await verify_and_repair(story, messages, evidence, backend)
        print(story)
        _print_report(report, regenerated)
    print(f'\n💡 Want a walking tour of this area? guide.py tour {args.lat} {args.lon} --interest "..."')


async def cmd_tour(args: argparse.Namespace) -> None:
    backend = EndpointBackend()
    store = GuideStore()
    interest = args.interest or DEFAULT_INTEREST

    print(f"Curating a tour near ({args.lat}, {args.lon}) — interest: {interest}")
    plan = await plan_tour(args.lat, args.lon, interest, backend, language=args.lang)

    if plan.note:
        print(f"\nnote: {plan.note}")
    if not plan.stops:
        print("No tour possible here — try another interest or location.")
        return

    print(f"\nYour route ({plan.total_length_m} m, {len(plan.stops)} stops):")
    for i, stop in enumerate(plan.stops):
        print(f"  {i + 1}. {stop.name} ({stop.leg_distance_m} m) — {stop.reason}")
    print(f"\nWalk it: {plan.maps_url}")

    tour_path = store.root / plan.guide_id / "tour.json"
    tour_path.parent.mkdir(parents=True, exist_ok=True)
    tour_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nPlan written: {tour_path}")

    if args.local:
        print("\nBaking locally via the endpoint backend (no job)...")
        from city_guide.prebake import bake

        manifest = await bake(plan, backend, store)
        print(f"Guide ready: guide.py show {manifest.plan.guide_id}")
    else:
        print("\nSubmit the bake job:")
        print(f"  ./scripts/submit_prebake.sh {tour_path}")
        print(f"Then: guide.py status {plan.guide_id}")


def cmd_status(args: argparse.Namespace) -> None:
    manifest = GuideStore().load_manifest(args.guide_id)
    if manifest is None:
        print(f"Unknown guide: {args.guide_id}", file=sys.stderr)
        sys.exit(1)
    print(f"{args.guide_id}: {manifest.status} ({len(manifest.plan.stops)} stops)")


def cmd_show(args: argparse.Namespace) -> None:
    store = GuideStore()
    manifest = store.load_manifest(args.guide_id)
    if manifest is None:
        print(f"Unknown guide: {args.guide_id}", file=sys.stderr)
        sys.exit(1)
    if manifest.status != "ready":
        print(f"Guide is {manifest.status} — not ready yet.")
        return

    plan = manifest.plan
    print(f"# Walking tour — {plan.interest}")
    print(f"{plan.total_length_m} m, {len(plan.stops)} stops. Map: {plan.maps_url}\n")
    print(manifest.intro)
    for i, story in enumerate(store.load_stops(args.guide_id)):
        print(f"\n## {i + 1}. {story.stop.name} ({story.stop.leg_distance_m} m)\n")
        print(story.story)
        if story.verify is not None:
            print(f"\n_verification: {story.verify.summary()}_")
    print(f"\n{manifest.outro}")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("-l", "--lang", type=Language, choices=list(Language), default=DEFAULT_LANGUAGE)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Serverless city guide — every place has a story")
    sub = parser.add_subparsers(dest="command", required=True)

    p_intro = sub.add_parser("intro", help="live story about what's around the pin")
    _add_common(p_intro)
    p_intro.add_argument("-r", "--radius", type=int, default=None, help="display radius, meters")
    p_intro.add_argument("-f", "--focus", type=Theme, choices=list(Theme), default=DEFAULT_THEME)
    p_intro.add_argument("-d", "--detail", type=Verbosity, choices=list(Verbosity), default=DEFAULT_VERBOSITY)
    p_intro.add_argument(
        "-o", "--output", type=OutputMode, choices=list(OutputMode), default=OutputMode.STORY,
        help="raw (JSON) | prompt (evidence dump) | story",
    )
    p_intro.add_argument("--no-verify", action="store_true", help="skip the judge pass (comparison switch)")
    p_intro.add_argument("--no-web", action="store_true", help="skip Tavily web search")

    p_tour = sub.add_parser("tour", help="curate + route a walking tour")
    _add_common(p_tour)
    p_tour.add_argument("-i", "--interest", type=str, default=None, help=f"tour focus (default: {DEFAULT_INTEREST})")
    p_tour.add_argument("--local", action="store_true", help="bake in-process via the endpoint (no job)")

    p_status = sub.add_parser("status", help="guide status")
    p_status.add_argument("guide_id")

    p_show = sub.add_parser("show", help="print a baked guide")
    p_show.add_argument("guide_id")

    args = parser.parse_args()
    try:
        if args.command == "intro":
            asyncio.run(_with_cleanup(cmd_intro(args)))
        elif args.command == "tour":
            asyncio.run(_with_cleanup(cmd_tour(args)))
        elif args.command == "status":
            cmd_status(args)
        elif args.command == "show":
            cmd_show(args)
    except KeyboardInterrupt:
        sys.exit(130)


async def _with_cleanup(coro) -> None:
    try:
        await coro
    finally:
        await close_client()


if __name__ == "__main__":
    main()
