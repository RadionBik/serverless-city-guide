"""Per-claim judge eval on the dev set via Token Factory.

Modes:
  pipeline  — generic strict per-claim verdict prompt (v2 fallback style)
  minicheck — the Bespoke-MiniCheck-7B prompt template, verbatim
Usage: uv run python eval_judge.py <mode> [model]
Writes results to results_<mode>_<model-slug>.jsonl next to this script.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
HERE = Path(__file__).parent
BASE_URL = os.environ.get("EVAL_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/")
API_KEY = os.environ.get("EVAL_API_KEY") or os.environ["NEBIUS_API_KEY"]

# https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B — official template
MINICHECK_TMPL = (
    "Determine whether the provided claim is consistent with the corresponding document. "
    "Consistency in this context implies that all information presented in the claim is "
    "substantiated by the document. If not, it should be considered inconsistent.\n\n"
    "Document: {doc}\n\nClaim: {claim}\n\n"
    'Please assess the claim\'s consistency with the document by responding with either "Yes" or "No".'
)

PIPELINE_TMPL = (
    "You are a strict fact-checking judge. Check the claim ONLY against the evidence below — "
    "never use your own knowledge. A claim is supported only if every part of it is stated in "
    "the evidence.\n\nEvidence:\n{doc}\n\nClaim: {claim}\n\n"
    'Is the claim supported by the evidence? Answer with a single word: "Yes" or "No".'
)

TMPL = {"pipeline": PIPELINE_TMPL, "minicheck": MINICHECK_TMPL, "minicheck_chunked": MINICHECK_TMPL}


def chunks(doc: str, size: int = 2000) -> list[str]:
    """Line-boundary chunks ~size chars — MiniCheck protocol scores per chunk, takes max."""
    out, cur = [], ""
    for line in doc.splitlines(keepends=True):
        if len(cur) + len(line) > size and cur:
            out.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        out.append(cur)
    return out


async def ask(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, tmpl: str, model: str, doc: str, claim: str
) -> tuple[int | None, str]:
    suffix = " /no_think" if "qwen" in model.lower() else ""  # Qwen soft switch; keep MiniCheck template exact
    body = {
        "model": model,
        "messages": [{"role": "user", "content": tmpl.format(doc=doc, claim=claim) + suffix}],
        "max_tokens": 2048,
        "temperature": 0.0,
    }
    async with sem:
        for attempt in range(3):
            try:
                r = await client.post(f"{BASE_URL}/chat/completions", json=body, timeout=120)
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                clean = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
                m = re.search(r"\b(yes|no)\b", clean.lower())
                return (1 if m.group(1) == "yes" else 0) if m else None, clean[:200]
            except (httpx.HTTPError, KeyError) as e:
                if attempt == 2:
                    return None, f"error: {e}"
                await asyncio.sleep(2 * (attempt + 1))
    return None, "unreachable"


async def main() -> None:
    mode, model = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "Qwen/Qwen3-32B")
    rows = [json.loads(x) for x in (REPO / "tests/data/dev_claims.jsonl").read_text().splitlines()]
    evidence = json.loads((REPO / "tests/data/dev_evidence.json").read_text())
    sem = asyncio.Semaphore(16)
    headers = {"Authorization": f"Bearer {API_KEY}"}

    async def ask_row(client: httpx.AsyncClient, r: dict[str, Any]) -> tuple[int | None, str]:
        doc = evidence[r["stop"]]
        if mode != "minicheck_chunked":
            return await ask(client, sem, TMPL[mode], model, doc, r["claim"])
        results = await asyncio.gather(*(ask(client, sem, TMPL[mode], model, c, r["claim"]) for c in chunks(doc)))
        votes = [p for p, _ in results if p is not None]
        return (max(votes) if votes else None), f"chunks={len(results)} yes={sum(votes)}"

    async with httpx.AsyncClient(headers=headers) as client:
        preds = await asyncio.gather(*(ask_row(client, r) for r in rows))

    out = HERE / f"results_{mode}_{model.split('/')[-1]}.jsonl"
    with out.open("w") as f:
        for r, (pred, raw) in zip(rows, preds, strict=True):
            f.write(json.dumps({**r, "pred": pred, "raw": raw}, ensure_ascii=False) + "\n")

    scored = [(r, p) for r, (p, _) in zip(rows, preds, strict=True) if p is not None]
    check = [(r, p) for r, p in scored if r["category"] in ("fact", "distance")]
    acc = sum(p == r["label"] for r, p in check) / len(check)
    fa = sum(1 for r, p in check if p == 1 and r["label"] == 0)
    fr = sum(1 for r, p in check if p == 0 and r["label"] == 1)
    print(f"mode={mode} model={model} answered={len(scored)}/{len(rows)}")
    print(f"checkable rows: {len(check)}  accuracy: {acc:.0%}  false accepts: {fa}  false rejects: {fr}")
    for src in ("cg", "th"):
        s = [(r, p) for r, p in check if r["source"] == src]
        s_acc = sum(p == r["label"] for r, p in s) / len(s)
        s_fa = sum(1 for r, p in s if p == 1 and r["label"] == 0)
        s_fr = sum(1 for r, p in s if p == 0 and r["label"] == 1)
        print(f"  {src}: acc {s_acc:.0%}  FA {s_fa}  FR {s_fr}")
    subj = [(r, p) for r, p in scored if r["category"] == "subjective"]
    print(f"subjective rows rejected (should be ~all): {sum(1 for r, p in subj if p == 0)}/{len(subj)}")


asyncio.run(main())
