# RAG at scale — 1k → 1M users

> Golden rule: every box exists because a **number** demanded it.

## 1. Estimate first, out loud

1M registered → 5% DAU = **50k**. Say 5 questions each = **250k queries/day** ≈ **3 QPS
average**. Design for peak 10× = **30 QPS**. Each query ≈ 2s end to end →
Little's Law: **~60 concurrent in flight**.

That's small for the app tier and **large for an LLM provider quota**. Which tells you where
the bottleneck is before you've drawn anything.

## 2. Bottlenecks, in the order they actually bite

| # | Bottleneck | Why it's first |
|---|---|---|
| 1 | **LLM provider rate limit + cost** | 250k calls/day is a procurement problem, not an engineering one |
| 2 | **Vector search latency** | grows with corpus size; ANN params become load-bearing |
| 3 | **Embedding cost at ingest** | re-embedding a large corpus on a model change |
| 4 | **DB / metadata hotspots** | conversation writes, audit rows |
| 5 | **Context/token budget** | more chunks ≠ better; cost scales linearly with tokens |

## 3. Levers, in order of impact

**1 · Semantic cache — say this first.** Cache answers keyed by *embedding similarity*, not
exact string. Production Q&A traffic is dominated by near-duplicate questions ("what's the
notice period" in fifteen phrasings). Cuts cost **and** latency at once.
*Trade:* it can serve a slightly-wrong answer to a slightly-different question, so you need a
similarity threshold, a TTL, and **per-tenant namespacing** — a cross-tenant semantic cache
hit is a data leak.
*You already built the string-similarity version of this in `cache.ts`, namespaced per
persona. Say that — it's the same shape one step down.*

**2 · Model routing / cascading.** Classify difficulty, send easy questions to a small cheap
model, escalate only what needs the big one. Typically 60–80% go cheap.

**3 · Queue + load levelling.** Absorb bursts so the provider sees a smooth rate and you
never trip a rate limit.

**4 · Provider fallback.** Multi-provider behind one interface — which is exactly what a
LiteLLM-style proxy buys you. Provider outage becomes degraded quality, not downtime.

**5 · ANN tuning.** `numCandidates` / `ef_search` down until measured recall@k starts
dropping. Free latency until you hit the quality wall.

**6 · Precompute + warm.** Embeddings computed at ingest, never at query time for documents.

## 4. The answer most candidates miss

At 1M users **quality degrades, not just latency**. Corpus size and query diversity both
explode, so:

- more chunks are *plausible* for any query → precision falls → **reranking stops being optional**
- long-tail questions appear that the corpus doesn't answer → the **refusal path** becomes
  load-bearing
- you cannot eyeball quality any more → **continuous eval in production**: sampled
  groundedness scoring, retrieval recall on a rolling labelled set, drift monitoring

Saying this puts you in a different tier. Everyone says "add a cache."

## 5. Reliability

Retries with backoff **and jitter** (synchronised retries after a provider blip are a
self-inflicted DDoS) · circuit breaker per provider · graceful degradation: retrieval-only
extractive answer with citations when generation is unavailable, which is still useful ·
idempotency on anything that writes.

## 6. Cost model to have in your head

Cost/query ≈ (embed) + (retrieval) + **(prompt tokens + output tokens) × rate**.
Prompt tokens dominate, and prompt tokens are *your* choice — chunk count × chunk size. So
**retrieval precision is a cost lever, not just a quality lever.** Better retrieval means
fewer chunks for the same answer quality. That connection is the one interviewers remember.

## 7. Observability

p50/p95/p99 · error rate per provider · **tokens and cost per request** · cache hit rate ·
retrieval recall@k on a rolling sample · refusal rate (a spike means corpus drift) ·
groundedness on sampled traffic.
