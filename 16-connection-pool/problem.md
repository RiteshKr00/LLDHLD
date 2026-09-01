# Problem 16: Connection Pool (LLD)

*Not yet worked through — this problem was added for pattern coverage. Do Steps 1-3 yourself before reading the solution.*

## The prompt (as an interviewer would give it)

> "Design a connection pool. Opening a database connection is expensive, so we keep a bounded set
> of them around and hand them out. Callers `acquire()` one, use it, and `release()` it back."

Sounds like a wrapper around a list. It is not. **The borrower is not trustworthy** — that single
fact generates every hard question in this problem, and four of the seven verbs in Step 1.

---

## Clarifying questions to ask
1. **What is pooled, and how expensive is one?** *(If creating one is cheap, there is no pool. Ask this first.)*
2. **Sizing** — a minimum idle floor and a hard maximum? Opened up front or on demand?
3. **Exhaustion** — every connection is out and a caller asks for one: block, fail fast, or grow past the max? If block, for how long? *(The core decision.)*
4. **Leaks** — what happens when a borrower never returns its connection? Log it, or take it back by force?
5. **Staleness** — can a pooled connection die while it sits idle? Validate on borrow, on return, or on a sweep?
6. **Concurrency and fairness** — how many threads share one pool, and are waiters served FIFO or is a barge-in acceptable?
7. **Lifecycle** — is a clean shutdown needed, and what happens to connections still out on loan?

## Clarifications (locked scope from Q&A)
1. Fake in-process connections, assumed expensive to open — that *is* why a pool exists. A `FakeConnection` with an `is_alive` flag, **no real sockets**, so the file runs anywhere.
2. A `min_idle` **floor** and a hard `max_size` ceiling, **created lazily** — the pool starts empty and grows to demand; `min_idle` is a floor the sweep refills to, not a warm-up.
3. **Block with an explicit timeout, then raise `PoolExhaustedError`.** Never forever. Fail-fast is the same path with `timeout=0`; "grow past the max" is not a policy, it is a bigger `max_size`.
4. **Both, configurable:** `LeakPolicy.LOG` (safe default) and `LeakPolicy.RECLAIM` (revoke the lease, destroy the connection, refuse the late `release()` with `ConnectionRevokedError`).
5. Yes. **Validate on borrow** plus a `max_idle_seconds` age cap, validate-on-return as an option, and a `sweep()` for stale idle ones. A pool handing out corpses is worse than no pool.
6. Many threads, one pool, one lock, correct under heavy contention. **Barge-in accepted** — a plain condition variable makes no fairness promise; FIFO noted as the upgrade with its cost.
7. Yes — `close()`. Idle connections destroyed immediately, in-flight ones as they come back (never re-pooled), and new `acquire()` calls raise `PoolClosedError`.

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- **`acquire()` / `release()`**, plus a context manager — `with pool.connection() as conn:` gives it back even if the body raises
- Create connections **lazily** up to `max_size`; keep a `min_idle` floor of warm spares
- **Exhaustion:** block up to an explicit timeout, then raise **`PoolExhaustedError`** — never forever
- **Leak detection:** track borrow time; past `leak_threshold`, either log it or forcibly reclaim it
- **Health check:** validate on borrow plus an idle-age cap, and evict stale idle ones on a `sweep()`
- **Ownership:** reject a **double release** and an **alien release** (never issued here) — both raise
- **`stats()`** — size / idle / in_use / waiting / timeouts / leaks: the numbers you page on — and **`close()`**

### Non-functional (constraints — the "-ilities")
- **Thread-safe and bounded** — "is one free?" and "take it" must be ONE critical section; never exceed `max_size`, never block a caller forever
- **Self-healing, swappable, observable** — a leaked or dead connection comes back without a human noticing; pooling Redis instead of Postgres is a new subclass, not an edit; exhaustion and leaks must be countable

### Explicitly out of scope (say this out loud — it is a senior move)
- Real drivers · async pools · multi-datasource routing · per-tenant pools · prepared-statement caching · retry-on-failover · a distributed connection limit · strict FIFO

> 📝 **Trap (Step 1):** the requirement almost everyone omits is what `acquire()` does when the pool is **empty** — an acquire with no timeout is an unbounded hang, which surfaces as "the whole service froze" rather than as an error, so nothing pages and nobody can find it. Write the timeout into the requirements, not into the code as an afterthought.

---

## Step 2 — Entities  (nouns → classes)

1. **FakeConnection** — the pooled resource, fake so the file runs with no network — `conn_id, is_alive, created_at, idle_since, use_count`; `execute(sql)`, `close()`
2. **ConnectionFactory** *(ABC)* → **FakeConnectionFactory** — `create()`, `validate(conn)`, `destroy(conn)`, all three `@abstractmethod`; the pool knows nothing about what it pools
3. **PoolConfig** *(frozen dataclass)* — every knob in one object — `min_idle, max_size, acquire_timeout, max_idle_seconds, leak_threshold, validate_on_borrow, validate_on_return`, plus `leak_policy`: a **LeakPolicy** *(Enum)* of `LOG` (HikariCP's `leakDetectionThreshold`) or `RECLAIM` (DBCP's `removeAbandoned`)
4. **Lease** — the borrow record, one per connection out — `conn, borrower, borrowed_at, revoked, leak_reported`; `age_seconds()`. Skipped by almost everyone, because a `set` of borrowed connections looks sufficient. It is not: without a Lease the pool knows only *how many* are out, and **who holds what since when** is what makes leak, double-release and alien-release detection possible at all
5. **PoolStats / SweepReport** *(frozen snapshots)* — `size, idle, in_use, waiting, created, destroyed, borrowed, timeouts, stale_discarded, leaks_reclaimed` · and per sweep: `leaks_found, leaks_reclaimed, stale_evicted, refilled`
6. **PoolGuard** — the context manager `pool.connection()` returns — `__enter__` acquires, `__exit__` releases
7. **ConnectionPool** — the orchestrator, and the only thing holding a lock — `acquire()`, `release()`, `connection()`, `sweep()`, `stats()`, `close()`
8. **The exception family** — `PoolError` base, with `PoolExhaustedError`, `PoolClosedError`, `DoubleReleaseError`, `UnknownConnectionError`, `ConnectionRevokedError`, `ConnectionDeadError`, `ConnectionCreationError`

**The state, all under one lock:** `_idle: deque` (free) · `_in_use: dict[conn_id → Lease]` (on loan) ·
`_all: dict[conn_id → conn]` (owned) · `_revoked: set[conn_id]` · `_waiting` · `_closed`.

### The data-vs-behavior test, applied twice in one problem
| Axis | Differs by | Verdict |
|---|---|---|
| The resource pooled (Postgres / Redis / fake) | **BEHAVIOUR** — opening, probing, closing are different code | **Polymorphism** — `ConnectionFactory` ABC, injected |
| The exhaustion policy (fail fast / block / grow) | **DATA** — fail-fast is `timeout=0`, block is `timeout=T`, grow is a bigger `max_size` | **A parameter.** Three "policies", one code path, one float |
| The leak policy (log / reclaim) | **DATA** — two short branches differing in bookkeeping, not shape | **Enum + branch**; Strategy when a third needs real logic |

> 📝 **Trap (Step 2):** the reflex is an `ExhaustionStrategy` hierarchy, because "block / fail fast / grow" sound like three behaviours — run the test first: fail-fast *is* `timeout=0` and growing *is* a larger `max_size`, so three classes would exist to express one number. **The pain that does justify a hierarchy is the factory** — pooling something that is not a DB connection is real, and it is different code.

---

## Step 3 — Relationships & APIs

```python
# Pool ──uses (DI)──▶ ConnectionFactory (ABC) ──▶ FakeConnectionFactory
#      ──tracks────▶ a Lease per borrow ·  ──creates──▶ PoolGuard ──▶ acquire / release
class ConnectionPool:
    def __init__(self, factory: ConnectionFactory, config: PoolConfig = None) -> None
    def acquire(self, timeout: float = None) -> FakeConnection
    def release(self, conn: FakeConnection) -> None
    def connection(self, timeout: float = None) -> PoolGuard    # the `with` form
    def sweep(self) -> SweepReport
    def stats(self) -> PoolStats
    def close(self) -> None
```

### `acquire()` — the whole problem, in one critical section
```
with self._cv:                        # ONE lock, held across all three steps
    while True:
        1. an idle connection?   -> validate it; a stale one is destroyed, keep looking
        2. room to grow?         -> len(_all) < max_size -> create one LAZILY
        3. neither               -> wait(remaining); on deadline -> PoolExhaustedError
```
- Steps 1-2 must sit in the **same** `with` block as the take (`if self._idle:` in one locked block and `popleft()` in another is the check-then-act race); `cv.wait()` **releases the lock**, so loop and re-check (`while True`, never `if`); and the deadline is computed **once** up front on `time.monotonic()` — recomputing it after each wake turns 5 seconds into an unbounded wait.

**The check-then-act race, 8th appearance** — `exists+save` · `find+claim` · `get+set` · `balance+=` ·
matchmaking · `check+hold` · `find→claim` · now **`is-one-free? → take-it`**. Same fix every time —
**push atomicity into the shared store**: one lock across both halves in-process, `BLPOP` on a list of
connection tokens in Redis, the DB's own connection limit across processes.

### Exhaustion — the core decision (same shape as the thread pool's queue-full policy)
| Option | What it costs | Verdict |
|---|---|---|
| **Block forever** | The caller hangs, threads pile up behind it, and it looks like a freeze rather than a failure — so nothing pages | **Never.** The worst outcome |
| **Block with a timeout** | Waits out a transient spike, then returns a real error the caller can retry or shed | **Chosen.** `acquire_timeout` → `PoolExhaustedError` |
| **Fail fast / grow past the max** | Fail-fast turns a 5ms spike into a user-visible error; unbounded growth is the thing a pool exists to prevent — the DB falls over instead of your service | **Neither is a policy** — one is `acquire(timeout=0)`, the other a larger `max_size` |

> A pool timeout must be **shorter** than the caller's own request timeout, or the client has already
> given up while your thread politely waits for a connection nobody wants any more.

### Leak detection — the TTL/lease theme again
`Lease.borrowed_at` + `leak_threshold` = a lease with a deadline; `sweep()` finds every borrow past it.
**A reclaimed connection is destroyed, never returned to the idle set** — the leaker may still be
mid-query on it, and re-issuing it would hand one connection to two owners, the exact bug the lock
prevents. Third appearance after movie booking's seat hold and food delivery's reaper: **any resource
handed to a caller who might die needs a lease, not a handshake.**

### Health checking — three places to validate, three tradeoffs
| Where | Cost | Catches / misses |
|---|---|---|
| **On borrow** | A round trip on **every** `acquire()`, straight onto the hot path | Everything, right before it matters — but the most expensive |
| **On return** | Off the hot path; the borrower pays | What the borrower broke; misses one dying *later*, while idle |
| **Background sweep** | Amortised, costs the caller nothing | Idle rot in bulk; misses anything dying between sweeps |

**Chosen: borrow + a `max_idle_seconds` age cap (free, no probe) + the sweep.** The age cap is what
makes borrow-validation affordable — a connection returned milliseconds ago needs no probe. HikariCP
does exactly this; its `keepalive` thread is the sweep.

### Ownership — both bad releases must RAISE, and the `with` form is what prevents them
```
release(conn):  in _in_use -> normal return  |  with pool.connection() as conn:
   in _revoked -> ConnectionRevokedError     |      conn.execute("SELECT 1")
   in _all     -> DoubleReleaseError         |  #  __enter__ -> acquire
   otherwise   -> UnknownConnectionError     |  #  __exit__  -> release, ALWAYS
```
Silently accepting a double release is the worst of the three: the same object lands in `_idle` twice
and the next two callers get **the same connection** — the check-then-act bug, back through a lenient
error path. And discipline does not prevent leaks, code review does not prevent leaks — `finally`
does: the guard is the **Pythonic RAII** (destructors, try-with-resources, Go `defer`).

> 📝 **Trap (Step 3):** the sweep's probe must **not** be gated on `validate_on_borrow` — sharing one "is this usable?" helper between borrow and sweep is the obvious refactor, and it quietly means that turning the hot-path probe off (*the entire reason that flag exists*) turns the **background** probe off too, leaving no health check anywhere. Make the probe a parameter: borrow passes the flag, the sweep passes `True`.

> 📝 **Trap (Step 3):** `__exit__` returning `True` **swallows the body's exception** — and the mirror image nobody sees coming is that `__exit__` raising its **own** exception erases it just as completely, which `LeakPolicy.RECLAIM` makes reachable in normal operation: the reaper revokes the lease mid-body, so the `release()` inside `__exit__` raises and the real bug is gone. Return `False`, and wrap that release so the body's exception wins when there is one.

> 📝 **Trap (Step 3):** `time.time()` is the **wall clock**, which NTP or DST can move, so a timeout on it fires early or never — use `time.monotonic()` for durations. *(Movie booking's hold expiry is wall-clock on purpose: "held until 7:05 PM" is a business fact shown to a user.)*

---

## REST API mapping  (LLD method -> HLD endpoint)

**A connection pool is a library, not a service** — like the text editor. It surfaces in two ways:
the **status code** a request returns when the pool is the bottleneck, and the **operational
endpoints** that let you see it coming.

| LLD event / method | HTTP |
|---|---|
| `PoolExhaustedError` / `PoolClosedError` | **503 Service Unavailable** + `Retry-After` — a capacity signal, NOT a 500 |
| `ConnectionDeadError` / `ConnectionCreationError` | **502 Bad Gateway** — the dependency is down, not your code |
| `ConnectionRevokedError` (reclaimed leak) | **410 Gone** — the lease you held was withdrawn; acquire a fresh one and retry |
| `stats()` | `GET /api/v1/admin/db-pool` → **200** `{size, idle, in_use, waiting, timeouts}`; `/health/ready` → **503** unless `acquire(timeout=0.1)` succeeds |

> **`waiting` is the metric that predicts the outage.** Above zero and rising means the pool *is* the
> bottleneck and your p99 is queueing time — the fix is a bigger pool or faster queries, and no amount
> of application-server scaling helps. `sweep()` finding leaks is an **alert**, not an endpoint, and
> `close()` is the `SIGTERM` handler.

> 📝 **Trap (REST mapping):** exhaustion mapped to **500** is the classic error and it is actively harmful — it tells on-call "the code crashed" when the truth is "we are at capacity", and it makes clients and load balancers retry the wrong way. The errors that genuinely *are* 500s are the caller bugs: `DoubleReleaseError` and `UnknownConnectionError`.

## Notes / decisions (log the "why" here)
- **Pair this with problem 12 (thread pool)** — same two hard questions (what happens when the resource runs out, how you shut down cleanly), answered in **opposite directions**: the thread pool's rejection policy really does run different code per option (caller-runs / discard-oldest / abort), so Strategy earns its place there and a parameter is right here. **The axis of variation decides, not the vocabulary.**
- **YAGNI.** The only injected abstraction is `ConnectionFactory`, and its pain is concrete: pooling something that is not a DB connection, and keeping this file runnable with no network. No `ExhaustionStrategy`, no `HealthCheckStrategy`, no `PoolBuilder` — a frozen `PoolConfig` carries eight knobs.
- **`min_idle` is maintained by `sweep()`, not `release()`** — refilling on the hot path puts a 50-200ms open inside a `release()`. Cost, stated honestly: with no sweep running, `min_idle` does nothing. Same reasoning says a production pool creates **outside** the lock; this one does not (correct first, then narrow).
- **Lazy over eager prefill.** Lazy = fast boot, one slow first request. Eager (HikariCP prefills) = slow boot, no cold-start spike. Lazy matches the locked scope.
- **One lock, not one per field** — the invariant that matters (`idle + in_use <= max_size`) spans every field. And **`notify_all()`, not `notify()`**: a spurious wake costs one re-check against a deadline, a missed wake costs a full timeout.
- **Barge-in, not FIFO.** A condition variable makes no fairness promise, so a lucky arrival can beat a long waiter. The fix is a ticket queue, which costs a data structure and can *lower* throughput by forcing handoffs. Name the tradeoff rather than pretend it is not there.
- **`validate()` is a question, so it must never raise.** A real probe is `SELECT 1`, which on a closed socket raises rather than returning `False`; if that escapes, the connection sits in no collection at all while still counting against `max_size` — one leaked slot per corpse. One non-throwing helper wraps every probe, and the idle set is drained peek-then-pop.
- **The demo proves rather than asserts** — reuse timed on the clock (cold ~50ms, warm ~0ms), the timeout firing at a measured 0.25s while `timeout=0` returns in ~0.0000s, a waiter woken by a `release()` and not by its timeout, 60 threads over a pool of 4 with zero double-holds, and `close()` ending with `created == destroyed`.
