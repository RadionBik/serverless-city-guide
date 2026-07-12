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
3. **Narrate** — one call to the storyteller endpoint. Strict JSON output.
4. **Verify** — second call to the *same* endpoint with a judge prompt:
   split the story into claims, mark each `supported | unsupported | uncertain`
   against the gathered data. Unsupported claims → one regenerate with the
   violations as feedback. The final verification report ships with the story.
5. **Print** — story + report, plus a hint: "want a walking tour of this area?
   `guide tour …`". `--no-verify` skips step 4 (also the demo switch for the
   verify on/off comparison).

The CLI is thin glue, no GPU, runs anywhere. The endpoint is the only served compute.

## Tour path: curate → route → bake

One model, three roles: **storyteller** (writes), **judge** (checks),
**curator** (picks). The tour path uses all three.

### Submit time (seconds, CLI + endpoint)

1. **Gather wide** — shallow fan-out around the pin (~1.5–2 km): names, types,
   coordinates, wiki titles. No deep extracts yet.
2. **Pre-rank** — deterministic analysis scores candidates, caps the list
   (~top 50), assigns each an integer ID.
3. **Curate** — one LLM call: candidates + interest ("street art", "cool
   buildings", default = "most surprising, story-rich mix") → pick 6–10 stops.
   The curator answers with **IDs from the list**, so it cannot invent a place.
   Unknown ID → reject, one retry. If the area can't serve the interest, it
   picks fewer stops and says so in a `note` — the CLI answers honestly instead
   of forcing a bad tour.
4. **Route** — pure code, no LLM: greedy nearest-neighbor from the pin, one
   2-opt pass to untangle crossings, drop worst-detour stops beyond ~4 km
   total. Produces per-leg distance + bearing. Deterministic, unit-tested.
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
5. **Package** — manifest + one JSON per stop + a Google Maps walking
   deep-link (all stops as waypoints — real street routing outsourced to Maps,
   no API key) → written to the bucket mounted into the job, marked ready.

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
├── guide.py                    # CLI: intro | tour | status | show
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

## Cut from the first draft (and why)

- **Telegram bot + async delivery** → CLI polls job status. A bot is transport,
  not architecture; judges read repos, not chats.
- **Two model tiers (L40S live / H100 batch)** → one model. Two deploys to debug
  in one evening is how evenings die.
- **Agent tool-choice loop** → fixed parallel gather. The model narrates and
  judges; it does not route.
- **String-match grounding** → LLM judge (see verifier).
- **Eval harness** → the verify report itself is the demo.

## Out of scope

Voice, TTS, embeddings RAG, user state, multi-language UX (prompt supports it,
product doesn't), monetization, live GPS, fine-tuning.
