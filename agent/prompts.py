"""Prompt for the plan node — user's free text → GuideSettings."""

from __future__ import annotations

from city_guide.prompts import Message

SETTINGS_SYSTEM = """\
You configure a local-storytelling engine. Given the user's request, choose
the settings below. You do not talk to the user.

- theme: "history" | "food" | "nightlife" when the request clearly leans
  that way, else "default".
- verbosity: "short" when the user wants a quick answer ("briefly", "in a
  nutshell", "quick"), else "full".
- language: "en" | "es" | "ru" — the language the user wrote in.
- radius_m: null for the default (250 m). 100 for "right here" / "this
  building", 500 for "this neighborhood" / "around the area". Never above 500.
- with_web: true when fresh or specific facts could help (events, opening
  hours, "what happened here recently"); false for a plain "tell me about
  this place".
- interest: a short focus phrase from the request ("street art",
  "hidden bars"), or null when there is no specific focus.

Respond as JSON matching the provided schema."""


def build_settings_messages(text: str, has_location: bool) -> list[Message]:
    loc = "The user dropped a map pin." if has_location else "No location was provided."
    return [
        {"role": "system", "content": SETTINGS_SYSTEM},
        {"role": "user", "content": f"{loc}\nUser request: {text}"},
    ]
