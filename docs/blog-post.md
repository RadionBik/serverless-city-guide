# Every place has a story: building a grounded city guide on Nebius Serverless

*Built by a team of two for the Nebius Serverless AI Builders Challenge.*

*Code: https://github.com/RadionBik/serverless-city-guide*

## The problem

Ask a language model "what is interesting around me?" and it will usually give
you a fluent answer. Fluency can hide invention: a model may create a pub, move
a monument, or attach a real place name to the wrong coordinates.

We saw this in rural Wales. Given a pin in empty moorland, the model confidently
described The Mumbles, a real seaside area about 90 km away, then linked the
story back to the empty moor.

Our goal became simple: given a location, produce a useful story from local
evidence, and say that nothing notable was found when the evidence is empty.
The application can answer immediately or prepare a multi-stop walking guide
in advance.

## From a pin to a story

The application gathers nearby information from OpenStreetMap, Wikipedia,
Wikidata, and optional web search results. Qwen3-32B then performs three roles:

- The **curator** chooses tour stops from places that were actually found.
- The **storyteller** turns the evidence into readable local history.
- The **judge** compares the story with the evidence and reports supported,
  uncertain, and unsupported claims.

The curator can only select numbered candidates supplied by the application.
Walking order is calculated from coordinates. These constraints prevent the
model from inventing stops or routes.

We run the model on two Nebius Serverless surfaces. An **endpoint** exposes it
through an API for interactive requests. A **job** starts a GPU for a finite
batch, writes the result to object storage, and stops.

We call the second process "baking" a guide. The job gathers deeper evidence for
each stop, writes and checks every chapter, retries failed chapters once, and
stores the guide with an audit trail. During development, the same application
can use Nebius Token Factory, a hosted per-token service, without deploying a
GPU at all.

## Grounding in layers

A prompt that says "do not hallucinate" is only a request. Our controls remain
visible outside the prompt.

First, an evidence guard stops before generation when it finds no nearby places,
web snippets, or previously baked material. It returns an honest message such
as "Nothing notable within 250 m of this pin" and spends no model tokens.

Second, candidate selection and route calculation are constrained by retrieved
data and geometry.

Third, every story receives an evidence-only review. Unsupported claims go back
to the storyteller for one rewrite. If a rejected claim remains and can be
matched confidently to a sentence, deterministic code removes that sentence.

This is a layered defence, not a proof of truth. The judge can be wrong, and the
stripper leaves text alone when a match is ambiguous. Verification is therefore
visible: the response includes a claim report, while a baked guide stores its
evidence, review rounds, and removed sentences.

Those traces produced a labeled development set of 140 claim-and-evidence pairs
from dense London and sparse moorland locations. It showed that the current
judge can be too lenient, especially with distance and direction. We keep the
dataset as a regression target: it makes limitations measurable without
treating a model verdict as ground truth.

## Ask naturally

A small LangGraph planner converts requests such as "What is interesting
nearby? Focus on food and keep it short" into validated settings for radius,
subject, language, and length. Code restricts settings that affect retrieval;
tone remains flexible but cannot override the evidence rules.

For example:

```bash
uv run guide.py ask "что интересного вокруг? коротко и с юмором" 51.5245 -0.0786
```

The answer remains in Russian while using the same gathering and review
pipeline. If planning fails, the application falls back to safe defaults.

## What deployment taught us

Real GPU runs exposed two issues that local development did not. Qwen3-32B uses
about 65 GB with 16-bit weights. Its default context left too little working
memory on an 80 GB H100, so the first job failed. Matching the endpoint's
16,000-token limit fixed it.

A vLLM update also renamed the feature used to force valid JSON responses.
Supporting both API versions fixed the container. Serverless job logs made both
failures reproducible.

## The economics changed our recommendation

Our proof runs used one H100 at $3.85 per GPU-hour:

| Path | End-to-end time | Approximate cost |
|---|---:|---:|
| Select and order the route | 30-60 seconds | Pennies |
| Bake five stops through a running endpoint | About 2 minutes | About $0.13 |
| Bake the same guide as a new GPU job | About 20 minutes | About $1.27 |

The useful pipeline work took less than two minutes inside the job. Most of the
remaining time went to scheduling, pulling a 19 GB image, and loading 65 GB of
weights.

Hosted inference was cheaper still. A typical guide used roughly 45,000 input
tokens and 8,000 output tokens, costing about $0.007 at the Token Factory prices
available during the build. A shared service keeps GPUs busy across customers;
a dedicated job pays its own startup cost.

The conclusion is clear: a GPU job is not the right response to one visitor
requesting one small guide. The endpoint or per-token service is the practical
interactive path. The job belongs on the publishing side, where it can prepare
larger assets asynchronously and keep batch work away from live capacity.

Our proof bakes one tour, so it demonstrates the offline path but does not claim
a multi-tour break-even we have not measured. The next scaling step is to submit
a catalog of tour plans in one job and spread startup across them.

The broader rule: pay per token for a standard model when possible; rent a GPU
when custom weights, isolation, or a genuinely large batch justifies it.

## Results

We tested four conditions:

- In data-rich Covent Garden, the judge reported all ten extracted claims as
  supported on the first pass.
- At the isolated Tan Hill Inn, one rejected claim triggered regeneration; the
  replacement had no reported unsupported claims.
- On empty moorland, the evidence guard returned no story and used no tokens.
- Near a baked guide, accepted chapters could enrich a live answer.

This is not a city guide that can never be wrong. It starts from local evidence,
limits where the model may improvise, shows its checks, and leaves behind data
with which to test the verifier again.

Every place may have a story. The useful ones should come with receipts.

#NebiusServerlessChallenge
