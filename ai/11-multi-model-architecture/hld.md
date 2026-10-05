# Multi-model platform — the scaled design

> Golden rule: every box exists because a **number** demanded it, and every layer exists
> because a **failure** demanded it.

## 1. Scope (state this, don't assume it)

**Features:** RAG chat · summarisation · extraction · real-time voice.
**Non-functional:** chat p95 < 3s · voice sub-second per turn · extraction correctness over
latency · monthly cost ceiling per tenant · no cross-tenant leakage.
**Out of scope:** training, fine-tuning, model hosting hardware.

## 2. Numbers first

| Input | Value |
|---|---|
| Tenants | 500 |
| DAU | 50k |
| LLM calls/day | 600k (chat 400k, summarise 150k, extract 50k) |
| Average | **~7 QPS** |
| Peak (10×) | **~70 QPS** |
| Avg service time | 2s → Little's Law: **~140 concurrent in flight** |
| Voice | 2k concurrent calls → **~250 turn-QPS** |

**The conclusion those numbers force:** 140 concurrent in flight is trivial for your app tier
and **large against a single provider's quota**. So the architecture is not about compute — it
is about **quota, cost and failure isolation**. Say that out loud; it reframes the whole
design.

## 3. The topology

```
clients
  │
  ├─ sync features ──► API (stateless) ──► semantic cache ──► GATEWAY
  │                                                             │
  └─ async features ─► queue (per-task) ──► workers ────────────┤
                                                                │
                        ┌───────────────────────────────────────┴──────────┐
                        │  router  ← capability registry  ← budget state   │
                        └───────────────────────────────────────┬──────────┘
                                                                │
                      per-provider circuit breakers + token buckets
                                                                │
                  ┌──────────────┬──────────────┬───────────────┴────┐
                  ▼              ▼              ▼                    ▼
             provider A     provider B     self-hosted vLLM     degraded path
                  └──────────────┴──────────────┴────────────────────┘
                                                                │
                                            usage ledger (one rate card)
                                                                │
                                        observability: per-model, per-tenant
```

## 4. What scales how

| Component | Scaling | Why |
|---|---|---|
| API tier | horizontal, stateless | trivial; not the bottleneck |
| Gateway | horizontal, but **token buckets must be shared state** (Redis) | per-process buckets over-admit by N× |
| Router | stateless, reads registry from cache | pure function of request + registry + health |
| Queue | partitioned **per task type** | bulkhead: summarisation must not starve extraction |
| Semantic cache | Redis / vector cache, **namespaced per tenant** | cross-tenant hit = leak |
| Usage ledger | append-only, async writes | must never be in the request's critical path |

**The shared-token-bucket point is the one interviewers probe.** If each gateway instance
keeps its own bucket, ten instances admit ten times the intended rate and you get 429s
anyway. Rate state must be central.

## 5. Bottlenecks, in the order they bite

1. **Provider quota** — 70 QPS peak against a per-key TPM/RPM limit. Fix: multi-key rotation, multi-provider spill, queue-based levelling.
2. **Cost** — 600k calls/day. Fix: semantic cache, cascading, Batch API for the staleness-tolerant slice.
3. **Tail latency** — p99 on the sync path. Fix: timeouts, hedged requests, streaming.
4. **Vector search** — grows with corpus. Fix: ANN tuning, then sharding by tenant.
5. **The ledger** — 600k writes/day is fine, but only if async.

## 6. Multi-tenant fairness — the noisy neighbour

At 500 tenants this becomes the dominant operational problem, and it's what turns a demo
architecture into a platform:

- **per-tenant token buckets** at the gateway, not just global
- **per-tenant queues** or weighted fair queueing, so one tenant's 10k-document batch doesn't
  own the workers
- **per-tenant budgets** with a spend breaker
- **per-tenant cache namespaces**

Without these, tenant 1's bulk job is tenant 2's outage. Bring it up unprompted — most
candidates never mention fairness.

## 7. Cost model

```
cost/request ≈ (prompt_tokens + output_tokens) × rate[model]
```

Prompt tokens are **your choice** — chunk count × chunk size. So:

> **Retrieval precision is a cost lever, not just a quality lever.** Better retrieval means
> fewer chunks for the same answer quality.

Levers ranked by impact: **semantic cache** (removes the call entirely) → **cascading**
(cheaper model on 60–80%) → **retrieval precision** (fewer prompt tokens) → **Batch API**
(half price on staleness-tolerant) → prompt compression.

## 8. Reliability posture

- **Timeouts** on every provider call — no unbounded waits, ever
- **Retry**: gateway only, transport errors only, backoff **+ jitter**
- **Circuit breaker per provider**, per model class
- **Bulkhead**: separate queues and separate worker pools per task
- **Idempotency** on anything that writes
- **Graceful degradation**, defined per feature — and *different* per feature
- **Load shedding**: reject early with a clear error rather than queueing unboundedly. An
  infinite queue is just a slow failure with worse latency.

## 9. Rollout / change safety

Model swaps and prompt changes are the **most frequent** changes in an LLM system, and the
most likely to regress quality invisibly:

1. golden set per task, offline score
2. **noise floor** established before comparing
3. hard gate in CI
4. canary behind a flag, with guardrail metrics
5. one-config-change rollback

**Prompts and models are config, so they escape code review unless you build a gate for
them.** That sentence is the insight — and it's why the eval harness is infrastructure, not
a nice-to-have.

## 10. Observability

Per **model** and per **tenant**, not aggregate:
p50/p95/p99 · error rate **split by class** (429 / 5xx / timeout / parse failure) ·
tokens and cost per request · cache hit rate · **fallback rate** · **escalation rate** ·
queue depth · sampled quality score.

**Leading indicators** (they move before users complain): fallback rate, escalation rate,
parse-failure rate, and cache hit rate falling. Alert on those, not just on errors.
