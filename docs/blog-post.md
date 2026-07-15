# Every place has a story: building a grounded city guide on Nebius Serverless

*Built by a team of two for the Nebius Serverless AI Builders Challenge.*

*Code: https://github.com/RadionBik/serverless-city-guide*

## The problem

Ask an LLM "what's interesting around me?" and it will answer — beautifully and
often wrongly. It may create a pub, move a monument, or attach a real place name
to the wrong coordinates.

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
each stop, writes and checks every chapter, and stores the guide with an audit trail.
During development, the same application can use Nebius Token Factory, a hosted per-token service, without deploying a GPU at all.

A small LangGraph planner provides a natural-language front door. It converts a
request such as "What is interesting nearby? Focus on food and keep it short"
into validated settings for radius, subject, language, and length.

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

This is a layered defence, not a proof of truth. Verification is visible: the
response includes a claim report, while a baked guide stores its
evidence, review rounds, and removed sentences.

Those traces became a reusable development set for evaluating the judge across
different evidence conditions. It suggested that the current judge can be too
lenient, especially with distance and direction. We keep the dataset as a
regression target: it makes limitations measurable without treating a model
verdict as ground truth.

## Lessons from the cloud runs

Real GPU runs exposed two issues that local development did not. Qwen3-32B uses
about 65 GB with 16-bit weights. Its default context left too little working
memory on an 80 GB H100, so the first job failed. Matching the endpoint's
16,000-token limit fixed it. The lesson was that fitting a model means budgeting
for its working memory, not only its weights, and keeping those limits consistent
between endpoint and job configurations.

A vLLM update also renamed the feature used to force valid JSON responses.
Supporting both API versions fixed the container. Serverless job logs made both
failures reproducible. Serverless removed the work of provisioning a cluster;
we still had to own the model configuration and compatibility of our container.

## Finding the serverless tipping point

The two serverless surfaces match two different lifecycles. The endpoint keeps a
custom model available for live requests without operating a cluster.
The job turns a tour plan into an asynchronous, isolated run with durable output
and logs, then releases the GPU. Neither requires a permanent worker.

Our proof runs used one H100 at $3.85 per GPU-hour:

| Path | Observed time | Estimated compute cost |
|---|---:|---:|
| Select and order the route | 30-60 seconds | Pennies |
| Bake five stops through a running endpoint | About 2 minutes | About $0.13 |
| Bake the same guide as a new GPU job | About 13 minutes | About $0.82 |

The useful pipeline work took less than two minutes inside the job. Most of its
active time went to provisioning the runtime, pulling a 19 GB image, and loading
65 GB of weights. The costs above are estimates from measured duration and the
GPU rate; they exclude small storage charges.

Hosted inference was cheaper still. A typical guide used roughly 45,000 input
tokens and 8,000 output tokens, costing about $0.007 at the Token Factory prices
available during the build. A shared service keeps GPUs busy across customers;
a dedicated job pays its own startup cost.

A job makes more sense for offline preparation than for a single live request.
For example, a publisher could use one batch to prepare or refresh many guides
before visitors need them. Running this work separately prevents it from slowing
the live endpoint, and completed guides can be stored for later use.

The job becomes compelling when the batch is large enough to make startup a
small fraction of the run, when custom weights are not available from a hosted
service, or when batch work should not compete with live capacity. The endpoint
fits interactive workloads: it serves a custom model through an HTTP API while
Nebius manages the GPU infrastructure behind it. Serverless does not make every
workload cheaper; its advantage here is matching interactive and finite
workloads without making our team operate a GPU cluster.

## Outcome

The prototype runs end to end and leaves an audit trail from source evidence to
the final guide. Nebius Serverless gave us interactive and batch GPU lifecycles,
useful logs, and durable job output without requiring us to operate a cluster.
The guide is not infallible, but its constraints and visible checks make errors
easier to find and verifier quality possible to measure.

Every place may have a story. The useful ones come with receipts.

#NebiusServerlessChallenge
