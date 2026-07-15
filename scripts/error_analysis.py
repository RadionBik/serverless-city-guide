"""Error analysis of the v1 judge verdicts against dev-set labels.

Product mapping: only 'unsupported' triggers regen/strip; 'supported' and
'uncertain' claims ship in the story. So:
  hard false accept  = v1 'supported'   but label 0  (judge asserted support that isn't there)
  soft keep          = v1 'uncertain'   but label 0  (ships unverified; by design for subjective)
  false reject       = v1 'unsupported' but label 1  (wrong regen/strip pressure)
"""

import json
from collections import Counter
from pathlib import Path

claims_path = Path(__file__).resolve().parents[1] / "tests/data/dev_claims.jsonl"
rows = [json.loads(line) for line in claims_path.read_text().splitlines()]


def pct(a: int, b: int) -> str:
    return f"{a}/{b} = {a / b:.0%}" if b else "n/a"


for src in ("cg", "th", None):
    sub = [r for r in rows if src is None or r["source"] == src]
    name = {"cg": "Covent Garden", "th": "Tan Hill", None: "ALL"}[src]
    facts = [r for r in sub if r["category"] in ("fact", "distance")]
    hard_fa = [r for r in facts if r["v1_status"] == "supported" and r["label"] == 0]
    soft = [r for r in facts if r["v1_status"] == "uncertain" and r["label"] == 0]
    false_rej = [r for r in facts if r["v1_status"] == "unsupported" and r["label"] == 1]
    missed_keep = [r for r in facts if r["v1_status"] == "uncertain" and r["label"] == 1]
    correct_acc = [r for r in facts if r["v1_status"] == "supported" and r["label"] == 1]
    correct_rej = [r for r in facts if r["v1_status"] == "unsupported" and r["label"] == 0]
    print(f"\n=== {name}: {len(facts)} checkable rows (fact+distance) ===")
    print(f"correct accepts: {len(correct_acc)}   correct rejects: {len(correct_rej)}")
    print(f"HARD FALSE ACCEPTS (supported, but not substantiated): {pct(len(hard_fa), len(facts))}")
    print(f"soft keeps (uncertain, not substantiated — ships anyway): {len(soft)}")
    print(f"false rejects (unsupported, but substantiated): {len(false_rej)}")
    print(f"timid accepts (uncertain, but substantiated): {len(missed_keep)}")

print("\n=== HARD FALSE ACCEPTS, by claim ===")
for r in rows:
    if r["category"] in ("fact", "distance") and r["v1_status"] == "supported" and r["label"] == 0:
        note = f"  [{r['note']}]" if r["note"] else ""
        print(f"- ({r['id']}) {r['claim'][:90]}{note}")

print("\n=== FALSE REJECTS + TIMID ACCEPTS ===")
for r in rows:
    if r["category"] in ("fact", "distance") and r["label"] == 1 and r["v1_status"] != "supported":
        print(f"- ({r['id']}, v1={r['v1_status']}) {r['claim'][:90]}" + (f"  [{r['note']}]" if r["note"] else ""))

cat_counts = Counter((r["category"], r["v1_status"] == "supported", r["label"]) for r in rows)
dist = [r for r in rows if r["category"] == "distance"]
dist_wrong = [r for r in dist if (r["v1_status"] == "supported") != (r["label"] == 1)]
print(f"\ndistance rows: {len(dist)}, judged wrong: {len(dist_wrong)} ({len(dist_wrong) / len(dist):.0%})")
