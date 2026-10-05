# Concepts you must define crisply, cold

One or two lines each. If you hesitate on any of these, you lose the thread of a bigger
answer. Drill them like flashcards.

## Resilience & distributed systems

- **Idempotency** — the same operation applied twice has the same effect as once. What makes a retry safe.
- **Backpressure** — the system signalling upstream to slow down instead of silently queueing until it dies.
- **Bulkhead** — isolated capacity per workload, so one saturating can't sink another. *Your Celery queue split.*
- **Circuit breaker** — after N failures, stop calling and fail fast; retry after a cooldown. Protects you *and* the struggling dependency.
- **Retry with backoff + jitter** — exponential delay plus randomness. Jitter matters because synchronised retries create a thundering herd.
- **Little's Law** — concurrency ≈ arrival rate × service time. How you size worker pools.
- **Graceful degradation** — shed features, not availability. Voice saturated → fall back to text.
- **Fail closed** — on ambiguity, deny. *Your tenant resolver: no tenant → no rows.* The opposite (fail open) turns an auth bug into a full data dump.

## Data & consistency

- **Eventual vs strong consistency** — will a read definitely see the last write, or only converge?
- **CAP** — under a network partition, choose availability or consistency. Often over-quoted; the useful version is PACELC (latency vs consistency when there's *no* partition).
- **Cache-aside** — read cache, miss → read DB → populate cache. The two hard problems: **invalidation** (stale data) and **stampede** (many misses hit the DB at once).
- **Semantic cache** — cache keyed by embedding similarity, not exact string. The #1 cost lever in production RAG.
- **Sharding vs replication** — sharding splits data (write scaling), replication copies it (read scaling + HA). Different problems.
- **Read replica** — a copy serving reads; lags the primary, so it's eventually consistent.
- **N+1 query** — one query for the list, then one per row. Fix with eager loading (`select_related` / `prefetch_related`).

## Concurrency in Python — the trio interviewers conflate

- **`asyncio`** — concurrency *inside one process*, cooperative, one thread. Great for I/O waiting. A blocking call freezes the whole loop.
- **Threading** — multiple threads in one process, limited by the **GIL** for CPU work but fine for I/O.
- **Multiprocessing** — separate processes, real CPU parallelism, higher overhead.
- **Task queue (Celery)** — *different machines/processes entirely*, durable, retryable, survives restarts. **Not** the same axis as the three above.
- **The GIL** — one thread executes Python bytecode at a time, so CPU-bound threading doesn't parallelise.

## LLM & RAG

- **RAG** — retrieve relevant context, inject it into the prompt, generate. Grounds output in your data instead of the model's memory.
- **Chunking** — splitting documents for retrieval. Small enough to be selective, large enough to contain a complete answer, overlapped so boundary facts survive.
- **Embedding** — a vector encoding meaning, so similarity is geometric.
- **Cosine similarity** — angle between vectors, magnitude-independent. Preferred over dot product when vectors aren't normalised.
- **ANN / HNSW** — approximate nearest neighbour via a navigable small-world graph. Trades exactness for speed; `ef`/`numCandidates` is the recall↔latency dial.
- **Reranking** — a cross-encoder rescoring the top-k. Slower per item but far more accurate, because it sees query and document *together* rather than as separate embeddings.
- **Hybrid search** — BM25 keyword + vector, fused. Catches exact terms that embeddings blur.
- **Context window / token budget** — the hard cap on prompt + output. Drives chunk count and truncation decisions.
- **Function calling / tool use** — the model emits a structured call your code executes; the model chooses, your code acts.
- **Structured output** — constraining generation to a schema. Validate on receipt anyway; never trust the model to have honoured its own contract.
- **Groundedness** — is every claim supported by retrieved context? The metric that matters more than fluency.
- **Streaming / SSE** — server→client token-by-token over plain HTTP. One-directional, proxy-friendly.

## Evaluation

- **Precision / recall / F1** — precision: of what you flagged, how much was right. Recall: of what existed, how much you caught. F1: harmonic mean. **Know which one your use case should optimise and why** — a privacy filter wants recall, because a false negative is an unrecoverable leak.
- **Noise floor** — run-to-run variance with everything held constant. Any difference smaller than it is not a result. Establishing it *before* comparing is the senior move.
- **Ablation** — remove one component, remeasure, attribute the delta. The only honest way to say a component earned its place.
- **Golden set** — a fixed labelled dataset you score every release against.
- **LLM-as-judge** — a model scoring output. Useful and cheap; non-deterministic, so a poor release *gate*.
- **Regression gate** — a threshold that blocks a release. Must have three states: pass / fail / **no-data** — and no-data must block, never pass. *(This is the exact bug you found.)*

## Security & multi-tenancy

- **AuthN vs AuthZ** — who you are vs what you may do. 401 vs 403.
- **JWT claims / expiry / scoping** — signed assertions with a TTL. A **purpose-scoped** token works for exactly one thing, so a leak has a bounded blast radius.
- **Replay attack** — reusing a captured valid token. Countered by short TTL, purpose scoping, nonces.
- **RBAC** — permissions attach to roles, users get roles. Contrast ABAC (attribute-based) and ReBAC (relationship-based).
- **Least privilege** — every actor gets the minimum. *Applies to third-party vendors too — that's your voice token.*
- **Prompt injection** — untrusted text in the prompt hijacking instructions. Defences: separate instructions from data, filter I/O, least-privilege tools, tenant-scoped retrieval so injected text can't reach another tenant.
- **404 not 403** — for out-of-scope resources, so existence isn't leaked.

## Ops

- **p50 / p95 / p99** — median and tail latency. Averages hide the tail; users feel the tail.
- **SLO vs SLA** — internal target vs contractual promise with consequences.
- **Horizontal vs vertical** — more machines vs bigger machines. Horizontal needs statelessness.
- **Stateless service** — holds no per-client state between requests, so any instance can serve any request. Prerequisite for horizontal scaling.
- **Load levelling** — a queue absorbing bursts so downstream sees a smooth rate.
