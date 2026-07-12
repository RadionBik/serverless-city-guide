#!/usr/bin/env bash
# Submit the pre-bake job for a tour plan.
# Usage: ./scripts/submit_prebake.sh guides/<guide_id>/tour.json
# Requires: BUCKET (s3://... guide store bucket), JOB_IMAGE (this repo's built image).
# Check flag names against `nebius ai job create --help` before first run.
set -euo pipefail

TOUR_JSON="${1:?usage: submit_prebake.sh path/to/tour.json}"
GUIDE_ID="$(basename "$(dirname "$TOUR_JSON")")"
BUCKET="${BUCKET:?set BUCKET=s3://your-guide-store}"
JOB_IMAGE="${JOB_IMAGE:?set JOB_IMAGE=cr.nebius.cloud/<registry>/city-guide-prebake:latest}"
PRESET="${JOB_PRESET:-1gpu-16vcpu-200gb}"

# Upload the plan; the job reads it from the mounted bucket
aws s3 cp "$TOUR_JSON" "$BUCKET/$GUIDE_ID/tour.json"

nebius ai job create \
  --name "prebake-$GUIDE_ID" \
  --image "$JOB_IMAGE" \
  --preset "$PRESET" \
  --mount "bucket=$BUCKET,path=/store" \
  --env "GUIDE_STORE_DIR=/store" \
  --env "TOUR_JSON=/store/$GUIDE_ID/tour.json" \
  --env "LLM_MODEL=${LLM_MODEL:-Qwen/Qwen3-32B}" \
  "$@"

echo "When done: aws s3 sync $BUCKET/$GUIDE_ID guides/$GUIDE_ID && ./guide.py show $GUIDE_ID"
