# AI-01 — async vs Celery

## META
- difficulty: medium
- time: 12 min
- tags: concurrency, celery, asyncio, fastapi, bulkhead
- source: `01-async-vs-celery/`

## PROMPT

> "Your resume says the AI Insights layer runs on 'an async task layer on its own dedicated
> Celery queue', and you also list FastAPI. Walk me through the difference between that queue
> and an `async def` endpoint. When a Gemini call takes four seconds — what is waiting, and
> where?"

## CLARIFY

- **"Do you mean within one request, or across requests?"**
  → *"Across. I want to know if you understand they're different axes."*
- **"Is the caller waiting for the result?"**
  → *"No — the insight is generated and stored, read later."*
- **"Should I cover the queue-isolation decision too?"**
  → *"Yes, that's the part I care about."*

## STEP 1 — Scope & stakes

State what the feature is and why latency matters here.

### CHECKPOINTS
- AI Insights generates written narratives from dealership analytics
- Gemini calls take **seconds**, not milliseconds
- The stake: a burst of LLM work must not degrade user-facing traffic
- Nobody is waiting for the narrative → it doesn't belong in a request at all

## STEP 2 — Mechanism

Explain what is waiting, and where, in each model.

### CHECKPOINTS
- **`async def` + `await`**: the *event loop* is free; the **caller still waits 4s**
- **`async def` + blocking call**: freezes the loop → **every concurrent request** in that process stalls
- **plain `def`**: FastAPI runs it in an anyio **threadpool** (≈40 slots) — blocking is safe
- **Celery**: a *separate worker process* waits; the request returns in milliseconds
- Celery is durable — the broker holds the task across a web-server restart
- Names the axes correctly: asyncio = concurrency *in* a process; Celery = work moved *out*

## STEP 3 — Trade-offs

Why a dedicated queue, and why not just more workers?

### CHECKPOINTS
- Names **bulkheading** — isolated capacity per workload
- More workers on one pool raises the threshold, doesn't remove the failure mode
- **Independent tuning** is the killer argument: LLM workers want high concurrency-per-worker (I/O-bound); CPU-bound jobs want the opposite. One pool can't be tuned for both
- Concedes Redis-as-broker is a SPOF; mitigation is Sentinel/HA or managed
- Says what would change the decision (e.g. if LLM volume collapsed, one pool is simpler)

## STEP 4 — Failure modes

What breaks, and how would you know?

### CHECKPOINTS
- LLM queue backs up → **degrades in isolation**; insights stale, app responsive
- Alert on **queue depth**, not just error rate
- Worker dies mid-call → `acks_late=True` so the broker redelivers
- **And** says the second half: only safe because the task is **idempotent**
- `BackgroundTasks` distinction: same process, dies with it, no retries, no visibility
- A failing background task doesn't change the client's response — it already has its 200

## STEP 5 — Scale

Sizing, and what you'd change at 10×.

### CHECKPOINTS
- **Little's Law**: concurrency ≈ arrival rate × service time (2/s × 4s ≈ 8 in flight)
- Measure both terms rather than guessing worker counts
- At scale: Batch API for staleness-tolerant work (trade latency for cost)
- Rate-limit awareness — the provider quota binds before your workers do
- Cost circuit breaker, since queue isolation protects latency but **not spend**

## STEP 6 — Honesty

The weakness, and what the framework did vs what you did.

### CHECKPOINTS
- Volunteers: **queue isolation doesn't cap cost** — a runaway loop still burns Gemini spend
- Separates credit: *Celery* gives retries; *you* chose `acks_late` and made the task idempotent
- No metric claimed here — doesn't invent one
- Optionally cites the measured 2.8× from `lessons/04`

## TRAP

Calling Celery "async", or saying "we made it async so it's faster." Celery makes nothing
faster — it makes the **caller not wait**. And `async def` doesn't speed up a single request
either; it makes the *server* concurrent. Conflating the two vocabularies is the fastest way
to lose this question.
