# Problem 14: Logging Framework (LLD)

*Not yet worked through — this problem was added for pattern coverage. Do Steps 1-3 yourself before reading the solution.*

## The prompt (as an interviewer would give it)

> "Design a logging framework — the thing an application calls to record what it is doing.
> Levels, several destinations, different formats per destination."

Deceptively familiar: everyone has *used* one, almost nobody has *designed* one. Two things are
being probed — **can you compose behaviour without an explosion of subclasses**, and **can you defend
a global when the rest of your design is dependency-injected.**

---

## Clarifying questions to ask
1. **Levels** — which severities, a total order, and will they grow later? *(the enum-vs-classes test)*
2. **Destinations** — how many sinks per logger, and does each get its OWN threshold and OWN format?
3. **Filtering beyond severity** — predicate filters (`app.db.*`, `tenant=acme`), or is level enough?
4. **Cross-cutting behaviour** — request context, off-thread buffering, throttling a hot loop — must they combine freely? *("freely combinable" is the Decorator tell)*
5. **Namespace** — flat, or hierarchical (`app.db.query` inheriting from `app.db`)? Can a subtree stop propagating?
6. **How does a caller get a logger** — global or injected? If global, how does a test isolate it? *(the Singleton question — do not let it pass)*
7. **Call-site cost** — is the message string built at the call site, or only if the level passes?
8. **Concurrency** — must a record stay intact? May writes block the caller? What when a queue fills?

## Clarifications (locked scope from Q&A)
1. **Levels:** five — `DEBUG < INFO < WARN < ERROR < FATAL`, a total order, numbered in **10s** so `TRACE=5` / `NOTICE=25` slot in later without renumbering.
2. **Destinations:** **many** handlers per logger, each with its own threshold AND its own formatter — one record leaves as a human line on the console *and* as JSON in a file.
3. **Filters:** in scope, as a small predicate abstraction (name prefix, context key), separate from the level comparison.
4. **Cross-cutting:** three wrappers — **context enrichment, async buffering, rate limiting** — **combinable in any order, at runtime, from config**.
5. **Namespace:** hierarchical, dot-separated. Level inherited from the nearest configured ancestor; records propagate UP unless a node sets `propagate=False`.
6. **Access:** module-level `get_logger(name)` over a process-wide registry, with a documented seam (`set_registry` / `use_registry`). The registry class stays an ordinary injectable object.
7. **Call-site cost:** **lazy** — pass `template, *args`, joined only if a sink will actually write, and memoised so a fan-out to N sinks renders once.
8. **Concurrency:** one record's output is **indivisible**; async writes never block the caller; a full queue **drops and counts**. **Out of scope:** rotation, syslog/network sinks, tracing, shipping, search, retention.

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- **Log** at five ordered levels — `debug / info / warn / error / fatal(template, *args, **context)`
- **Fan out** one record to **many handlers**, each with its OWN level and OWN formatter — suppressed at the **logger**, then again independently at **each sink**
- **Format** (human line, or one-line JSON for a shipper) and **filter** on what severity cannot express — name prefix, context key
- **Wrap** a handler to add behaviour — enrich, buffer asynchronously, rate-limit — and **close** the chain cleanly (drain queues, flush pending counts)
- **Resolve a logger by dotted name**, auto-creating ancestors (`app.db.query` → `app.db` → `app` → root), **inheriting** level from the nearest configured one and **propagating** up unless a node turns it off

### Non-functional (constraints — the "-ilities")
- **Composable** — wrappers must combine in any order **without a class per combination**; a new sink is one `write()`, a new format one `format()` ← the requirement that names Decorator
- **Thread-safe** — writes must not interleave *within* one record, and `get_logger` must not hand two threads two different objects for one name
- **Low overhead on the disabled path** — a suppressed `debug()` must not build a string ← this is what makes the API `(template, *args)` and not an f-string
- **Never crash the host, and still be testable** — a broken sink degrades itself, not the request; the global registry must be swappable

### Explicitly out of scope (say this out loud — senior move)
- Rotation · syslog/network sinks · tracing & spans · shipping, search, retention · config hot-reload · multi-process aggregation

> 📝 Trap (Step 1): "extensible" is a Strategy/Decorator tell, but here it points at THREE seams — **sink**, **format**, **behaviour**. One bullet mashing them together produces a `Handler` that formats, filters, throttles *and* writes: the god-class this problem exists to avoid.

> 📝 Trap (Step 1): the low-overhead NFR looks like a nice-to-have, gets dropped, and Step 3 then quietly designs `log(message: str)` — which makes the NFR unachievable, because the caller already paid for the string before the framework saw it.

---

## Step 2 — Entities  (nouns → classes)
_Format: `Name — single responsibility — key attributes/methods`_

1. **LogLevel** *(IntEnum)* — the severity ORDER — `DEBUG=10 … FATAL=50`, `parse(name)`
2. **LogRecord** *(frozen dataclass)* — one event, carried UNFORMATTED — `logger_name, level, template, args, context, created_at, thread_name`; `message()`, `with_context(extra)`
3. **Formatter** *(Strategy, ABC)* — record → one line, nothing else — **PlainFormatter**, **JsonFormatter**
4. **Filter** *(Strategy, ABC)* — a pure predicate over a record — **NamePrefixFilter**, **ContextFilter**
5. **Handler** *(ABC)* — the ONE type every sink and every wrapper shares — `handle(record)`, `close()`
6. **SinkHandler** *(ABC, Handler)* — the handlers that actually WRITE; owns its own `level`, `formatter` and lock, delegating only `write(line)` — **ConsoleHandler / FileHandler / MemoryHandler** (a `deque(maxlen=capacity)` ring buffer, `lines()`)
7. **HandlerDecorator** *(Decorator, ABC, Handler)* — IS-A Handler **and** HAS-A Handler (`inner`); `close()` delegates, `handle()` abstract
8. **ContextEnricher / FilteringHandler** *(Decorators)* — merge static fields + a per-call `provider()` into the record; apply a `Filter` in front of what is wrapped
9. **RateLimitingHandler / AsyncHandler** *(Decorators)* — token bucket counting drops and emitting a `suppressed N` WARN; bounded queue + ONE writer thread, dropping on overflow, draining on `close()` — `dropped_count()`, `flush()`
10. **Logger** — a NODE in the dotted namespace: nullable level, handler list, `propagate`, `parent` — the five level methods plus `log`, `effective_level`, `is_enabled_for`, `add_handler`, `set_propagate`
11. **LoggerRegistry** + module-level accessor *(Singleton)* — the tree, look-up-or-create **atomically** (`get_logger`, `root`, `names`, `close`), plus `current_registry / set_registry / use_registry` — the global **and its test seam**
12. **LoggingError** hierarchy — `UnknownLevelError`, `InvalidLoggerNameError`, `HandlerClosedError`, `LogFormatError`, `HandlerConfigError`

**Levels are DATA, handlers are BEHAVIOUR — both halves of the test in one file.** A level's whole
semantics is *where it sits in an order*, so filtering is `record.level >= threshold` and a
class-per-level is the parking-lot vehicle-type mistake again. A console sink and a file sink
genuinely *do* different things — that one is polymorphic.

> 📝 Trap (Step 2): the shortcut is one fat `Handler` holding level + formatter + filter + a rate limit + an async flag. It is smaller — until the next requirement is "async on the file sink but not the console" and every flag has to be plumbed through every sink. And with five ABCs here, watch the missing `@abstractmethod`: a method merely set to `...` is not abstract, so a subclass forgetting `write()` fails at runtime as a silent no-op instead of at construction.

> 📝 Trap (Step 2): `LogRecord` must be immutable and enrichment must RETURN A COPY. One record is shared by every handler in the fan-out, so a wrapper mutating it in place leaks the first sink's context into the second sink's output — and it only surfaces once someone adds a second sink.

---

## Step 3 — Relationships & APIs
_Signatures before bodies._

```
Logger ──has many──▶ Handler  ·  Logger ──parent──▶ Logger  (registry owns name -> node)

Handler (ABC)
  ├── SinkHandler (ABC) ──has──▶ Formatter, LogLevel, Lock
  │     ├── ConsoleHandler   ├── FileHandler   └── MemoryHandler
  └── HandlerDecorator (ABC) ──has──▶ Handler      ◀── IS-A and HAS-A: the pattern
        ├── ContextEnricher  ├── FilteringHandler ──has──▶ Filter
        ├── RateLimitingHandler                └── AsyncHandler
```

**The Decorator claim, as an inequality — this *is* the argument:**

| behaviours wanted | subclassing needs | wrapping needs |
|---|---|---|
| enrich, filter, throttle, async × 3 sinks | up to `3 × 2⁴ = 48` classes | `3 + 4 = 7` classes |
| a 5th behaviour added later | doubles it again | **one** new class |
| chosen at runtime from config | impossible — the class is fixed at compile time | trivial — build the chain |

Say it as: *"the behaviours are independent and the caller wants arbitrary subsets, so the
combinations multiply — inheritance enumerates them, composition builds them."*

**Signatures:**
```python
class SinkHandler(Handler, ABC):        # __init__(formatter, level=DEBUG)
    handle(record)                      # level -> format -> LOCKED write
    write(line: str)                    # abstract; the only thing a sink overrides

class HandlerDecorator(Handler, ABC):   # __init__(inner); close() delegates to inner
    handle(record)                      # abstract
#  ContextEnricher(inner, static: dict = None, provider: Callable[[], dict] = None)
#  FilteringHandler(inner, log_filter: Filter)
#  RateLimitingHandler(inner, capacity: int, refill_per_second: float).dropped_count()
#  AsyncHandler(inner, queue_size=1000).flush(timeout=2.0) / .dropped_count()

Logger: effective_level() -> LogLevel   # walks UP to the nearest configured node
        handlers() -> tuple             # snapshot, so fan-out is mutation-safe
        log(level, template, *args, **context)    # the five level methods delegate here
LoggerRegistry(root_level=INFO).get_logger(name)  # ATOMIC look-up-or-create
set_registry(registry) -> LoggerRegistry   # returns the previous one
use_registry(registry)                     # contextmanager, restores on exit
```

**Why `(template, *args)`:** if DEBUG is off, `log.debug("cart %s", cart)` returns after **one
integer comparison** and `str(cart)` never runs; `log.debug(f"cart {cart}")` renders *before* `debug`
is entered, every iteration, forever. `message()` memoises, so a fan-out to three sinks renders once.

**The dispatch path — two thresholds, checked in two places:**
```
logger.info(...)
  1. logger.is_enabled_for(INFO)?  <- effective level, inherited; fails -> nothing is built
  2. build LogRecord, walk UP the tree; for each ancestor's handler:
       3. the handler's OWN level  <- a sink can be stricter than its logger
       4. its OWN formatter,  5. its OWN lock around the write
     stop at the first node with propagate=False
```
What is **not** re-checked is an ancestor's *level*: once a record exists only the sinks' own
thresholds can stop it. Python's `logging` does this too, and it surprises people.

**Two different races, two different answers:**

| race | fix |
|---|---|
| two threads write one sink, output interleaves mid-record | a per-handler lock around `write` **only** — format outside it, so the critical section stays short. A lock on the *Logger* instead serialises every sink behind the slowest one |
| two threads `get_logger("app.db")`, both miss, both create | **push atomicity into the store** — miss-check and insert inside ONE registry lock (an `RLock`: ancestor creation recurses upward) |

The second is the repo's recurring **check-then-act (TOCTOU)**, same shape as `save_if_absent` in
problem 01, and its consequence is silent: two `Logger` objects for one name, so handlers added to
the loser never fire.

> 📝 Trap (Step 3): decorators are interchangeable in TYPE, not in MEANING, and order bites hardest with `AsyncHandler`. Anything reading caller context — a request id in thread-local storage — must sit OUTSIDE the async hop; inside it the work runs on the writer thread where that context is empty. `ContextEnricher(Async(sink))` is right; `Async(ContextEnricher(sink))` compiles, runs, and silently logs a blank request id.

> 📝 Trap (Step 3): a queue or a counter means a shutdown path, and it must not throw — a `RateLimitingHandler`'s last notice goes into an inner handler that may already be closed, so make it best-effort. And `flush()` must wait on the **write**, not the queue: `while not self._queue.empty()` returns with the write still in flight, because the worker pops *first* and calls `inner.handle()` *second*.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

**A library, not a service** — like the text editor in problem 10, `log.info(...)` runs in-process.
Two parts of it *do* become HTTP, and both are real production features:

| LLD method | HTTP |
|---|---|
| `Logger.set_level(level)` | `PUT /api/v1/loggers/{name}` `{level, propagate}` -> **200** · **400** `UnknownLevelError` · **404** unknown logger |
| `LoggerRegistry.names()` / `effective_level()` | `GET /api/v1/loggers` -> **200** `[{name, level, effective_level, propagate}]` |
| `MemoryHandler.lines()` | `GET /api/v1/logs/tail?logger=app.db&level=WARN&limit=200` -> **200** (the ring buffer, for a crash dump) |
| *(the sink, in reverse)* | `POST /api/v1/logs` `{records: [...]}` -> **202 Accepted** — a log **ingestion** service receiving what an `HttpHandler` shipped |

> The `PUT` earns its place: turning `app.db` to DEBUG on a live box without a redeploy is the most
> valuable operational feature a logging framework has, and it works *because* the level lives on a
> mutable tree node that existing objects read through. Ingestion is **202, never 201** —
> fire-and-forget, idempotent by record id.

## Notes / decisions (log the "why" here)
- **The sink got smaller, not bigger.** `SinkHandler` owns level + formatter + lock and delegates the one varying thing to `write(line)`. If a wrapper ever needs to know *which* sink it wraps, it is not a decorator any more.
- **Rate limiting reuses problem 04's token bucket as an ALGORITHM, not an import.** Deliberately *not* reused: its `RateLimitAlgorithm` Strategy + swappable `StateStore` — one bucket in front of one handler needs neither. The moment the limit must hold across processes, that store is what you reach for.
- **Async drops rather than blocks**, and drops are counted and announced, never silent — blocking turns a slow disk into an application outage. One writer thread, not a pool, so per-sink ordering survives.
- **`**context` is a known-cost convenience.** `log.info("paid %s", amt, tenant="acme")` reads well, but kwargs share a namespace with the method's own parameters, so a field named `template` or `level` is impossible — Python's `logging` uses `extra={...}`. Kept for shorter call sites, but **name the tradeoff**; "why not `extra=`?" is a fair follow-up.
- **Never raise into the application** — the fan-out wraps every handler call and sends failures to an internal error channel (problem 07's per-channel bulkhead). `LogFormatError` is still *typed*, so a test can assert on it.
- **SINGLETON — and here is the cost, because a senior candidate names it unprompted:**

| | |
|---|---|
| **Why a global is right *here*** | a logger is needed at every depth, leaf helpers and import-time code included — threading a `logger` parameter through every constructor poisons every signature for one cross-cutting concern. And config must be process-wide: "set `app.db` to DEBUG" has to reach objects that exist *and* objects not yet built. |
| **What it costs** | the dependency is **hidden** (a class calling `get_logger()` never declares that it does I/O); state **leaks between tests** in one process; it is global **mutable** state. The classic `__new__`/`getInstance` Singleton is strictly worse — it makes the instance unreplaceable. |
| **The compromise here** | the registry is an ordinary injectable class; only the module-level **default** is global; `set_registry` / `use_registry` are the documented seam. Convenience for 99% of call sites, injectability for the 1% — the only place in the repo where DI is set aside, narrowly and on purpose. |

> 📝 Trap (Step 4 build): the cheap demo proves nothing. "Two sinks, two formats" must print BOTH renderings of the SAME record. "Level filtering works" needs a counter that stayed at zero — an object whose `__str__` increments a counter is the honest proof nothing was built. "The lock matters" must show the UNLOCKED version corrupting output next to the locked one; zero corruptions alone is indistinguishable from a test that never raced. And give the rate limiter a bucket that does not refill, or the numbers wobble run to run.
