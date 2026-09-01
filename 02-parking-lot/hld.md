# Parking Platform — HLD (city scale)

Companion to [`solution.py`](solution.py) (the single-lot LLD). Now: **a platform for a whole city —
~1000 garages, drivers searching "open spots near me", reserving, entering, and exiting.**
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).

> LLD = one lot's classes. HLD = the platform: many lots, real-time availability, reservations, at scale.
> **Golden rule: every box exists because a _number_ demanded it.**

---

## 1. Requirements & scope   ✅ LOCKED

### Functional
- **Search** open spots **near me** (by location / radius) — the dominant, read-heavy path
- **Reserve** a spot (hold it before arrival)
- **Check-in** (arrive → occupy the reserved spot)   *(the LLD's `park()`)*
- **Check-out** (leave → free the spot, compute fee)
- Track parking duration + calculate cost

### Non-functional
- **Search / availability = eventually consistent** — "7 free" vs really 6 for a second is fine → favor latency + availability (AP)
- **Reservation = strongly consistent** — never hand the last spot to two drivers (CP on the reserve write) → the distributed cousin of the LLD `find→claim` TOCTOU
- **Low read latency** — search is the hot path (target < ~200 ms)
- **Scalable** to ~1000 garages / millions of drivers; **read-heavy** (search ≫ reserve/check-in)
- **High availability** — 99.99% (finding & parking must keep working)

### Out of scope
- Payments processing · admin / garage-owner management · dynamic surge pricing · EV charging · in-garage sensor hardware · turn-by-turn navigation

> 📝 **Review note (Step 1):** carried the LLD verbs but the platform adds **search-near-me** (geo, read-heavy) and **reserve** (the signature feature + the reservation race). Key senior move: split consistency by subsystem — **search = eventual (AP)**, **reservation = strong (CP)** — instead of one blanket "must be consistent". That split is the whole design; it's the distributed form of the single-lot TOCTOU.

## 2. Capacity estimate   ✅ LOCKED

**Assumptions:** 1000 garages × 200 spots = **200K spots** · DAU 1M, MAU 15M.

- **Writes** = reserve + check-in + check-out ≈ 3/session. 1M × 3 ÷ 86,400 ≈ **~35 QPS** (~70 peak) → tiny, single primary handles it.
- **Reads** = search, but a search = map UI polling (pan/zoom/refresh) ≈ **15 reads/trip**. 1M × 15 ÷ 86,400 ≈ **~175 QPS** (~350 peak).
- **Ratio ≈ 5:1 read-heavy** → availability **cache + geo read replicas**.
- **Storage:** spots are static → 200K × 300 B ≈ **60 MB** (nothing). The growth is **session history**: 1M/day × 365 × 5 yr ≈ 1.8B rows × 300 B ≈ **~550 GB** → shardable, modest.

> 📝 **Review note (Step 2):** two fixes — (1) **QPS = daily ÷ 86,400** (not the raw daily count); (2) **"define a read" first** — a search is really ~15 map-poll queries, which turns a fake ~1.3:1 into a real **5:1 read-heavy**, the thing that *justifies* cache + replicas. Writes are tiny (~35 QPS) → no write scaling needed. Storage volume is **session history**, not spots.

## 3. API   ✅ LOCKED

```
GET  /api/v1/search?lat&lng&radius&filters        -> nearby garages + availability   (read, cacheable)
POST /api/v1/reservations                          -> hold a spot                      (strongly-consistent write)
POST /api/v1/reservations/{id}/check-in            -> occupy the spot
POST /api/v1/reservations/{id}/check-out           -> free spot, return fee
```
- check-in/out are **POST** (state change), not GET (GET must be side-effect-free).

## 4. Data model + DB choice   ✅ LOCKED

```
Garage(id, name, lat, lng, geohash)                       -- static; geo-indexed
Spot(id, garage_id, type, status)                         -- source of truth for occupancy
Reservation(id, garage_id, spot_id, user_id, status,
            reserved_at, checkin_at, checkout_at)
Availability (cache):  garage_id -> {SpotType: free_count} -- Redis, eventual, serves search
```

- **DB = PostgreSQL (+ PostGIS)** — relational, ACID, small data (200K spots). Availability counts → **Redis**.
- **Reservation strong-consistency:** a spot can't have two active reservations → **UNIQUE / conditional write** (`INSERT … WHERE NOT EXISTS active` or `SELECT … FOR UPDATE`). This is `save_if_absent` at the DB level — the arbiter across all app servers.
- **Availability for search:** served from the Redis counts (updated on reserve/checkin/checkout), **not** a per-search DB scan → eventual + fast.
- **"Near me":** **bounding box → refine by haversine** (✓). Fast via a **geospatial index** — **geohash** prefix / PostGIS GIST / S2 cells. 1000 garages barely needs it; geohash is the scale-up.

> 📝 **Review note (Step 3–4):** two strong instincts — reservation = **conditional insert** (`save_if_absent` at DB), geo search = **bounding box + haversine**. Fixes: check-in/out are **POST** not GET (state change); live availability lives in a **Redis cache** (eventual), not a per-search scan; **DB = Postgres/PostGIS** (small, relational, ACID reservations); named the **geohash** geospatial index as what makes the box fast at scale.

## 5. Architecture (boxes + read/write flows)   ✅ LOCKED

```
                         ┌─▶ Search Service ──▶ Geo index (garages: STATIC → cached / replica)
Client ─▶ LB / API GW ──┤                    └─▶ Redis (availability counts: DYNAMIC)
                         └─▶ Reservation Svc ─▶ Postgres (conditional insert)
                                                     │  └─▶ Redis (decrement count)
                                                     └─▶ Kafka ─▶ session history / analytics
```

- **Search (read, ~175 QPS):** client → LB → Search Svc → geo index finds candidate garages in the bbox (static → cached, never the primary) → Redis returns their live counts → refine by haversine → return.
- **Reserve (write, ~35 QPS):** client → LB → Reservation Svc → **conditional insert** in Postgres (atomic claim) → on success **decrement the Redis count** → return. On conflict → 409 (spot just taken).
- **Split by consistency:** Search Svc (read/AP, scales on replicas+cache) vs Reservation Svc (write/CP, hits Postgres) — different scaling, different guarantees.

> 📝 **Review note (Step 5):** both flows correct — search = geo-index candidates + Redis counts; reserve = conditional insert + count update. Refinement: garage geo-index is **static** → cache it / serve from replica so search never touches the primary; only counts are dynamic. The reserve path does **two writes** (Postgres + Redis) → dual-write **drift** is the §6 crux.

## 6. Deep dive (the crux: real-time availability + reservations)   ✅ LOCKED

**Problem 1 — dual-write drift** (Postgres reserved, but the Redis count-update is lost):
- **Outbox pattern:** in the *same Postgres transaction* as the reservation, write a `count_change` event to an outbox table → a relay worker reads the outbox and applies it to Redis → marks the event processed. The update can't be silently lost (at-least-once).
- **Idempotency:** at-least-once means an event can replay, and a counter delta (`-1`) is **not** idempotent (applying twice double-counts) → dedup by event id (skip if already `done`), or apply as an absolute set.
- **Self-heal net:** a periodic job recomputes each garage's counts from Postgres (source of truth) and refreshes Redis → bounds any drift (eviction, failover, bug). Allowed because availability is *eventually consistent*. *(CDC from the Postgres WAL is an alternative to a hand-rolled outbox.)*

**Problem 2 — no-show leak** (a hold that never checks in):
- Each reservation carries a **hold expiry** (`reserved_at + TTL`). A **background reaper** finds expired, un-checked-in reservations → marks them expired → releases the spot (incrementing the count via the *same* outbox path). The distributed cousin of the LLD double-park leak / URL-shortener expiry.

> 📝 **Review note (Step 6):** nailed both — **outbox** for reliable Redis propagation (at-least-once + idempotent via event status), and **reservation TTL + reaper** for no-shows. Added: counter deltas aren't naturally idempotent → dedup by event id; and a **periodic reconcile** from Postgres as the self-heal net (CDC = alternative). Postgres stays source of truth; Redis is derived.

## 7. Scale

- **Reality check:** 1000 garages is *small* — one Postgres (+PostGIS) + Redis + read replicas serves the whole city. Say this; don't over-build.
- **Scale-up story (many cities / Uber-scale):**
  - **Geo:** geohash-shard the garage index by region; **multi-region** deploy (GeoDNS) so search hits a nearby region.
  - **Search svc:** stateless, cache-fronted → scale horizontally on the ~175→N QPS.
  - **Redis:** cluster + replicas; hot-city keys get local/CDN caching.
  - **Postgres:** read replicas for the search-side reads; shard reservations by `region/garage_id` only if writes actually grow.
  - **Session history (~550 GB, growing):** partition by time; archive old to cold/columnar store.

## 8. Reliability & failure (what if each dies)

- **Redis down** → availability cache miss → recompute counts from Postgres (slower, still works). Reservations unaffected (Postgres is truth).
- **Postgres primary down** → replica auto-promotes; reservations pause for seconds, **search still served** from Redis/replicas.
- **Outbox worker down** → events pile up in the outbox table, drained on recovery → no loss.
- **Kafka down** → outbox retries; history/analytics delayed, not lost.
- **Region down** → GeoDNS / global LB reroutes to a healthy region.
- **Graceful degradation:** never block search if counts are stale — show garages, maybe without exact counts. The only hard-fail path is reservation on Postgres-down → fail fast (correct: better than double-booking).

## 9. Wrap (bottlenecks, tradeoffs, monitoring, DR, cost)

- **Bottleneck:** the search read path → cache + replicas; hot cities → shard / multi-region.
- **Key tradeoffs:** eventual availability (fast, slightly stale) vs strong reservation (correct); Postgres+PostGIS (simple, ACID, small data) vs dedicated geo-store (only at scale); outbox complexity vs guaranteed count consistency.
- **Monitoring:** search P99, cache hit rate, **reservation conflict rate (409s)**, **outbox lag**, count-drift (reconcile diffs), reaper releases/hr.
- **DR:** RTO/RPO targets; cross-region replicas; WAL backups.
- **Cost:** cache to cut DB load; footprint is small; tier session history to cold storage.

---

## LLD ↔ HLD mapping (connect the two rounds)

| LLD (`solution.py`) | HLD (this doc) |
|---|---|
| `SpotAssignmentStrategy` (find a fitting spot) | **geo search** — bounding box + haversine over a geohash index |
| `find→claim` under `self.lock` (TOCTOU) | **reservation** — Postgres conditional insert (the arbiter across servers) |
| `is_available` flag on a spot | **Redis availability counts** (derived cache, eventual) |
| double-park guard (spot leak) | **reservation TTL + reaper** (no-show leak) |
| `CostCalculator` on check-out | fee at **check-out**, session history → Kafka |
| single-process, one lot | **platform**: geo-sharded, cached, multi-service, eventually-consistent availability |

