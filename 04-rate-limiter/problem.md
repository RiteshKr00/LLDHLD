# Problem 4: Rate Limiter (LLD)

## The prompt (as an interviewer would give it)

> "Design a rate limiter — something that caps how many requests a client can make in a time window."

Deliberately vague. **Your job is to make it concrete** — that's Step 1.

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **Single process or distributed** — one server, or many sharing one limit? *(The biggest lever: N servers with in-memory counters = N× the limit. Decides in-memory vs Redis.)*
2. **What identifies a client** — user? IP? API key? And is the limit **per endpoint** or global? *(Defines the key.)*
3. **The limit spec** — N requests per T seconds? Different limits per endpoint?
4. **On exceed** — reject with 429? queue? drop silently?
5. **Strict or approximate** — are short bursts acceptable, or must the limit hold over *any* window? *(This picks the algorithm: fixed window is cheap but allows a boundary burst; sliding window is stricter; token bucket allows bursts deliberately.)*
6. **Should the algorithm be swappable?** *(Strategy signal.)*

---

## Clarifications (locked scope from Q&A)
- **Deployment:** distributed (limit shared across many servers). LLD builds the *algorithm* in-memory + thread-safe, with a **swappable state store** so it extends to Redis (single-process → distributed = swap the store).
- **Key:** per **(user, endpoint)** — a separate limit for each user on each endpoint.
- **Limit:** **50 requests per window** per (user, endpoint).
- **On exceed:** **reject** (HTTP 429).
- **Algorithm:** **swappable** (Strategy) — Token Bucket / Sliding Window / Fixed Window.
- **Accuracy:** approximate is acceptable; prefer near-strict + cheap (Sliding Window Counter or Token Bucket). Fixed Window's boundary-burst is the known tradeoff.
- **Out of scope:** actual HTTP server, auth, billing/quota management.

---

## Step 1 — Requirements  ✅ LOCKED

### Functional (what it DOES — the verbs)
- **allow / reject** a request: `allow(user, endpoint) -> bool`
- enforce **50 requests per window** per (user, endpoint)
- on exceed → **reject (429)**

### Non-functional (constraints — the "-ilities")
- **Thread-safe** — concurrent requests to the same key must not miscount  ← changes the code
- **Low latency** — runs on *every* request's hot path
- **Extensible** — swappable **algorithm** (sliding-window-counter now) *and* swappable **state store** (in-memory now, Redis later)

### Explicitly out of scope (say this out loud — senior move)
- Actual HTTP server · auth · billing / quota management

> 📝 **Review note (Step 1):** core functional right (allow/reject + the 50/window limit + 429). Relabel: "swappable algorithm/storage" are the **extensibility** NF, not functional verbs — same functional-vs-"-ility" catch as parking. The code-shaping NFs are **thread-safe** (concurrent same-key counting) and **low-latency** (hot path). Two swap-points → two Strategies/abstractions (algorithm + store).

---

## Step 2 — Entities  (nouns → classes)
_Format: `Name — single responsibility — key attributes/methods`_

1. **RateLimiter** — entry point; builds the key, loads the rule, delegates — `allow(user, endpoint) -> bool`
2. **RateLimitAlgorithm** *(Strategy)* — decides allow/reject for a key; concrete: `SlidingWindowCounter`, `TokenBucket`, `FixedWindow` — `allow(key, rule) -> bool`
3. **StateStore** *(abstraction)* — holds per-key state (counters / tokens / timestamps); `InMemory` now, `Redis` later — atomic `increment(...)`
4. **RateLimitRule** *(value object)* — the spec — `limit: int, window_seconds: int`
5. **Key** — `(user, endpoint)` composite — identifies one client on one endpoint

> 📝 **Review note (Step 2):** had orchestrator + algorithm Strategy + key. Key miss: the **`StateStore`** as its own abstraction — the *second* swap-point (in-memory → Redis) that makes distributed possible. The crux (Step 3): **algorithm = stateless logic, store = per-key state.** Renamed `WindowStrategy → RateLimitAlgorithm` (token bucket isn't a window); pulled the 50/window spec into a `RateLimitRule` value object. A `Request` object is optional — the API takes `(user, endpoint)` directly.

---

## Step 3 — Relationships & APIs  ✅ LOCKED
_Signatures before bodies._

**Relationships:**
```
RateLimiter ──composition──▶ RateLimitAlgorithm
RateLimitAlgorithm ──uses (DI)──▶ StateStore        (algorithm reads/writes per-key state HERE)
RateLimiter ──has──▶ RateLimitRule (per endpoint)
```

**Signatures:**
```python
# RateLimiter (entry point)
def allow(self, user: str, endpoint: str) -> bool      # build key, look up rule, delegate

# RateLimitAlgorithm (Strategy) — holds the store (DI), no state of its own
def allow(self, key: str, rule: RateLimitRule) -> bool # uses self.store

# StateStore (swappable: InMemory / Redis) — MUST expose an ATOMIC op
def increment(self, key: str, window_seconds: int) -> int   # atomic incr + TTL -> new count
#   (token-bucket variant: atomic take-token; general: compare-and-set / Lua script)

# RateLimitRule (value object)
limit: int
window_seconds: int
```

> 📝 **Review note (Step 3):** two linked fixes — (1) the **store is injected into the ALGORITHM** (it's what reads/writes state); RateLimiter composes the algorithm, which composes the store. (2) Crux resolved: the store exposes **one atomic op** (`increment` + TTL / compare-and-set / Lua), NOT separate `get`+`set` — else check-then-set is a **TOCTOU** (two reqs both see 49 → both allow → 51). Atomicity lives **in the store** (Redis `INCR`), not a lock → correct in-process *and* distributed = the `save_if_absent` lesson.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

The rate limiter is **middleware**, not a resource — `allow()` does not get its own endpoint. It
shapes the response of *every other* endpoint:

| LLD method | HTTP |
|---|---|
| `allow(user, endpoint)` -> `True` | request proceeds · headers `X-RateLimit-Limit`, `X-RateLimit-Remaining` |
| `allow(...)` -> `False` | **429 Too Many Requests** + `Retry-After: <seconds>` |
| *(admin)* | `PUT /api/v1/rate-rules/{endpoint}` `{limit, window_seconds}` -> **200** |
| *(admin)* | `GET /api/v1/rate-rules/{endpoint}/usage?user=...` -> **200** `{count, resets_at}` |

> A limiter that returns 429 **without** `Retry-After` is a bad citizen — the client has no idea when
> to come back and will just hammer you.

## Notes / decisions (log the "why" here)
- Implemented 3 algorithms side by side: `FixedWindowCounter`, `TokenBucket`, `SlidingWindowCounter` — each gets its **own narrow store interface** (`StateStore` / `TokenBucketStore` / `SlidingWindowStore`) rather than one fat interface, because each needs different state shape (a count vs tokens+time vs curr/prev counts). **ISP**, same lesson as pruning `exists()` from `URLRepository`.
- `RedisStore` (commented reference): the distributed swap for `StateStore`. Only the store changes — `RateLimitAlgorithm`/`RateLimiter` untouched. Atomicity via a **Lua script** (`INCR`+`EXPIRE` as one server-side unit) — plain sequential calls aren't atomic (crash mid-way leaves no TTL). Redis is single-threaded, so a script *is* the cross-server lock.
- All in-memory stores follow the same shape: `with self.lock:` wraps read→decide→write as one block — the atomic op, mirroring `save_if_absent`.

> 📝 **Review note (Step 4c + demo):** `RateLimiter` built as pure DI — it holds an injected `RateLimitAlgorithm` and never knows which concrete one it's running. Demo proves the swap is real: FixedWindow / TokenBucket / SlidingWindow all enforce the same 5-per-2s rule through the *same* `RateLimiter`, with only the constructor arg changing. Per-user isolation verified (`dave` unaffected by `alice2`'s exhausted quota) — the `(user,endpoint)` key does its job. **Problem 4 LLD complete.**

