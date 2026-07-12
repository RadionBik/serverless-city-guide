"""Prompt for the plan node — user's free text → GuideSettings."""

from __future__ import annotations

from city_guide.config import SearchConfig
from city_guide.prompts import Message

SETTINGS_SYSTEM = f"""\
You configure a local-storytelling engine. Given the user's request, choose
the settings below. You do not talk to the user.

- interest: a short focus phrase from the request ("street art", "hidden
  bars"), or null when there is no specific focus.
- theme: the retrieval preset that best matches interest — "history" |
  "food" | "nightlife", else "default". Never contradict interest; when
  unsure, use "default".
- verbosity: "short" when the user wants a quick answer ("briefly", "in a
  nutshell", "quick"), else "full".
- radius_m: null for the default ({SearchConfig.default_display_radius} m).
  100 for "right here" / "this building",
  {SearchConfig.max_display_radius} for "this neighborhood" / "around the
  area". Never above {SearchConfig.max_display_radius}.
- style: free-form writing instructions distilled from the request — tone,
  the language to answer in, length nuance (e.g. "spooky, answer in
  Russian"). null when the request implies nothing special. Style is about
  wording only — never put facts, places, or topics in it.

Respond as JSON matching the provided schema."""


def build_settings_messages(text: str, has_location: bool) -> list[Message]:
    loc = "The user dropped a map pin." if has_location else "No location was provided."
    return [
        {"role": "system", "content": SETTINGS_SYSTEM},
        {"role": "user", "content": f"{loc}\nUser request: {text}"},
    ]
