"""One-off: build labeled dev dataset from covent-garden trace.

Labels: MiniCheck semantics — 1 iff ALL info in the claim is substantiated by
the stop's evidence document; hedged/poetic/navigational without evidence -> 0.
Labeled by Claude (Fable 5) reading each claim against its evidence; weak
supervision, not gold truth. Borderline rows carry a note.
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCES = {
    "cg": REPO / "proofs/guide-covent-garden/trace",  # data-rich urban
    "th": REPO / "guides/tour-54.4556_-2.1603-1783883280/trace",  # sparse moorland
}
OUT = REPO / "tests/data"

# (source, stop, round) -> list of (label, category, note) aligned with claim order in trace
L = {
    ("cg", 0, 0): [
        (0, "distance", "10m in evidence; '5-minute stroll' not substantiated"),
        (1, "fact", ""),
        (0, "fact", "'first public square' nowhere in evidence; v1 verdict was circular"),
        (0, "fact", "'drew visitors from across the country' not in evidence; v1 fabricated support"),
        (0, "fact", ""),
        (1, "fact", "food hub (100) substantiates it"),
        (1, "fact", "6x Memorial, 4x Art in evidence"),
        (0, "fact", "'heart of British theatre' stronger than 'Actors Church' in evidence"),
        (0, "fact", "haunted/prayers not in evidence (haunted ref is Drury Lane)"),
        (0, "subjective", "navigational imperative; cobblestones not in evidence"),
    ],
    ("cg", 0, 1): [
        (0, "distance", ""),
        (1, "fact", ""),
        (0, "fact", ""),
        (1, "fact", ""),
        (1, "distance", "highlight #1 'St Paul Covent Garden - 10m' substantiates; v1 rationale cited the 40m entry"),
        (0, "fact", ""),
        (0, "fact", ""),
        (0, "subjective", ""),
        (0, "subjective", ""),
    ],
    ("cg", 1, 0): [
        (0, "distance", "no piazza relation in evidence"),
        (1, "fact", ""),
        (0, "fact", "'until the 1880s' not in evidence; v1 rationale even admits it"),
        (0, "fact", "menu not in evidence"),
        (0, "fact", "built 1712 for Russell substantiated; 'Georgian' not (and 1712 predates George I)"),
        (1, "fact", ""),
        (0, "subjective", "Dickens speculation"),
        (0, "fact", "'still hosts elite gentlemen' not substantiated by POI listing"),
        (0, "subjective", ""),
        (0, "subjective", ""),
    ],
    ("cg", 1, 1): [
        (0, "distance", "'behind the Piazza's back wall' not in evidence; v1 used map link as proof"),
        (1, "fact", ""),
        (0, "fact", "'until the 1880s' not in evidence"),
        (0, "fact", "'Georgian' not substantiated"),
        (1, "fact", ""),
        (0, "subjective", ""),
        (0, "fact", "v1: 'implied by its existence' — not substantiation"),
        (1, "fact", "Grade II* in evidence"),
    ],
    ("cg", 2, 0): [
        (0, "distance", "'12 meters straight ahead' not in evidence; v1 cited NSC wiki that says nothing about it"),
        (1, "fact", ""),
        (0, "fact", "white-only + after dinner substantiated; 'before brandy'/'espresso now' not"),
        (0, "fact", "'1960s counterculture' not in this evidence; only the club name appears"),
        (0, "subjective", ""),
    ],
    ("cg", 3, 0): [
        (0, "fact", "ME at 43 King St not substantiated (NSC is)"),
        (0, "fact", "1968 not in evidence"),
        (0, "distance", "both POIs are 10m from the pin, not from each other; borderline"),
        (0, "distance", "same pin-distance logic; borderline"),
        (0, "subjective", ""),
        (0, "subjective", ""),
        (0, "subjective", "wikipedia listing is real but claim as a whole is poetic"),
    ],
    ("cg", 3, 1): [
        (0, "fact", "'1960s hippie club' true in the world, absent from this evidence — strictness probe"),
        (0, "fact", "1968 not in evidence"),
        (0, "fact", "King Street not stated for ME; map coords only; borderline"),
        (0, "fact", "cross-stop leakage: 19th-century Evans facts live in stop-1's evidence, not here"),
        (0, "fact", "choral singing not in this evidence; cross-stop leakage"),
        (0, "subjective", ""),
        (0, "subjective", ""),
        (1, "fact", "NSC at 43 King St in evidence"),
        (0, "distance", "'3 meters west' not in evidence"),
    ],
    ("cg", 4, 0): [
        (0, "distance", "91m/14 King St WC2 not in evidence"),
        (1, "fact", "30m + Actor's Church + first purpose-built protestant church (England entails London)"),
        (0, "fact", "70m substantiated; 'hosted playwrights and performers' not (POI title only)"),
        (1, "fact", "tripadvisor snippet substantiates open-air theatre"),
        (0, "subjective", ""),
        (0, "subjective", ""),
        (0, "subjective", ""),
    ],
    ("cg", 4, 1): [
        (0, "distance", ""),
        (1, "fact", ""),
        (1, "fact", "evidence says first in England, which entails London"),
        (1, "fact", "Actors Church + 1633 + theatre connection; borderline"),
        (1, "distance", "70m in evidence"),
        (0, "fact", "v1 round 1 said supported, round 2 unsupported — same evidence"),
        (0, "fact", ""),
        (0, "subjective", ""),
        (1, "fact", ""),
        (0, "subjective", ""),
        (0, "subjective", ""),
        (0, "subjective", ""),
        (0, "subjective", ""),
    ],
    ("th", 0, 0): [
        (1, "fact", "highest inn in British Isles at 1,732 ft entails highest pub in Britain"),
        (1, "fact", ""),
        (1, "fact", ""),
        (1, "fact", "May 2007 KFC legal threat in evidence"),
        (1, "fact", ""),
        (0, "fact", "Paltrow's ex not in evidence"),
        (
            1,
            "fact",
            "groundedness-not-truth probe: '2000+ years' IS in evidence (Instagram snippet); v1 said uncertain",
        ),
        (1, "distance", "camping 60m in evidence"),
    ],
    ("th", 0, 1): [
        (0, "distance", "'6m northeast' not in evidence"),
        (1, "fact", ""),
        (1, "fact", ""),
        (1, "fact", "entailed by 'first public house in the UK'"),
        (1, "fact", ""),
        (1, "fact", ""),
        (1, "fact", ""),
        (0, "fact", "building has 17th-c origins and exposed beams; beams' age not stated; borderline"),
        (0, "fact", "drovers/packhorse routes in evidence; 'today's weary hikers' not — v1 fabricated it"),
        (0, "distance", "60m is the distance to the camp site, not a 'stretch of moor'; borderline"),
        (1, "fact", "groundedness-not-truth probe (Instagram snippet)"),
    ],
    ("th", 1, 0): [
        (0, "distance", "no elevation info in evidence; claim-split also distorted the story's 'descending 440m'"),
        (0, "distance", ""),
        (1, "fact", "coords verbatim in evidence"),
        (0, "fact", "type Mine + coal-field context, but 'relic of the past' (disused) not stated; strict borderline"),
        (0, "fact", ""),
        (1, "fact", ""),
        (0, "subjective", ""),
        (0, "fact", "current state not in evidence; v1 accepted 'implied'"),
        (0, "subjective", ""),
        (0, "distance", ""),
    ],
    ("th", 1, 1): [
        (
            0,
            "distance",
            "doc has 10m-from-pin only; v1 confused pin coords with Tan Hill Inn and called 440m supported",
        ),
        (0, "fact", "'quiet reminder' (disused) not stated; strict borderline, paired with r0 relic row"),
        (0, "fact", "'local tradition' framing not in evidence"),
        (0, "fact", ""),
        (0, "fact", ""),
        (0, "subjective", ""),
        (1, "fact", ""),
        (0, "fact", "no info on when coal extraction ended"),
        (0, "subjective", ""),
        (0, "subjective", ""),
        (0, "subjective", ""),
    ],
    ("th", 2, 0): [
        (0, "distance", "'400m southwest' not in evidence"),
        (0, "fact", "'Mine Shaft' type substantiates the noun; 'forgotten/once echoed with coal mining' not; strict"),
        (1, "distance", "distance_m 10 + bearing_deg 0 (north) substantiate '10m north'; v1 missed the bearing field"),
        (0, "distance", "70m yes, but bearing 212 deg is southwest, not east; v1 accepted it"),
        (1, "fact", ""),
        (1, "fact", ""),
        (0, "fact", ""),
        (0, "fact", "sealed state not in evidence"),
        (0, "subjective", ""),
    ],
    ("th", 2, 1): [
        (0, "distance", "v1 said supported because 'bearing 0 aligns with southwest' — bearing 0 is north"),
        (0, "fact", "'abandoned' state not in evidence; strict, paired with r0 'forgotten' row"),
        (0, "fact", ""),
        (1, "distance", "10m in evidence"),
        (0, "distance", "bearing 212 deg = southwest, not east; v1 invented directional support again"),
        (0, "fact", ""),
        (0, "fact", ""),
        (1, "fact", ""),
        (1, "fact", ""),
        (1, "fact", ""),
        (0, "fact", ""),
        (0, "subjective", ""),
        (0, "subjective", ""),
    ],
}

OUT.mkdir(parents=True, exist_ok=True)
evidence = {}
rows = []
for src, trace_dir in SOURCES.items():
    for stop_file in sorted(trace_dir.glob("stop-*.json")):
        stop = int(stop_file.stem.split("-")[1])
        data = json.loads(stop_file.read_text())
        evidence[f"{src}{stop}"] = data["evidence"]
        for rnd, round_data in enumerate(data["rounds"]):
            claims = round_data["verify"]["claims"]
            labels = L[(src, stop, rnd)]
            assert len(claims) == len(labels), (
                f"{src} stop-{stop} round {rnd}: {len(claims)} claims vs {len(labels)} labels"
            )
            for idx, (c, (label, cat, note)) in enumerate(zip(claims, labels, strict=True)):
                rows.append(
                    {
                        "id": f"{src}-s{stop}r{rnd}c{idx}",
                        "source": src,
                        "stop": f"{src}{stop}",
                        "claim": c["claim"],
                        "label": label,
                        "category": cat,
                        "v1_status": c["status"],
                        "note": note,
                    }
                )

(OUT / "dev_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=1))
with (OUT / "dev_claims.jsonl").open("w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

n = len(rows)
pos = sum(r["label"] for r in rows)
facts = [r for r in rows if r["category"] == "fact"]
v1_map = {"supported": 1, "unsupported": 0, "uncertain": 0}
agree = sum(v1_map[r["v1_status"]] == r["label"] for r in rows)
agree_f = sum(v1_map[r["v1_status"]] == r["label"] for r in facts)
print(f"rows: {n} ({pos} supported / {n - pos} not)")
print(f"fact rows: {len(facts)} ({sum(r['label'] for r in facts)} supported)")
print(f"v1 judge agreement (uncertain->not supported): {agree}/{n} = {agree / n:.0%}")
print(f"v1 agreement on facts only: {agree_f}/{len(facts)} = {agree_f / len(facts):.0%}")
