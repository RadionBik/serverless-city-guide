# Proofs — Nebius Serverless AI Builders Challenge

Execution evidence for both serverless surfaces, captured 2026-07-12,
project `eu-north1`.

- `endpoint-overview.png` — the `city-guide-storyteller` endpoint RUNNING:
  stock `vllm/vllm-openai` image, `--model Qwen/Qwen3-32B --max-model-len 16384`,
  1× H100 (`gpu-h100-sxm`, `1gpu-16vcpu-200gb`), public URL up.
- `jobs-page.png` — the prebake jobs. `prebake-covent-garden-v3` COMPLETE
  in 12 min on the same H100 preset. The failed v1/v2 are left visible on
  purpose: KV-cache OOM and the vLLM guided-decoding rename — both described
  in the blog post.
- `job-v3-get.json` — full spec + status of the completed job
  (`nebius ai job get`). S3 credentials are hidden by the CLI; the Tavily
  key is redacted by hand.
- `job-v3-pipeline.log` — the job's own pipeline log: narrate 5 chapters →
  verify → regenerate 4 failed chapters → strip 3 still-ungrounded
  sentences → guide ready. The grounding loop, visible in one screen.
- `guide-covent-garden/` — the guide that job wrote to the bucket:
  `manifest.json`, `tour.json`, one story per stop in `stops/`, and the
  full audit trail in `trace/` (curation candidates, evidence, every
  verify round, what was stripped).
