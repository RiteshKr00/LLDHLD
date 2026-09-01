# HLD Method Bank (the Superset)

**How to use:** walk the phases in order (see `HLD-revision.md`). At each phase, **scan the menu
below and pick only what THIS problem's requirements justify.** Never dump the whole list — the
skill is constraint-driven selection. Every pick must trace back to a requirement or a number.

> Universal rule: **Business requirement → traffic pattern → bottleneck → simplest fix → tradeoff → failure → 10× evolution.**

---

## Phase 1 — Capacity Estimation

**Numbers to memorize:** 1 day ≈ 86,400 s ≈ 10⁵ s · 1 month ≈ 2.5M s · peak QPS ≈ 2× avg · read:write often 100:1.

| Estimate | Formula |
|---|---|
| Write QPS | daily writes ÷ 86,400 |
| Read QPS | write QPS × read:write ratio |
| Storage | items × row size × retention years |
| Cache size | hot-set % (≈20%) × daily items × row size |
| Bandwidth | QPS × payload size |

> The estimate *drives every later pick*: read-heavy → cache + replicas; big storage → shard; global → multi-region.

## Phase 2 — API Design
| Decision | Options | Pick when |
|---|---|---|
| **Style** | REST · gRPC · WebSocket · GraphQL | REST default · gRPC internal/low-latency · **WebSocket when the SERVER must push** (chat, live game) · GraphQL when clients need wildly different shapes |
| **Pagination** | cursor · offset | **cursor almost always** — offset drifts and duplicates when rows are inserted while you scroll, and gets slow at depth |
| **Long work** | sync 200 · **202 + poll/webhook** | 202 whenever the work outlives a request (transcode, export, batch) |
| **Retries** | idempotency key | **any non-GET with a real side effect** (charge, send, book) — the client WILL retry |
| **Versioning** | URL `/v1/` · header | URL is simplest and most visible |
| **Rate limits** | `X-RateLimit-*` + `Retry-After` on 429 | always — a 429 without `Retry-After` just gets hammered |

**Status codes that carry meaning:** `201` created · `202` accepted-not-done · `204` no content ·
`404` never existed vs **`410` existed and is gone** (expired/disabled) · `409` conflict (someone beat
you) · `429` slow down.

> The API is where your error *types* become visible. If your service raises `LotFullError` and
> `AlreadyParkedError`, they map to 503 and 409 — that's why raising beats returning `None`.

## Phase 3 — Database Choice (pick per workload)

| DB | Pick when | Avoid when |
|---|---|---|
| **PostgreSQL / SQL** | ACID, joins, transactions, reporting, < ~100M rows, strong consistency | internet-scale writes, pure KV |
| **Cassandra** | massive write throughput, KV access, horizontal scale, AP/high-availability | joins, transactions, strong consistency |
| **MongoDB** | document/nested data, flexible schema, moderate scale | pure KV at internet scale |
| **Redis** | serving/cache layer, hot data, counters, locks | as the source of truth (RAM cost, loss risk) |
| **DynamoDB** | managed KV, conditional writes, predictable scale | complex queries/joins |

> Default: **start with PostgreSQL** unless scale/workload *clearly* demands Cassandra. Don't optimize for 1B users on day 1.

## Phase 4 — ID / Key Generation (pick per need)

| Method | Pick when | Watch out |
|---|---|---|
| **Auto-increment → Base62** | simple, single DB | counter is a bottleneck/SPOF distributed |
| **KGS (counter ranges)** | distributed, no per-write coordination | KGS is a SPOF → replicate/pre-gen |
| **Snowflake ID → Base62** | distributed, time-sortable, no central counter | clock skew, machine-id mgmt |
| **Random + conditional write** | unguessable codes, no coordination | rare collision → retry (`save_if_absent`) |
| **Hash of content (SHA)** | dedup identical inputs | collisions, long codes, no custom alias, breaks on update |

> **Base62 not Base64** — Base64 has `+ / =` which are URL-unsafe. Base62 = `A–Z a–z 0–9`.

## Phase 5 — Database Scaling (the progression — never jump to the end)

```
Vertical  →  Read Replicas  →  Partitioning  →  Sharding  →  Multi-Region
(bigger box) (scale reads)   (split tables)   (scale writes/storage) (global)
```

**Sharding strategies:**
| Strategy | Pros | Cons |
|---|---|---|
| Hash `hash(key)%N` | even distribution | hard resharding |
| Range (A–F, G–M…) | simple, range scans | hot shards |
| Geo (US/EU/IN) | low latency | cross-region queries |
| **Consistent hashing** (ring) | adding a node moves only nearby keys | more complex (Cassandra, Dynamo) |

**Replication models:**
| Model | Writes | Note |
|---|---|---|
| Leader–Follower | leader only | reads from followers; **replication lag** → eventual consistency |
| Multi-Leader | multiple regions | low write latency, **conflict resolution** needed |
| Leaderless (Cassandra) | any node | **Quorum**: `W + R > RF` guarantees latest read |

- **Partitioning ≠ Sharding:** partitioning = split tables *inside one DB*; sharding = *across machines*.
- **Replication lag fix** (read-your-own-write): read from primary after write · sticky session · accept eventual.
- **CAP:** partitions are unavoidable → trade **C vs A** during a partition. Postgres = CP, Cassandra = AP.

## Phase 6 — Caching (pick pattern + protect it)

**Patterns:** cache-aside (default) · read-through · write-through (consistent, slower) · write-back (fast, risky).
**Placement:** CDN (static/redirects) → local LRU (per app node) → Redis (shared) → DB.

| Problem | Fix |
|---|---|
| **Hot key** (one viral item) | CDN · local LRU · Redis replicas · cache warming |
| **Cache stampede** (key expires, all hit DB) | single-flight · mutex · soft TTL · background refresh |
| Stale data | TTL + invalidation on write |

## Phase 7 — Async / Messaging (only when it earns it)

Use a queue/**Kafka** when: decouple producers/consumers · smooth spikes · async work (analytics, email) · event fan-out.
- **Outbox pattern:** DB txn writes an outbox row → worker publishes → Kafka. Guarantees the event isn't lost if the broker is down.
- **DLQ:** consumer fails repeatedly → route to Dead Letter Queue → investigate → replay. (Don't retry forever.)
- **Sync vs async rule:** never block the core path (redirect) on non-core work (analytics).

## Phase 8 — Reliability (tie each to a real failure)

| Pattern | Fixes |
|---|---|
| Retry + **exponential backoff** | transient failures (don't retry-storm) |
| **Timeout** | never wait forever on a dependency |
| **Circuit breaker** (Closed→Open→Half-open) | stop hammering a failing dependency |
| **Bulkhead** (separate thread pools) | one workload's overload can't sink another |
| **Idempotency / dedup key** | safe retries, no duplicates — at-least-once *will* redeliver, so any real-world side effect (send/charge/ship) needs `event+user+channel` checked before acting |
| **Graceful degradation** | core keeps working when a non-core dep dies |

## Phase 9 — Availability (kill every SPOF)
**The method: point at every box and ask "what if this one dies?"** Anything with no answer is a SPOF.

| Layer | Single point of failure | Fix |
|---|---|---|
| DNS | one region | GeoDNS / Anycast, health-checked |
| Load balancer | one LB | ≥2, active-active |
| App servers | one box | stateless + N behind the LB |
| Database | one primary | replicas + **automatic failover** (promotion) |
| Cache | one node | cluster + replicas; and survive it being empty |
| Queue | one broker | replicated partitions |
| Region | one region | multi-AZ first, multi-region if the SLA demands |

**Health checks — two kinds, often confused:**
- **liveness** (`/health`) — "am I alive?" → if not, **restart me**
- **readiness** (`/ready`) — "can I serve?" → if not, **take me out of the LB** but leave me running
  *(a box warming its cache is alive but not ready)*

**Availability maths (know these):**
```
99%      = 3.65 days/year down
99.9%    = 8.8 hours       <- "three nines"
99.99%   = 52 minutes      <- typical serious target
99.999%  = 5 minutes       <- expensive; needs multi-region
```
> Every extra nine roughly **10×s the cost**. Ask what the business actually needs before promising five.

## Phase 10 — Bottleneck Analysis (where it breaks, in order)
**The method: walk the request path and ask what saturates FIRST** — where the first *queue* forms, not the slowest box. Bottlenecks are found **in order**: fix one, the next appears.

| Layer | Symptom | Usual cause | Lever |
|---|---|---|---|
| **App tier** | latency up, pool exhausted, CPU *idle* | threads blocked downstream | scale out — *only* if downstream has room |
| **Cache** | hit rate drops, DB QPS jumps | hot key, mass expiry, set > RAM | jittered TTL · local LRU · cluster |
| **DB reads** | scans in the slow log | missing index, N+1 | index → cache → **read replicas** |
| **DB writes** | commit latency, lock waits, iowait | one primary, row contention, fsync | batch → partition → **shard** |
| **Queue** | lag rising without bound | consumers slower than producers | more consumers → more partitions |
| **External** | your p99 *is* their p99 | sync dependency | timeout + breaker + async (Phase 8) |

**The DB goes first** — the stateful layer you can't clone: a second primary isn't a copy, it's a consistency problem. **Replicas fix reads; sharding fixes writes** — every replica replays every write.

**Little's Law:** `concurrency = arrival rate × latency` — 2k QPS × 100 ms = 200 in flight; at 300 ms the *same* traffic needs 600. Latency and throughput are **not** independent.

**The trap:** DB pinned, so you autoscale the app tier — 10 boxes × a 50-conn pool = **500 more connections onto the thing already dying.** Never scale out in front of a saturated stateful tier.

> *"I'd look for the first queue, not the slowest box"* — then the metric: **p99 per layer** (RED, Phase 12), cache hit rate, consumer lag. Averages hide the queue.

## Phase 11 — Security
| Concern | Method | When |
|---|---|---|
| **Who are you** | OAuth2 / JWT / session cookie | any user-facing system |
| **What may you do** | RBAC (roles) · ABAC (attributes) | multi-tenant, admin surfaces |
| **Abuse volume** | **rate limiting** per user/IP/endpoint | any public endpoint |
| **Bots** | CAPTCHA, device fingerprint, per-account caps | drops, signups, voting |
| **In transit** | TLS everywhere, including service-to-service | always |
| **At rest** | disk/field encryption, KMS for keys | PII, money, health |
| **Secrets** | a secret manager, never in code or env dumps | always |
| **Input** | validation + parameterised queries | always (SQLi/XSS) |
| **Data exposure** | least privilege, tokenise PII, audit reads | regulated data |

**The ones people forget in HLD rounds:**
- **Pre-signed URLs** so big uploads/downloads bypass your servers *without* being public
- **Server-side re-validation** of anything the client claims — the chess anti-cheat lesson: never
  trust the client's idea of what's legal
- **Idempotency keys** are a security control too — they stop replayed writes
- **Dedup can leak information**: global content-dedup lets someone probe whether a file already exists

> Say "auth, transport, at-rest, abuse" as four buckets and you'll never blank on this section.

## Phase 12 — Monitoring & Observability
**Three pillars:** metrics (aggregate numbers) · logs (individual events) · traces (one request end-to-end).

| Framework | Use for | The four/three things |
|---|---|---|
| **RED** | services | **R**ate, **E**rrors, **D**uration |
| **USE** | resources | **U**tilisation, **S**aturation, **E**rrors |
| **Four Golden Signals** | anything | latency, traffic, errors, saturation |

**Percentiles, not averages.** An average of 50 ms hides that 1% of users wait 4 seconds. **Watch p99.**
```
p50  the typical user      p95  the annoyed user      p99  the one who tweets about you
```

**Per-system headline metric** (know the one that matters for each design):
| System | The metric |
|---|---|
| Cache | **hit rate** (a 1% drop = hundreds of extra DB QPS) |
| Queue | **consumer lag** |
| Feed / fan-out | fan-out lag |
| Scheduler | **scheduling lag** (fired_at − scheduled_for) |
| Ticketing | oversell count (**must be 0**) + conflict rate |
| Payments | ledger sum ≠ 0 (should be impossible → page instantly) |
| Video | rebuffer ratio, startup time |

**Tracing:** one **trace id** propagated App→Cache→DB→Queue. Without it, "it's slow" is unanswerable
in a distributed system.

**Alerting rule:** alert on **symptoms users feel** (p99, error rate), not causes (CPU 80%). A paged
engineer at 3am should be looking at something a user noticed.

## Phase 13 — Disaster Recovery
**The two numbers that define everything — state them, then design to them:**
```
RTO  Recovery Time Objective  = how long may we be DOWN?      (e.g. 15 min)
RPO  Recovery Point Objective = how much data may we LOSE?    (e.g. 30 s)
```

| Strategy | RTO | RPO | Cost | Pick when |
|---|---|---|---|---|
| **Backup + restore** | hours | hours | 💲 | internal tools, non-critical |
| **Pilot light** (core replicated, rest off) | ~1 h | minutes | 💲💲 | most businesses |
| **Warm standby** (scaled-down live copy) | minutes | seconds | 💲💲💲 | serious products |
| **Active-active** (both regions serving) | ~0 | ~0 | 💲💲💲💲 | payments, comms, anything 99.99%+ |

**How RPO is actually achieved:** continuous WAL/commit-log shipping (RPO ≈ seconds) vs nightly
snapshots (RPO = up to 24 h). Snapshots alone can never give you a seconds-level RPO.

**The three failure scopes** — don't conflate them:
```
one machine  -> replicas + auto-failover            (minutes, routine)
one AZ       -> multi-AZ deployment                 (should be automatic)
one REGION   -> cross-region replication + GeoDNS   (this is what DR means)
```

> **The line that matters: "an untested backup is not a backup."** Say you'd run DR drills — restore
> to a scratch environment on a schedule. Most real outages are made worse by a restore path nobody
> had ever exercised.

## Phase 14 — Cost Optimization
**Where the money actually goes** (roughly, and it surprises people):
```
egress bandwidth  >  compute  >  storage  >  requests
```
Cross-region and internet egress is the silent killer — **a CDN is usually a cost decision as much as
a latency one.**

| Lever | What it does | Watch out |
|---|---|---|
| **Cache / CDN** | cuts both DB load *and* egress | staleness; cache infra costs too |
| **Tiered storage** | hot → warm → cold (S3 → Glacier) | retrieval is slow *and* charged |
| **TTL / retention** | delete what nobody reads | check compliance before deleting |
| **Right-sizing** | stop paying for 90% idle | needs real utilisation data |
| **Autoscaling** | pay for the peak only at peak | scale-up lag; scale on the right signal |
| **Spot / preemptible** | ~70% cheaper compute | only for **retryable** work (transcoding, batch) |
| **Reserved / committed** | ~40% off steady baseline | locks you in for 1–3 years |
| **Compression** | smaller storage *and* egress | CPU cost |
| **Approximate counting** | HyperLogLog instead of exact sets | ~1% error |
| **Batching** | fewer requests, fewer round trips | added latency |

**The routing insight:** when channels have different costs, **cost becomes a design rule**, not an
afterthought. Notifications: prefer push → in-app → email → **SMS last, it costs real money per message.**

> A good line: *"the cheapest request is the one that never reaches my origin"* — which is why CDN
> hit-rate is simultaneously a latency metric and a cost metric.

## Phase 15 — Geospatial search ("find X near me")

| Method | Pick when | Watch out |
|---|---|---|
| **Bounding box + haversine** | any radius query; simple | needs a lat/lng index; box ≠ true circle → refine by haversine |
| **Geohash** (prefix = cell) | internet-scale "near me"; shardable | edge points share no prefix → query the **8 neighbor cells** too |
| **S2 / H3 / quadtree** | variable density, poles, ride-hailing supply | more machinery |
| **PostGIS GIST · ES geo_point · Redis GEOSEARCH** | you already run that store | — |

> Small/static set (≤ millions) → PostGIS or a plain lat/lng index. Internet-scale → geohash/S2 **sharded by cell** + cache hot cells.

## Phase 16 — Fan-out (one event → many recipients)

**The amplification:** ingest is small, delivery is huge. 1 event × N recipients × M channels.
Design for the multiplication, not the ingest rate.

| Strategy | How | Pick when | Cost |
|---|---|---|---|
| **Fan-out on write** (push) | precompute per recipient at event time | normal users; anything that must actually be *sent* (SMS/email/push) | write amplification; brutal for celebrities |
| **Fan-out on read** (pull) | store once, compute per-viewer at read time | huge follower counts; feeds & in-app inboxes | slower reads |
| **Hybrid** | push for normal users, pull above a follower threshold | the real production answer | two code paths |

- **Celebrity / hot-partition problem:** one event → 10M writes. Fix: chunk the recipient list and
  fan out in parallel, or flip that event to pull-based.
- **Per-consumer isolation:** one topic + worker pool **per channel/consumer type** — a dead provider
  backs up only its own lane (bulkhead in infrastructure).
- **Priority lanes:** transactional (OTP) must never queue behind a marketing blast.
- **Dedup:** at-least-once means re-delivery. Deterministic key (`event_id+user_id+channel`) checked
  before send — users notice duplicates, not latency.
- **Digest/caps:** 200 comments ≠ 200 pushes. Cap per user per window, then batch into a summary.
- **Third-party limits:** circuit breaker + token bucket **per provider**, and a fallback channel.

## Phase 17 — Extreme contention (inventory, ticket drops, flash sales)

Not a throughput problem — a **contention** problem. Millions of users, but all fighting over a few
thousand rows at the same instant.

| Method | What it does |
|---|---|
| **Waiting room / virtual queue** | give everyone a position, admit N/sec into the real flow. Sheds the spike *before* the DB sees it; also makes the wait honest and **fair by arrival time** (bots don't win) |
| **Atomic claim in the WHERE clause** | `UPDATE … SET status='HELD' WHERE status='AVAILABLE'` — the DB arbitrates; `rowcount` tells you if you won. App-level locks don't span servers |
| **All-or-nothing via transaction** | `rowcount != requested` → ROLLBACK. Partial claims strand inventory |
| **TTL-based holds, not locks** | a crashed service or abandoned payment **self-heals** when the TTL lapses — no compensating transaction |
| **Lazy reclaim** | fold `OR (status='HELD' AND expires_at < now())` into the claim itself → expired holds are reclaimed by the next buyer, no sweeper needed |
| **Split read/write consistency** | seat map stale-by-seconds is fine (revalidated at claim time); the claim itself must be exact |
| **Shard by the contended entity** (`show_id`, `event_id`) | one hot item can't slow the rest |
| **Fail CLOSED** | refuse to sell rather than risk double-selling (opposite of a rate limiter's fail-open) |
| **Fail fast on loss** | 49,999 losers need an instant clear rejection, not a timeout |

## Scaling Evolution (say what changes at each step, and why)
**The method: climb one rung at a time, and for each name the new problem it buys.**

| Rung | Rough scale | New problem it creates |
|---|---|---|
| **1 box (vertical)** | ~10K users | hard ceiling; app + DB both SPOFs |
| **Split the DB onto its own box** | ~50K | a network hop; DB is now the SPOF |
| **LB + N stateless app servers** | ~100K | deploys/health checks; sessions must leave the box (below) |
| **Add a cache** | ~1M | staleness · stampede · hot key |
| **Read replicas** | ~5M | **replication lag** → read-your-writes breaks |
| **CDN for static/media** | ~10M | invalidation; cache-key design |
| **Shard the write path** | ~50M+ | no cross-shard joins/txns · resharding · hot shards → **Phase 5** |
| **Multi-region** | global | conflict resolution · cross-region egress |

**The ordering *is* the answer:** LB early — the 2nd app box is bought for **availability**, not load · cache before replicas (cheaper, no lag) · **sharding last, it's the one that's painful to undo.**

**Stateless is the precondition for horizontal:** sessions → Redis/JWT, uploads → S3, nothing on local disk — else the LB can only do sticky sessions.

**Vertical before horizontal** — 2× the box is one afternoon and no new failure modes. It just stops at a known ceiling.

> Juniors recite the ladder. Seniors name **what they'd measure before climbing**: *"reads are 95% of load and the primary is CPU-bound at 70% — that's a replica, not a shard."*

## Per-Component Template (for the component-breakdown phase)
**The method: run these seven on every box before you draw the next.** Merges spine steps 5 and 8 — the death question answered under your pen.

| Ask | Why it matters |
|---|---|
| **Owns** — one sentence · and what it does **NOT** own | no one-sentence answer → it's two boxes |
| **Interface** — callers · callees · sync or async | arrow direction, and where latency is paid |
| **State** — stateless, or what it stores and where | "stateless" is a claim you must earn |
| **Scale** — horizontal? partition key? singleton? | "add servers" is nothing without the key |
| **Dies** — who notices · what degrades · open or closed | no death story = a hidden SPOF (Phase 9) |
| **Headline metric** — the number that says it's sick | one tile per box, picked as you draw |
| **Bottleneck** — what saturates first *inside* it | everything breaks somewhere; say it first |

**Memorise:** stateless → add instances · stateful → owe a shard key · singleton → only if leader-elected **with automatic failover** (a write primary is the accepted exception). Fail **OPEN** when the box is non-core (analytics, enrichment, rate limiter) — never fail the core path for non-core work; **CLOSED** only when being wrong costs money or inventory (payments, seat claims).

**Worked — notification consumer:** owns event → message once per `event+user+channel`; not *when* it changed. In async, out sync HTTP. Stateless: offset in broker, dedup in Redis. One per partition, key `user_id`. Dies → lag grows, nothing blocks: fail-open. Metric: lag seconds. Bottleneck: slowest provider → bulkhead + DLQ.

> Naming what a component does **not** own is the fastest way to show you drew the boundaries on purpose.

## Common Mistakes
**The method: at this level you lose on process, not knowledge.** The five in `interview-mode/HLD-BASICS.md` §9 (no estimate, boxes first, over-engineering, silence, no failure story) are assumed fixed — these are the layer above them.

| Mistake | Do instead |
|---|---|
| "I'll use Kafka" — a name, not a tradeoff | say what it **buys** and what it **costs**: decouples the write path, pays in duplicates + ordering only per partition |
| NoSQL by reflex | lead with the access pattern — "always read by `(user_id, ts)`" — *then* the store |
| Polished read path, no ingest story | trace **one write end-to-end** before optimising any read |
| Fail-open vs fail-closed left implicit | it is a product call — it belongs in **requirements (step 1)**, not discovered mid-deep-dive |
| Retried writes with no idempotency key | mark idempotent endpoints in **Phase 2 (API)**, not once they ask |
| SPOF pass skipped, or "it dies, we fail over" | per box: blast radius + **degraded mode** ("stale reads, no new signups") |

**Self-check once the boxes are drawn** (the clock lives in `HLD-revision.md`):
```
stated a number?       no -> back to Phase 1; nothing after it is justified
named the ONE crux?    no -> stop drawing, start the deep dive
said a cost out loud?  no -> you described it, you didn't design it
```

> The round is decided in the deep dive, not the diagram — and piling 1B-user machinery around a thin core reads as *avoiding* the crux. Strong candidates state a number, pick the simplest thing that meets it, and name out loud what it costs.

