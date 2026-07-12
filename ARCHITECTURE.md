# Architecture

> Lean design for the Nebius Serverless AI Builders Challenge.
> One evening, one builder. Every piece here either ships or is cut.

## Idea

Give a location → get a grounded, **verified** local story.
Two halves share one brain:

- **Live** — "what's around me now": gather open geo-data, write a story, verify it, print it.
- **Pre-bake** — "prepare a guide for this area": a batch job does the same pipeline
  for many stops at once, and saves the result as a guide.

One model, one container image, two Nebius serverless surfaces.

```
              ONE IMAGE  (vLLM + this package)
        ┌──────────────────────┴──────────────────────┐
        ▼                                             ▼
  ENDPOINT (serve)                              JOB (batch)
  live story requests                           pre-bake a guide
  HTTP, one story at a time                     offline vLLM, all stops at once
        │ reads                                       │ writes
        └────────────►  GUIDE STORE  ◄────────────────┘
                   (JSON guides in a bucket)
```

## Live path

CLI sends coordinates. Pipeline:

1. **Gather** — fixed parallel fan-out, no agent decisions:
   Overpass (OSM POIs), Wikipedia geosearch, Wikidata SPARQL, Tavily web search
   (templated queries), and a guide-store lookup (nearest pre-baked stops).
2. **Analyze** — deterministic scoring and highlights (ported from city-guide).
   The output is the LLM user message: only real places, real URLs, real distances.
   If the pin has no data at all, the CLI says so honestly and stops — no
   evidence, no LLM call, no story (a story from nothing is pure hallucination).
3. **Narrate** — one call to the storyteller endpoint. Strict JSON output.
4. **Verify** — second call to the *same* endpoint with a judge prompt:
   split the story into claims, mark each `supported | unsupported | uncertain`
   against the gathered data. Unsupported claims → one regenerate with the
   violations as feedback. The final verification report ships with the story.
5. **Print** — story + report, plus a hint: "want a walking tour of this area?
   `guide tour …`". `--no-verify` skips step 4 (also the demo switch for the
   verify on/off comparison).

The CLI is thin glue, no GPU, runs anywhere. The endpoint is the only served compute.

### Free-text shell: the agent

`guide.py ask "any dark history here? keep it short" LAT LON` runs a small
LangGraph pipeline (`agent/`): `intake → plan → gather → narrate → verify → reply`.
The agent's one real decision is the **plan** node: a strict-JSON LLM call
turns the free text into the engine settings. Structured fields gate
retrieval and are validated in code — interest (Tavily seed), theme (the
retrieval preset derived from interest), radius (clamped), verbosity (keeps
the hard length-limit prompt block). Wording wishes — tone, language, length
nuance — ride in one free-form `style` field the storyteller reads directly,
subordinate to the data rules. Web search is not a knob: always on, the
engine skips Tavily without an API key anyway. Every other node delegates to
the engine above. Planning failure degrades to the CLI defaults; no node
failure kills the turn.

Deferred on purpose: streaming narration, a cheap pre-check before the LLM
judge, multi-turn memory (chat history is carried in state, not yet used).

## Tour path: curate → route → bake

One model, three roles: **storyteller** (writes), **judge** (checks),
**curator** (picks). The tour path uses all three.

### Submit time (seconds, CLI + endpoint)

Route **length is the one user knob** (`-L 1km`, default 2 km, circular by
default): it sets the gather radius (a circular route of length L reaches ~L/2
from the pin), the curator's stop budget (~1 stop per 250 m, clamped 3–12), and
the route trim cap. Sparse areas undershoot the target honestly — never padded.

1. **Gather wide** — shallow fan-out around the pin (radius from the length
   target, capped at 2.5 km): names, types, coordinates, wiki titles. No deep
   extracts yet.
2. **Pre-rank** — deterministic analysis scores candidates, caps the list
   (~top 50), assigns each an integer ID.
3. **Curate** — one LLM call: candidates + interest ("street art", "cool
   buildings", default = "most surprising, story-rich mix") → pick stops within
   the length budget. The curator answers with **IDs from the list**, so it
   cannot invent a place. Unknown ID → reject, one retry. If the area can't
   serve the interest, it picks fewer stops and says so in a `note` — the CLI
   answers honestly instead of forcing a bad tour.
4. **Route** — pure code, no LLM: greedy nearest-neighbor from the pin, one
   2-opt pass to untangle crossings, worst-detour stops dropped until the tour
   (return leg included) fits the length target. Produces per-leg distance +
   bearing and a per-stop map pin. Deterministic, unit-tested.
5. **Confirm + submit** — print the proposed route right away, write
   `tour.json`, submit the Job. The user sees their route in seconds and the
   stories arrive minutes later.

### Inside the Job (minutes, GPU batch)

1. **Deep gather per stop** — small radius (~200 m) around each stop, full
   sources, parallel across stops. Network-bound, cheap.
2. **Batch narrate** — one **offline vLLM** pass over all stops at once
   (in-process, guided JSON decoding). Each stop's prompt carries the full
   route context (what other chapters cover → no repeats) and its leg data
   (distance + bearing → real walking transitions, not spatial guessing).
   Plus a tour intro and outro. This is what GPU batch jobs are for.
3. **Batch verify** — second pass, judge prompt per stop story.
4. **Regenerate** — third pass, only failed stops, violations as feedback.
   Claims that still fail are stripped from the story deterministically
   (see verifier) — no unsupported claim ships.
5. **Package** — manifest + one JSON per stop + a Google Maps walking
   deep-link (all stops as waypoints — real street routing outsourced to Maps,
   no API key) → written to the bucket mounted into the job, marked ready.
   A `trace/` folder beside them is the audit trail: candidates the curator
   saw, evidence per stop, every verify round, strip counts, run metadata.

Baked tours are richer than live answers because batch has no latency budget —
full verify, longer stories, cross-stop coherence. Quality comes from time,
not from a bigger model. ~90% of tokens are burned in the Job (intro = 1 call,
curator = 1 call, tour = 20+ generations) — the GPU batch is where compute
honestly lives.

## The seam: guide store

Bucket of JSON files, one per stop. Retrieval is a haversine scan — nearest
stops within a radius. No vector index: per-location data fits the prompt, and
"near me" is answered by coordinates.

- **Warm area** (pre-baked) → live answer reuses baked stories as extra evidence → richer, faster.
- **Cold area** → full live gather → slower, still works.

## Grounding: the verifier

No string-match heuristics — too brittle for alt spellings and phrasing.
The verifier is the same storyteller model in judge mode:

- Input: gathered evidence + the story.
- Output (strict JSON): list of claims, each with status and an evidence pointer.
- `unsupported` claims trigger one regenerate with explicit feedback.
- Claims that still fail after the retry are stripped: the best-matching
  sentence is removed deterministically (word-overlap match, never below a
  confidence threshold) and the claim is marked `[removed from story]` in the
  report. Regeneration is the polite fix; the strip is the guarantee.
- The report is part of the output, not hidden — the user (and the judges) see
  exactly what was checked.

Known limit, stated honestly: the judge checks the story against gathered data,
not against the world. If every source misses a fact, the verifier can't rescue it.

## Inference: one protocol, two backends

Prompts and response schemas live in one place. Inference goes through a tiny
protocol with two implementations:

| Backend | Used by | How |
|---|---|---|
| `EndpointBackend` | live CLI | httpx → vLLM endpoint (OpenAI-compatible, strict JSON schema) |
| `OfflineBackend` | pre-bake job | in-process `vllm.LLM`, guided JSON decoding, true batching |

Same model, same prompts, same schemas — the only difference is how tokens get made.

## Nebius surface mapping

| Surface | Runs | Image | GPU |
|---|---|---|---|
| **Endpoint** | vLLM serving the storyteller | stock vLLM image, model as arg | 1× H100 80 GB |
| **Job** | `prebake.py` (offline batch) | this repo's Dockerfile (vLLM base + package) | 1× GPU, exists only during the run |

Model: ONE mid-size instruct model on every surface (default: Qwen3-32B —
hosted on Token Factory for dev, fits one H100 80 GB for serving and batch).
Exact model id is config, not architecture. For development without any
deployed endpoint, the CLI falls back to Nebius Token Factory (hosted
inference, same model, same OpenAI-compatible protocol).

## Repo layout

```
serverless-city-guide/
├── ARCHITECTURE.md / README.md / LICENSE / pyproject.toml / .env.example
├── Dockerfile                  # job image: vLLM base + this package
├── guide.py                    # CLI: intro | ask | tour | status | show
├── agent/
│   ├── state.py                # AgentState + GuideSettings (the plan node's LLM schema)
│   ├── prompts.py              # settings-planner prompt
│   ├── nodes.py                # intake, plan, gather, narrate, verify, reply
│   └── graph.py                # LangGraph wiring
├── scripts/
│   ├── deploy_endpoint.sh      # nebius CLI: create the endpoint
│   └── submit_prebake.sh       # nebius CLI: submit the job
├── city_guide/
│   ├── config.py               # trimmed: geo, sources, llm, store
│   ├── types.py                # enums + StoryResponse / VerifyReport schemas
│   ├── http_client.py, bearing.py, maps_url.py
│   ├── sources/
│   │   ├── overpass.py (+types), wikipedia.py, wikidata.py (+types)
│   │   └── tavily.py           # NEW — templated queries, snippets + URLs
│   ├── collector.py            # parallel fan-out (ported, + tavily, − google)
│   ├── place.py                # normalize / dedup / radius filter (ported)
│   ├── analyze.py              # deterministic analysis → prompt (ported)
│   ├── prompts.py              # storyteller + judge + curator system prompts
│   ├── backends.py             # protocol + Endpoint / Offline backends
│   ├── narrator.py             # narrate(data) → StoryResponse
│   ├── verifier.py             # verify(story, evidence) → VerifyReport + regenerate
│   ├── curator.py              # candidates + interest → stop IDs (validated)
│   ├── route.py                # greedy NN + 2-opt ordering, legs, length trim
│   ├── store.py                # guide store: write / haversine lookup
│   ├── pipeline.py             # gather → analyze → narrate → verify (shared)
│   └── prebake.py              # job entrypoint: tour.json → batch pipeline → store
└── tests/                      # ported source/analyze/place tests + new verifier/store tests
```

Ported from city-guide unchanged or near-unchanged: sources, collector, place,
analyze, bearing, maps_url, http_client, prompt scaffolding (strict schema,
truncation repair). Dropped: Telegram bot, sqlite cache/session layer, Google
Places (licensing + one less key; open data only fits the challenge rules).

## Challenge deliverables map

| Requirement | Covered by |
|---|---|
| Uses Jobs or Endpoints | both, one image |
| Dockerfile | job image |
| README: setup, hardware, cost | endpoint + job presets, per-run cost estimate |
| Execution proof | endpoint URL + job logs + baked guide JSONs |
| Blog ≥600 words | verify on/off comparison + one-image-two-surfaces story |
| Open license, no secrets | MIT, .env.example |

## Out of scope

Voice, TTS, embeddings RAG, user state, multi-language UX (prompt supports it,
product doesn't), monetization, live GPS, fine-tuning.
