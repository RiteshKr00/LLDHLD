# LRU Cache — HLD (distributed cache)

Companion to [`solution.py`](solution.py) (the in-process cache).
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).

> **Framing:** the LLD built the cache that lives **inside one process**. The HLD question is what
> changes when the cache is a **separate service shared by hundreds of app servers** — i.e. Redis /
> Memcached. Two things dominate: **which node holds a key**, and **what happens when the cache lies**.

## 1. Scope
- **Functional:** `get` / `put` / `delete` · TTL · eviction when memory is full · stats.
- **Non-functional:** **sub-millisecond reads** (a cache slower than the DB is worthless) · high hit-rate · survive node loss without a stampede · **cache is never the source of truth**.

## 2. Estimate — why a cache exists at all
- Say the DB can do **5K QPS** but traffic is **50K QPS**. A **90% hit rate** leaves 5K QPS hitting the DB — exactly what it can take. **The hit rate is the whole product.**
- 100M keys × ~1KB ≈ **100 GB** → doesn't fit on one box → **must shard**.
- A 1% hit-rate drop = **500 extra QPS** on the DB. That's why hit-rate is monitored like a SLA.

## 3. The crux: which node holds a key?

**Naive:** `node = hash(key) % N`. Works — until N changes.

Add one server (4 → 5) and **`% 4` becomes `% 5` for every key** → almost **every key maps somewhere
new** → the entire cache is effectively empty → all traffic slams the DB at once. Adding capacity
takes you *down*.

**Fix — consistent hashing.** Put nodes and keys on the same circular hash ring; a key belongs to the
first node clockwise from it.

```
        Node A
      ↗        ↘
  k3            Node B
   ↑              ↓
  Node D  ← k1 ← Node C
```
Add a node → only the keys in **that node's arc** move. **~K/N keys instead of ~all of them.**

- **Virtual nodes:** each physical node is placed at many points on the ring, so load spreads evenly
  and removing a node redistributes to *many* neighbours rather than dumping everything on one.
- **Note:** Redis Cluster does the same job with **16384 hash slots** — same goal, different mechanics.

## 4. What changes from the LLD

| LLD (in-process) | HLD (distributed) |
|---|---|
| `dict` + DLL | **Redis** (which has its own LRU/LFU internally — `maxmemory-policy`) |
| `capacity` = item count | `maxmemory` = **bytes**; eviction is memory-driven |
| `threading.Lock` | gone — Redis is single-threaded; each command is atomic |
| policy as a Python class | a **config flag** (`allkeys-lru` / `allkeys-lfu`) |
| which node? — n/a | **consistent hashing** |
| — | **TTL**, invalidation, stampede protection, replication |

> Notice how much of the LLD **disappears** rather than scales: the lock, the DLL, the policy classes
> all get absorbed by the cache server. What remains is a **client-side routing decision** plus a pile
> of consistency problems the LLD never had.

## 5. Cache consistency — the hard part

The cache holds a **copy**. The moment the DB changes, the copy is a lie.

**Write strategies:**

| | How | Pros | Cons |
|---|---|---|---|
| **Cache-aside** (default) | app reads cache → miss → DB → populate | simple; only requested data cached | first hit always misses; stale until TTL |
| **Write-through** | write cache **and** DB together | cache never stale | slower writes; caches data nobody reads |
| **Write-behind** | write cache, flush to DB async | fastest writes | **data loss** if the node dies before flush |

**Invalidation** — famously the hard one:
- **TTL** — simplest, always correct *eventually*. Bounded staleness.
- **Delete-on-write** — on a DB update, delete the key (don't update it — updating races with a
  concurrent read repopulating an older value).
- **Event-driven** — DB change → event → invalidate. Precise, more moving parts.

## 6. The three failure modes (know these cold)

| Problem | What happens | Fix |
|---|---|---|
| **Stampede** (dogpile) | ONE hot key expires → thousands of concurrent misses hit the DB at the same instant | single-flight (one request recomputes, others wait) · mutex · **soft TTL** (serve stale while one refreshes) |
| **Avalanche** | MANY keys expire together (or a node dies) → mass misses flood the DB | **jittered TTLs** (`ttl + random`) so expiries spread out · staggered warmup · circuit breaker |
| **Penetration** | Requests for keys that exist **nowhere** (often malicious) → miss cache AND miss DB every time | **cache the negative result** (short TTL) · **Bloom filter** to reject impossible keys before the DB |

**Hot key** (one key so popular a single node saturates): replicate that key to several nodes, add a
**local in-process cache** in front (this is literally your LLD, running on each app server), or push it
to a CDN.

> **Nice symmetry:** the standard fix for a hot key in a distributed cache is… the in-process LRU cache
> you just built. **Two tiers: L1 local (your code), L2 shared (Redis).**

## 7. Reliability & scale
- **Node dies** → its share of keys is lost → those requests miss and hit the DB. With consistent
  hashing only that node's arc is affected. Add **replicas** so a failover keeps the data.
- **Cache cluster down** → the app must still work, just slower. **A cache going down must never take
  the system down** — same fail-open reasoning as the rate limiter.
- **Cold start** → an empty cache after deploy can stampede the DB. **Warm** it, or ramp traffic.
- **Scale** = add nodes to the ring (cheap now, thanks to consistent hashing) + replicas for hot shards.

## 8. Monitoring
**Hit rate** (the headline metric) · evictions/sec (high = cache too small) · memory used vs
`maxmemory` · p99 latency · key-space size · replication lag.

---

## LLD ↔ HLD mapping
| LLD (`solution.py`) | HLD |
|---|---|
| `dict[key → Node]` | key-space sharded across nodes by **consistent hashing** |
| DLL + `EvictionPolicy` | Redis's internal eviction — now a **config flag**, not a class |
| `capacity` (item count) | `maxmemory` (bytes) |
| `threading.Lock` | unnecessary — Redis is single-threaded, commands are atomic |
| `hits` / `misses` counters | the **hit-rate SLA**; a 1% drop = hundreds of extra DB QPS |
| *(nothing)* | TTL · invalidation · stampede/avalanche/penetration · replication · warmup |
| **the whole LLD cache** | becomes the **L1 local cache** in front of Redis (the hot-key fix) |

**The line to say:**
> *"In-process the hard part was getting O(1) from two structures. Distributed, the hard parts are
> **which node owns a key** — consistent hashing, so adding capacity doesn't invalidate everything —
> and **what happens when the copy is stale or gone**: TTL and invalidation for correctness,
> single-flight and jitter so an expiry doesn't turn into a DB outage."*
