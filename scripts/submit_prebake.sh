#!/usr/bin/env bash
# Submit the pre-bake job for a tour plan.
# Usage: ./scripts/submit_prebake.sh guides/<guide_id>/tour.json
# Requires: BUCKET (s3://... guide store bucket), JOB_IMAGE (this repo's built image),
#           aws CLI configured for Nebius Object Storage (profile "default").
# Flags verified against `nebius ai job create --help` (CLI 0.12.x).
set -euo pipefail

TOUR_JSON="${1:?usage: submit_prebake.sh path/to/tour.json}"
shift
GUIDE_ID="$(basename "$(dirname "$TOUR_JSON")")"
BUCKET="${BUCKET:?set BUCKET=s3://your-guide-store}"
JOB_IMAGE="${JOB_IMAGE:?set JOB_IMAGE=cr.eu-north1.nebius.cloud/<registry>/city-guide-prebake:latest}"
PLATFORM="${JOB_PLATFORM:-gpu-h100-sxm}"
PRESET="${JOB_PRESET:-1gpu-16vcpu-200gb}"

# Upload the plan; the job reads it from the mounted bucket
aws s3 cp "$TOUR_JSON" "$BUCKET/$GUIDE_ID/tour.json"

# S3 volume auth uses the local aws "default" profile (append @secret for MysteryBox)
nebius ai job create \
  ${NEBIUS_PROJECT:+--parent-id "$NEBIUS_PROJECT"} \
  --name "prebake-$GUIDE_ID" \
  --image "$JOB_IMAGE" \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --timeout 2h \
  --volume "$BUCKET:/store:rw" \
  --env "GUIDE_STORE_DIR=/store" \
  --env "TOUR_JSON=/store/$GUIDE_ID/tour.json" \
  --env "LLM_MODEL=${LLM_MODEL:-Qwen/Qwen3-32B}" \
  ${TAVILY_API_KEY:+--env "TAVILY_API_KEY=$TAVILY_API_KEY"} \
  "$@"

cat <<EOF

Watch it:  nebius ai job list
Logs:      nebius ai job logs <job_id> --follow
When done: aws s3 sync $BUCKET/$GUIDE_ID guides/$GUIDE_ID && uv run guide.py show $GUIDE_ID
EOF
