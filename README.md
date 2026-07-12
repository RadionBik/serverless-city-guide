# Travel Companion — Agentic Real-Time Travel Agent

Pipeline: `intake → planner → gather (parallel) → narrate → verify → reply`,
with a future async `memory` writer branching off after reply.

One storyteller LLM endpoint (Nebius), one orchestration graph. Planner and
verify are designed to run on a cheaper/faster model (also via Nebius) or
rule-based logic — see `NEBIUS_UTILITY_MODEL` in `.env`.

## Structure

```
travel-companion/
├── main.py                  # entry point — wires graph + runs a turn
├── .env / .env.example      # secrets & config (Nebius keys, provider keys)
├── requirements.txt
│
├── config/
│   └── settings.py          # loads/validates .env via pydantic-settings
│
├── schemas/                 # typed data contracts shared across nodes
│   ├── query.py             # normalized user query (text/coords/pin/intent)
│   ├── evidence.py          # gathered evidence bundle + provenance tags
│   └── profile.py           # user preference/profile schema (future memory)
│
├── graph/
│   ├── state.py             # shared graph state object (TypedDict/pydantic)
│   ├── build_graph.py       # compiles the LangGraph StateGraph + edges
│   └── nodes/
│       ├── intake.py        # normalize raw input -> Query
│       ├── planner.py       # decide which gather sources are needed
│       ├── gather.py        # fan-out/fan-in calls to tools/*
│       ├── narrate.py       # single storyteller Nebius call
│       ├── verify.py        # claim-check narration against evidence
│       └── reply.py         # format final response to client
│
├── tools/                   # gather-step data sources
│   ├── geo/
│   │   ├── reverse_geocode.py
│   │   └── places.py
│   ├── web_search.py
│   ├── guide_store.py       # geo-keyed guide/knowledge retrieval
│   └── user_profile_store.py# future: user preference retrieval
│
├── llm/
│   ├── nebius_client.py     # thin wrapper around Nebius (OpenAI-compatible)
│   └── prompts/             # prompt templates per node
│       ├── planner_prompt.py
│       ├── narrate_prompt.py
│       ├── verify_prompt.py
│       └── memory_extraction_prompt.py
│
├── memory/                  # future: async, off-critical-path
│   ├── extractor.py         # post-turn preference/topic extraction
│   └── store.py             # persistence for user profiles
│
└── tests/
```

## Notes

- All Nebius calls route through `llm/nebius_client.py` — single place to
  swap models/endpoints.
- `tools/user_profile_store.py` and `memory/` are scaffolded but not wired
  into `graph/build_graph.py` yet; they plug into `gather` (read) and a
  post-`reply` async branch (write) without changing the graph shape.
- Copy `.env.example` to `.env` and fill in keys before running.
