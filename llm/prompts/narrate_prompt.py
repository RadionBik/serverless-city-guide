"""
Prompt template for the narrate node -- the single storyteller call.

Two things this prompt has to get right, because `verify` depends on them:
  1. The model must not state specific facts (hours, prices, names, dates,
     history) that aren't backed by the evidence bundle -- it should speak
     generally or flag uncertainty instead of inventing detail.
  2. Every source it does draw on should be tagged inline with the short
     ids assigned in `_format_evidence` (e.g. "[guide1]", "[web2]"), so
     verify can trace each claim back to a specific evidence item instead
     of having to re-match free text against the whole bundle.
"""

from __future__ import annotations

from typing import Optional

from llm.prompts.citation import format_evidence as _format_evidence

SYSTEM_PROMPT = """\
You are the voice of a real-time travel companion app. You speak directly \
to a traveler, in a warm, knowledgeable, concise tone -- like a well-read \
local friend, not a brochure.

You are given a bundle of evidence (resolved location, guide notes, web \
search results), each item tagged with a short id like [geo], [guide1], \
[web2]. These are the ONLY facts you're allowed to state as fact.

Rules:
- Every specific claim (a name, date, price, opening hour, distance, or \
historical detail) must be tagged with the id of the evidence item it \
came from, e.g. "It was built in 1897 [guide1]."
- If the evidence doesn't cover something the user asked about, say so \
plainly rather than guessing -- e.g. "I don't have current hours for \
that, but it's worth calling ahead."
- You may still speak in general, well-known terms without a tag (e.g. \
"London is known for its parks") as long as you're not stating something \
specific enough to be wrong.
- Keep it conversational and tight -- a few sentences to a short \
paragraph, not an essay. This is spoken/read in the moment, not a guidebook \
entry.
- Never invent a source tag that wasn't given to you.
- Tags are trailing citations on a fact you've already stated in words --
  never let the tag stand in for the fact itself. Wrong: "The location is \
[geo]." Right: "You're standing outside Downing Street [geo]."
"""


def build_user_prompt(
    query: dict,
    evidence: Optional[dict],
    user_profile: Optional[dict] = None,
) -> str:
    text = query.get("text") or "(no specific question -- describe what's nearby)"
    location = query.get("location")
    loc_desc = (
        f"lat={location['lat']}, lon={location['lon']}" if location else "(none provided)"
    )

    parts = [
        f"User's request: {text}",
        f"Raw location: {loc_desc}",
        "",
        "Evidence:",
        _format_evidence(evidence),
    ]

    if user_profile:
        parts += ["", f"What you know about this traveler: {user_profile}"]

    parts += ["", "Respond directly to the traveler now."]
    return "\n".join(parts)