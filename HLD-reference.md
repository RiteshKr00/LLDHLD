# HLD Deep Reference

The **depth tier**. Use this to *understand* a strategy well enough to explain it in an interview
(each entry ≈ a 30–60s spoken answer). To *walk* an interview use `HLD-revision.md`; to *pick fast*
use `HLD-method-bank.md`. This file is the permanent, question-agnostic reference — grow it over time.

> Answer shape for everything below: **what it is → why (the problem) → how it works → tradeoff → failure mode.**

---

## 1. Capacity Estimation

Back-of-envelope to justify every later decision. Memorize: **1 day ≈ 86,400 s ≈ 10⁵ s**, peak ≈ 2× avg, read:write often 100:1.

- **Write QPS** = daily writes ÷ 86,400. **Read QPS** = write QPS × ratio.
- **Storage** = items × row size × retention (years × 12 months).
- **Cache size** = hot-set (~20%) × daily items × row size.
- **Bandwidth** = QPS × payload.

*Worked (URL shortener):* 100M writes/mo ÷ 2.5M s ≈ 40 writes/s; ×100 read ratio ≈ 4,000 reads/s → read-heavy → cache + replicas. 6B rows × 500 B ≈ 3 TB → shardable, not huge.

---

## 2. API Design

- **REST verbs**, resource nouns, versioning (`/v1/`).
- **Idempotency:** a retried write must not create duplicates. Client sends an **idempotency key**; server stores `key → result`, returns the stored result on replay. Essential for POST over unreliable networks.
- **Sync vs async:** long work returns `202 Accepted` + job id (poll or webhook); fast work returns `200`.
- **Pagination:** cursor-based > offset (offset drifts and gets slow on large tables).

---

## 3. Database Choice

| DB | Model | Pick when | Tradeoff |
|---|---|---|---|
| **PostgreSQL** | relational, ACID | transactions, joins, reporting, strong consistency, < ~100M rows | vertical ceiling; sharding is manual |
| **Cassandra** | wide-column, LSM-tree | massive writes, KV access, horizontal + AP | no joins/txns; eventual consistency |
| **MongoDB** | document | nested/flexible docs, moderate scale | weaker at pure KV internet-scale |
| **Redis** | in-memory KV | serving/cache, counters, locks, rate-limit | not source of truth (RAM cost, loss risk) |
| **DynamoDB** | managed KV | predictable scale, conditional writes | limited query flexibility, cost |

**Default: PostgreSQL** until the workload *clearly* demands Cassandra (write throughput, KV-only, internet scale). Postgres reduces operational complexity — don't design for 1B users on day 1.

**Why Cassandra writes are fast:** LSM-tree → writes are appends to an in-memory memtable + commit log, flushed sequentially. No in-place updates.

---

## 4. ID / Key Generation

- **Auto-increment → Base62:** DB sequence, encode to 7 URL-safe chars. Simple; but a single counter is a distributed bottleneck/SPOF.
- **KGS (Key Generation Service):** pre-allocate counter **ranges** to each server (A owns 1–1M, serves locally). Coordinate once per *million* writes. KGS itself needs replication/pre-generation so it isn't a SPOF.
- **Snowflake ID:** 64-bit = `timestamp | machine-id | sequence`. Time-sortable, no central coordination. Watch clock skew.
- **Random + conditional write:** generate N random chars, insert only if absent (`save_if_absent` / `PutItem(attribute_not_exists)`), retry on the rare collision. No coordination at all.
- **Hash of URL (why not):** collisions, long ugly codes, no custom alias, and the code changes if the destination changes.
- **Base62 not Base64:** Base64 has `+ / =` → URL-unsafe. Base62 = `A–Z a–z 0–9`.

---

## 5. Database Scaling

**Progression (never jump to the end):** Vertical → Read Replicas → Partitioning → Sharding → Multi-Region.

**Vertical:** bigger box. Zero code change; hits a hardware ceiling + still a SPOF.

**Read Replicas:** writes → primary, reads → replicas. Scales a read-heavy load + adds HA.
- **Replication lag:** replica hasn't synced → a user may not read their own just-written data.
- Fixes: **read-your-writes** from primary · **sticky session** · accept eventual consistency.

**Partitioning vs Sharding:** partitioning = split a table *within one DB* (e.g. by year). Sharding = spread data *across machines*. Sharding scales storage **and** writes.

**Sharding strategies:**
- **Hash** `hash(key)%N` — even spread; but adding a node reshuffles almost everything.
- **Range** (A–F, G–M…) — simple, supports range scans; risks hot shards.
- **Geo** (US/EU/IN) — low latency per region; cross-region queries are painful.
- **Consistent hashing** — keys and nodes on a ring; adding/removing a node moves only *adjacent* keys. **Virtual nodes** smooth the distribution. Used by Cassandra, DynamoDB.

**Replication models:**
- **Leader–Follower:** one writer, many readers. Simple; lag.
- **Multi-Leader:** each region accepts writes → low write latency; needs **conflict resolution** (LWW, vector clocks).
- **Leaderless (Cassandra/Dynamo):** any node writes. Uses **quorum**: with replication factor RF, `W + R > RF` guarantees a read sees the latest write. E.g. RF=3, W=2, R=2. Plus gossip + anti-entropy repair.

**CAP:** partitions are unavoidable, so during one you trade **Consistency vs Availability**. Postgres = **CP**, Cassandra = **AP**. (PACELC extends it: *else*, trade latency vs consistency even without a partition.)

**Reshard without downtime:** add shard → dual-write / background backfill → verify → shift reads gradually → cut over. Never stop production traffic.

---

## 6. Caching

**Patterns:**
- **Cache-aside (lazy):** app reads cache; miss → read DB → populate. Default. Only requested data is cached; first hit is always a miss; staleness bounded by TTL.
- **Read-through:** cache library loads from DB on miss (app only talks to cache).
- **Write-through:** write cache + DB together → consistent, slower writes.
- **Write-back (write-behind):** write cache, flush to DB async → fast, risk loss on crash.

**Eviction:** **LRU** (default), LFU, FIFO — when memory is full, evict by policy.

**TTL + jitter:** expiry bounds staleness; **randomize TTLs** so keys don't expire together (prevents avalanche).

**The three failure modes (know the difference cold):**

| Mode | What happens | Fix |
|---|---|---|
| **Stampede** (dogpile / thundering herd) | *one hot key* expires → thousands of concurrent misses hit DB at once | single-flight / request coalescing · mutex (one recompute) · soft-TTL (serve stale while one refreshes) · background refresh |
| **Avalanche** | *many keys* expire together, or the cache cluster dies → mass misses flood the DB | **jittered TTLs** · staggered expiry · multi-layer cache · circuit breaker · cache HA/cluster |
| **Penetration** | requests for keys that **don't exist anywhere** (often malicious) → miss cache *and* miss DB every time | **cache the negative result** (short TTL) · **Bloom filter** to reject non-existent keys before the DB · input validation |

**Hot key:** one key so popular a single node saturates. Fixes: local/client LRU · CDN · replicate the key across nodes · Redis replicas · cache warming.

**CDN:** cache at edge PoPs near users. For redirects, serve cached 301s at the edge → offloads origin + cuts latency.

---

## 7. Async / Messaging

- **When Kafka/queue:** decouple producer/consumer · absorb spikes · async side-work (analytics, email) · event fan-out. Not "because every design has it."
- **Outbox pattern:** to avoid "DB committed but event lost," write the event into an **outbox table in the same DB transaction**; a relay worker reads the outbox and publishes to Kafka; consumers are idempotent. Guarantees at-least-once delivery.
- **DLQ (Dead Letter Queue):** after N failed retries, move the message aside → investigate → replay. Prevents poison messages from blocking the stream.
- **Delivery semantics:** at-least-once (default, needs idempotent consumers) vs exactly-once (expensive, often faked via idempotency).

---

## 8. Reliability (each pattern → the failure it prevents)

- **Retry + exponential backoff + jitter:** transient blips. Backoff/jitter stop a synchronized retry-storm from finishing off a struggling service.
- **Timeout:** never block forever on a dependency; fail fast (e.g. 200 ms) and free the thread.
- **Circuit breaker:** states **Closed → Open → Half-Open**. On a failure threshold it *opens* and rejects instantly (stops hammering a dying dependency), periodically half-opens to test recovery.
- **Bulkhead:** isolate resources so one failure can't spread. **The name is from ships** — a hull is
  divided into watertight compartments (bulkheads); if one floods, the water can't reach the others and
  the ship stays afloat. *(The Titanic had bulkheads — they just weren't tall enough, so water spilled
  over the tops into the next compartment. Partial isolation, total loss.)*

  ```python
  for channel in channels:          # WITHOUT: email raises -> sms/push/in_app NEVER run
      channel.send(n)
  for channel in channels:          # WITH: one dead channel is contained
      try:    channel.send(n)
      except: log_and_continue()
  ```
  It applies at **every** level, not just try/except:

  | Level | What it looks like |
  |---|---|
  | Code | per-channel `try/except` inside the loop |
  | Threads | separate thread pool per workload (analytics flood ≠ redirect outage) |
  | Queues | **one topic + worker pool per channel** — a dead provider backs up only its own lane |
  | Connections | separate DB connection pool per workload (one slow query can't eat them all) |
  | Servers | separate service / separate machines |

  **Bulkhead vs Circuit breaker** (often confused — you want both):

  | | Bulkhead | Circuit breaker |
  |---|---|---|
  | Job | stop failure from **spreading** | stop **hammering** something already failing |
  | How | isolate resources | trip open after N failures, retry later |
  | Ship analogy | water can't reach the next compartment | stop sailing toward the iceberg |
- **Idempotency:** safe retries; dedupe by idempotency key / request id.
- **Graceful degradation:** shed non-core features to keep the core alive (analytics down → redirects still serve).

---

## 9. Availability

- **Kill SPOFs:** ≥2 of everything (LBs, app servers, DB replicas) behind a balancer.
- **Health checks:** **liveness** (`/health`, restart if dead) vs **readiness** (`/ready`, pull from LB if not ready). Unhealthy node → LB stops routing.
- **Failover:** primary dies → replica auto-promotes (seconds of downtime).
- **Multi-AZ** (survive a datacenter) → **Multi-Region** (survive a region) via GeoDNS / global LB / Anycast.
- **Availability math:** 99.9% ≈ 8.7 h/yr down; 99.99% ≈ 52 min; 99.999% ≈ 5 min.

---

## 10. Bottleneck Progression

```
DB (read overload)   → add Redis
Redis (hot keys)     → CDN / local cache / Redis Cluster
Network (global RTT) → multi-region
Single region        → GeoDNS / Anycast
```
**"At 10× traffic?"** be specific: more service instances · bigger Redis cluster · more replicas · more shards · CDN · regional deploy · autoscaling. Never just "add servers."

---

## 11. Trade-offs (junior answer → staff answer)

- **Postgres vs Cassandra:** not "Cassandra scales better." → *"< 100M rows, transactions, reporting → Postgres for lower operational complexity; internet-scale KV writes with no joins → Cassandra."*
- **Why not all Redis:** not "Redis is expensive." → *"RAM-bound and loss-prone; it's the **serving layer**, the DB stays source of truth."*
- **Why not MongoDB:** workload is `shortCode → longURL`, pure KV; Cassandra is built for that access pattern at scale (Mongo fine at moderate scale).
- **301 vs 302:** 301 permanent → browser caches → less load but **no analytics**; 302 temporary → every hit reaches you → **click tracking** possible. Track clicks → 302.
- **Base62 vs Hash:** hashing → collisions, long codes, no custom alias, breaks on destination change. Counter/Snowflake + Base62 avoids all four.
- **Sync vs async analytics:** never block the redirect on Kafka; publish the click event async, return 301/302 immediately.
- **CDN usage:** worth it for global latency + hot-redirect offload; not for uncacheable/personalized responses.

---

## 12. Monitoring & Observability

- **RED** (services): Rate, Errors, Duration. **USE** (resources): Utilization, Saturation, Errors.
- **Latency percentiles:** watch **P95/P99**, not average (tail latency is the user pain).
- **Tracing:** one **Trace ID** propagated App→Redis→DB→Kafka; spans show where time went.
- **Logging:** structured + trace id for end-to-end correlation.
- **Alerts:** SLO-driven (P99 > 100 ms → page; cache hit < 80% → investigate; consumer lag rising → scale).

---

## 13. Disaster Recovery

- **RTO** = how fast you must recover (e.g. 5 min). **RPO** = how much data loss is tolerable (e.g. 30 s).
- **Backups:** periodic snapshots + continuous WAL/commit-log shipping to meet RPO.
- **Topologies:** **active-passive** (standby region, cheaper, slower failover) vs **active-active** (both serve, instant failover, costlier + conflict handling).
- **Region down:** global LB / GeoDNS reroutes to a healthy region; cross-region replication keeps data current.

---

## 15. Geospatial indexing ("near me")

- **Problem:** `WHERE lat BETWEEN … AND lng BETWEEN …` scans without a spatial index, and a box isn't a true radius.
- **Bounding box + haversine (the standard 2-step):** a cheap, indexable box filter narrows candidates → **haversine** computes true great-circle distance to rank/cut the edges.
- **Geohash:** interleave lat/lng bits → a base32 string; longer prefix = smaller cell; nearby points share a prefix → a **prefix range scan** finds neighbors. **Gotcha:** two points either side of a cell border can be meters apart but share no prefix → always query the **8 neighbor cells** too.
- **S2 (Google) / H3 (Uber):** map the sphere to hierarchical cells with 64-bit ids; better at poles/edges and variable resolution. Uber uses H3 for supply/demand matching.
- **Stores:** PostGIS (`GIST` index, `ST_DWithin`) · Elasticsearch `geo_point` · Redis `GEOSEARCH` · Mongo `2dsphere`.
- **Scale:** shard by geohash prefix / cell → region-local queries; cache hot cells (dense cities).
- **When:** any "near me" — parking, ride-hailing supply, delivery ETA, store locator.

## 16. Redis atomicity — Lua scripts

- **Why Redis commands are atomic for free:** Redis is **single-threaded** — one command runs fully before the next starts, so no client ever sees a command half-done. `INCR key` alone needs zero locks; Redis itself is the lock.
- **The gap:** two related commands (`INCR` then `EXPIRE`) are each atomic *individually*, but the **pair** isn't — another client's command (or a crash) can land between them, e.g. leaving a key with no TTL.
- **Pipeline ≠ atomic:** a pipeline batches commands into one network round-trip for speed only; Redis still executes them as separate commands. `MULTI/EXEC` (Redis's transaction) is atomic but can't branch on a value read mid-transaction.
- **The fix: a Lua script (`EVAL`).** Redis embeds a Lua interpreter; a script sent via `EVAL` runs as **one indivisible unit** — nothing interleaves inside it. This is how you get "read a value, decide, write" atomically, server-side.
  ```lua
  local count = redis.call('INCR', KEYS[1])
  if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
  return count
  ```
  `KEYS[]` = the Redis keys touched (Redis Cluster uses these to route the script to the right shard); `ARGV[]` = plain values. `redis.call` invokes a Redis command from inside the script.
- **`client.register_script(src)`** (redis-py): uploads the script once, returns a Python callable; each call sends `EVALSHA` (hash reference) instead of the full source — cheaper after the first upload.
- **One-liner:** *a single command is atomic because Redis is single-threaded; once you need two operations atomic **together**, push the logic into a Lua script.*
- **Reused for:** rate limiting (`INCR`+`EXPIRE`), distributed locks (`SET key val NX PX ttl` + a matching-token `DEL`), idempotency keys, leaderboard updates (`ZADD` + conditional logic).

## 17. Derived vs materialized state (precompute or recompute?)

**The question:** when a value can be *calculated* from other data (a balance from transactions, a
like-count from likes, a feed from posts) — do you compute it on demand, or store it and keep it updated?

**Bank passbook analogy:** to know your balance you could add up every transaction since the account
opened (**derive**), or the bank could keep your current balance written down and adjust it on each
transaction (**materialize**). Banks materialize — for the same reason your system will.

| | **Derive** (compute on read) | **Materialize** (store + update on write) |
|---|---|---|
| Read cost | **O(n)** — grows with history, forever | **O(1)** — one row lookup, always |
| Write cost | O(1), just append | O(1) append **+** update the stored value |
| Correctness | always right (recomputed from truth) | a second copy → **can drift** |
| Concurrency | append-only ⇒ **no read-modify-write race** | `x = x + n` ⇒ race returns |
| Complexity | simple | transaction + repair job |

**Why derive stops working:** a 5-year group with 20,000 expenses recomputes all of them on every
balance view — on the app's most-opened screen. O(history) on the hot path is the tell.

**How to materialize safely — three rules:**
1. **Keep the log as the source of truth.** The materialized value is a *cached projection*, never the
   only copy.
2. **Update it in the same transaction as the write**, so they can't disagree:
   ```sql
   BEGIN;
     INSERT INTO expenses (...);
     UPDATE balances SET amount = amount + ? WHERE user_id = ?;
   COMMIT;                       -- both land, or neither does
   ```
   The read-modify-write race that deriving avoided is back — but the DB transaction (row lock /
   atomic `SET x = x + n`) provides the atomicity. *Same lesson as `save_if_absent`: push atomicity
   into the store.*
3. **Add a reconciliation job** that recomputes from the log and repairs drift — possible precisely
   *because* you kept rule 1.

**Related shapes:** event sourcing + periodic **snapshots** (state = snapshot N + events since);
**CQRS** (write to the log, read from projections); a **materialized view** in SQL.

**When to pick which:** derive while the history per key is small and reads are rare; materialize once
reads are frequent or history is unbounded. **Say the tradeoff out loud** — "derive for correctness,
materialize for read performance, keep the log so the projection stays verifiable."

## 18. Deduplication & delivery semantics

**The problem:** a worker sends an SMS, succeeds, then **crashes before marking the message done**.
The queue sees an unacknowledged message and hands it to another worker → **the user gets two SMS**.

```
Worker A: sent SMS ✓ ... crash 💥 (never acked)
Queue:    "still pending" -> gives it to Worker B
Worker B: sends the SAME SMS again
User:     two OTPs 😠
```

**Why this is unavoidable — pick your poison:**

| Guarantee | Meaning | Cost |
|---|---|---|
| **At-most-once** | never duplicated | messages **get lost** |
| **At-least-once** | never lost | **duplicates happen** ← almost everyone picks this |
| **Exactly-once** | neither | very expensive end-to-end; usually *faked* = at-least-once + dedup |

Losing a notification/payment is worse than duplicating one, so systems choose **at-least-once** —
which makes **handling duplicates your job**.

**The fix — a deterministic dedup key, checked before the side effect:**
```python
dedup_key = f"{event.event_id}:{user.user_id}:{channel.value}"   # "evt-9931:user-42:SMS"

if seen(dedup_key):          # Redis SET NX / a unique DB column
    return                    # already done, skip
do_the_side_effect()
mark_seen(dedup_key, ttl=24h)
```
- **Deterministic is the whole point:** the same event+user+channel must produce the **same string
  every time**. Generate a random id per attempt and dedup silently does nothing.
- Store it where all workers can see it (Redis / a `UNIQUE` column) — a local set only dedups within
  one process, same lesson as locks.
- TTL it: you only need to remember long enough to cover retries, not forever.

**Related but distinct — the idempotency key:** same idea pushed to the API edge. The *client*
generates a UUID per user action and sends it with the request; the server stores `key → result` and
replays the stored result instead of re-executing. Protects against the user's phone retrying a
payment, not just your own workers.

> **Rule of thumb:** any operation with a real-world side effect (send, charge, ship) that runs behind
> a queue or a retry **needs a dedup key**. Users notice duplicates; they don't notice latency.

## How to grow this file

When a new problem introduces a method not here (rate-limiter token bucket, geohashing, Raft/Paxos consensus, WebSocket fan-out, search/inverted index…), add it under the right phase in the same *what → why → how → tradeoff → failure* shape. This stays the single deep reference for every future HLD.
