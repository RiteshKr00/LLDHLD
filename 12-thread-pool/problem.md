# Problem 12: Thread Pool / Task Scheduler (LLD)

*Not yet worked through — this problem was added for pattern coverage. Do Steps 1-3 yourself before reading the solution.*

## The prompt (as an interviewer would give it)

> "Design a thread pool. Callers hand it work; a fixed set of worker threads runs that work.
> The caller should be able to get the result back. And it has to shut down cleanly."

**Why this one is in the set.** Problems 01-11 all *use* a lock to protect state; this one **builds the
coordination primitive itself** — a different muscle:

```
protecting state   "hold the lock while I mutate"          <- problems 02, 04, 08, 09, 11
coordinating       "sleep until someone else changes it"   <- this problem
```

---

## Clarifying questions to ask
1. **Pool size** — fixed at construction, or does it grow and shrink with load?
2. **Queue bound** — bounded or unbounded? If bounded, what happens to the submit that does not fit — one right answer, or swappable per deployment? *(The real design question.)*
3. **Results & cancellation** — fire-and-forget, or can the submitter wait for a value — and change its mind after submitting?
4. **Task failures** — a task raises. Does the worker die? Does the caller ever find out?
5. **Shutdown** — one or two? Does "stop" mean "finish what you started" or "drop everything"? Can a running task be stopped?
6. **Ordering** — strict FIFO, or priorities / delays?
7. **Workload shape** — CPU-bound or IO-bound? *(Decides the thread count, and whether threads are the right tool in CPython at all.)*

## Clarifications (locked scope from Q&A)
1. **Fixed size** at construction. Elastic resizing (core vs max threads, idle reaping) is out of scope.
2. **Bounded**, capacity at construction, and the **rejection policy is pluggable** — abort, block, discard-oldest, caller-runs. An unbounded queue is not a queue, it is a memory leak with extra steps.
3. **`submit()` returns a `Future` immediately**, waitable with an optional timeout. **`cancel()`** succeeds only while the task is still `PENDING`.
4. **A task exception must NOT kill its worker and must NOT vanish** — it is parked on the `Future` and re-raised in the *caller's* thread.
5. **Two:** `shutdown()` stops accepting and drains queued + in-flight work; `shutdown_now()` also abandons the backlog and hands it back. **Neither stops a task already executing.**
6. **Strict FIFO.** Priority / delayed scheduling out of scope — a heap plus a timer thread, a different problem.
7. **Both**, and the design must be honest about the GIL. The demo measures it rather than asserting it.

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- [x] **`submit(fn, *args, **kwargs) -> Future`** — returns immediately; the Future gives `result(timeout)`, `exception()`, `done()`, `state()`, `cancel()` (cancel wins only while `PENDING`)
- [x] **M fixed workers** consume **one bounded queue** — the cap is a hard ceiling and the backpressure knob; the submit that does not fit triggers a **pluggable rejection policy**
- [x] **`shutdown()`** — stop accepting, **drain** queued + in-flight, retire every worker; **`shutdown_now()`** also **abandons** the backlog and **returns** it
- [x] **`stats()`** — queued / active / completed / failed / rejected; you cannot tune a pool whose queue depth you cannot see

### Non-functional (constraints — the "-ilities")
- [x] **No busy-waiting** — an idle worker must consume **zero** CPU, not poll a flag in a loop
- [x] **Every Future settled exactly once, on every path** — success, exception, cancel, discard, abandon. An unsettled Future is a caller blocked forever, which is worse than an error
- [x] **Fault isolation (bulkhead)** — one poisonous task must not kill a worker or take the pool down
- [x] **Deterministic shutdown** — bounded time, no thread left alive, no hang, idempotent

### Explicitly out of scope (say this out loud — it is a senior move)
- Elastic resizing · priority / delayed scheduling · work stealing · task chaining (`then`) · persistence across restarts · a distributed queue · killing a running task · process pools

> 📝 **Trap (Step 1):** the easy Step 1 lists the verbs and stops. The requirements that shape the code are the ones nobody writes down: **"an idle worker burns no CPU"** (forces `Condition.wait()` over a polling loop) and **"every Future is settled on every path"** (stops a caller hanging forever when a task is discarded or abandoned). Third miss: **"unbounded queue"**, tempting because it makes `submit()` never fail — reject it out loud, it turns a *throughput* problem into an *OOM crash* and moves the failure from the submitter (who could retry) to the process (which cannot).

---

## Step 2 — Entities  (nouns → classes)
_Format: `Name — single responsibility — key attributes/methods`_

1. **TaskState** *(Enum)* — the label a caller reads back — `PENDING, RUNNING, SUCCESS, FAILED, CANCELLED`
2. **Future** — the caller's handle on a value that does not exist yet: blocks until it arrives, and carries an exception across the thread boundary — `_done: Event, _value, _exc, _state` · `result()`, `exception()`, `cancel()`, `set_result()`, `set_exception()`, `_start()`
3. **Task** — the envelope through the queue: what to call, with what, and where the answer goes — `task_id, fn, args, kwargs, future` · `run()`
4. **BoundedBlockingQueue** — the hand-off point and the only real primitive here: producers sleep when FULL, consumers when EMPTY, closing wakes everyone — `_items: deque, _lock, _not_empty/_not_full: Condition, _closed` · `offer()`, `offer_evicting()`, `put()`, `take()`, `close()`, `drain()`
5. **RejectionPolicy** *(Strategy, ABC)* — what "the queue is full" means here — `rejected(task, pool)` — with **AbortPolicy** (raise) · **BlockPolicy** (park the submitter) · **DiscardOldestPolicy** (evict the head **and fail its Future**) · **CallerRunsPolicy** (run it on the submitting thread)
6. **Worker** *(threading.Thread)* — a three-line loop `take() → run() → repeat`, retiring when `take()` returns `None` — `completed` · `run()`
7. **ThreadPool** — orchestrator; owns the queue, the workers and the policy — `submit()`, `shutdown()`, `shutdown_now()`, `await_termination()`, `stats() -> PoolStats`, `worker_load()`

### The data-vs-behaviour test — this problem has one of each

| Candidate | Do the variants DO different work? |
|---|---|
| `TaskState` | **No → DATA → enum.** Nothing branches on state to run different logic; they are labels. Contrast the elevator, whose `step()` did different work per state — *that* earned State |
| `RejectionPolicy` | **Yes → BEHAVIOUR → Strategy.** Raise vs sleep vs evict vs execute inline — four genuinely different bodies, and no table of flags expresses that |

### YAGNI — one pattern, and the pain that bought it

| Deployment | Right answer when the queue is full, and why |
|---|---|
| API front-end | **Abort** — the LB needs a 429 to shed load; a blocked request thread is worse than a fast failure |
| Batch ingest | **Block** — a fast reader *should* be throttled by a slow writer, and there is nobody to return an error to |
| Metrics / telemetry | **DiscardOldest** — stale samples are worthless; the newest reading is the valuable one |
| CLI tool | **CallerRuns** — no queue growth, no dropped work, the main thread self-throttles |

Four deployments, four behaviours, one unchanged `ThreadPool`. Nothing else earns a pattern: no Factory
(one kind of worker), no Observer (nobody subscribes), no State (see above).

> 📝 **Trap (Step 2):** two entities go missing. **`Future`** — "run this function" does not sound like it needs a noun, but without it there is nowhere for a return value to land and, worse, **nowhere for an exception to go**. And **the queue as a class you write** — easy to list "a queue" and substitute `queue.Queue`, the very thing being rebuilt; owning it is what makes the good shutdown possible (Step 3).

---

## Step 3 — Relationships & APIs

```
ThreadPool ──owns──▶ BoundedBlockingQueue (one, shared)  ──owns──▶ Worker[] (fixed M)
           ──uses (DI)──▶ RejectionPolicy (default Abort)    Task ──holds──▶ Future

  submitter                queue (cap N)              M workers
     │  submit(fn) ──▶ [ t3 | t2 | t1 ] ──take()──▶  ┌ w0 ┐
     │  ◀── Future                                    │ w1 │ ── task.run()
     │  result() ── blocks on Event ◀───────set───────┴ w2 ┘
```

```python
def submit(self, fn, *args, **kwargs) -> Future   # never blocks on the happy path
def shutdown(self, wait=True, timeout=None) -> bool          # stop accepting, DRAIN
def shutdown_now(self) -> List[Task]                         # returns the abandoned backlog
def offer(self, task) -> bool                     # non-blocking; False = full
def offer_evicting(self, task) -> Optional[Task]  # evict head + append, ONE lock hold
def put(self, task, timeout=None) -> bool         # blocks; False = timed out
def take(self) -> Optional[Task]                  # blocks; None = closed AND drained
def rejected(self, task, pool) -> None            # RejectionPolicy (Strategy)
def result(self, timeout=None) -> Any             # Future — RE-RAISES the task's exception
def cancel(self) -> bool                          # True only while PENDING
def run(self) -> None       # Task.run never raises; Worker.run is the take-loop
def suggest_pool_size(io_bound, wait_ms=0.0, service_ms=1.0) -> int
```

### Why the worker must BLOCK, not spin

```python
while True:                       # ❌ busy-wait
    if self.queue:
        task = self.queue.popleft(); task.run()
```

That pins a **whole core at 100%** doing nothing, and under the GIL it is worse than wasteful: the
spinner holds the GIL to re-test `if self.queue` thousands of times a second, **stealing bytecode slots
from workers with real work**. `time.sleep(0.01)` only trades CPU for **latency**. `Condition.wait()`
parks the thread on an OS wait queue — zero CPU — until a producer notifies.

- **`while`, never `if`, around `wait()`** (spurious wakeups, and the *stolen wakeup*: you are notified but must re-acquire the lock, and another thread takes the item in that gap) — and **notify the OTHER condition after changing the size**: `take()` removes so it signals `_not_full`, `put()` adds so it signals `_not_empty`. Signalling the wrong one is the classic mysterious hang

**Check-then-act, the 9th appearance:** `if not queue.full(): queue.put(task)` lets two submitters see
one free slot and both put. Same fix as `save_if_absent` (01) and `find→claim` (11) — **push atomicity
into the shared store**: `offer()` tests capacity *and* appends under the queue's own lock. Three more
of the shape: `is_shutdown()`-then-enqueue, `poll_oldest() + offer()` for DiscardOldest (frees a slot,
**releases the lock**, a racing producer steals it — hence `offer_evicting()`), and `cancel()` versus a
worker starting the task.

### Graceful shutdown — poison pill vs flag

| Approach | How it stops a worker, and what it costs |
|---|---|
| **Poison pill** — push N sentinels, one per worker | Instant, respects FIFO. But it **deadlocks on a bounded queue that is full**: pushing N pills blocks, so `shutdown()` waits on the workers it is stopping. Needs the worker count, and leaves `shutdown_now()` fishing pills out of the drained list |
| **Flag + timeout poll** — `take(timeout=0.1)`, re-check a flag | Always works, no deadlock. Costs a wakeup per worker per interval **forever** (a slow busy-wait), and shutdown is late by up to the interval |
| **Flag inside the wait predicate** ← **chosen** | `close()` sets `_closed` and `notify_all()`s: parked workers wake immediately, `take()` returns `None` once the backlog is gone. Instant like the pill, safe on a bounded queue like the flag, **zero idle wakeups** |

```python
while not self._items and not self._closed:   # <- the flag IS part of the predicate
    self._not_empty.wait()
if not self._items:
    return None            # closed AND drained -> this worker retires
```

Closed-but-not-empty keeps serving, so the backlog **drains** — that predicate *is* graceful shutdown.
`close()` must `notify_all()`: one `notify()` wakes one worker, the rest sleep forever and `shutdown()`
hangs on `join()`. Both calls reject new work with `PoolShutdownError` and differ only on what is
already in the system:

| Fate of… | `shutdown()` vs `shutdown_now()` |
|---|---|
| Work already **queued** | `shutdown()` **runs it** — the queue drains · `shutdown_now()` **abandons it**, fails its Future with `TaskAbandonedError`, and **returns** the `Task` so the caller can requeue it |
| Work already **running** | both let it **run to completion** — **neither can stop it** |

**Say this out loud:** Python has no safe thread kill (`Thread.stop()` was removed because it can release
a lock mid-mutation); Java's `interrupt()` is only a *request* the task must check. The honest contract
is **"no NEW work starts"** — stopping live work needs a flag the task itself polls.

### The exception path

```python
try:
    value = self.fn(*self.args, **self.kwargs)
except BaseException as exc:         # <- BULKHEAD: settle FIRST...
    self.future.set_exception(exc)
    if not isinstance(exc, Exception):
        raise                        # ...THEN propagate SystemExit / KeyboardInterrupt
else:
    self.future.set_result(value)
```

The usual advice — "catch `Exception`, not `BaseException`" — gets the **order** wrong, not the width:
follow it literally and a task calling `sys.exit()` leaves its Future never settled and its caller
blocked forever. That `except` **is** problem 07's bulkhead, and `Worker.run()` wraps `task.run()` in a
second one — isolation belongs at **every** boundary, not just the innermost.

### Thread count is a decision, not a constant

```
CPU-bound:  threads ≈ cpu_count()
            more threads than cores buys context switches and cache thrash, not throughput

IO-bound:   threads ≈ cpu_count() * (1 + wait_time / service_time)
            90ms waiting on a socket per 10ms of compute -> ratio 9 -> ~10x cores
            those threads are asleep in a syscall, not competing for CPU
```

Cap it from above by the downstream: 200 threads against a 20-connection DB pool just moves the queue
somewhere with a worse error message. And say the GIL out loud — one thread executes bytecode at a
time, so four threads of pure-Python arithmetic gain nothing but switching overhead, while IO wins
because the GIL is **released** around blocking syscalls. **Threads for IO, processes for CPU.**

> 📝 **Trap (Step 3):** the failure invisible until production — **an unsettled Future**. It happens on the paths nobody thinks about: `DiscardOldestPolicy` evicts a queued task and forgets to fail its Future; `shutdown_now()` drops the backlog and forgets theirs; a task raises and the code only called `set_result()` on the happy path. **Whatever removes a Task owns settling its Future.** A hang is worse than an error, because an error has a stack trace.

> 📝 **Trap (Step 3):** do not answer the sizing question with a number. `cpu_count()` for a pool that spends its life waiting on HTTP calls leaves the machine ~90% idle; 200 threads for CPU-bound work makes it slower than one. The answer is the ratio formula plus "measure it", plus the GIL caveat.

---

## REST API mapping  (LLD method -> HLD endpoint)

A thread pool is a **library**, not a service — but the moment it becomes a **job/worker service** the
mapping is exact, and the rejection policies are literally status codes:

| LLD method | HTTP |
|---|---|
| `submit(fn, *args)` | `POST /api/v1/jobs` -> **202 Accepted** `{job_id}` · **429** queue full (AbortPolicy) · **503** shutting down |
| `Future.state()` / `result(timeout)` | `GET /api/v1/jobs/{id}?wait=5s` -> **200** `{state, result?, error?}` · **404** unknown · **504** if the wait expires (the job keeps running) |
| `Future.cancel()` · `stats()` · `shutdown()` | `DELETE /jobs/{id}` -> **204** · **409** already running · `GET /admin/pool` -> **200** · `POST /admin/drain` -> **202** |

> **`202`, not `201`** — the work is *accepted*, not *completed*. And **a failed job is still a 200**: the
> read succeeded and faithfully reports `{"state": "FAILED"}`; a 500 conflates "your task raised" with
> "my API is broken". **`/admin/drain` is the Kubernetes story** — on SIGTERM fail the readiness probe,
> call `shutdown()`, let `terminationGracePeriodSeconds` cover the drain. A pod that hard-exits drops
> every in-flight job: the same bug as `shutdown_now()` where `shutdown()` was meant.

## Notes / decisions (log the "why" here)
- **Bounded queue, always** — unbounded turns a throughput problem into an OOM crash and moves the failure from the submitter (who could retry) to the process (which cannot).
- **`RejectionPolicy` is the one pattern (YAGNI)** — the pain varies by *deployment*, not by task: 429 for an API, block for batch, discard-oldest for telemetry, caller-runs for a CLI.
- **`TaskState` = enum, `RejectionPolicy` = Strategy** — one problem holding both halves of the data-vs-behaviour test.
- **Flag-in-the-predicate over poison pills**, and `close()` uses `notify_all()`, never `notify()`.
- **Whoever removes a Task owns settling its Future** — discard, abandon, cancel, raise: every path ends with the `Event` set.
- **Catch `BaseException` in `Task.run`, settle, then re-raise the non-`Exception` ones.** The order is the senior detail, not the width.
- **Two `Condition`s over one shared `Lock`** — producers and consumers wait for different things; waking all of them so most go back to sleep is a thundering herd.
- **`await_termination(timeout)` budgets ACROSS workers, not per worker** — `for w in workers: w.join(1)` with 8 workers can take 8 seconds, and the caller who set a 1-second bound never learns why the SLA blew.

> 📝 **Trap (Step 4 build):** the demo *is* the design here, and a concurrency demo that only passes *sometimes* proves nothing. Any test of "the queue is full" must first wait until a worker has genuinely *picked up* the blocking task — `submit()` returns before any worker has dequeued anything, so without a `threading.Event` handshake the blocker is still in the queue and the arithmetic is off by one. And prove what a print cannot fake: a wakeup counter on the queue (idle pool shows **0**), the *slowest* task submitted first so "results in order" is the futures list working rather than luck, and CPU- vs IO-bound **timed** at 1 and 4 workers rather than asserted.
