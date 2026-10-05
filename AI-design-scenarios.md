# Design scenario bank — "architect it so it doesn't fail"

Ten open-ended architecture questions of the kind asked in AI-engineer interviews. Each has
the clarifying questions, the numbers that force the design, the layers, **what breaks first**,
and the trap.

**Use them out loud.** Read the prompt, cover the rest, talk for five minutes, then check.

**The universal opening, for every one of these:**
1. Clarify and scope — state assumptions if they won't answer
2. Put **numbers** on it, out loud. Little's Law: concurrency = arrival rate x service time
3. Draw the boxes — but **introduce each by the failure it prevents**
4. Name what breaks **first**, and in what order
5. Degradation, cost, security, observability
6. What you'd measure to know it's working

---

## 1 - Multi-model LLM platform that doesn't fail at scale
**Covered in depth:** `11-multi-model-architecture/`

**Skeleton:** gateway -> capability registry -> router (cascade) -> per-provider circuit
breakers + shared token buckets -> fallback chain with per-feature degradation -> validate on
receipt -> usage ledger -> per-model observability.

**Breaks first:** rate limits (daily) -> tail latency -> cost -> outage -> deprecation.
**Trap:** listing components without naming the failure each prevents.

---

## 2 - Build an LLM gateway (i.e. build LiteLLM yourself)

**Clarify:** how many providers? streaming needed? in the request path or async? per-tenant
keys or one company key?

**Numbers:** if it's in the sync path it must add under ~20ms of overhead — that rules out
anything chatty. 70 QPS peak x 2s = ~140 concurrent connections held open.

**Layers, each by its failure:**
- **Unified request/response schema** — *prevents:* call sites coupling to provider SDKs
- **Per-provider adapters** (auth, error mapping, streaming envelope) — *prevents:* provider quirks leaking upward
- **Shared token bucket in Redis** — *prevents:* N instances each admitting the full rate
- **Retry + backoff + jitter, transport errors only** — *prevents:* retry amplification
- **Streaming passthrough** — *prevents:* buffering destroying time-to-first-token
- **Usage capture from the stream** — *prevents:* unattributable cost
- **Key rotation / multi-key** — *prevents:* one key's quota being the ceiling

**Breaks first:** the gateway becoming a **single point of failure** — it must be stateless
and horizontally scaled, with rate state external.
**Trap:** buffering the whole response to count tokens. Count as you stream, or you have
destroyed the latency you were hired to protect.

---

## 3 - Multi-tenant RAG platform, 500 tenants

**Clarify:** shared corpus or per-tenant? can tenants ever see each other's documents (never)?
corpus size per tenant? update frequency?

**Numbers:** 500 tenants x 10k docs x 20 chunks = **100M chunks**. That is past "one index".

**Layers:**
- **Per-tenant namespace or index** — *prevents:* cross-tenant retrieval. Structural, not filtered
- **Shard by tenant** — *prevents:* one huge tenant degrading everyone's ANN latency
- **Per-tenant token buckets + weighted fair queues** — *prevents:* noisy neighbour
- **Tenant-namespaced semantic cache** — *prevents:* a cache hit becoming a data leak
- **Async ingest, per-tenant queue** — *prevents:* a 10k-doc upload blocking live queries
- **Per-tenant budgets** — *prevents:* one tenant's bill becoming your problem

**Breaks first:** **ingest, not query.** A tenant onboarding 10k documents saturates embedding
throughput and blocks everyone — which is why ingest gets its own queue and rate limit.
**Trap:** one shared index with a post-filter. That makes isolation one filter bug away, and
the leak is *content*, not row ids.

---

## 4 - Agentic workflow engine that cannot loop forever or overspend

**Clarify:** how many steps typically? tools with side effects? human in the loop? is partial
progress useful?

**Numbers:** 8 LLM calls per run x 10k runs/day = 80k calls. An agent's cost is its **step
count**, and step count is unbounded by default. That is the whole problem.

**Layers:**
- **Typed state machine** (LangGraph-shaped) — *prevents:* implicit control flow you cannot reason about
- **Max-step budget per run** — *prevents:* infinite loops
- **Per-run token/cost cap + breaker** — *prevents:* one run costing a fortune
- **Loop/repeat detection** (same state seen N times) — *prevents:* semantic loops the step cap catches too late
- **Timeouts per step and per run** — *prevents:* a hung tool call holding a slot forever
- **Checkpointing** — *prevents:* losing 7 steps of work to one failure
- **Critic/verify node that can terminate** — *prevents:* confidently wrong completion
- **Human escalation on low confidence** — *prevents:* automating a decision you should not
- **Least-privilege tools** — *prevents:* prompt injection reaching a destructive action

**Breaks first:** cost, then tool side effects — a retried non-idempotent tool call.
**Trap:** relying on the prompt to say "do not loop". Control flow belongs in **code**; the
model gets judgement, your code gets the budget. *Your PII filter puts the strictness ladder
in a Python data table rather than the prompt — that is exactly this principle, cite it.*

---

## 5 - Document ingestion pipeline, 10M documents

**Clarify:** one-time backfill or continuous? document types? is re-embedding on a model
change in scope (it should be)? how fast must a new doc become searchable?

**Numbers:** 10M docs x 20 chunks = 200M embeddings. At 1k embeddings/sec that is **~55 hours**
of pure embedding. So the design is about **throughput and resumability**, not cleverness.

**Layers:**
- **Stage-per-step pipeline** with a durable queue between stages — *prevents:* one failure restarting everything
- **Content-hash dedup** — *prevents:* re-embedding unchanged documents. Usually the biggest single win
- **Per-stage input fingerprinting** (skip if unchanged) — *prevents:* full reprocessing on a partial change. *You built this in CSR-Exp*
- **Batched embedding calls** — *prevents:* per-item API overhead dominating
- **Backpressure from the index** — *prevents:* overwhelming the vector store on writes
- **Dead-letter queue** — *prevents:* one corrupt PDF stalling the run
- **Idempotent upserts** with deterministic ids (uuid5 of content) — *prevents:* duplicates on retry

**Breaks first:** embedding throughput/quota, then vector-store write throughput.
**Trap:** treating it as a single job. At this size it is a **resumable pipeline**, and
"what happens if it dies at 60%?" is the question actually being asked.

---

## 6 - Real-time voice at 50k concurrent
**Covered in depth:** `04-voice-custom-llm/hld.md`

**Skeleton:** serial latency budget (STT -> retrieval -> LLM -> TTS) - stream into TTS -
autoscale on **sessions not CPU** - regional edge - warm pools - degrade to **text** -
per-tenant concurrency caps.
**Breaks first:** provider concurrency quotas -> cost -> p99 tail -> cold starts.
**Trap:** treating it like a chat system. Voice cannot queue.

---

## 7 - Design a semantic cache

**Clarify:** acceptable staleness? multi-tenant? are answers personalised (if so the key must
include persona/user)?

**Numbers:** if 40% of traffic is near-duplicate, a working cache removes 40% of LLM spend and
latency. Usually the single largest lever in the system.

**Layers:**
- **Embed the query, ANN search the cache** — *prevents:* exact-match caches missing paraphrases
- **Similarity threshold** — *prevents:* answering a *different* question. Too loose is a correctness bug, not a perf regression
- **Namespace by tenant + persona + corpus version** — *prevents:* cross-tenant leaks and stale answers after a re-index
- **TTL + invalidation on corpus change** — *prevents:* serving pre-update policy answers
- **Negative caching for refusals** — *prevents:* repeatedly paying to say "I don't know"
- **Metrics:** hit rate plus a sampled correctness check **on hits**

**Breaks first:** **correctness, not capacity.** A loose threshold silently serves wrong
answers and it looks like a cache win.
**Trap:** not versioning the cache key by corpus version. Re-index and the cache serves the
old world indefinitely.

---

## 8 - Eval and release-gate pipeline for LLM features in CI

**Clarify:** what is the golden set and who maintains it? are prompts versioned? who can
change a production model?

**The insight to lead with:** **prompts and models are config, so they bypass code review
unless you build a gate.** The most frequent change in an LLM system is the least reviewed.

**Layers:**
- **Golden set per task**, versioned in the repo — *prevents:* "it feels better"
- **Deterministic metrics where possible** — *prevents:* judge variance masking regressions
- **Noise floor established first** — *prevents:* reading variance as a result
- **Gates as data with hard/soft flags** — *prevents:* a warning nobody reads
- **Tri-state pass / fail / no-data**, where no-data **blocks** — *prevents:* the failed-open gate *(your bug)*
- **Import the production module** into the harness — *prevents:* scorecard drift
- **Canary + guardrail metrics** — *prevents:* offline-good, online-bad
- **LLM-as-judge as a supplementary signal only**, never the gate

**Breaks first:** **golden-set rot** — it stops representing production traffic, so the gate
passes while users suffer. Refresh it from sampled real queries.
**Trap:** claiming an LLM judge as your release gate. Non-deterministic, so you cannot
separate a regression from variance.

---

## 9 - Cost governance across 500 tenants

**Clarify:** do you bill through? hard ceiling or soft alert? per-tenant or per-feature
budgets?

**Numbers:** 600k calls/day at even a fraction of a penny each is a four-figure daily spend. A
3x runaway doubles it before anyone notices — which is why **detection latency** matters more
than the average.

**Layers:**
- **Per-call attribution** (tenant, feature, model) — *prevents:* an unattributable invoice. *You built this*
- **One rate card, rendered where it is displayed** — *prevents:* displayed not equal to billed
- **Per-tenant and per-feature budgets** — *prevents:* one runaway becoming everyone's problem
- **Spend circuit breaker that degrades** — *prevents:* both the bill and a hard cutoff
- **Anomaly alerting on rate of change**, not absolute spend — *prevents:* slow detection
- **Showback dashboards** — *prevents:* nobody owning the number

**Breaks first:** **detection latency.** The invoice is monthly; the runaway is hourly.
**Trap:** using monthly provider invoices as your cost system. Aggregate and late — you
cannot attribute, cap, or find the cause.

---

## 10 - LLM observability platform

**Clarify:** debugging individual requests or tracking aggregate quality? is prompt/response
content storable given PII?

**Layers:**
- **Trace per request:** prompt, retrieved chunks, model, tokens, cost, latency, output, validation result
- **Sampling + PII redaction before storage** — *prevents:* your observability store becoming your biggest data-protection liability
- **Per-model and per-tenant aggregates** — *prevents:* an average hiding one broken model
- **Error taxonomy** (429 / 5xx / timeout / parse failure / refusal) — *prevents:* "error rate" meaning nothing
- **Quality proxies on sampled traffic:** groundedness, refusal rate, escalation rate
- **Leading indicators:** fallback rate, escalation rate, parse-failure rate, cache hit rate falling

**Breaks first:** storage cost and PII exposure. Full prompt/response logging at 600k/day is
both expensive and a compliance problem. Sample and redact.
**Trap:** tracking only latency and errors. In an LLM system a **quality** regression is
invisible to both, and it is the one that loses users.

---

## The five sentences that improve any of these answers

1. *"Let me put numbers on it first."*
2. *"Each layer here prevents a specific failure — let me name the failure."*
3. *"What breaks first is X, not Y, and here is why."*
4. *"Degraded means something different per feature — for RAG it is extractive-only, for voice it is text."*
5. *"And the thing I would measure to know it is working is the fallback rate, because it moves before users complain."*
