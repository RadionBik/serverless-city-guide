# Agent — conversational shell over the city_guide engine

LangGraph pipeline: `intake → planner → gather → narrate → verify → reply`.

The graph owns conversation concerns (normalizing free-text + pin input,
deciding which sources a request needs, formatting the reply). All heavy
lifting delegates to the `city_guide` engine: gathering (Overpass,
Wikipedia, Wikidata, Tavily, guide store), storytelling, and the
verify → regenerate → strip grounding loop.

```
agent/
├── main.py                  # compiles the graph
├── graph/
│   ├── state.py             # shared AgentState (TypedDict)
│   ├── build_graph.py       # LangGraph StateGraph wiring
│   └── nodes/
│       ├── intake.py        # normalize raw input -> query
│       ├── planner.py       # which sources to call (LLM w/ strict schema, heuristic fallback)
│       ├── gather.py        # -> city_guide.pipeline.gather + guide store
│       ├── narrate.py       # -> city_guide.narrator
│       ├── verify.py        # -> city_guide.verifier.verify_and_repair
│       └── reply.py         # final text + verification summary
└── llm/prompts/planner_prompt.py
```

Install: `uv sync --extra agent`. Run a turn:

```python
from agent.graph.build_graph import build_graph
from agent.graph.state import initial_state

graph = build_graph()
result = await graph.ainvoke(initial_state(
    raw_text="what is interesting around here?",
    coords={"lat": 51.5117, "lon": -0.1240},
))
print(result["reply"])
```

Open design threads (deliberately deferred):
- **Streaming narration** — `on_token` callback needs a streaming method on
  `EndpointBackend`.
- **Two-tier verify** — deterministic citation-tag check before the LLM
  judge, as a cost optimization.
- **Memory / user profiles** — post-reply preference extraction; pruned as
  empty scaffolding, design lives in the PR #2 discussion.
- **reverse_geocode** — no provider wired; wiki/overpass data names the
  area for now.
