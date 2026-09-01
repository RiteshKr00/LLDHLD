# Food Delivery — HLD (Swiggy / Zomato / DoorDash scale)

Companion to [`solution.py`](solution.py) (the single-process orchestrator).
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).
Geo search → `../02-parking-lot/hld.md`: **bbox → haversine over a geohash index** + the **AP-search /
CP-reserve** split. Both carry over unchanged — don't re-derive them.

> **Framing:** parking indexed **garages, which do not move** — static, cached, 5:1 read-heavy. Here the
> indexed thing is a `DeliveryPartner` whose `location` changes every few seconds. That one word inverts the
> design: the index becomes **~550:1 write-heavy** and can no longer live where parking's did.

## 1. Scope
- **Functional:** place + price · accept/reject · **assign a partner** · drive
  `PLACED → ACCEPTED → PREPARING → READY → PICKED_UP → DELIVERED` (+`CANCELLED`) · notify the right actors ·
  **live tracking** (out of LLD scope, in HLD scope) · surge.
- **Non-functional:** an order is **never silently lost** · a partner is **never double-assigned** ·
  assignment p99 in seconds · matching *quality* may degrade, correctness may not.
- **Out:** payments, browse/search, ratings, refunds, scheduled orders.

## 2. Estimate — the location stream dwarfs everything

**Assumptions:** 2M orders/day · 200K partners online at peak · ping every 4 s · ~30 min per delivery.

| | Arithmetic | Result |
|---|---|---|
| Orders, average | 2,000,000 ÷ 86,400 | **~23/s** |
| Orders, peak (2× rule) | 23 × 2 | ~46/s |
| Orders, **real** peak | 65% in a 4 h lunch+dinner window: 1.3M ÷ 14,400 | **~90/s (≈4× avg)** |
| Lifecycle writes | 90 × 7 (create + 5 transitions + the assignment write) | ~630/s — one Postgres primary |
| **Location pings** | 200,000 ÷ 4 s | **50,000/s at peak** · ~5 MB/s · ~6 peak-hours/day → **~110 GB/day** |
| Geo **reads** | one candidate search per order | ~90/s |
| Tracking sessions | 90/s × 1,800 s per delivery | **~160K concurrent** |
| Order storage | 2M/day × ~2 KB | 4 GB/day ≈ **1.5 TB/yr** → shard by city |

- **Say the duty cycle out loud, or the day figure is wrong.** 50,000/s is a *peak* rate; 5 MB/s sustained for a
  full 86,400 s would be **~430 GB/day**. Partners log off between meal rushes, so ~6 peak-equivalent hours is the
  honest number — **~110 GB/day**. Quote **430 GB/day raw** only if you mean round-the-clock. Either way it is
  cold-store data: compress and downsample past the dispute window, never keep it at ping resolution.
- **The two numbers to say out loud:** location writes are **~80× the whole order-lifecycle write load**, and the
  geo index runs at **~550 writes per read** — parking was 5:1 *read*-heavy over a static set. Index size is
  trivial (200K × ~200 B = **40 MB**): shard by city for blast radius, not capacity. The write rate hurts, not the volume.

## 3. Architecture

```
 Customer ─┐                  ┌─▶ Postgres (orders, items, amount PINNED)  [CP]
 Restaurant┼─▶ API GW ─▶ Order Service ─outbox─▶ Kafka order-events (key = order_id)
 Partner ──┘         (ALLOWED_TRANSITIONS       ├─▶ notifiers (1 consumer group/channel, dedup)
                      = the ONLY writer)        ├─▶ ETA · analytics · ledger
                                                └─▶ Tracking edge ══WS══▶ customer's phone
 Partner app                                                  ▲ subscribes to one partner key
   │ 50K pings/s (fire & forget, lossy OK)                    │
   ▼                                                          │
 Location Ingest ─▶ Redis GEO: partner → (lat,lng) TTL 30s ───┘   [AP, no durability]
   └────────▶ Kafka breadcrumbs ─▶ cold store (disputes, ETA training)
                                     ▲
 Dispatcher (per city, batch window)─┘ reads candidates
   └─▶ claim ▶ UPDATE partners SET status='BUSY' WHERE id=? AND status='AVAILABLE'  [CP]
 Surge pipeline ─▶ Redis zone→multiplier ──read ONCE at quote time──▶ Order Service
```

## 4. The key decisions

### (a) A write-heavy geospatial index
- Parking could keep its geo index **in Postgres/PostGIS at all** — the garages are static, so it was cached and
  served off a replica and the primary never saw a write to it; only the availability counts moved. Here the index
  *is* the write path, so that escape hatch is gone: 50K/s of coordinate updates = rewriting a B-tree entry
  50,000×/s, plus WAL, plus vacuum, for a value worthless in 30 s.
- **Right shape:** in-memory, keyed by partner (`Redis GEOADD`, or h3 cell → set of ids) — an overwrite touches
  one key. At 20 km/h a partner crosses a ~1 km cell every ~3 min, so ~45 of 46 pings don't change cell membership.
  The **read** is unchanged: candidate cell + 8 neighbours → refine by `Location.distance_km`.
- **TTL is the offline detector.** Each ping refreshes a 30 s TTL, so a dead battery drops the partner out by
  itself — no sweeper, no heartbeat table. **TTL/lease self-healing.**

### (b) Location ingest is a separate tier, allowed to lose data
- Pings never reach the Order Service or Postgres: validate → write one key → done.
- **Losing a ping is free** — the next is 4 s away and more accurate. No ack, no retry, no DLQ. The order write
  may never be lost: **two streams, two guarantees, deliberately separated.** Skip the split and one bad
  partner-app release doubling its ping rate takes down order placement.
- Breadcrumbs (dispute replay, ETA training) are a *different consumer* → Kafka → cold store, off the hot path.

### (c) The claim — the 7th appearance of check-then-act
The LLD holds `self._lock` across `find_partner(...)` → `partner.status = PartnerStatus.BUSY`. One process.
Across dispatchers that lock means nothing; **push atomicity into the shared store**:

```sql
UPDATE partners SET status='BUSY', current_order=:oid, claim_expires_at = now() + interval '90 seconds'
 WHERE partner_id = :pid
   AND (status = 'AVAILABLE'
        OR claim_expires_at < now()      -- lazy reclaim of a stuck claim
        OR current_order = :oid);        -- my own retry re-wins, doesn't burn a 2nd partner
```
- `rowcount == 1` → won. `rowcount == 0` → **walk to the next candidate**, don't fail. Same shape as ticketing's
  `UPDATE … WHERE status='AVAILABLE'` — seventh costume, one lesson.
- **Search is AP, the claim is CP** — parking's split restated: the geo query may hand you a partner who moved
  or was just taken; only the conditional update is authoritative.
- **`PartnerStatus.BUSY` becomes a lease, not a flag** — a dispatcher dying between claim and offer strands
  nobody; `claim_expires_at` lapses. No compensating transaction.
- The `(2, 5, 8)` loop becomes a **ranked candidate list** from widening rings that the claim walks top-down —
  widening now backstops an *exhausted list*, not a retry of the same query.

### (d) Batched dispatch beats greedy nearest
`NearestPartnerStrategy` takes the closest `AVAILABLE` partner the instant an order needs one — locally
optimal, globally worse:

| | to O1 | to O2 | |
|---|---|---|---|
| **P1** | 0.5 km | 0.3 km | greedy, O1 first: O1→P1 (0.5) + O2→P2 (4.0) = **4.5 km** |
| **P2** | 1.0 km | 4.0 km | batched optimum: O1→P2 (1.0) + O2→P1 (0.3) = **1.3 km** |

- **Batch:** hold arriving orders per city for 10–30 s, then min-cost bipartite matching over the
  (orders × candidates) matrix. Cost = *predicted minutes to the restaurant*, not raw `distance_km` — traffic
  plus how far along `PREPARING` is. Also unlocks pooling (two orders, one trip), invisible to greedy.
- **The honest cost:** every order waits the window before it is even *considered*. 30 s only pays if the routing
  gain exceeds 30 s; at 3 a.m. with idle partners it is pure latency for nothing.
- **So: adaptive** — batch when the zone's demand/supply is tight, greedy when supply is loose. That ratio is
  already computed by (g); reuse it. Batching makes collisions rarer, not impossible — (c) stays.

### (e) `ALLOWED_TRANSITIONS` becomes a durable workflow
- In-process, `_transition` checks the table and mutates `order.status`; the caller then publishes, and
  `EventBus.publish` calls each `Subscriber.handle` synchronously. Distributed, one transition = a durable row
  write + an event that must reach notifiers, ETA, analytics and the restaurant tablet.
- **The table survives verbatim — as the WHERE clause:** `UPDATE orders SET status='PICKED_UP'
  WHERE order_id=? AND status='READY'`. `can_transition_to()` is enforced by the DB, so check and write stop
  being two steps. **One writer:** only the Order Service sets `status`; everyone else *requests* a transition.
- **Idempotency falls out, but decode `rowcount = 0` two ways:** `current == target` → replayed retry → **200**;
  otherwise → **409** (the LLD's `InvalidTransitionError`). The partner app *will* retry the "Picked up" tap;
  without this, a success comes back as an error.
- **At-least-once + dedup keys:** Kafka redelivers, so consumers dedup on `(order_id, to_status)` — skip it and
  the customer gets "Out for delivery" twice. Key the topic by `order_id` for per-order ordering, and publish via
  the **outbox** inside the status write's transaction so row and event can't drift.

### (f) Live tracking: push vs poll
Fan-out is ~1:1 (one partner → one waiting customer) — **not the celebrity problem.** It is a *connection-count*
problem: ~160K concurrent sessions at peak.

| | Polling every 3 s | WebSocket / SSE |
|---|---|---|
| Cost at peak | 160K ÷ 3 = **~54K QPS**, mostly TLS + auth overhead | **160K open conns** ≈ 4 nodes @ 50K, ~5 GB RAM |
| Per delivery | **600 requests** (1,800 ÷ 3) per customer | 1 connection |
| Freshness | 3 s stale, paid even when nothing moved | pushed on change |
| Ops | stateless; survives deploys, proxies, flaky mobile | connection state to drain and rebalance |

- **Hybrid, split by update rate.** Status changes are rare (5 transitions + the assignment ping over 30 min —
  six pushes, not a stream) and must not be missed → **push notification + a poll on foreground**. The moving
  dot is high-rate and disposable → **WebSocket, open only while the tracking screen is visible.**
- Coalesce to ~1 update per 5 s and interpolate client-side — don't burn battery to move a dot 20 m. The edge
  subscribes to one partner key; it never re-queries the index per poll.

### (g) Surge must be **pinned**, not read live
- The LLD injects `SurgePricing(delivery_fee, surge_multiplier)` once — a constant. At scale it is a **stream
  job**: per zone, rolling few minutes, `demand ÷ supply` = (orders + carts opened) ÷ (partners `AVAILABLE` in
  the zone) → a **capped, smoothed** step function (max ~2×, or it oscillates every tick), published to a
  `zone → multiplier` map in Redis. `calculate()` does **one lookup**, never an aggregation on the order path.
- **The pin is the whole point.** `Order.amount` is already written once inside `place_order` — exactly right,
  and it must survive the port: the quote (multiplier + amount + ~5 min expiry) is frozen onto the order and
  payment charges *the stored amount*. Re-read Redis at charge time and the price moves between the customer
  tapping "Place order" and the card being hit.
- **derive-vs-materialise, stated properly:** `demand ÷ supply` is never **derived** on the order path — that
  would be an O(zone-traffic) aggregation per quote. The stream job **materialises** it into `zone → multiplier`,
  so the quote costs one O(1) lookup; the event stream stays the source of truth and a stale projection is
  repaired by the next tick (§17's cached-projection + repair rules). `Order.amount` then goes one step
  further: it is **pinned** — a materialised value deliberately *never* refreshed, because here drift from the
  live multiplier is the feature, not the bug.
- **Fail-open on surge** — pipeline stale or down → fall back to `1.0`, i.e. plain `StandardPricing`.
  Undercharging costs margin; overcharging on a stale 1.8× costs a refund and a screenshot on Twitter. Note the
  split inside one request: surge fails **open**, the order write fails **closed**.

## 5. Failure — two invariants

**(1) An order is never silently lost.**
- `self._pending` is a list that dies with the process → a **durable per-city pending queue** (Kafka topic or a
  `pending_assignments` table). The LLD never auto-cancels; neither does the platform.
- `_free_partner` pops one pending order and re-assigns it — a push hook. **Drop the hook:** the dispatcher
  re-sweeps the whole pending set every tick. A crashed hook loses an order; a periodic sweep cannot.
- Escalation ladder: widen the rings → raise the incentive → tell the customer → surface to ops. Cancellation is
  a human decision or an explicit timeout. Tablet offline → order sits in `PLACED` → call → `reject_order` + refund.

**(2) A partner is never double-assigned.**
- Guaranteed only by the conditional UPDATE in (c); everything upstream is best-effort.
- **Stuck claim** (assigned, never accepted): the lease lapses → lazy reclaim in the next claim's WHERE, plus a
  reaper returning the order to the pending queue flagged "don't re-offer to this partner".
- **The reverse leak:** a lost `DELIVERED` event leaves a partner `BUSY` forever. Freeing must be idempotent and
  backstopped by a reconciler — order terminal but partner still `BUSY` → fix it (parking's periodic recompute).

**Component deaths:**
- **Redis geo down** → degrade, don't stop: fall back to a coarse city-wide pool (worse ETAs, still delivering).
  **Fail-open on match quality, fail-closed on the claim** — claim store unreachable → refuse to assign; two
  partners at one restaurant costs real money and a furious partner.
- **Postgres primary down** → replica promotes, placement pauses (fail closed); in-flight deliveries continue,
  device-buffered transitions replay, safe *because* of (e). **Kafka down** → outbox drains on recovery.
  **Dispatcher crash mid-batch** → a few leases lapse, nothing to compensate.

## 6. Scale
- **Shard everything by city** — orders, pending queue, geo index, dispatcher. No cross-city matching exists, so
  it is a free boundary; a festival spike in one metro can't starve another. Mirrors shard-by-`show_id`.
- **The dispatcher is a partitioned singleton per city** — one batch solver per shard so two don't fight over the
  same supply. (c) makes a brief overlap during failover *safe*, not *correct*.
- **The location tier scales independently** of the order tier — the whole point of separating them.
- **At 10×:** more ingest nodes and geo shards (linear, near-stateless); the order path barely notices
  630 → 6,300 writes/s; the limit is the dispatcher's cost matrix — cap candidates per order, shorten the window.

**Monitoring** (alert on symptoms users feel, not causes):
- **Unassigned order age — the headline metric.** Alert on the **max**, not p99: one order stuck 40 minutes is a
  support ticket even when the percentile looks fine.
- **Assignment latency** (`ACCEPTED` → `PARTNER_ASSIGNED`, p50/p99) — the visible cost of (d)'s window. Measure it
  from acceptance, not `READY`: a partner should already be riding while the food cooks.
- **Double-assignment count — must be 0, page instantly** (ticketing's oversell count, same class).
- **Partner utilisation** (online time spent `BUSY`) — too low = paying for idle supply, too high = no slack, ETAs blow out.
- **Late-delivery rate** vs promised ETA. Plus stale-index ratio (entries past the 30 s TTL = matching on
  ghosts) · ingest lag · surge staleness · outbox lag.

---

## LLD ↔ HLD mapping
| LLD (`solution.py`) | HLD |
|---|---|
| `NearestPartnerStrategy.find_partner` scanning `self._partners` | cell/bbox query over a **write-heavy in-memory geo index** (~550:1 writes:reads) |
| `Location.distance_km` (haversine) | unchanged — but only to **refine** cell candidates (parking HLD) |
| `DeliveryPartner.location` reassigned in place | **50K pings/s** into a separate ingest tier, **TTL 30 s**, never the primary DB |
| `with self._lock:` around find→claim | `UPDATE partners SET status='BUSY' WHERE partner_id=? AND status='AVAILABLE'` |
| `PartnerStatus.BUSY` as a flag | a **lease** (`claim_expires_at`) — lazy reclaim + reaper, self-healing |
| radius loop `(2, 5, 8)` inside the lock | ranked candidate rings + **claim-with-fallback** down the list |
| `self._pending` / `_free_partner` popping one order | **durable per-city pending queue**; no push hook — the next batch tick re-sweeps the whole set |
| `ALLOWED_TRANSITIONS` / `can_transition_to()` | the same table, now the **`WHERE status = :from`** of every transition UPDATE |
| `_transition` raising `InvalidTransitionError` | `rowcount 0` decoded: current == target → **200** (replay); else → **409** |
| `EventBus.publish` → `Subscriber.handle` | **Kafka `order-events`**, keyed by `order_id`, published via the **outbox** |
| `CustomerNotifier` / `RestaurantNotifier` / `PartnerNotifier` + try/except bulkhead | one consumer group + **DLQ** per channel; **dedup key** on `(event, user, channel)` |
| `SurgePricing(delivery_fee, surge_multiplier)` constant | streaming **demand ÷ supply per zone** → Redis `zone → multiplier`, read at quote time |
| `Order.amount` set inside `place_order` | **the pin** — quote frozen on the order row; payment never re-reads it |
| one greedy `find_partner` per order | **batched min-cost matching** over a short window; adaptive when supply is loose |
| *(nothing — tracking was out of LLD scope)* | ingest tier · breadcrumb cold store · **WebSocket tracking edge** · claim reaper · surge pipeline |

**The line to say:**
> *"Parking taught me to index a static set and split AP-search from CP-reserve. Here the indexed thing **moves**,
> so it flips to ~550 writes per read — out of the transactional DB, into an in-memory store with a 30-second TTL
> whose pings I'm happy to lose. The `find→claim` lock becomes a conditional UPDATE carrying a **lease**, so a
> crashed dispatcher self-heals instead of stranding a partner as BUSY. And I'd batch dispatch over a short
> window rather than greedily — greedy is locally optimal and globally worse — while being honest that the
> window is latency I'm spending to buy routing quality."*
