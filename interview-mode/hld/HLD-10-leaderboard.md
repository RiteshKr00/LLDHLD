# HLD-10 — Leaderboard / Analytics Counting

## META
- difficulty: medium
- time: 45 min
- tags: sorted-sets, approximate-counting, hyperloglog, count-min-sketch, hot-keys
- why-it-matters: the only problem where the right answer is **"be deliberately approximate"** — and
  the place to learn HyperLogLog and Count-Min Sketch, which interviewers love.

## PROMPT
> "Design a leaderboard for a game with 100 million players — show the global top 100, and let any
> player see their own rank."

## CLARIFY
- **How fresh must ranks be?**
  → Top-100 near-real-time; **your own rank can lag a bit.** That asymmetry is exploitable.
- **Do we need exact ranks for everyone?**
  → **Exact rank for player #47,000,000 is meaningless.** "Top 8%" is fine. Get this concession — it
  unlocks approximation.
- **Time windows?**
  → Daily, weekly, all-time.
- **Score updates?**
  → Frequent — a score changes on every match.
- **Related counters** (unique daily players, most-played maps)?
  → Yes — and this is where approximate counting comes in.

## STEP 1 — Requirements
**Functional:** update a player's score · get the global top-N · get **my** rank · leaderboards per
time window (daily/weekly/all-time) · related stats (unique players, top items).
**Non-functional:** top-N read must be **fast (<50 ms)** and is read constantly · score writes are
frequent · **approximate is acceptable outside the top ranks** · availability > perfect accuracy.
**Out of scope:** anti-cheat · friend leaderboards (mention as an extension) · rewards/payouts.

### CHECKPOINTS
- Extracts the concession that **exact rank is only needed near the top**
- Separates the **hot read (top-N)** from the **long-tail read (my rank)** — they have different requirements
- Names time-windowed boards as separate structures, not one board filtered

### TRAPS
- Promising exact global rank for 100M players — that's a full sort on every read
- Treating all reads as equal; 99% of reads are the same top-100 list

## STEP 2 — Capacity
```
players        100M, 10M DAU
score updates  each DAU plays 20 matches/day -> 200M updates/day ÷ 86,400 ≈ 2,300 writes/sec
top-N reads    every player opens the board 5×/day -> 50M/day ≈ 600 reads/sec
               ** but they are all the SAME 100 entries -> one cache entry serves everyone **
my-rank reads  also ~600/sec, but each is a DIFFERENT player -> not cacheable the same way
memory         100M players × (8 B id + 8 B score) ≈ 1.6 GB   -> FITS IN REDIS
```

### CHECKPOINTS
- Notices the **top-N is one cacheable answer** while **my-rank is per-player**
- Computes the sorted-set memory and concludes it **fits in memory**
- Write rate is modest (thousands/sec), so writes aren't the problem

### TRAPS
- Not separating the two read types — they need completely different solutions

## STEP 3 — API
```
POST /api/v1/scores           {player_id, delta|score}     -> 204
GET  /api/v1/leaderboard?window=daily&limit=100            -> 200 (heavily cached)
GET  /api/v1/players/{id}/rank?window=daily                -> 200 {rank, score, percentile}
GET  /api/v1/stats/unique-players?date=                    -> 200 {approx_count}
```

### CHECKPOINTS
- Top-N and my-rank are **separate endpoints** (different cache strategies)
- Approximate results are **labelled as approximate** in the response

## STEP 4 — Data structure — the sorted set
**Redis sorted set (ZSET)** is the whole answer for ranking:
```
ZADD leaderboard:daily 5000 player:42        O(log N)   update a score
ZREVRANGE leaderboard:daily 0 99 WITHSCORES  O(log N + 100)   top 100
ZREVRANK leaderboard:daily player:42         O(log N)   this player's exact rank
ZCARD / ZCOUNT                                          how many, and in a score range
```
A ZSET is a **skip list + hash map**: the hash gives O(1) member→score, the skip list keeps order and
supports rank queries. **This is the one data structure this problem exists to teach.**

```
one key per window:
   leaderboard:alltime
   leaderboard:daily:2026-08-31       (TTL 48 h)
   leaderboard:weekly:2026-W35        (TTL 2 weeks)
```

### CHECKPOINTS
- Chooses **sorted set** and can say what it is internally (skip list + hash)
- Gives the **operations with their complexity** — O(log N), not O(N log N)
- **Separate key per time window**, with TTLs, rather than filtering one board by timestamp

### TRAPS
- `SELECT … ORDER BY score DESC LIMIT 100` on 100M rows per request
- One board with a timestamp column, filtered per query — you re-sort on every read
- Recomputing ranks in a batch job — then "my rank" is hours stale for no reason

## STEP 5 — Architecture
```
match ends ──▶ Score Service ──▶ Redis ZADD (all relevant window keys)
                     └────────▶ Kafka ──▶ durable store (Postgres/S3) for history & rebuild

read top-N  ──▶ CDN / app cache (TTL 5-10 s) ──(miss)──▶ Redis ZREVRANGE
read my-rank ──▶ Redis ZREVRANK  (not cacheable per-player, but it's O(log N))
```

### CHECKPOINTS
- **Redis is the serving structure; a durable store is the source of truth** — Redis can be rebuilt
- Top-N cached for a few seconds — 600 reads/sec collapse to ~0.1 reads/sec on Redis
- A score update writes to **all relevant window keys** (daily, weekly, all-time)

### FOLLOWUPS
- *"Redis restarts and the leaderboard is gone. What do you do?"*
- *"Every player is refreshing the top-100 during a tournament final. Where does that traffic go?"*

## DEEP DIVE — exact vs approximate, and the counting sketches

### 1. Where exactness actually matters
```
rank 1-1000      exact — people screenshot this, prizes depend on it
rank 47,000,000  "top 47%" is genuinely more useful than an exact integer
```
So: **exact ranks from the ZSET for the top slice; percentile estimates for the tail.**

For the tail you don't need `ZREVRANK` at all — you can bucket scores into a histogram and answer
"you're better than 62% of players" from the histogram. That's O(1) and it's the answer users prefer anyway.

### 2. HyperLogLog — counting unique things in 12 KB
*"How many unique players today?"*
```
exact:  a set of 10M player ids  ->  ~80 MB per day, per counter
HLL:    ~12 KB, with ~0.81% error
```
HLL works on the statistics of hashes: hash each id, look at the **position of the leading zeros** —
seeing a hash with 20 leading zeros suggests you've seen ~2²⁰ distinct items. Average many such
observations across buckets and you get a very good estimate in constant space.
```
PFADD  unique:2026-08-31 player:42
PFCOUNT unique:2026-08-31          -> 9,918,443  (±0.8%)
PFMERGE unique:week unique:day1 day2 …   <- unions are exact and cheap: the killer feature
```
**Use it when:** you need cardinality (uniques) over huge sets and ~1% error is fine.
**Don't use it when:** you must answer "is player 42 in this set?" — HLL cannot tell you that.

### 3. Count-Min Sketch — frequency in fixed space
*"Which items/maps are played most?"* over millions of distinct keys:
```
exact:  a counter per key -> unbounded memory
CMS:    a fixed 2-D array of counters + k hash functions
        add(x):    increment cell[i][h_i(x)] for each i
        count(x):  MIN over those cells   <- the min is why collisions inflate but never deflate
```
CMS **overestimates, never underestimates** — collisions can only add. That asymmetry is what makes
it safe for "find heavy hitters": a genuinely frequent item can never be reported as rare.

### 4. The hot-key problem
A tournament final: everyone reads the same top-100 key.
```
Redis single key -> one shard -> that shard saturates
```
Fixes, in order of cheapness: **cache the response at the app/CDN for a few seconds** (600 reads/sec
becomes ~0.1); **replicate the key** across nodes and read from a random replica; **push to CDN** with
a short TTL. Note this is the same hot-key playbook as the news feed and the distributed cache.

### CHECKPOINTS
- Splits **exact top-N** from **approximate tail percentile**, with the reason (nobody needs rank 47M)
- Explains **HyperLogLog**: what it estimates, roughly how, its ~1% error, its 12 KB size, and that
  **PFMERGE unions are cheap**
- Explains **Count-Min Sketch** and that it **overestimates but never underestimates** — and why that
  makes it safe for heavy hitters
- Knows **what HLL cannot do** (membership)
- Handles the **hot key** on the top-N with short-TTL caching

### TRAPS
- Using a sketch where exactness matters (prize ranks, money) — approximation is a *choice*, scoped
  to where it's harmless
- Saying "HyperLogLog" without being able to say what it estimates or its error rate
- Claiming CMS can undercount — it can't, and that's the whole point

### FOLLOWUPS
- *"Your HLL says 9.9M unique players. The real number is 10M. Is that a bug?"*
- *"Can you use HyperLogLog to check whether player 42 played today?"* (no — and knowing why matters)

## STEP 7 — Scale
- **Sharding**: a global board is one key by nature. Shard by **region/segment** and merge top-Ns
  (each shard's top-100 is enough to compute the global top-100 — a nice property).
- **Windows**: separate keys with TTLs; expiry is free cleanup.
- **Writes**: 2,300/sec is nothing for Redis; batch multi-window updates in one pipeline.
- **Rebuild**: Redis is a cache — replay from the durable event log to reconstruct any board.
- **Cold storage**: all-time history to Postgres/S3; Redis holds only the active windows.

## STEP 8 — Failure
- **Redis dies** → leaderboard unavailable, **rebuild from the event log**. Scores were never only in
  Redis. *(Same "derived structure + durable log" shape as the news feed cache.)*
- **Score write lost** → at-least-once from Kafka; use `ZADD` with an absolute score (idempotent)
  rather than `ZINCRBY` (not idempotent) wherever possible.
- **Hot key saturates a shard** → serve stale from cache; degrade rank precision before degrading availability.
- **Sketch corrupted** → recompute from the log; sketches are derived data too.

## STEP 9 — Wrap
- **Bottleneck:** the hot top-N key (solved by short-TTL caching) — not write throughput.
- **Tradeoffs:** exact ZSET ranks (accurate, memory-heavy at 100M) vs sketches (tiny, ~1% error) ·
  real-time updates vs cached reads · one global board (simple, hot) vs sharded (scalable, needs merging).
- **Monitoring:** top-N latency, cache hit rate, Redis memory, sketch error vs periodic exact counts,
  update lag from match-end to board.
- **Next:** friend leaderboards (a small per-user board), seasons/resets, anti-cheat, reward payouts.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | SQL table with `ORDER BY score DESC LIMIT 100`, maybe a cache |
| **Senior** | Redis sorted sets, per-window keys with TTL, cached top-N, ZREVRANK for my-rank, durable log behind it |
| **Staff** | all that **+ deliberately splitting exact-vs-approximate**, HyperLogLog for uniques *with its limits*, Count-Min Sketch and the **overestimate-never-underestimate** property, shard-and-merge top-Ns, and treating Redis as rebuildable derived data |

## REFERENCE
**A match ends:**
1. `POST /scores` → Score Service
2. Pipeline into Redis: `ZADD leaderboard:alltime`, `ZADD leaderboard:daily:…`,
   `ZADD leaderboard:weekly:…` — each O(log N)
3. `PFADD unique:2026-08-31 player:42` — unique-player counter, 12 KB total
4. Emit to Kafka → durable store (so Redis is always rebuildable)

**Reading the top 100:** almost always the app/CDN cache (5–10 s TTL). On a miss:
`ZREVRANGE leaderboard:daily 0 99` — O(log N + 100).

**Reading my rank:** `ZREVRANK` gives an exact O(log N) answer. For deep ranks you can instead answer
from a score histogram — "top 47%" — which is O(1) and more meaningful to the player.

**"How many unique players today?"** `PFCOUNT` → ~9.9M ±0.8%, from 12 KB instead of 80 MB.

## ONE-LINER
> *"A sorted set is the whole ranking answer — O(log N) updates, O(log N + k) for the top-N, and exact
> ranks — with one key per time window so expiry is free. The interesting decision is **where to stop
> being exact**: nobody needs an exact integer rank for player 47 million, so I serve exact ranks near
> the top and percentiles from a histogram below, and for 'how many unique players today' I use
> **HyperLogLog** — 12 KB instead of 80 MB for under 1% error, and unions are cheap. The one thing to
> be careful about is that these are choices scoped to where error is harmless; anything tied to prizes
> stays exact."*
