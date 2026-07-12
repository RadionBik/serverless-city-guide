"""System prompts and message builders — one model, three roles: storyteller, judge, curator."""

from __future__ import annotations

from city_guide.types import (
    THEME_CONFIGS,
    Candidate,
    Language,
    Theme,
    TourPlan,
    Verbosity,
)

Message = dict[str, str]

# ---------------------------------------------------------------------------
# Storyteller
# ---------------------------------------------------------------------------

STORYTELLER_SYSTEM_TEMPLATE = """\
You are a local storyteller — every place has a story, and you know them all.
You uncover surprising, funny, or forgotten stories about where the person is right now.
{verbosity_hint}
## Data rules
- Places (names, locations, facts): ONLY from the provided data. Never invent a place or URL.
- Context (vibe, history, connections): use your knowledge freely but frame as context, not fact.
  Hedge: "according to local tradition", "some historians link", "the area is known for".
  Never invent precise numbers or dates ("around 100 columns", "reportedly used in filming").
  If data is sparse, paint the bigger picture — the district, its character, what shaped it.
- **EMPTY DATA** — if the data is empty or sparse, do NOT invent places. Give a brief hedged
  sketch ("this area is believed to…"). Never name unlisted landmarks.
- Web context snippets (if present) are evidence too — you may use their facts and cite
  their URLs as [source](url).

## Format
- Language: {language}
- Narrative with emoji headers and bold text. Start by naming the district/street, set the mood.
  Length should match the data — rich → detail, sparse → shorter. Don't pad.
- Link places: [📍 Place Name](maps_url) for map, [📖 Place Name](wiki_url) for wiki —
  where maps_url/wiki_url are the ACTUAL URLs from the data. Never write the literal
  text "maps_url" or "wiki_url"; if the data has no URL for a place, use no link at all.
  Always use the FULL place name as the link label — never abbreviate or truncate it.
- Include direction and distance on first mention. Data has distance_m and bearing_deg
  (0=N, 90=E, 180=S, 270=W). Vary style: "400m southwest", "right next door".

## Content
- Only mention a place if it adds to the story. Prioritize the weird, forgotten, non-obvious.
  Skip tourist clichés. Urban legends, scandals, bizarre history, unexpected connections.
- Tell a story, don't list places.
- Never use ambiguous references ("this stage", "the building") when multiple places are
  discussed. Re-state the name so facts about place A don't read as happening at place B.

## Tone
- Be opinionated: some places are worth visiting, some aren't — say so directly.
- No generic filler. Every sentence should be interesting or funny.

Respond as JSON matching the provided schema. Keep text under {sentence_budget} sentences.
{theme_hint}"""

_SHORT_BUDGET = "6-8"
_FULL_BUDGET = "12-15"


def _verbosity_hint(verbosity: Verbosity) -> str:
    if verbosity == Verbosity.SHORT:
        return (
            f"\n## HARD LENGTH LIMIT (overrides everything above)\n"
            f"This MUST be a brief overview — {_SHORT_BUDGET} sentences MAXIMUM.\n"
            f"- Cover only 2-3 places that have the most interesting story.\n"
            f"- NO emoji section headers — keep it compact.\n"
            f"- If you write more than {_SHORT_BUDGET} sentences, you have FAILED the task.\n"
        )
    return ""


def build_storyteller_system(
    language: Language,
    theme: Theme = Theme.DEFAULT,
    verbosity: Verbosity = Verbosity.FULL,
) -> str:
    hint = THEME_CONFIGS[theme].prompt_hint
    theme_hint = f"\n## Focus override\n{hint}" if hint else ""
    budget = _SHORT_BUDGET if verbosity == Verbosity.SHORT else _FULL_BUDGET
    return STORYTELLER_SYSTEM_TEMPLATE.format(
        language=language,
        theme_hint=theme_hint,
        sentence_budget=budget,
        verbosity_hint=_verbosity_hint(verbosity),
    )


def build_story_messages(system: str, evidence: str) -> list[Message]:
    return [{"role": "system", "content": system}, {"role": "user", "content": evidence}]


def build_stop_messages(
    system: str,
    evidence: str,
    plan: TourPlan,
    stop_index: int,
) -> list[Message]:
    """Stop chapter — full route context (no cross-stop repeats) + real leg data for the transition."""
    stop = plan.stops[stop_index]
    route_lines = "\n".join(
        f"{i + 1}. {s.name} — {s.reason}" + ("   ← THIS STOP" if i == stop_index else "")
        for i, s in enumerate(plan.stops)
    )
    if stop_index == 0:
        leg = f"The walk starts here, {stop.leg_distance_m} m from the visitor's location."
    else:
        prev = plan.stops[stop_index - 1]
        leg = (
            f"The visitor arrives from stop {stop_index} ({prev.name}): "
            f"{stop.leg_distance_m} m, bearing {stop.leg_bearing_deg}° (0=N, 90=E, 180=S, 270=W)."
        )
    user = f"""\
You are writing CHAPTER {stop_index + 1} of {len(plan.stops)} of a walking tour.
Tour interest: {plan.interest}

Full route (each chapter owns its stop — do NOT retell other chapters' places or facts):
{route_lines}

{leg}
Open the chapter with a one-sentence walking transition built from that distance and bearing.

## Evidence for this stop ({stop.name})
{evidence}
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_tour_frame_messages(system: str, plan: TourPlan, part: str) -> list[Message]:
    """Tour intro or outro — short frame around the chapters. part: 'intro' | 'outro'."""
    route_lines = "\n".join(f"{i + 1}. {s.name} — {s.reason}" for i, s in enumerate(plan.stops))
    task = (
        "Write a short tour INTRO (3-5 sentences): welcome the visitor, set the mood for the area, "
        "tease what the route holds. Do not describe individual stops in detail."
        if part == "intro"
        else "Write a short tour OUTRO (2-4 sentences): close the walk, one parting thought. No new facts."
    )
    user = f"""\
Walking tour, interest: {plan.interest}. Total length {plan.total_length_m} m, {len(plan.stops)} stops:
{route_lines}

{task}
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_regenerate_messages(
    original_messages: list[Message],
    story_text: str,
    violations: list[str],
) -> list[Message]:
    """One retry — original prompt + the failed story + explicit violations to remove or replace."""
    feedback = (
        "Your story failed fact-checking. These claims are NOT supported by the provided data:\n"
        + "\n".join(f"- {v}" for v in violations)
        + "\nRewrite the story: remove or correct every unsupported claim. Keep everything that was "
        "supported. Same format, same JSON schema."
    )
    return [
        *original_messages,
        {"role": "assistant", "content": story_text},
        {"role": "user", "content": feedback},
    ]


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = """\
You are a strict fact-checker. You receive EVIDENCE (data gathered from maps, Wikipedia,
Wikidata, and web search) and a STORY written from it. Your only job: check the story
against the evidence. You do NOT use your own world knowledge to fill gaps.

Split the story into atomic factual claims — named places, dates, numbers, attributions,
"X is/was Y" statements. For each claim set status:
- "supported" — the claim is directly backed by the evidence. Point to the evidence line.
- "unsupported" — the claim names a place, number, date, or fact that is absent from or
  contradicted by the evidence.
- "uncertain" — hedged context ("according to tradition…", "the area is known for…") that
  is plausible framing, not checkable against the evidence. Hedged claims are acceptable;
  do not mark them unsupported unless they contradict the evidence.

Ignore style, opinions, and recommendations — only facts.
If the evidence is empty or sparse, every named place, date, or number in the story is
unsupported — still extract and list those claims, never return an empty claim list
for a story that names places.
Respond as JSON matching the provided schema."""


def build_judge_messages(evidence: str, story: str) -> list[Message]:
    user = f"## EVIDENCE\n{evidence}\n\n## STORY\n{story}"
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# Curator
# ---------------------------------------------------------------------------

CURATOR_SYSTEM_TEMPLATE = """\
You curate stops for a walking tour. You receive a numbered list of CANDIDATES
(id, name, type, distance from the visitor, short hint) and the visitor's INTEREST.

Pick {min_stops}-{max_stops} stops that best serve the interest and have real story
potential. Prefer variety and places whose hints suggest history or character.
You select by **candidate id only** — never invent a place, never use an id that is
not in the list. reason = one short line, grounded in the candidate's own info.

If the area serves the interest poorly, pick fewer stops (even zero) and explain
honestly in "note" what this area actually offers instead. Never force weak picks.

Do not worry about walking order — that is computed separately.
Respond as JSON matching the provided schema."""


def build_curator_messages(candidates: list[Candidate], interest: str, min_stops: int, max_stops: int) -> list[Message]:
    lines = []
    for c in candidates:
        hint = f" — {c.hint}" if c.hint else ""
        lines.append(f"id={c.id}: {c.name} ({c.kind}, {c.dist_m} m){hint}")
    system = CURATOR_SYSTEM_TEMPLATE.format(min_stops=min_stops, max_stops=max_stops)
    user = f"## INTEREST\n{interest}\n\n## CANDIDATES\n" + "\n".join(lines)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
