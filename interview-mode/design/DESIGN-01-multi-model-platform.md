# DESIGN-01 — multi-model LLM platform at scale

## META
- difficulty: hard
- time: 25 min
- tags: architecture, multi-model, gateway, routing, fallback, cost
- source: `11-multi-model-architecture/`

## PROMPT

> "You're building a platform serving several LLM-powered features — chat, summarisation,
> extraction, voice — across multiple models and providers. Architect it so it doesn't fall
> over at scale. What breaks, and what do you put in place before it does?"

## CLARIFY

- **"How many distinct task types?"**
  → *"Four, as listed."*
- **"Self-hosted, API providers, or both?"**
  → *"Both. Assume two API providers and one self-hosted."*
- **"Latency SLO per feature?"**
  → *"Chat p95 under 3s. Voice sub-second per turn. Extraction: correctness over latency."*
- **"Cost ceiling, and is it per tenant?"**
  → *"Yes, per tenant, and it's enforced."*
- **"External customers or internal teams?"**
  → *"500 external tenants."*
- **"What happens if a feature is down 10 minutes?"**
  → *"You tell me — that's part of the design."*

## STEP 1 — Clarify and scope

### CHECKPOINTS
- Asks at least four of the clarify questions **before** designing
- States assumptions out loud where unanswered
- Separates functional (four features) from non-functional (per-feature SLO, cost ceiling, no cross-tenant leakage)
- Explicitly puts training/fine-tuning **out of scope**

## STEP 2 — Numbers

### CHECKPOINTS
- Derives QPS rather than guessing: e.g. 50k DAU, ~600k calls/day = **~7 QPS average**
- Designs for **peak, ~10x = 70 QPS**
- Applies **Little's Law**: 70 x 2s = **~140 concurrent in flight**
- Voice treated separately: 2k concurrent calls -> ~250 turn-QPS
- **Draws the right conclusion:** 140 concurrent is trivial for the app tier and **large against one provider's quota** -> "this system is about quota, cost and failure isolation, not compute"

## STEP 3 — Architecture, each layer by its failure

### CHECKPOINTS
- **Gateway** — prevents every call site knowing every provider SDK
- **Capability registry** — model choice as **data**: context window, modalities, JSON mode, cost, latency, rate limit, status. Prevents a deprecation becoming a 20-file migration
- **Router with cascading** — cheap model first, escalate on low confidence; routes on **capability, not a hardcoded name**
- **Shared token buckets in Redis** — and explains *why shared*: per-process buckets over-admit by N x
- **Circuit breaker per provider**, not global
- **Ordered fallback chain** per task
- **Semantic cache**, **tenant-namespaced**, with a similarity threshold
- **Validate output on receipt** regardless of model
- **Per-tenant budgets** with a spend breaker
- **Usage ledger, one rate card, async write** — never in the critical path
- Bonus: names bulkheading — separate queues and worker pools per task type

## STEP 4 — What breaks first

### CHECKPOINTS
- Gets the **order** right: **rate limits (daily)** -> tail latency -> cost -> provider outage (quarterly) -> deprecation
- Explicitly says rate limits come before outages — the common mistake is naming outage first
- For each, names the mitigation: token bucket/queue/multi-key -> timeouts + hedged requests -> cache/cascade/Batch -> circuit breaker + chain -> registry + eval gate
- Handles retry placement: **gateway for transport, worker for business, never both** (3 x 3 = 9 calls)

## STEP 5 — Degradation and cost

### CHECKPOINTS
- Defines "degraded" **differently per feature**:
  - RAG chat -> retrieval-only extractive answer with citations
  - summarisation -> queue it, return "processing"
  - voice -> fall back to **text**
  - extraction -> **fail loudly** (a wrong extraction is worse than none)
- Budget breach -> **degrade, don't cut off**
- Cost model: prompt tokens dominate, and prompt tokens are **your choice** -> **retrieval precision is a cost lever**
- Lever order: semantic cache -> cascading -> retrieval precision -> Batch API -> prompt compression
- Multi-tenant fairness raised **unprompted**: per-tenant buckets, weighted fair queues, per-tenant cache namespaces

## STEP 6 — Observability and change safety

### CHECKPOINTS
- Metrics **per model and per tenant**, not aggregate
- **Error taxonomy**: 429 vs 5xx vs timeout vs parse failure
- Names **leading indicators**: fallback rate, escalation rate, parse-failure rate, cache hit rate falling
- **A model swap is a release**: golden set, noise floor first, hard gate in CI, canary
- Names the insight: **prompts and models are config, so they escape code review unless you gate them**
- Testability: fake providers at the gateway interface that can return 429/5xx/timeout/malformed JSON

## TRAP

Listing components without failures. *"I'd add a gateway, a router, caching and
observability"* is a blog post. **Every layer must be introduced by the failure it prevents**,
and naming rate limits before outages is what proves you've operated one of these.
