# async vs Celery — explained

## The one-sentence version

**`asyncio` is about not blocking a thread while you wait. Celery is about not doing the
work in the request at all.** Different problems, different axes, frequently both.

---

## What is actually waiting, in each case

### `async def` + `await` — the event loop waits

One process, one thread, an event loop. When you `await`, the coroutine yields control and
the loop runs *other* coroutines. The OS thread is never idle.

```python
@app.post("/insight")
async def insight(body: Req):
    result = await gemini.generate(body.prompt)   # loop free for 4s
    return result
```

The **caller still waits 4 seconds.** You have not made anything faster — you've made the
*server* able to handle other requests during those 4 seconds.

### The catastrophic version — `async def` + a blocking call

```python
@app.post("/insight")
async def insight(body: Req):
    result = gemini.generate_sync(body.prompt)    # BLOCKS THE EVENT LOOP
    return result
```

Now nothing else in that worker runs for 4 seconds. Not other requests, not health checks.
**One blocking call in one `async def` freezes every concurrent request in the process.**

### Plain `def` — a threadpool thread waits

```python
@app.post("/insight")
def insight(body: Req):
    result = gemini.generate_sync(body.prompt)    # fine — runs in the threadpool
    return result
```

FastAPI runs `def` handlers in an anyio threadpool (40 slots by default). Blocking is safe
because it blocks *a* thread, not *the* loop. **This is why writing `def` is often safer
than `async def`** — the counter-intuitive answer that wins this question.

### Celery — a different process waits, and the caller doesn't

```python
@app.post("/insight")
def insight(body: Req):
    generate_insight.apply_async(args=[body.id], queue="ai_insights")
    return {"status": "queued"}                   # returns in milliseconds
```

The request returns immediately. A **separate worker process** picks the task off Redis and
does the 4 seconds. The caller never waits. The work survives a web-server restart because
the broker holds it.

---

## The decision tree — memorise this

```
Is the caller waiting for the result?
├── NO  → Celery. (Durable, retryable, and the request returns instantly.)
│         Unless it's short + loss-tolerant → BackgroundTasks (same process, no durability).
└── YES → it stays in the request. Now: does every call inside have an `await`?
          ├── YES → async def
          └── NO  → def  (let the threadpool absorb the blocking)
                    ...or async def + `await asyncio.to_thread(blocking_fn)`
```

---

## What your system actually does, and why

The AI Insights layer is **Celery**, because nobody is waiting for a dealership narrative to
be written — it's generated and stored, then read later. That's the "caller isn't waiting"
branch.

The interesting decision isn't Celery, it's the **dedicated queue**:

> Celery routes tasks by queue name; workers subscribe to specific queues. A separate queue
> plus its own worker pool means LLM tasks and ordinary tasks never compete for execution
> slots.

That's **bulkheading** — isolated capacity per workload. Without it, a burst of 4-second
Gemini tasks occupies every worker and every other background job queues behind them.

And the tuning point that proves you understand it: **LLM workers want high
concurrency-per-worker** because they're I/O-bound waiting on an API, whereas CPU-bound jobs
want low concurrency. One shared pool can't be tuned for both. That's the argument against
"just add more workers."

---

## The follow-ups, answered

**1 · "Why not just add more workers to one queue?"**
A bigger shared pool raises the threshold but doesn't remove the failure mode — a big enough
burst still starves everything. And you lose independent tuning, which matters here because
the two workloads want opposite concurrency settings.

**2 · "What if the LLM queue backs up?"**
It degrades in isolation — insights get stale, the app stays responsive. That's the point of
the bulkhead. Add a queue-depth alert, and for staleness-tolerant work move to the Batch API.

**3 · "A worker dies mid-call?"**
`acks_late=True` means the task isn't acknowledged until it completes, so the broker
redelivers. **That's only safe if the task is idempotent** — regenerating an insight for the
same period overwrites one row, so it is. Say both halves; `acks_late` without idempotency is
a duplicate-work bug.

**4 · "Redis as broker is a SPOF."**
Correct — concede it. Mitigation is Sentinel/HA or a managed broker. The blast radius here is
background insight generation, not the request path, so it was an accepted trade.

**5 · "How would you size the pools?"**
Little's Law: concurrency ≈ arrival rate × service time. 2 insights/sec × 4s = ~8 in flight.
Measure both terms rather than guessing worker counts.

**6 · "When `BackgroundTasks` instead of Celery?"**
Short, loss-tolerant work that must not delay the response — send an email, invalidate a
cache, write an audit row. It runs in the **same process** and dies with it: no retries, no
durability, no visibility. The test: *"would I be upset if this silently vanished on a
deploy?"* Yes → Celery.

**7 · "Inside `async def` and must call something blocking?"**
`await asyncio.to_thread(fn)` or Starlette's `run_in_threadpool(fn)`. Never call it directly.

**8 · "Why is `async def` sometimes worse than `def`?"**
Because `def` is defensive: FastAPI moves it to a threadpool, so a blocking call you forgot
about hurts one thread. In `async def` the same call freezes the whole loop. `async def` is a
promise that everything inside awaits — only make the promise if you can keep it.

---

## One-line summary you can say in an interview

> "Celery moved the work out of the request; the dedicated queue was bulkheading so LLM
> latency couldn't starve other jobs. `asyncio` is a different axis — concurrency inside one
> process — and mixing the two vocabularies is where people get into trouble."

## The trap answer to avoid

Calling Celery "async", or saying "we made it async so it's faster." Celery doesn't make
anything faster; it makes the *caller* not wait. And `async def` doesn't make a single request
faster either — it makes the server concurrent.

## Measured proof you own

`~/projects/fastapi-crash-course/lessons/04_async_vs_sync.py` — three concurrent requests,
identical 0.3s of work:

```
/sync-blocking     0.32s   def + time.sleep        -> threadpool, concurrent
/async-blocking    0.91s   async def + time.sleep  -> event loop frozen
/async-await       0.30s   async def + await
/async-offloaded   0.31s   async def + to_thread
```

**2.8× slower for one keyword.** Quoting a number you measured yourself lands far harder than
reciting the theory.
