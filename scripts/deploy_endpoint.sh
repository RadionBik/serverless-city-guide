#!/usr/bin/env bash
# Deploy the storyteller endpoint — stock vLLM image, no custom build needed.
# Check flag names against `nebius ai endpoint create --help` before first run.
set -euo pipefail

MODEL="${LLM_MODEL:-Qwen/Qwen3-32B}"
NAME="${ENDPOINT_NAME:-city-guide-storyteller}"
PRESET="${ENDPOINT_PRESET:-1gpu-16vcpu-200gb}"

nebius ai endpoint create \
  --name "$NAME" \
  --image "vllm/vllm-openai:latest" \
  --preset "$PRESET" \
  --port 8000 \
  --args "--model $MODEL --max-model-len 16384" \
  "$@"

echo "Set LLM_BASE_URL in .env to the endpoint URL + /v1 once it is up."
