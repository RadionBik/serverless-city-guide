# Every place has a story — building a hallucination-proof city guide on Nebius Serverless

*Built by a team of two for the Nebius Serverless AI Builders Challenge.*
*Code: https://github.com/RadionBik/serverless-city-guide*

## The problem

Ask an LLM "what's interesting around me?" and it will answer — beautifully and
often wrongly. It invents pubs, moves monuments, and makes up dates. For a
travel guide this is fatal: the user is standing right there and can check.

Our test case made this brutal. We dropped a pin in the middle of empty Welsh
moorland and asked for a story. The model confidently described "The Mumbles" —
a real seaside town 90 km away — complete with a fabricated Google Maps link
pointing at the empty moor. That output is the whole problem in one screenshot.

So the goal: drop a pin, get a local story where **every named place and fact
is checked against real data** — and when there is no data, the app says so
instead of inventing a town. The app answers in two forms: an instant story
for where you stand, and pre-built ("baked") multi-stop walking tours.

## The architecture: right model, right surface

Nebius Serverless gives you two ways to run a model on a GPU: an **endpoint**
(always ready, scales to zero when idle) and a **job** (starts, runs a batch,
stops). Our first design was "one model, three roles": Qwen3-32B played
storyteller, curator and judge, served from a vLLM endpoint for live answers
and loaded in-process in the job that bakes tours. It worked — and then the measurements and one
out-of-memory crash (both below) taught us where each model and surface
actually belongs. The redesign starts from a simple observation: the pipeline
does two kinds of LLM work, and they are not equal.

- **Writing** — a storyteller narrates from gathered evidence (OpenStreetMap,
  Wikipedia, Wikidata, Tavily web search); a curator picks tour stops from a
  numbered candidate list by integer ID only, so it structurally cannot invent
  a place; a splitter breaks each story into atomic claims.
- **Judging** — one verdict per claim: supported by the evidence, or not.

Writing is a commodity: any strong open model does it, so we buy it per token
from **Nebius Token Factory** (Qwen3-32B) — same surface for live answers and
the batch job, same voice everywhere.

Judging is the product. The promise is not "writes stories" — every model
writes stories. The promise is "every claim checked", so the judge is where
quality matters most. And at this one task, fine-tuned specialists beat giant
generalists: on the [LLM-AggreFact leaderboard](https://llm-aggrefact.github.io/),
**Bespoke-MiniCheck-7B** — a 7B model tuned for exactly "is this claim
supported by this context" — is the top open model, ahead of GPT-4o and
Llama-405B. No per-token service hosts it. The only way to run the best judge
is to serve it yourself, and that is what the serverless surfaces are for:

- **Endpoint** — MiniCheck-7B behind a vLLM serverless endpoint, scale-to-zero,
  answering verdicts for live stories.
- **Job** — the same MiniCheck weights loaded in-process for batch runs that
  "bake" whole walking tours: deep-gather evidence per stop, narrate all
  chapters via Token Factory, verdict hundreds of claims in one local batch,
  write the guide to S3.

Same specialist weights, two surfaces. Batch verdicts cost the same
GPU-seconds wherever they run — we spend them inside the job so a big bake
can never degrade the live endpoint's latency, and in-process batching beats
per-claim HTTP round-trips. If your verdict volume is small, the honest
fallback is a CPU-only job that calls the endpoint; ours is the shape you
want when baking at scale.

## Grounding that actually guarantees something

Prompting a model to "not hallucinate" is a wish, not a mechanism. The pipeline
stacks three real mechanisms:

1. **Selection by construction.** The curator can only answer with candidate
   IDs from gathered data. Route order is pure geometry (nearest-neighbor +
   2-opt), not LLM guesswork.
2. **Verify → regenerate.** Unsupported claims go back to the storyteller as
   explicit feedback for one rewrite.
3. **Deterministic strip.** Whatever still fails after the retry is removed
   from the text by code, not by another LLM call — the best-matching sentence
   is cut and the claim is marked `[removed from story]` in the report that
   ships with every story. Regeneration is the polite fix; the strip is the
   guarantee.

And the empty-moor case? A guard checks the evidence before any LLM call:
no places, no web snippets, no baked stories nearby → "Nothing notable within
250 m of this pin" and zero tokens spent. The cheapest hallucination is the
one you never generate.

The verification is visible, not hidden: every story prints its claim report,
and `--no-verify` shows the unchecked version. A `trace/` folder beside every
baked guide keeps the full audit trail — candidates, evidence, every verify
round, what was stripped. One note for multilingual stories: claims are
extracted in English (the evidence is English anyway), so the judge always
works on its home turf.

## Ask in your own words

Everything so far is driven by structured settings — coordinates, search
radius, theme. Honest, but robotic. A small LangGraph agent adds a free-text
front door, so you can just ask:

```bash
uv run guide.py ask "что интересного вокруг? коротко и с юмором" 51.5245 -0.0786
```

One strict-JSON LLM call turns the request into engine settings. Knobs that
gate retrieval — radius, OpenStreetMap tag preset, web-search seed — become
validated fields, clamped in code. Wording wishes — tone, language, length —
travel as one free-form style string, always subordinate to the data rules.
The Russian request above came back short, humorous, in Russian, and still
fact-checked: 9 claims, 0 unsupported. If planning fails, the turn falls back
to the engine's defaults instead of dying. Every run prints its plan:

```
Plan: {"interest":"food","theme":"food","verbosity":"short","radius_m":250}
Evidence: {'places': 170, 'web_snippets': 10, 'baked_stories': 0}
```

## What the cloud taught us

Both real bugs only appeared in the actual Nebius job — no local test could
catch them:

- **KV-cache OOM.** In our first design the job loaded Qwen3-32B in-process.
  Its default 40k context left no room for the KV cache (the GPU memory that
  holds the context a model is reading) after 65 GB of weights on an H100;
  the endpoint had survived only because its launch flags capped context at
  16k. One config field fixed it — and the incident fed the redesign: the job
  now loads a 7B specialist instead of 65 GB of generalist.
- **vLLM moved our cheese.** The latest vLLM renamed guided JSON decoding
  (`GuidedDecodingParams` → `StructuredOutputsParams`). The backend tries the
  new API and falls back to the old one.

Job logs made both failures diagnosable in minutes: `nebius ai job logs <id>`.

## The numbers that shaped the architecture

All measured on `gpu-h100-sxm`, `1gpu-16vcpu-200gb`, $3.85/GPU-hour.

Why buy writing per token? A 5-stop tour uses roughly 45k input + 8k output
tokens; at Token Factory's $0.10/$0.30 per million that is **~$0.007 per
tour**. Self-hosting the same 32B in the job cost $1.09 of fixed startup
(scheduling, 19 GB image, 65 GB of weights) plus ~$0.12 of GPU time per tour —
and batching cannot close the gap: even a perfectly saturated H100 needs ~10
GPU-seconds per tour, about $0.011, still above per-token. A shared per-token
service keeps its GPUs saturated across many customers; a single-tenant GPU
pays for every idle second. So the GPU is reserved for the one model money
cannot buy per token: the judge.

With only 14 GB of MiniCheck weights, the job's startup tax collapses:
[TODO: measured startup + total job cost from the new proof run]. The live
path stays interactive: picking and ordering tour stops takes ~30–60 s, a
fresh verified intro arrives in seconds via Token Factory, verdicts come from
the MiniCheck endpoint in [TODO: measured verdict latency].

Rule of thumb, earned the hard way: **pay per token for standard models; rent
GPUs when you must — for weights nobody serves, or when compliance keeps your
data off shared infrastructure — and give batch its own capacity so it never
touches the live SLA.** A dedicated endpoint or job is single-tenant by
construction, which is exactly what regulated data needs.

## Results

The same pipeline, four kinds of places:

- **Covent Garden (rich data):** 10 claims, 10 supported, first try.
- **Tan Hill Inn (one famous pub on a moor):** first draft had 1 unsupported
  claim → regenerated → 9 supported, 0 unsupported.
- **Empty moorland:** no story, honest message, zero LLM calls.
- **Warm area:** a pin near an already-baked tour reuses its verified chapters
  as extra evidence — richer live answers where a job ran before.

[TODO: re-run the four cases with the MiniCheck judge and refresh the counts.]

Every place has a story. Now the stories have receipts.

#NebiusServerlessChallenge
