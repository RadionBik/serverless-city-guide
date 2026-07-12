# Every place has a story — building a hallucination-proof city guide on Nebius Serverless

*Built solo, mostly in one evening, for the Nebius Serverless AI Builders Challenge.*
*Code: https://github.com/RadionBik/serverless-city-guide*

## The problem

Ask an LLM "what's interesting around me?" and it will answer — beautifully and
often wrongly. It invents pubs, moves monuments, and makes up dates. For a
travel guide this is fatal: the user is standing right there and can check.

My test case made this brutal. I dropped a pin in the middle of empty Welsh
moorland and asked for a story. The model confidently described "The Mumbles" —
a real seaside town 90 km away — complete with a fabricated Google Maps link
pointing at the empty moor. That output is the whole problem in one screenshot.

So the goal: drop a pin, get a local story where **every named place and fact
is checked against real data** — and when there is no data, the app says so
instead of inventing a town.

## The architecture: one model, three roles, two surfaces

Everything runs on one model — Qwen3-32B, which fits a single H100 80 GB in
bf16 — playing three roles:

- **Storyteller** writes the story from gathered evidence (OpenStreetMap,
  Wikipedia, Wikidata, Tavily web search).
- **Judge** splits the story into atomic claims and marks each one supported,
  uncertain, or unsupported — strictly against the evidence, never from its
  own knowledge.
- **Curator** picks walking-tour stops from a numbered candidate list — by
  integer ID only, so it structurally cannot invent a place.

One container serves two Nebius Serverless surfaces:

- **Endpoint** — a stock vLLM image serving live stories. Drop a pin, get a
  verified intro in seconds.
- **Job** — a batch run that "bakes" whole walking tours: deep-gathers
  evidence per stop, narrates all chapters in one batched vLLM pass, verifies
  each chapter, regenerates failures, and writes the guide to an S3 bucket.

During development I did not deploy anything at all: with no endpoint URL
configured, the code falls back to Nebius Token Factory (per-token hosted
inference, same model). That fallback carried the entire build evening.

## Grounding that actually guarantees something

Prompting a model to "not hallucinate" is a wish, not a mechanism. The pipeline
stacks three real mechanisms:

1. **Selection by construction.** The curator can only answer with candidate
   IDs from gathered data. Route order is pure geometry (nearest-neighbor +
   2-opt), not LLM guesswork.
2. **Verify → regenerate.** The judge's unsupported claims go back to the
   storyteller as explicit feedback for one rewrite.
3. **Deterministic strip.** Whatever still fails after the retry is removed
   from the text by code, not by another LLM call — the best-matching sentence
   is cut and the claim is marked `[removed from story]` in the report that
   ships with every story. Regeneration is the polite fix; the strip is the
   guarantee.

And the empty-moor case? A guard now checks the evidence before any LLM call:
no places, no web snippets, no baked stories nearby → "Nothing notable within
250 m of this pin" and zero tokens spent. The cheapest hallucination is the
one you never generate.

The verification is visible, not hidden: every story prints its claim report,
and `--no-verify` shows the unchecked version for comparison. A `trace/`
folder beside every baked guide keeps the full audit trail — the candidates
the curator saw, the evidence per stop, every verify round, what was stripped.

## Ask in your own words

CLI flags are honest but robotic. A small LangGraph agent (`agent/`) adds a
free-text front door:

```bash
uv run guide.py ask "что интересного вокруг? коротко и с юмором" 51.5245 -0.0786
```

One strict-JSON LLM call turns the request into engine settings. The split
matters: knobs that gate retrieval — search radius, the OpenStreetMap tag
preset, the web-search seed — become validated fields, clamped in code.
Wording wishes — tone, language, length — travel as one free-form style
string the storyteller reads directly, always subordinate to the data rules.
The Russian request above came back short, humorous, in Russian, and still
fact-checked: 9 claims, 0 unsupported. If planning fails, the turn degrades
to the CLI defaults instead of dying. Every run prints its plan, so you can
see what the agent decided:

```
Plan: {"interest":"food","theme":"food","verbosity":"short","radius_m":250}
Evidence: {'places': 170, 'web_snippets': 10, 'baked_stories': 0}
```

## What the cloud taught me in one evening

Both real bugs only appeared in the actual Nebius job — no local test could
catch them:

- **KV-cache OOM.** Qwen3-32B defaults to a 40k context; after 65 GB of
  weights an H100 doesn't have the KV cache for that. The endpoint worked
  because its launch flags capped context at 16k; my in-process job backend
  didn't. One config field fixed it.
- **vLLM moved my cheese.** The latest vLLM renamed guided JSON decoding
  (`GuidedDecodingParams` → `StructuredOutputsParams`). The backend now tries
  the new API and falls back to the old one.

Job logs made both failures diagnosable in minutes: `nebius ai job logs <id>`.

## Measured numbers (not estimates)

Everything below ran on `gpu-h100-sxm`, `1gpu-16vcpu-200gb`, $3.85/GPU-hour:

| Path | Time | Cost |
|---|---|---|
| Route confirmation (gather + curate + route) | ~30–60 s | pennies |
| Bake 5 stops via the hot endpoint | ~2 min | ~$0.13 |
| Cloud job, total | ~20 min | ~$1.27 |

The interesting number is inside the job: actual baking took **1 minute 51
seconds**. The other ~17 minutes were fixed startup — scheduling, pulling a
19 GB image, downloading and compiling 65 GB of weights. That tax is per run,
not per tour. So the UX rule falls out of the measurements: a user waiting for
one tour is served by the hot endpoint in ~2 minutes; the job is the
throughput path — bake ten tours per run and the startup cost per tour
collapses. Serverless per-second billing makes both honest: the endpoint stops
when idle, the job bills only while it runs.

## Results

The same pipeline, four kinds of places:

- **Covent Garden (rich data):** 10 claims, 10 supported, first try.
- **Tan Hill Inn (one famous pub on a moor):** first draft had 1 unsupported
  claim → regenerated → 9 supported, 0 unsupported.
- **Empty moorland:** no story, honest message, zero LLM calls.
- **Warm area:** a pin near an already-baked tour reuses its verified
  chapters as extra evidence — richer live answers where a job ran before.

Every place has a story. Now the stories have receipts.

#NebiusServerlessChallenge
