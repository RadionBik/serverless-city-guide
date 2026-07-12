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

The exact sequence below was run end-to-end for this repo (CLI 0.12.x, project
in `eu-north1` — the only region with H100).

```bash
# 0. one-time: point the CLI at your project
nebius config set parent-id <project-id>

# 1. endpoint — stock vLLM image, Qwen3-32B on 1x H100 80 GB
./scripts/deploy_endpoint.sh
# prints URL + auth token when up; put them in .env:
#   LLM_BASE_URL=<url>/v1
#   LLM_API_KEY=<token>
# cold start ~15 min (65 GB weights download + compile); stop pauses billing:
#   nebius ai endpoint stop <endpoint-id>

# 2. registry + job image (image path uses the registry id WITHOUT "registry-")
nebius registry create --name city-guide
nebius registry configure-helper
docker build -t cr.eu-north1.nebius.cloud/<registry-path>/city-guide-prebake:latest .
docker push  cr.eu-north1.nebius.cloud/<registry-path>/city-guide-prebake:latest

# 3. bucket + S3 access for the job volume and the aws CLI
nebius storage bucket create --name city-guide-store
nebius iam service-account create --name city-guide-sa
nebius iam group create --name city-guide-writers --parent-id <tenant-id>
nebius iam group-membership create --parent-id <group-id> --member-id <sa-id>
nebius iam access-permit create --parent-id <group-id> --resource-id <bucket-id> --role editor
nebius iam access-key create --parent-id <project-id> --account-service-account-id <sa-id> --name city-guide-s3
nebius iam access-key get-secret-once --id <key-id>   # shown ONCE
# ~/.aws/credentials: the key pair; ~/.aws/config:
#   endpoint_url = https://storage.eu-north1.nebius.cloud, region = eu-north1

# 4. bake a tour in the cloud
uv run guide.py tour -i "theatre history" -L 1.5km 51.5117 -0.1240
BUCKET=s3://city-guide-store JOB_IMAGE=cr.eu-north1.nebius.cloud/<registry-path>/city-guide-prebake:latest \
  ./scripts/submit_prebake.sh guides/<guide-id>/tour.json
nebius ai job logs <job-id> --follow
aws s3 sync s3://city-guide-store/<guide-id> guides/<guide-id>
uv run guide.py show <guide-id>
```

## Hardware, runtime, cost (measured)

Both surfaces run `Qwen/Qwen3-32B` (bf16, ~65 GB) on one H100 80 GB
(`gpu-h100-sxm`, `1gpu-16vcpu-200gb`, $3.85/GPU-hr), `max_model_len` 16k.

| Path | Time | Cost |
|---|---|---|
| Route confirmation (gather + curate) | ~30–60 s | pennies (Token Factory or endpoint) |
| Bake via hot endpoint (`tour --local`) | ~2 min / 5 stops | ~$0.13 |
| Cloud job, total | ~20 min (17 min fixed startup + ~2 min baking) | ~$1.27 |

The job's ~17 min startup tax (scheduling, image pull, model load) is fixed per
run — batch many tours per job to amortize it. A single tour for a waiting user
is better served by the hot endpoint; the job is the throughput path.

## License

MIT
