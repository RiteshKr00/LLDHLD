# HLD-08 — Ticketmaster (high-contention booking)

## META
- difficulty: medium-hard
- time: 45 min
- tags: contention, waiting-room, atomic-claim, ttl-holds, fairness
- prerequisite: **LLD problem 09 (movie booking)** — this is its scale-up. Do that first.
- why-it-matters: the purest **contention** problem — low QPS, but everyone wants the same rows at the
  same instant.

## PROMPT
> "Design Ticketmaster. Tickets for a concert go on sale at 10:00 AM, and two million people are
> waiting."

## CLARIFY
- **Normal load or the drop?**
  → **The drop.** Steady state is boring. Design for 10:00:00.
- **Do users pick specific seats?**
  → Yes, a seat map. (If it were general admission this problem gets much easier — worth noting.)
- **Hold before payment?**
  → Yes, ~10 minutes while they pay.
- **Fairness — is first-come-first-served required?**
  → **Yes.** A bot beating a real fan who clicked earlier is a business problem, not just a technical one.
- **Overselling?**
  → **Never.** Not one seat. Legal and reputational consequences.
- **Payment?**
  → Assume a PSP result arrives (see HLD-05 for that half).

## STEP 1 — Requirements
**Functional:** browse events · view the seat map · hold seats (~10 min) · pay · confirm · cancel.
**Non-functional:** **never oversell a seat** · **fair** (arrival order, not fastest bot) · survive a
1000× spike on one event · seat map may be slightly stale but a *claim* must be exact.
**Out of scope:** payment rails · dynamic pricing · resale/transfer · fraud beyond basic bot defence.

### CHECKPOINTS
- "Never oversell" stated as an absolute
- **Fairness** named as a requirement (most candidates never mention it)
- Distinguishes **stale seat map (fine)** from **stale claim (fatal)**

### TRAPS
- Designing for average load — the entire problem is the spike
- Treating fairness as automatic; without a queue, the fastest client wins, and the fastest client is a bot

## STEP 2 — Capacity
```
normal day      trivial — a single box
THE DROP        2,000,000 users hit "buy" within ~60 seconds
inventory       50,000 seats
seat-map reads  everyone refreshing:  ~100,000 reads/sec, ALL on ONE event
claim attempts  tens of thousands/sec, ALL on the SAME few thousand rows
outcome         49,950,000 of 2M... i.e. ~97.5% of people get NOTHING
                -> most of your traffic is REJECTIONS. They must be fast and clear.
```

### CHECKPOINTS
- Recognises that the contention is **narrow and deep** — a few thousand rows, not millions of keys
- Notices **most requests will fail**, and that failing fast is a design goal
- Separates read volume (huge, cacheable) from write volume (small, must be exact)

### TRAPS
- Computing a global QPS and missing that it all lands on **one event**. A perfectly sharded system
  still has one hot shard.

### FOLLOWUPS
- *"Your DB can do 5,000 writes/sec. Fifty thousand claims arrive in one second. Now what?"*

## STEP 3 — API
```
GET  /api/v1/events/{id}/seats            -> 200 seat map        (cacheable, seconds-stale OK)
POST /api/v1/queue/{event_id}             -> 200 {position, eta} <- the waiting room
POST /api/v1/holds   {event, seat_ids}    -> 201 {hold_id, expires_at}  · 409 taken · 403 not your turn
POST /api/v1/bookings/{hold}/confirm      -> 200 · 410 hold expired
```

### CHECKPOINTS
- There is a **queue endpoint** — admission is a first-class concept, not an implicit thing
- `expires_at` is returned (the client must show a countdown)
- 409 vs 410 distinguished: *someone else took it* vs *your hold lapsed*

### TRAPS
- No queue → 2M requests hit the booking service directly and it dies

## STEP 4 — Data model
```
events(event_id, venue_id, starts_at, on_sale_at)
seats(seat_id, event_id, section, row, number, price)
seat_state(event_id, seat_id, status, held_by, hold_expires_at, version)
holds(hold_id, user_id, event_id, seat_ids[], expires_at)
bookings(booking_id, hold_id, user_id, status, paid_at)
queue(event_id, user_id, position, admitted_at)     -- Redis
```
- **`seat_state` → Postgres.** This is the contended table and it needs ACID. **Do not** put inventory
  in an eventually-consistent store.
- **Seat map for reading → Redis**, rebuilt from `seat_state`, allowed to lag a couple of seconds.
- **Queue → Redis** (a sorted set by arrival time).

### CHECKPOINTS
- Inventory in a **strongly consistent** store, and says why
- **Read model and write model separated** (cached map vs authoritative rows)
- Hold expiry is a **column**, i.e. a TTL, not an in-memory lock

### TRAPS
- Inventory in Cassandra/Dynamo with eventual consistency → **overselling by design**
- An application-level distributed lock per seat — slower and more fragile than letting the DB do it

## STEP 5 — Architecture
```
   2,000,000 users
        │
        ▼
 ┌─────────────────────────┐
 │  WAITING ROOM (Redis)   │  everyone gets a position instantly (cheap: one counter)
 │  "you are #482,193"     │  admits ~1,000 users/sec into the real flow
 └───────────┬─────────────┘
             │ admitted (signed token, short TTL)
             ▼
      API Gateway ──▶ Booking Service ──▶ Postgres (seat_state)  ← the ONLY hot spot
             │                        └──▶ Redis (seat map cache, TTL 2s)
             └──▶ CDN (event pages, images, static seat layout)
```

### CHECKPOINTS
- A **waiting room in front of everything** — the spike never reaches the DB
- Admission is **token-based and time-limited**, so it can't be shared or replayed
- Seat-map reads come from **cache**, never from the contended table
- Only the **claim** touches Postgres

### FOLLOWUPS
- *"What stops someone from skipping the queue by calling /holds directly?"* (the signed admission token)
- *"How many people do you admit per second, and how do you choose that number?"*

## DEEP DIVE — the waiting room, the atomic claim, and fairness

### 1. The waiting room (the signature technique)
```
WITHOUT:  2M requests -> booking service -> DB
          DB does 5K writes/sec. It receives 50K. Everything times out.
          Nobody gets a ticket, including the people who would have.

WITH:     2M requests -> Redis ZADD (one cheap op) -> "you're #482,193, ~8 min"
          admit 1,000/sec into the real flow
          the booking service NEVER sees more than it can handle
```
This is **load shedding done kindly**. You're not rejecting people — you're *scheduling* them, and
telling them the truth about the wait. Three wins:

| | Why it matters |
|---|---|
| **Protects the DB** | the tier behind it sees a constant, survivable rate |
| **Fairness** | position is by **arrival time**, so a bot with a faster connection gains nothing |
| **Honest UX** | "#482,193, ~8 minutes" beats a spinner that ends in a 500 |

Admission rate is tuned to what the booking tier can actually sustain — and you can raise it as
inventory drains.

### 2. The atomic claim — the DB is the arbiter
The LLD used `with lock:`. That's one process; here there are hundreds of app servers.
**Push the check into the write:**
```sql
UPDATE seat_state
   SET status='HELD', held_by=:user, hold_expires_at = now() + interval '10 minutes'
 WHERE event_id = :e
   AND seat_id = ANY(:seats)
   AND (status = 'AVAILABLE'
        OR (status = 'HELD' AND hold_expires_at < now()))   -- reclaim lapsed holds inline
RETURNING seat_id;
```
- `rowcount == len(seats)` → **you won all of them** → commit
- anything less → **ROLLBACK everything** → 409

The `WHERE status='AVAILABLE'` **is** the atomic claim — the same lesson as `save_if_absent`,
`find→claim`, `INCR`, and the movie-booking hold. **Eighth and final costume.**

All-or-nothing comes free from the transaction: you don't loop and mutate, you issue one statement
and check the count.

### 3. Hold expiry without a sweeper
Two mechanisms, and the second is the elegant one:
```
Redis TTL:      SET hold:{seat} user NX EX 600   -> the key simply evaporates
lazy reclaim:   the OR clause above — an expired hold is taken by the next buyer
```
With lazy reclaim, **a dead sweeper cannot strand inventory** — correctness doesn't depend on a cron
job being alive. That's a strictly better property than "run a cleanup task".

### 4. Fairness and bots
The queue gives arrival-order fairness, but you still need:
- **CAPTCHA at queue entry** (once, not per request)
- **Per-account seat caps** (4 tickets, not 400)
- **Device/IP fingerprinting**, rate limits per account
- **Signed admission tokens** so a queue position can't be resold or shared

### CHECKPOINTS
- **Waiting room** described with all three benefits (protection, fairness, honest UX)
- Atomic claim expressed as **`UPDATE … WHERE status='AVAILABLE'`** with `rowcount` checked
- **ROLLBACK on partial success** — all-or-nothing via the transaction
- **Lazy reclaim inside the WHERE clause**, so expiry doesn't depend on a background job
- At least two concrete **bot defences**

### TRAPS
- `SELECT` the seat, check it's free in app code, then `UPDATE` — the classic TOCTOU; two users both
  pass the check
- An app-level distributed lock per seat (Redlock etc.) when a single conditional `UPDATE` does it
  better and cheaper
- Relying only on a sweeper for expiry — if it lags, seats sit unsellable during the one hour they matter

### FOLLOWUPS
- *"Fifty thousand people claim seat A5 simultaneously. Exactly how many succeed, and why?"*
- *"A user's payment takes 11 minutes. Walk me through what happens."*

## STEP 7 — Scale
- **Shard by `event_id`** — one concert's contention is isolated; other events are unaffected. This is
  the direct scale-up of the LLD's **per-show lock**.
- **Seat map**: Redis + CDN, 1–2 s TTL. 100K reads/sec never touch Postgres.
- **Queue**: Redis sorted set; adding 2M entries is trivial (it's one `ZADD` each).
- **Read replicas** for event browsing; the primary handles only claims.
- **Pre-warm** caches and scale out *before* `on_sale_at` — the spike is scheduled, so there's no
  excuse for autoscaling to be caught cold.

## STEP 8 — Failure
- **Postgres primary down** → **fail closed**: stop selling. Rejecting sales beats double-selling.
  *(Contrast: rate limiter fails open. Say this contrast out loud — it shows you choose per-domain.)*
- **Payment slow/dies** → the hold expires and the seat returns automatically. **No compensating
  transaction needed** — that's the beauty of TTL-based holds over locks.
- **Booking service crashes mid-hold** → the row is HELD with an expiry; it self-heals in 10 minutes.
- **Redis queue lost** → everyone re-queues. Painful and unfair, so replicate it; but no tickets are
  lost or double-sold, because the queue is not the source of truth.
- **The 97.5% who lose** → must get a **fast, clear** rejection. A timeout is the worst outcome.

## STEP 9 — Wrap
- **Bottleneck:** contention on a few thousand rows — attacked by the queue (fewer concurrent claims)
  and by the conditional UPDATE (no app-level locking).
- **Tradeoffs:** waiting room (protects everything, but users wait and you must build it) ·
  strong consistency (no overselling, lower throughput) · short holds (inventory recycles fast,
  users feel rushed) vs long holds (comfortable, inventory sits idle during the only hour that matters).
- **Monitoring:** queue length and admission rate, claim success/conflict ratio, hold expiry rate,
  DB lock waits, p99 on the rejection path (not just the success path), oversell count (**must be 0**).
- **Next:** dynamic pricing, resale marketplace, seat recommendations, presale codes.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | seats table, "lock the row", cache the seat map |
| **Senior** | conditional UPDATE for the claim, TTL holds, cached read model, shard by event |
| **Staff** | all that **+ the waiting room with the fairness argument**, lazy reclaim so expiry survives a dead cron, explicit **fail-closed** choice contrasted against fail-open systems, and designing the **rejection path** for the 97.5% |

## REFERENCE
**10:00:00, two million people:**
1. Every request lands in the **waiting room**: one Redis `ZADD` by arrival timestamp → "#482,193".
   The booking tier sees none of this.
2. Admission drips ~1,000/sec, each with a **signed, short-lived token**.
3. An admitted user loads the seat map — from **Redis**, ~2 s stale, which is fine because it will be
   revalidated at claim time.
4. They pick A5, A6 → `POST /holds` → **one conditional UPDATE**:
   - matched 2 rows → held, `expires_at` returned → the client shows a countdown
   - matched fewer → **ROLLBACK**, 409 "someone just took A5" → shown instantly, not after a timeout
5. They pay within 10 minutes → `confirm` re-checks the hold is still theirs → `BOOKED`.
6. They don't pay → nothing runs, nothing cleans up: the **next buyer's UPDATE reclaims it** via the
   `hold_expires_at < now()` clause.

**Why it never oversells:** every claim is a single conditional write against one authoritative row.
There is no window between checking and taking, on any server, ever.

## ONE-LINER
> *"This isn't a throughput problem — it's contention: two million people want a few thousand rows in
> the same second. So first I **shed the spike into a waiting room** that admits people at the rate the
> database can actually take, which also gives me fairness by arrival time so bots don't beat real
> fans. Then the claim itself is a **single conditional UPDATE** — `WHERE status='AVAILABLE'` — so the
> database arbitrates and there's no gap between checking and taking. Holds are **TTL-based and
> reclaimed lazily inside that same WHERE clause**, so an abandoned payment or a crashed service
> self-heals without any cleanup job."*
