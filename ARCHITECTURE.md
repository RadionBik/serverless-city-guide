# Architecture (conceptual)

> The shared picture. No implementation specifics yet — models, sizes, configs come later.

## Idea

Give a location → get a grounded, surprising, **verified** local story. By voice or text.
Two layers: a real-time agent answers "what's around me now"; a batch job pre-bakes
rich guides ahead of time. Geography is stable, so the expensive work is done in advance.

## The two halves

```
        BATCH (Nebius Jobs)                 REAL-TIME (Nebius Endpoints)
   ┌──────────────────────────┐         ┌──────────────────────────────┐
   │      Pre-bake Job        │         │         Agent loop           │
   │  route/area → guide      │         │  location/voice → story      │
   └────────────┬─────────────┘         └───────────────┬──────────────┘
                │ writes                                 │ reads
                ▼                                        │
          ┌───────────────  Guide store  ───────────────┘
          (pre-baked stories = the agent's knowledge corpus)
```

## Real-time path (Endpoints)

User shares a location or asks a question (text). The agent:

1. **Plan** — decide which sources answer this intent.
2. **Gather** — call tools: geo-data sources, web search, and *retrieve from the guide store*.
3. **Narrate** — write the story (storyteller model endpoint).
4. **Verify** — every named place/fact must trace to gathered data or a cited source;
   strip anything ungrounded. Place-name grounding is **deterministic** (string match against
   fetched data, no model); contextual claims can get an optional second pass from the **same
   storyteller** — there is no separate grounding model.
5. **Reply** — stream the story back.

One model endpoint (storyteller) = the served compute. The agent itself is light
glue — it runs wherever (CLI locally, or a small host for a bot). No GPU.

## Pre-bake path (Jobs) — under the hood

A batch job, run to completion, no real-time constraint:

1. **Resolve** — turn a route or area into an ordered list of stops.
2. **Gather** — for each stop, pull geo-data from the sources.
3. **Narrate** — generate a grounded story per stop.
4. **Verify** — same grounding check as real-time.
5. **Package** — write the stops + stories into a guide artifact in the store.

Batch inference (not serving) → cheap, high-throughput, the right tool for many stops.
This is where Jobs genuinely fit: finite work, GPU throughput, run-and-stop.

## How the halves connect

The guide store is the seam. Pre-baked guides become the corpus the real-time agent
retrieves from (gather step). Retrieval is a **geo lookup keyed by location/area** —
proximity is the relevance function, not embedding similarity. No vector index: per-location
data is small enough to fit the prompt, and "near me" is answered by coordinates. This gives
graceful degradation:

- **Warm area** (pre-baked) → agent mostly retrieves + personalizes + narrates → fast.
- **Cold area** (not pre-baked) → agent does full live gather → slower, still works.

Two products, one architecture — each reinforces the other, not bolted-on demos.

## Request flow & delivery

Entry point is identical for CLI or Telegram: the user sends coordinates, a dropped pin,
or a typed question. **The agent always runs.**

```
entry (CLI / Telegram): coords | pin | question
  → AGENT (always)
     ├─ tool: geo sources (Overpass / Wikipedia)
     ├─ tool: web search (Tavily)        ← agent decides what to resolve
     ├─ tool: retrieve from guide store
     ├─ narrate + verify → immediate reply
     └─ tool: start_prebake(area, …)     ← intent "build a route / prepare a guide"
              → orchestrator submits a Nebius Job
              → store: job_id → chat
Job (async): resolve → gather → narrate → verify → write guide to store + mark ready
Delivery: poll / callback → push guide to the user
```

The agent decides, via tool calls, what to fetch and which places to resolve — straight
from the user's query. Two outcomes:

- **Immediate answer** — gather → narrate → verify → reply, one pass.
- **Route / "prepare a guide" intent** — the agent calls a `start_prebake` tool; the
  orchestrator submits a Nebius Job and records `job_id → chat` in the store. **The agent
  does not wait** — the submitting process may not be alive when the Job finishes.

Delivery of a finished Job is **decoupled** from the agent:

1. The Job writes its guide to the store and marks it `ready`.
2. A delivery step pushes it — either the Job notifies directly (chat id passed in as a
   param), or a poller (the bot, or Nebius job-status) picks up ready guides.
3. CLI is synchronous: it polls status until done, then prints.

Granularity:

- **Single pin** → answered **live** (a Job's cold start exceeds live latency).
- **Route / area** → **pre-bake Job** (many stops, run ahead of the trip).

## Quality & eval

Quality rests on the **verify step** (grounding check). It's demonstrated in the blog via
example outputs and a verify on/off comparison — no harness required.

A formal eval harness (fixed location set scored for hallucination rate, empty-data
behaviour, length) is **optional**: local, no GPU, only calls the endpoint. Worth adding for
regression gating or model comparison — not part of the MVP.

## Nebius surface mapping

| Surface | Used for | Why it's the right tool |
|---|---|---|
| **Endpoints** | storyteller model serving | low-latency real-time inference |
| **Jobs** | pre-bake guides | finite batch, GPU throughput, run-to-completion |

## Compute split (GPU)

| Workload | Surface | GPU | Model tier | Lifetime |
|---|---|---|---|---|
| Live storyteller | Endpoint | L40S (~48 GB) | mid (14–32B), strong tool-calling | always-on while up |
| Pre-bake | Job | H100 (80 GB) | large (32–70B), best quality | ephemeral — only during the run |

Live trades quality for latency on a cheaper GPU. Batch trades latency for quality and
throughput on a bigger GPU that exists only while the job runs (no idle cost, no
scale-to-zero needed). Same architecture, two model tiers — so **baked guides are higher
quality than live, not merely cached**.

## Out of scope (for now)

Voice input (STT), TTS reply, vector/embeddings RAG (geo lookup suffices at this scale),
persistent user state, multi-language, monetisation, live GPS tracking, fine-tuning.
All are layers on top of this picture, not part of it.
