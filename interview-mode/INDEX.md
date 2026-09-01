# Interview Mode — Index

The manifest an app reads first. Format spec: [`FORMAT.md`](FORMAT.md).

## HLD problems (10)

| # | File | Difficulty | The one thing it teaches |
|---|---|---|---|
| 1 | [HLD-01-news-feed](hld/HLD-01-news-feed.md) | hard | **fan-out on write vs read** + the celebrity problem |
| 2 | [HLD-02-chat](hld/HLD-02-chat.md) | hard | long-lived connections · **per-conversation sequence numbers** (not timestamps) |
| 3 | [HLD-03-dropbox](hld/HLD-03-dropbox.md) | hard | **chunking + content-hash dedup** · conflicts = keep both |
| 4 | [HLD-04-youtube](hld/HLD-04-youtube.md) | med-hard | **the CDN is the architecture** · async transcoding · client-side ABR |
| 5 | [HLD-05-payment](hld/HLD-05-payment.md) | hard | **double-entry ledger** · idempotency · the PSP-timeout ambiguity · saga |
| 6 | [HLD-06-typeahead](hld/HLD-06-typeahead.md) | medium | **precomputed top-k in an immutable in-memory trie** |
| 7 | [HLD-07-web-crawler](hld/HLD-07-web-crawler.md) | med-hard | **politeness scheduling** · Bloom filter's false-positive asymmetry |
| 8 | [HLD-08-ticketmaster](hld/HLD-08-ticketmaster.md) | med-hard | **waiting room** · atomic claim in the WHERE clause · TTL holds |
| 9 | [HLD-09-job-scheduler](hld/HLD-09-job-scheduler.md) | med-hard | **leader election** · leases · why exactly-once is impossible |
| 10 | [HLD-10-leaderboard](hld/HLD-10-leaderboard.md) | medium | **sorted sets** · HyperLogLog · Count-Min Sketch |

### Suggested order
`01 → 02 → 08 → 05 → 04 → 03 → 06 → 10 → 07 → 09`
News feed first (most-asked, and fan-out recurs everywhere). Ticketmaster early because you already
built its LLD. Scheduler last — it's the most niche.

## LLD problems (11, already built)

These live in the numbered folders at the repo root, each with `problem.md` (clarifying questions,
requirements, per-step review notes, REST API mapping), `solution.py` (runnable, with HINT-to-rebuild
blocks), `diagrams.md`, `explained.md`, and often `hld.md`.

| # | Folder | The one thing it teaches |
|---|---|---|
| 1 | `01-url-shortener/` | Strategy · Repository · **atomic claim** (`save_if_absent`) |
| 2 | `02-parking-lot/` | **enum + rule-map** · two Strategies · find→claim race |
| 3 | `03-elevator-system/` | **State pattern** · tick simulation |
| 4 | `04-rate-limiter/` | 3 algorithms · **ISP** · Redis/Lua atomicity |
| 5 | `05-chess/` | polymorphic behaviour · **simulate-and-undo** |
| 6 | `06-splitwise/` | ledger modelling · **derive-don't-store** · money correctness |
| 7 | `07-notification-system/` | **Observer** · bulkhead · channel as enum *and* Strategy |
| 8 | `08-lru-cache/` | dict+DLL for O(1) · **LFU exposed a leaky abstraction** |
| 9 | `09-movie-booking/` | **hold-with-expiry** · lazy expiry + sweeper |
| 10 | `10-text-editor/` | **Command + Memento** |
| 11 | `11-food-delivery/` | 🎓 capstone — 4 patterns kept untangled |

## The threads that run through everything

Recognising these across problems matters more than any single design.

**1. Check-then-act (appeared 8 times).** Every time, the fix is the same shape: make it one
indivisible operation, in the shared store.
| Problem | The racy pair | Pushed down into |
|---|---|---|
| URL shortener | `exists()` + `save()` | `save_if_absent` / `INSERT … ON CONFLICT` |
| Parking | find spot + mark taken | one critical section |
| Rate limiter | `get` + `set` | Redis `INCR` / Lua |
| Splitwise | `balance += x` | `UPDATE … SET x = x + n` in a transaction |
| Chess | *(none — turn-based)* | race lives in matchmaking |
| Movie booking | check seat + hold it | per-show lock |
| Food delivery | find partner + mark BUSY | one lock around both |
| Ticketmaster | check seat + claim it | `UPDATE … WHERE status='AVAILABLE'` |

**2. At-least-once + idempotency (3 times).** Notifications, payments, job scheduler — all reach the
same conclusion: exactly-once isn't achievable across a boundary you don't control, so you promise
at-least-once and dedupe with a deterministic key.

**3. Derived vs materialised (3 times).** Splitwise balances, news feed, leaderboard — keep the log as
truth, materialise for read speed, reconcile.

**4. TTL/lease self-healing (3 times).** Movie holds, Ticketmaster holds, scheduler job leases — a
claim that expires needs no cleanup process and survives a crash.

**5. Fail-open vs fail-closed.** Rate limiter fails **open** (it protects the backend, it mustn't
become the outage). Payments and ticketing fail **closed** (a wrong answer costs money). Being able
to say which and why is a senior signal.

## Study loop

```
1. read PROMPT only, close the file
2. answer aloud, on paper, timed
3. reopen -> score against CHECKPOINTS
4. read TRAPS -> did you fall in any?
5. read REFERENCE
6. next day: ONE-LINER only, from memory
```

Being unable to produce a checkpoint is information. Reading the reference and nodding is not.
