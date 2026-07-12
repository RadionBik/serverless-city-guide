# Serverless City Guide

Drop a pin → get a grounded, **verified** local story. Ask for a tour → a GPU batch
job bakes a walking guide with fact-checked chapters.

One model, three roles (storyteller, judge, curator), two Nebius serverless surfaces:

- **Endpoint** — live stories, vLLM serving (stock image).
- **Job** — pre-bake walking tours, offline vLLM batch (this repo's Dockerfile).

Every story is fact-checked against open data (OpenStreetMap, Wikipedia,
Wikidata, Tavily) — failed claims get regenerated, then stripped. Compare with
`--no-verify`.

Built for the [Nebius Serverless AI Builders Challenge](https://nebius.com/serverless-ai-builders-challenge).
Design, grounding mechanics, audit trail: [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick start

```bash
uv sync
cp .env.example .env      # set LLM_BASE_URL, or just NEBIUS_API_KEY to use
                          # Nebius Token Factory as the dev fallback

# live story about what's around a pin
uv run guide.py intro 52.4986 13.4194

# same story without the fact-check pass (comparison demo)
uv run guide.py intro 52.4986 13.4194 --no-verify

# 1 km circular walking tour, baked via the endpoint (no job)
uv run guide.py tour -i "street art" -L 1km --local 52.4986 13.4194

# or bake it as a Nebius job
uv run guide.py tour -i "street art" -L 1km 52.4986 13.4194
./scripts/submit_prebake.sh guides/<guide_id>/tour.json
uv run guide.py show <guide_id>
```

Full usage guide with all flags and examples: `uv run guide.py -h`.

## Deploy on Nebius

1. **Endpoint** (storyteller): `./scripts/deploy_endpoint.sh` — stock
   `vllm/vllm-openai` image serving `Qwen/Qwen3-32B` (the same model as the
   Token Factory dev fallback and the job), preset `1gpu-16vcpu-200gb`
   (H100 80 GB). Put the endpoint URL into `.env`.
2. **Job image**: `docker build -t <registry>/city-guide-prebake .` and push.
3. **Bake**: `BUCKET=s3://... JOB_IMAGE=... ./scripts/submit_prebake.sh guides/<id>/tour.json`

<!-- TODO before submission: hardware notes, runtime/cost estimate, execution proofs
     (endpoint URL, job logs, baked guide JSON), demo screenshots. -->

## License

MIT
