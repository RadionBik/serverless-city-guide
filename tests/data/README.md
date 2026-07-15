# Judge dev dataset

140 (evidence, claim) pairs labeled for the judge role, from two bakes:
`cg` = Covent Garden (`proofs/guide-covent-garden/trace/`, data-rich urban)
and `th` = Tan Hill (`guides/tour-54.4556_-2.1603-1783883280/trace/`, sparse
moorland).

- `dev_evidence.json` — evidence document per stop (snapshot; immune to proofs
  refresh).
- `dev_claims.jsonl` — one claim per row: `label` 1 iff every part of the
  claim is substantiated by that stop's evidence (MiniCheck semantics);
  hedged, poetic, or navigational claims without evidence are 0. `category`
  is `fact` / `distance` / `subjective`. `v1_status` is the original Qwen3-32B
  judge verdict, kept for comparison. `note` marks borderline rows.

Labeled by Claude (Fable 5) reading each claim against its evidence only —
weak supervision, not gold truth. Deliberate probes included: claims true in
the world but absent from the evidence (must be rejected), and one claim
backed only by a low-quality in-doc source (must be accepted — the judge
checks groundedness, not truth).

v1 judge baseline on the 110 checkable rows (fact+distance), product mapping
(only `unsupported` triggers regen/strip; `uncertain` ships): 36 hard false
accepts (33%) vs 1 false reject — the judge is lenient, almost never strict.
Distance/direction rows: 40% wrong (ignores `bearing_deg`/`distance_m`
fields; twice invented directional support).
