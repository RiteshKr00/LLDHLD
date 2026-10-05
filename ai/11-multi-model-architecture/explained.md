# Multi-model LLM architecture — explained

## Your credibility on this question

You have shipped a piece of most of these layers. Say so as you go — it turns a whiteboard
answer into an experience answer:

| Layer | What you actually have |
|---|---|
| Gateway / proxy | **Gemini via a LiteLLM proxy** — one call shape, central keys and logging |
| Pluggable backends | **CSR-Exp: OpenAI-compatible vLLM + remote embeddings**, swappable |
| Deprecation handling | **Migrated off a retired Gemini model at every call site, behind a guard** that blocks a stale env value reinstating it |
| Bulkhead | **Dedicated Celery queue** for LLM work |
| Cost/latency trade | **Gemini Batch API** for staleness-tolerant runs |
| Cost observability | **Per-call metering across five providers**, one rate card |
| Output contract | **Structured JSON + deterministic validator + maker-checker** |
| Model selection | **Controlled four-model bake-off with a measured noise floor** |
| Cache | **Persona-namespaced response/RAG cache** with similarity matching |

The gaps you should name: no budget *enforcement*, no hedged requests, no capability registry
(model choice is per-call-site, not data).

---

## The one framing that makes this answer good

> **Every layer exists because of a specific failure. Name the failure, then the layer.**

Candidates who list components sound like they've read a blog. Candidates who say *"providers
return 429s, so I need X"* sound like they've operated one. Walk failure → mitigation, every
time.

---

## The seven failure modes, in the order they actually bite

| # | Failure | Frequency | Mitigation |
|---|---|---|---|
| 1 | **Rate limits (429)** | daily | client-side token bucket, queue, multi-key, multi-provider, backoff **+ jitter** |
| 2 | **Latency tail** | daily | per-call timeouts, **hedged requests**, streaming |
| 3 | **Cost drift** | monthly | per-tenant budgets + **spend circuit breaker**, routing, caching, Batch API |
| 4 | **Provider outage** | quarterly | **circuit breaker per provider** + ordered fallback chain |
| 5 | **Model deprecation** | quarterly | capability registry, pinned versions, **eval gate** on swap |
| 6 | **Quality regression** | on every change | golden set + regression gate in CI |
| 7 | **Output contract drift** | per model | validate on receipt, per-model adapters |

**Rate limits are #1 and most candidates say "outage" first.** Getting the order right is a
signal — you've been paged for this.

---

## The layers, bottom up

### 1 · Gateway (the LiteLLM-shaped layer)

**Failure it prevents:** every call site knowing about every provider's SDK, auth, and error
shape.

One internal call shape; the gateway translates to each provider. Centralises **keys, retries,
timeouts, usage logging, rate limiting, and the fallback chain**. Without it, changing
providers is an N-call-site migration — which is exactly the pain you hit on the Gemini
retirement.

### 2 · Capability registry — model choice as data, not code

**Failure it prevents:** a model deprecation becoming a code change in twenty files.

```
model_id → { provider, context_window, modalities, json_mode, function_calling,
             cost_per_1k_in/out, p50_latency, rate_limit, status: live|deprecated|blocked }
```

Routing and validation **read from this**. A deprecation becomes a status flip plus a config
change, not a migration. This is the generalisation of the guard you already wrote — you
prevented a *stale value* reinstating a retired model; a registry prevents the whole class.

### 3 · Router — which model for this request

Decide on, in priority order:

1. **Task requirements** — does it need vision? function calling? 200k context?
2. **Difficulty** — cheap model first, escalate on low confidence (**cascading**). Typically 60–80% never escalate.
3. **Tenant tier** — paid tenants get the better model
4. **Budget state** — near cap → downgrade rather than cut off
5. **Provider health** — skip anything with an open circuit

**Route on capability, never on a hardcoded name.** The router asks "who can do JSON mode with
32k context under 2s?", not "call gpt-4o".

### 4 · Fallback chains and circuit breakers

**Failure it prevents:** one provider's outage becoming your outage.

Per task, an **ordered chain**: primary → secondary → self-hosted → degraded response.
A **circuit breaker per provider** (not global): after N failures, stop calling for a cooldown
so you fail fast and stop hammering something already struggling.

**The important design question is what "degraded" means per feature** — and it differs:

| Feature | Degraded but useful |
|---|---|
| RAG chat | **retrieval-only extractive answer with citations** — no generation, still useful |
| Summarisation | queue it, return "processing" |
| Voice | **fall back to text** |
| Extraction | fail loudly — a wrong extraction is worse than none |

Naming a different degradation per feature is what separates this from "add a fallback."

### 5 · Queue + load levelling

**Failure it prevents:** bursts hitting provider quotas, and slow work starving fast work.

Anything the caller isn't waiting for goes async. **Your dedicated Celery queue is this layer**
— and the bulkhead argument is the same one.

### 6 · Semantic cache

**Failure it prevents:** paying repeatedly for the same question.

Keyed on **embedding similarity**, not exact string. High hit rates on real traffic because
users ask the same thing many ways. Cuts cost and latency simultaneously.

**Two non-negotiables:** a similarity threshold (too loose serves a wrong answer to a
different question) and **per-tenant namespacing** — a cross-tenant semantic cache hit is a
data leak, not a performance bug. *You already namespaced your cache per persona after hitting
exactly this.*

### 7 · Output contract enforcement

**Failure it prevents:** models behaving differently, so a provider swap breaks parsing.

Same schema for all models; **per-model adapters** for how the schema is requested (native JSON
mode vs tool-call vs prompt-only). **Validate on receipt regardless** — never trust the model
to have honoured its own contract. Your deterministic-validator-then-maker-checker chain is
this layer, and it's what makes a model swap *safe*.

### 8 · Budget enforcement

**Failure it prevents:** a runaway loop or one tenant's traffic producing a bill nobody approved.

Per-tenant and per-task budgets, with a **spend circuit breaker**. On breach: **degrade, don't
cut off** — cheaper model, text instead of voice, queue instead of sync.

**Metering is the prerequisite; you built that.** Enforcement is the layer on top, and saying
plainly that you have the first and not the second is a stronger answer than pretending.

### 9 · Eval gate — a model swap is a release

**Failure it prevents:** a "cheaper model" silently degrading quality.

Golden set per task, scored offline, thresholds as **hard gates in CI**. No model change ships
without passing. And from your own work: **establish the noise floor first**, or you'll read
run variance as a regression.

### 10 · Observability, per model

Not aggregate — **per model and per provider**: p50/p95/p99, error rate by class (429 vs 5xx
vs timeout), tokens and **cost per request**, cache hit rate, fallback rate, escalation rate,
and a quality proxy on sampled traffic. **Fallback rate is the leading indicator** — it rises
before users complain.

---

## The follow-ups, answered

**1 · "30% of requests are 429s."**
Client-side token bucket so you shape traffic *before* the provider rejects it; queue absorbs
the burst; retry with backoff **and jitter** (synchronised retries are a self-inflicted DDoS);
spill to the secondary provider; if sustained, the circuit opens and the chain shifts. And
alert — sustained 429 is a capacity/quota conversation, not something to retry through
forever.

**2 · "40-minute provider outage."**
Circuit opens after N failures → fail fast, stop hammering them. Chain moves to secondary.
Sync features degrade per the table above; async work stays queued and drains later. Cost
spikes because the fallback is usually pricier — which is expected and should be visible, not
a surprise on the invoice.

**3 · "Deprecated with 30 days' notice."**
Registry status → `deprecated`; router stops selecting it for new traffic. Run the eval gate
on candidate replacements against the golden set. Migrate behind the gateway so **call sites
don't change**. **And the guard**: block a stale config value from reinstating the retired
model — that's the exact bug you fixed on ResumeFlow, and it's worth naming as lived
experience.

**4 · "p99 doubled, p50 unchanged."**
That's a **tail** problem, not a throughput problem — so adding capacity won't help. Options:
tighten the per-call timeout (fail fast into the fallback), **hedged requests** (fire the
secondary after the p95 mark and take whichever returns first — costs extra tokens, buys tail
latency), and check whether it's one provider or one model size. Averages would have hidden
this entirely, which is why you track p99.

**5 · "One tenant tripled the bill."**
Per-tenant metering identifies them (you have this). Then per-tenant budget with a breaker,
and **degrade rather than cut off**. Root-cause it: legitimate growth, a retry storm, or a
loop? An agent without a step budget is the usual culprit.

**6 · "Swap a model without a quality regression."**
Golden set per task, offline score, hard gate in CI, noise floor established first. Then a
canary — small traffic share behind a flag, with guardrail metrics. **Never swap on price
alone**; your bake-off found four models within a point of each other, so "cheaper" and "worse"
are not automatically linked, and neither is "bigger" and "better".

**7 · "Structured output across different models."**
One schema, per-model request adapters, validate on receipt, and treat parse failure as a
**retryable error with a repair prompt** before failing the request. Keep a per-model
parse-failure metric — it's how you discover a provider changed behaviour before your users do.

**8 · "Why not one big model for everything?"**
Cost and latency, mostly: most requests are easy, and paying frontier prices for a
classification is waste. Also capability mismatch (some tasks need vision, some need 200k
context), and **concentration risk** — one provider outage becomes total downtime. Concede the
counter-argument honestly: **one model is far simpler**, and if volume is low, simplicity wins.
Multi-model is a response to cost and risk at scale, not a default.

**9 · "Where does the retry live?"**
**Gateway** for transport-level retries (429, 5xx, timeout) — one place, consistent policy,
central metrics. **Worker** for business-level retries (the whole task failed and must re-run
later). **Never both**, or you get retry amplification: 3 × 3 = 9 calls for one logical
request. That multiplication is the trap in this question.

**10 · "How do you test it?"**
Fake providers at the gateway interface that can be told to return 429, 5xx, timeout, or
malformed JSON — so fallback and circuit logic are unit-testable with no network. Contract
tests per provider adapter. Eval gates on the golden set in CI. And chaos-style drills: force
a circuit open in staging and confirm the degradation is what you designed rather than a 500.

---

## One-line summary

> "One gateway so call sites don't know about providers, a capability registry so model choice
> is data, a router that cascades cheap-to-expensive, ordered fallback chains behind per-provider
> circuit breakers, a semantic cache that's tenant-namespaced, output validated on receipt, and
> per-tenant budgets with a breaker. Each layer is there for a named failure."

## The trap answer to avoid

Listing components without failures. *"I'd add a gateway, a router, caching and observability"*
is a blog post. **Every layer must be introduced by the failure it prevents**, and the ordering
of failures — rate limits before outages — is what proves you've run one of these.
