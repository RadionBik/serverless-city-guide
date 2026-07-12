"""
Prompt template for verify's tier-3 LLM judge.

Most of verify's work is deterministic (checking that cited [tag]s actually
exist in the evidence bundle -- see graph/nodes/verify.py). This prompt is
only reached for the harder case: sentences that look like specific factual
claims (a year, a price, a time, an opening/closing status) but weren't
tagged to any evidence item. Rather than running an LLM pass over the whole
narration, only those specific sentences are sent here, batched into one
call, to keep verify cheap.
"""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are a fact-checking pass in a travel companion pipeline. You will be \
given a bundle of evidence and a numbered list of sentences pulled from a \
generated response. None of these sentences carried a citation tag, but \
they look like they might be stating a specific fact.

For each sentence, decide: is this claim actually supported by the \
evidence provided, even without an explicit tag (e.g. it's a very close \
paraphrase of something in the evidence)? Or is it not grounded in the \
evidence at all (the model likely inferred, guessed, or used outside \
knowledge)?

Respond with ONLY a JSON object, no prose, no markdown fences:

{
  "results": [
    {"index": 1, "grounded": true | false},
    {"index": 2, "grounded": true | false}
  ]
}

Include one entry per sentence given, in order. Be strict: if the evidence \
doesn't clearly contain the specific detail (the exact year, price, hours, \
etc.), mark it false.
"""


def build_user_prompt(evidence_block: str, sentences: list[str]) -> str:
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
    return f"Evidence:\n{evidence_block}\n\nSentences to check:\n{numbered}\n\nReturn the JSON result now."
