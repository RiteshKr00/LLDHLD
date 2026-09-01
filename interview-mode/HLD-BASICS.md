# HLD Basics — start here

> New to HLD? Read this **before** any problem file. Those files assume you know the vocabulary;
> this one gives it to you. ~15 minutes.

---

## 1. What HLD actually is

**LLD:** "design the classes." Output = code.
**HLD:** "design the system." Output = **boxes, arrows, and numbers.**

You are answering one question over and over: **"why does this box exist?"**
And the only good answer is a **number**.

> ❌ "We'll add a cache for performance."
> ✅ "17,000 reads/sec would flatten one Postgres box, so a cache absorbs them."

That's the whole difference between a junior and senior HLD answer.

---

## 2. The only 6 building blocks

Every system you'll ever design is made of these. That's it.

| Block | What it does | Reach for it when |
|---|---|---|
| **Load balancer** | spreads requests over many servers | you have >1 server |
| **App server** | your code; stateless so you can add more | always |
| **Database** | the truth, durable | anything that must survive a restart |
| **Cache** | fast copy of hot data (Redis) | reads ≫ writes |
| **Queue** | work handed off to be done later (Kafka) | slow work that shouldn't block the user |
| **Blob store + CDN** | big files, served from near the user (S3 + CDN) | images, video, downloads |

**A design is just: which of these six, in what order, and why.**

```
Client → Load Balancer → App Servers → Cache → Database
                              ↓
                            Queue → Workers → Blob store → CDN
```

---

## 3. The numbers you must know

Memorise these six. Everything else you derive.

```
1 day            = 86,400 seconds   ≈ 10⁵     ← you will divide by this constantly
peak traffic     ≈ 2× average
read : write     usually 10:1 to 100:1 (people read far more than they write)

one Postgres box ≈ 5,000-10,000 writes/sec
one Redis box    ≈ 100,000 ops/sec
one server holds ≈ 50,000-100,000 open connections
```

**Latency, so you know what's slow:**
```
memory read           0.0001 ms      ← basically free
SSD read              0.1 ms
same-datacentre call  0.5 ms
India → US round trip 150 ms         ← 1,500,000× slower than memory
```
That last line is why CDNs exist.

---

## 4. The 3 calculations (do these every time)

**a) Write QPS**
```
daily writes ÷ 86,400        →  ×2 for peak
e.g. 30M posts/day ÷ 86,400 ≈ 350/sec, peak ~700
```

**b) Read QPS**
```
write QPS × the read:write ratio
e.g. 350 × 50 = 17,500 reads/sec   → "read-heavy, so: cache + read replicas"
```

**c) Storage**
```
rows/day × bytes/row × days to keep
e.g. 30M × 300 B × 365 ≈ 3 TB/year   → "modest, one sharded DB is fine"
```

**The point isn't precision.** Nobody checks your arithmetic. The point is that each number **forces
a decision**: read-heavy → cache. 3 TB → shard. 100M connections → 1,000 servers.

---

## 5. Vocabulary (plain English)

| Term | Plain meaning |
|---|---|
| **QPS** | queries (requests) per second |
| **p99 latency** | 99% of requests are faster than this. Watch this, not the average — the average hides the pain |
| **Sharding** | splitting data across machines. "Shard by user_id" = user 42's data always lives on one specific box |
| **Replication** | keeping copies. One primary takes writes, replicas serve reads |
| **Eventual consistency** | copies catch up in a moment. Fine for a like count, not for your bank balance |
| **Strong consistency** | everyone sees the same value immediately. Slower, sometimes mandatory |
| **CAP** | during a network split you must choose: stay **C**onsistent (refuse) or stay **A**vailable (answer, maybe stale) |
| **Idempotent** | doing it twice = doing it once. Essential, because retries happen |
| **Fan-out** | one event → many recipients (one tweet → 200 followers) |
| **Hot key** | one item everyone wants at once. One shard melts while the rest idle |
| **Backpressure** | slowing intake so you don't drown (a queue, a waiting room) |
| **TTL** | time-to-live: this data deletes itself after N seconds |

---

## 6. SQL or NoSQL? (the question you'll always be asked)

```
Do you need transactions, or joins, or is the data genuinely relational?
│
├── YES  →  PostgreSQL / MySQL
│           money, orders, bookings, anything where "half done" is a disaster
│
└── NO   →  what does the access pattern look like?
            │
            ├── always by key ("give me user 42's stuff")  →  Cassandra / DynamoDB
            ├── it's just a cache                          →  Redis
            ├── it's files                                 →  S3 + CDN
            └── time-series (metrics, events)              →  Timescale / Influx
```

**Default to PostgreSQL and make them argue you out of it.** "1,000 writes/sec fits comfortably on one
Postgres box, so I'd start there and shard later" is a *stronger* answer than reaching for Cassandra —
it shows you size things instead of pattern-matching on "big system".

---

## 7. The 9 steps (your script for 45 minutes)

```
1. Requirements ......  5 min   what it does + what you're NOT building
2. Capacity ..........  5 min   the 3 calculations         ← most skipped, most penalised
3. API ...............  3 min   3-4 endpoints, that's all
4. Data model + DB ...  5 min   tables + which DB and why
5. Architecture ......  8 min   draw the boxes, trace one read and one write
6. DEEP DIVE ......... 10 min   the ONE hard thing          ← the round is won here
7. Scale .............  5 min   what breaks first at 10×
8. Failure ...........  2 min   "what if this box dies?" for each box
9. Wrap ..............  2 min   tradeoffs, monitoring, what's next
```

**Step 2 and Step 6 are where the marks are.** Step 2 justifies everything after it; Step 6 is the
part only a senior can do.

---

## 8. Four sentences that make you sound senior

Use them literally.

> **"Let me do a rough estimate first, because that decides the design."**
> Before any architecture. Instantly separates you from people who start drawing boxes.

> **"This is out of scope — I'll mention it but not design it."**
> Scoping *down* is a senior move. Trying to design everything is a junior one.

> **"The tradeoff is X versus Y, and I'd pick X because…"**
> Every choice has a cost. Naming it is the whole game.

> **"If that component dies, the system degrades like this — it doesn't stop."**
> Nobody volunteers failure behaviour. Everyone is impressed when you do.

---

## 9. The 5 mistakes everyone makes

1. **Skipping the estimate.** Then no box has a justification and you can't answer "why?"
2. **Jumping to boxes.** Requirements first, numbers second, boxes third.
3. **Over-engineering.** Kafka + microservices + Cassandra for 100 requests/sec. Match the scale.
4. **Silence.** They're evaluating your *thinking*. Think out loud, always.
5. **No failure story.** "What if the DB dies?" should never be the first time you consider it.

---

## 10. The 5 threads that repeat across every problem

Once you see these, new problems stop being new.

| Thread | What it sounds like |
|---|---|
| **Check-then-act is a race** | two things check "is it free?", both say yes, both take it. Fix: make check+take **one** operation in the shared store |
| **Retries mean duplicates** | networks fail, clients retry. Promise **at-least-once** and dedupe with a key. Exactly-once is a myth |
| **Derive or store?** | compute from the log (always right, slow) vs keep a running total (fast, can drift). Usually: store it, but keep the log and reconcile |
| **Leases beat locks** | a claim that **expires** heals itself when the holder crashes. No cleanup job needed |
| **Fail open or closed?** | rate limiter fails **open** (don't take the site down). Payments fail **closed** (never risk being wrong). Knowing which is a senior signal |

---

## Now what

1. Read this once more tomorrow — it's short on purpose
2. Then open [`hld/HLD-01-news-feed.md`](hld/HLD-01-news-feed.md)
3. Read only the **PROMPT**. Close the file. Try to answer.
4. Reopen and score yourself against **CHECKPOINTS**

Getting a checkpoint wrong is the point. That's where the learning is.
