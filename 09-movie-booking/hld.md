# Movie Booking — HLD (Ticketmaster scale)

Companion to [`solution.py`](solution.py) (the single-process engine).
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).

> **Framing:** this is not a throughput problem — the QPS is modest. It's a **contention** problem.
> A normal cinema is boring at scale. A **Taylor Swift ticket drop** is the actual question:
> 2 million people hitting *one* show at *the exact same second*, for 50,000 seats.
> Everything below exists because of that one spike.

## 1. Scope
- **Functional:** browse shows · view seat map · hold seats · pay · confirm · cancel.
- **Non-functional:** **never double-book a seat** (correctness > availability here) · **fair** (first-come should actually win, not fastest bot) · survive a 1000× spike on one show · the seat map should be roughly live.

## 2. Estimate — the spike is the whole story

| | Normal day | Hot drop |
|---|---|---|
| Users on one show | ~50/min | **2,000,000 in the first minute** |
| Seats available | 200 | 50,000 |
| Reads (seat map) | trivial | **~100K QPS**, all on ONE show |
| Writes (holds) | trivial | tens of thousands, all on the SAME rows |

**So:** average load needs one small server. **Peak load on a single show is the entire design.**
And note the contention is *narrow* — not spread across millions of keys like a cache, but focused
on a few thousand rows. That's much harder.

## 3. Architecture

```
                       ┌──────────────────────────┐
   Users ─────────────▶│  WAITING ROOM (queue)    │  <- the Ticketmaster move
                       │  "you are #48,201"       │
                       └────────────┬─────────────┘
                                    │ admits N users/sec
                                    ▼
   CDN (static: movie art) ──▶  API Gateway  ──▶  Booking Service
                                                       │
              ┌────────────────────────────────────────┼──────────────┐
              ▼                    ▼                   ▼              ▼
        Redis                  Postgres            Kafka          Redis
   (seat map cache,        (SOURCE OF TRUTH:    (booking       (hold TTLs -
    hold locks w/ TTL)      seats, bookings,     events,        auto-expire
                            UNIQUE constraint)   analytics)     for free)
```

## 4. The four key decisions

### (a) Waiting room / virtual queue — the signature technique

You cannot let 2M people hit the booking service at once. So you **don't**:

```
   2M users arrive  ->  all get a queue position (cheap, just a counter)
                    ->  service admits ~500/sec into the real booking flow
                    ->  everyone else sees "you're #48,201, ~6 min"
```

- Protects the DB from a thundering herd it could never survive.
- Makes the wait **honest and visible** instead of showing everyone a spinner and then a 500.
- **Fairness:** queue position by arrival time, so a fast bot doesn't beat a real user who clicked first.

This is a **load-shedding** pattern — the same instinct as rate limiting, but queueing instead of rejecting.

### (b) Where the atomic claim lives

The LLD used `with lock:`. That's one process — useless across servers. The DB must arbitrate:

```sql
-- ONE statement. Either it updates a row or it updates nothing.
UPDATE show_seats
   SET status = 'HELD', held_by = :user, hold_expires_at = now() + interval '5 minutes'
 WHERE show_id = :show AND seat_id = ANY(:seats)
   AND (status = 'AVAILABLE'
        OR (status = 'HELD' AND hold_expires_at < now()))   -- reclaim expired holds
RETURNING seat_id;
```
- **`rowcount == len(seats)`** → you got them all → commit.
- **anything less** → someone beat you → **ROLLBACK the whole transaction** (all-or-nothing, exactly
  like the LLD, now enforced by the transaction instead of a Python loop).
- The `WHERE status = 'AVAILABLE'` clause **is** the atomic claim. Same lesson, 6th costume:
  *push the check into the write.*

> Alternative: Redis `SET seat:{id} user NX EX 300` per seat — faster, and the **TTL does hold-expiry
> for free** (no sweeper needed). Tradeoff: Redis isn't durable, so Postgres still owns the truth and
> Redis is the fast gate in front of it.

### (c) Reads and writes are wildly different — split them

| | Seat map (read) | Hold/book (write) |
|---|---|---|
| Volume | ~100K QPS | thousands total |
| Consistency | **stale-by-seconds is fine** | **must be exact** |
| Where | Redis cache, fanned out to replicas | Postgres primary, single row lock |

The seat map being 2 seconds stale is acceptable — you'll re-validate at hold time anyway. Users
already understand "that seat just got taken". **Don't pay for strong consistency on the read path.**

### (d) Hold expiry at scale

Three options, in increasing order of nice:
1. Sweeper job (`DELETE WHERE hold_expires_at < now()`) — works, but it's a cron you must keep alive.
2. **Lazy reclaim in the UPDATE itself** — see the `OR (status='HELD' AND hold_expires_at < now())`
   clause above. Expired holds are reclaimed *by the next person who wants the seat*. No job needed.
3. **Redis TTL** — the hold key simply evaporates. Zero code.

**Best answer: (2) + (3).** Lazy reclaim guarantees correctness even if everything else is broken.

## 5. Failure & fairness
- **Payment gateway slow/down** → holds expire naturally and seats return. Nothing stuck. This is
  exactly why the hold has a TTL and not a flag.
- **Booking service dies mid-hold** → the row is HELD with an expiry; 5 minutes later it self-heals.
  **No compensating transaction needed** — that's the beauty of TTL-based holds over "locks".
- **Postgres primary down** → **fail closed.** Refuse to sell rather than risk double-selling.
  (Opposite call from the rate limiter's fail-open — because here a wrong answer costs a real seat.)
- **Bots/scalpers** → the fairness problem: CAPTCHA at queue entry, per-account seat caps, device
  fingerprinting, rate limits per IP.
- **The last seat problem:** 50,000 people fighting for 1 seat. 49,999 must get a *fast, clear*
  rejection, not a timeout. Fail fast beats hanging.

## 6. Scale
- **Shard by `show_id`** — a hot show's contention stays on one shard and can't slow other shows.
  (Directly mirrors the LLD's **per-show lock**.)
- Seat map reads → Redis + read replicas; the cache key is `show_id`, invalidated on any hold/book.
- The waiting room absorbs the spike so nothing downstream ever sees 2M concurrent.

---

## LLD ↔ HLD mapping
| LLD (`solution.py`) | HLD |
|---|---|
| `with self._lock_for(show_id)` | **`UPDATE … WHERE status='AVAILABLE'`** in a transaction (or Redis `SET NX`) |
| per-show lock | **shard by `show_id`** — contention isolated per show |
| all-or-nothing loop | **transaction rollback** if `rowcount != len(seats)` |
| `hold_expires_at` + sweeper | **Redis TTL** + **lazy reclaim inside the UPDATE** |
| `confirm()` re-checks the hold | same check, now `WHERE held_by = :user AND hold_expires_at > now()` |
| `seat_map()` reads live state | **Redis cache**, deliberately allowed to be seconds stale |
| *(nothing)* | **waiting room**, bot defence, fail-closed on DB loss |

**The line to say:**
> *"The throughput here is small — the hard part is that all the contention lands on a few thousand
> rows at once. So: a **waiting room** to shed the spike before it reaches the DB, the **atomic claim
> pushed into the UPDATE's WHERE clause** so the database arbitrates instead of an app-level lock, and
> **TTL-based holds** so a crashed service or an abandoned payment self-heals with no compensating
> transaction."*
