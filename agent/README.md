# Agent — free-text shell over the city_guide engine

LangGraph pipeline: `intake → plan → gather → narrate → verify → reply`.

The agent's job is to turn a free-text request into engine settings — the
same knobs `guide.py intro` exposes as CLI flags (theme, verbosity,
language, radius, web search, interest). The `plan` node picks them with
one strict-JSON LLM call; every later node runs the `city_guide` engine
with those settings. Any planning failure degrades to the CLI defaults.

```
agent/
├── state.py     # AgentState + GuideSettings (the plan node's LLM schema)
├── prompts.py   # settings-planner prompt
├── nodes.py     # all six nodes
└── graph.py     # LangGraph wiring
```

Install and run:

```bash
uv sync --extra agent
uv run guide.py ask "what's the food story here? keep it short" 51.5117 -0.1240
```

Or from Python:

```python
from agent.graph import build_graph
from agent.state import initial_state

result = await build_graph().ainvoke(initial_state(
    raw_text="que hay de interesante por aqui?",
    coords={"lat": 51.5117, "lon": -0.1240},
))
print(result["reply"])
```

Open design threads (deliberately deferred):
- **Streaming narration** — an `on_token` callback needs a streaming method
  on `EndpointBackend`.
- **Two-tier verify** — deterministic citation-tag check before the LLM
  judge, as a cost optimization.
- **Memory / user profiles** — post-reply preference extraction; pruned as
  empty scaffolding, design lives in the PR #2 discussion.
- **Multi-turn** — `messages` history is carried in state but not yet used
  by any node.
