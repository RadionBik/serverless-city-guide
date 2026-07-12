#!/usr/bin/env bash
# Deploy the storyteller endpoint — stock vLLM image, no custom build needed.
# Flags verified against `nebius ai endpoint create --help` (CLI 0.12.x).
# Project comes from the CLI profile (nebius config set parent-id ...) or NEBIUS_PROJECT.
set -euo pipefail

MODEL="${LLM_MODEL:-Qwen/Qwen3-32B}"
NAME="${ENDPOINT_NAME:-city-guide-storyteller}"
PLATFORM="${ENDPOINT_PLATFORM:-gpu-h100-sxm}"
PRESET="${ENDPOINT_PRESET:-1gpu-16vcpu-200gb}"

nebius ai endpoint create \
  ${NEBIUS_PROJECT:+--parent-id "$NEBIUS_PROJECT"} \
  --name "$NAME" \
  --image "vllm/vllm-openai:latest" \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --container-port 8000 \
  --auth token \
  --args "--model $MODEL --max-model-len 16384" \
  "$@"

cat <<EOF

Endpoint creating. When it is up:
  URL:   nebius ai endpoint get-by-name --name $NAME --format json \\
           | jq -r '.status.public_endpoints[] | select(startswith("https://"))'
  Token: nebius ai endpoint get-by-name --name $NAME --format json

Then in .env:
  LLM_BASE_URL=<url>/v1
  LLM_API_KEY=<token>

Pause billing when idle: nebius ai endpoint stop --id <endpoint_id>
EOF
