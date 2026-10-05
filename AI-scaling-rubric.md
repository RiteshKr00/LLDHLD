# The scaling rubric — say these ten steps out loud

When asked *"scale this"* / *"1M users, redesign it"*, walking a rubric aloud is itself
the seniority signal. Don't jump to Kubernetes. Walk the ladder.

## The ten steps

**1 · Clarify & scope.** Users, QPS, read/write mix, latency SLO, consistency needs, cost
ceiling. **State your assumptions out loud** — you will be scored on this, and it stops you
designing for the wrong system.

**2 · Estimate.** Back of envelope, always. 1M users → 5% DAU = 50k. 10 LLM calls each/day
= 500k/day ≈ **6 QPS average**. Design for peak, say 10× → **60 QPS**. Each call ~2s →
**Little's Law**: concurrency ≈ arrival × service time = 60 × 2 = **120 in flight**.

**3 · High-level components.** Gateway → stateless app tier → queue → LLM workers → vector
store + cache + primary DB → object storage → observability.

**4 · Separate data path from control path.** Real-time serving must not share capacity with
batch/background. This is bulkheading at the architecture level, and it's the same idea as
your Celery queue split — say that.

**5 · Name the bottlenecks, in order.** For an LLM system it is almost always:
**provider rate limits & cost → vector search latency → DB hotspots → token/context limits.**
Naming them in the right order shows you've actually run one of these.

**6 · Scale levers.** Horizontal stateless app tier · queue-based load levelling ·
**semantic caching** · read replicas · sharding · provider fan-out and fallback · model
routing (cheap model first, escalate) · batching.

**7 · Reliability.** Retries with backoff **and jitter** · circuit breakers · bulkheads ·
graceful degradation · idempotency everywhere a retry can happen.

**8 · Cost.** Cache hits · smaller models for easy queries · Batch API for
staleness-tolerant work · prompt compression · per-tenant quotas.

**9 · Security / multi-tenancy / PII.** Tenant isolation · per-tenant rate limits and
quotas · PII redaction before the model · prompt-injection defence.

**10 · Observability.** p50/p95/p99 · error rate · **token usage and cost per request** ·
and the one most people forget: **eval metrics in production** — groundedness, hallucination
rate, retrieval recall.

## The single most valuable lever to name

> **Semantic caching.** Cache answers keyed by *embedding similarity*, not exact string.
> Most production RAG traffic is near-duplicate questions, so hit rates are high — and it
> cuts cost and latency simultaneously.

If you say only one thing when asked to scale RAG, say this. Then note the trade: a
semantic cache can serve a *slightly wrong* answer to a *slightly different* question, so
you need a similarity threshold and per-tenant namespacing.

You already have the ingredients for this answer — `cache.ts` does fuzzy matching within a
persona namespace (`stringSimilarity` above a threshold). That's a string-similarity cache,
which is the same shape one step down from embeddings. Say that: *"I built the string
version; the embedding version is the production form."*

## Worked scenario 1 — "your RAG chatbot goes 1k → 1M users"

**First bottleneck:** the LLM provider — rate limits, then cost. Not your servers.

**Levers, in order of impact:** semantic cache → request queue + load levelling → model
routing (cheap model for easy queries) → provider fallback → precomputed embeddings →
ANN index tuning (`ef`/`M` on HNSW, or `numCandidates` on Atlas) → read replicas →
per-tenant quotas.

**The answer most candidates miss:** at 1M users the **quality** degrades too, not just
latency. Corpus size and query diversity explode, so retrieval precision falls. You need
continuous eval and reranking, not just more machines. Saying this puts you in a different
tier.

## Worked scenario 2 — "50k concurrent voice calls on Digital Twin"

**The constraint is a hard real-time latency budget** — sub-second round trip to feel
natural, and that budget covers STT + retrieval + LLM + TTS in series.

**Levers:** stream everything (partial tokens → TTS as they arrive, don't wait for a
complete response) · regional edge deployment to cut network RTT · warm model pools ·
connection-level backpressure · **graceful fallback to text** when the voice pipeline
saturates · autoscale on *concurrent sessions*, not CPU.

**Cost is the real ceiling:** voice is expensive per minute across five providers. Per-tenant
concurrency caps, and the metering you already built is the prerequisite for enforcing them.

## Worked scenario 3 — "stop your agent looping forever / burning cost"

Max-step budget · per-run token and cost cap with a circuit breaker · loop and repeat
detection · timeouts · a critic/verify node that can terminate · human escalation on low
confidence.

You built a version of the last one — the PII filter's verify node routes low-confidence
findings to human review. Lead with that.

## Worked scenario 4 — "a tenant's data leaks to another tenant"

**How the design prevents it:** every tenant-owned query goes through one scope resolver
that **fails closed** — no valid tenant resolves to a sentinel matching no rows. Out-of-scope
reads return **404, not 403**, so a tenant can't even probe for another's resources.

**How you'd catch it:** the 17-probe regression suite, plus audit logs on cross-tenant
superadmin access. **Hardening you don't have:** Postgres row-level security, so the
database refuses rather than trusting the app layer.

## Worked scenario 5 — "the vector DB returns irrelevant chunks. Debug it."

Ordered checklist, and the order matters:
1. **Chunking** — too large (not selective) or too small (fact split across boundary)?
2. **Embedding mismatch** — same model for index and query? Asymmetric models need the right prefix.
3. **No hybrid search** — policy/legal questions contain exact terms; pure vector misses them. Add BM25.
4. **No reranking** — first-stage ANN returns *plausible*, not *best*. Cross-encoder over top ~20.
5. **Query preprocessing** — is the raw question the right query? Multi-turn needs reformulation.
6. **Then measure** — recall@k on a labelled set. Everything above is a hypothesis until you do this.
