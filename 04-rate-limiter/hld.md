# Rate Limiter — HLD (quick)

> **Framing:** the LLD already built the hard part (algorithm + atomic store). The HLD question is
> almost entirely: **"where does the shared counter live when you have many app servers?"**

## 1. Scope
- **Functional:** same as LLD — cap requests per (user, endpoint); reject over limit (429).
- **Non-functional:** the limiter itself must be **fast** (adds latency to every request) and **available**
  (if it goes down, don't take the whole API down with it) — this last one is the key HLD decision.

## 2. Estimate
- If the API does ~50K req/s total, the rate limiter is checked **~50K times/s** — it's on the hot path of
  *everything*, not a separate feature. That number alone rules out anything slow (no synchronous DB write per check).

## 3. Architecture
```
Client ─▶ LB ─▶ API Gateway ──▶ [ RateLimiter middleware ] ──▶ App servers
                                        │
                                        ▼
                              Redis (shared counter store)
                              — same INCR+Lua atomic op as the LLD's RedisStore
```
- **Where it runs:** as **middleware in the API gateway** (checked before the request reaches app logic) — not inside each app server's own memory (that's the single-process version, wrong once you scale out).
- **Why Redis specifically:** it's fast (in-memory), and its single-threaded atomicity is exactly what the LLD's `RedisStore` + Lua script already solved — the HLD reuses the LLD unchanged, just points the same `StateStore` interface at a shared Redis instead of a local dict.

## 4. Key decisions
- **Redis as a single shared source of truth** across all app servers → the "N servers = N× the limit" bug from single-process is closed (same lesson as `save_if_absent` closing double-booking).
- **Fail-open vs fail-closed when Redis is down:** the actual design decision.
  - **Fail-closed** (reject everything) → safest for the backend, but takes your whole API down if Redis blips.
  - **Fail-open** (allow everything) → API stays up, but you're briefly unprotected.
  - **Standard answer: fail-open**, because a rate limiter's job is to protect the backend from overload — the backend being briefly unprotected is a smaller risk than the rate limiter itself becoming a new single point of failure for the entire API.
- **Local + shared, two-tier (optimization):** a small in-memory cache of "definitely still under limit" on each app server avoids a Redis round-trip on *every single* request — only call Redis near the boundary. Trades a little precision for a lot of latency.
- **Sharding Redis:** partition by the same key (`user:endpoint`) across a Redis Cluster if one instance can't take the QPS — a hot user only ever hits one shard.

## 5. Reliability & scale
- **Redis down** → fail-open (above); alert; the API keeps serving, just temporarily unprotected.
- **Hot key** (one abusive user/IP hammering) → same fix as any hot key: that one Redis shard gets hot, not the others — isolated by the key structure.
- **At 10× traffic:** more gateway instances (stateless), bigger/sharded Redis cluster — the algorithm and LLD code never change.

## LLD ↔ HLD mapping
| LLD | HLD |
|---|---|
| `StateStore` abstraction | the seam — `InMemoryStore` (single server) → `RedisStore` (fleet-wide) |
| Lua script atomic `increment` | the exact mechanism Redis uses in production, unchanged |
| `RateLimitAlgorithm` (Strategy) | unchanged — same class runs against local or shared store |
| in-process, one server | **middleware layer** in front of the whole fleet, shared Redis |
