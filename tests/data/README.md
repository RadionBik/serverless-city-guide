# Judge dev dataset

78 (evidence, claim) pairs from `proofs/guide-covent-garden/trace/`, labeled
for the judge role.

- `dev_evidence.json` — evidence document per stop (snapshot; immune to proofs
  refresh).
- `dev_claims.jsonl` — one claim per row: `label` 1 iff every part of the
  claim is substantiated by that stop's evidence (MiniCheck semantics);
  hedged, poetic, or navigational claims without evidence are 0. `category`
  is `fact` / `distance` / `subjective`. `v1_status` is the original Qwen3-32B
  judge verdict, kept for comparison. `note` marks borderline rows.

Labeled by Claude (Fable 5) reading each claim against its evidence only —
weak supervision, not gold truth. Baseline: the v1 judge matches these labels
on 56% of `fact` rows (uncertain counted as not-supported).
