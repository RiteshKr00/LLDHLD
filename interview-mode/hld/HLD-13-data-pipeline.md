# HLD-13 — Data Pipeline / Analytics Warehouse

## META
- difficulty: hard
- time: 45 min
- tags: batch-vs-stream, lambda-kappa, elt, columnar, partitioning, watermarks, event-time, backfill, schema-registry
- priority: core
- why-it-matters: the only round about **moving and reshaping data** rather than serving a request — and the
  home of **event time vs processing time**, the most interview-worthy idea in the track.

## PROMPT
> "Our product emits a few billion events a day — clicks, page views, purchases. Analysts and dashboards
> need to query them. Design the pipeline."

## CLARIFY
- **How fresh do the numbers have to be?**
  → Dashboards want **minutes**, the 9am report can be **hours** old. That split drives everything.
- **Who queries it, and how?**
  → Wide scans over a time range, never a point lookup by id.
- **Are these events the source of truth?**
  → No, Postgres is. Losing a click is survivable; losing a purchase is not.
- **Do the numbers have to be exactly right?**
  → Revenue exactly, and stable after publication. Engagement: approximate is fine.
- **Can events arrive late or out of order?**
  → **Yes** — phones buffer offline and upload hours later. The crux of the round.
- **Will the event schema change?**
  → Constantly, and nobody tells you.
- **Do we ever need to recompute history?**
  → Yes — metric bugs and schema changes both force a backfill. A requirement, not an incident.

## STEP 1 — Requirements
**Functional:** ingest from web/mobile/backend · SQL-queryable · near-real-time dashboards · derived
aggregates · **backfill and reprocess history** · evolve schemas without breaking consumers.
**Non-functional:** ingest **never blocks the product** · no loss for revenue events · **minutes for
dashboards, hours for the warehouse** · **numbers reproducible** — same input, same code, same answer.
**Out of scope:** BI tool · ML feature store · GDPR row-level deletion — name it, because deleting one user's
rows from immutable columnar files is genuinely hard.

### CHECKPOINTS
- Splits freshness into **two SLAs**: dashboard minutes vs warehouse hours
- Ingest is **fail-open** — analytics never takes down the product's write path
- Names **backfill/reproducibility** as a requirement, not an afterthought

### TRAPS
- Treating "analytics" as one workload — a 1-minute dashboard and a year-long scan want opposite storage
- Making checkout synchronously write to the warehouse, so a pipeline outage stops people buying things

### FOLLOWUPS
- *"The CFO asks why yesterday's revenue number changed overnight. What do you tell her?"*

## STEP 2 — Capacity
```
DAU 50M × ~40 events/day = 2B/day ÷ 86,400 ≈ 23,000/sec      peak 3× ≈ 70,000/sec
~1 KB raw JSON -> 2 TB/day raw;  columnar+zstd ~10:1 -> ~200 GB/day stored
2 years hot: 200 GB × 730 ≈ 150 TB  <- rules out Postgres   (+7 y cold archive)

"revenue by day for the last year", 200-column table, ~2M purchases/day × 365 ≈ 700M rows:
   row store 1 KB × 700M ≈ 700 GB scanned    columnar 4 B × 700M ≈ 3 GB    ~200× less

reads: 200 analysts × 10 queries/day = 2,000/day ≈ 0.02 QPS
       500 dashboards refreshing every minute   ≈ 8 QPS on PRE-AGGREGATED tables
```
The metric is **bytes scanned per query**, not RPS — which is why every later decision is about *not reading* data.

### CHECKPOINTS
- Derives events/sec **and** raw bytes/day, and applies a **peak multiplier**
- Says the real metric is **bytes scanned per query**, not QPS

### TRAPS
- Sizing the warehouse for QPS: 2,000 queries a day is 0.02 QPS, and no replica helps a full scan

### FOLLOWUPS
- *"Only 2,000 queries a day. Why can't I run this on one big Postgres box?"*

## STEP 3 — API — the ingest contract
```
POST /api/v1/events  {batch:[{event_id, event_name, event_time, user_id, props{}}]} -> 202
     batches up to 500 events / 5 s · retries reuse the SAME event_ids
     server stamps ingest_time on arrival — it never trusts the client for that one
GET/POST /api/v1/schemas/{event_name}  -> current + history · 409 if incompatible
```
`202` because the work outlives the request. **`event_id` is producer-generated** — the payment round's
`Idempotency-Key`, per row. **Two timestamps always:** `event_time` (client, when it happened), `ingest_time`
(server, when we saw it); clamp anything hours in the future. Analysts get plain SQL, not a query API.

### CHECKPOINTS
- A **producer-generated `event_id`** is the dedup key, and retries reuse it
- Carries **both `event_time` and `ingest_time`**, server-stamping the latter

### TRAPS
- One request per event — 70K RPS of 1 KB requests, where batching at 500 moves the same bytes in ~140 req/sec
- Stamping only at the server, which permanently destroys the ability to window by event time

### FOLLOWUPS
- *"A phone was offline six hours and just uploaded 4,000 events. Which timestamp do you bucket them by?"*

## STEP 4 — Data model — columnar, partitioned, versioned
| | Row store (OLTP) | Columnar (OLAP) |
|---|---|---|
| Layout | a row's fields contiguous | a column's values contiguous |
| Good at | "user 42's row" — one seek | "sum revenue over a year" — 1 column of 200 |
| Compression | poor — adjacent bytes differ in type | excellent — one column, one type |
| Examples | Postgres, MySQL | Parquet/ORC on S3, ClickHouse, BigQuery |

"Good at" is the 700 GB vs 3 GB from step 2, purely layout. Compression is the other half — `country` is ~200
distinct strings over 700M rows, so dictionary-encode to 1 byte then RLE — and Parquet's **min/max per column
chunk** lets a predicate skip whole files undecompressed.
```
raw/bronze    s3://events/purchase/dt=2026-08-31/hour=14/*.parquet — immutable, INGEST date
clean/silver  deduped, typed, conformed, partitioned by EVENT date
marts/gold    the aggregates dashboards read (daily_revenue, dau, funnel)
```
- Every analytics query has a time predicate — 7 days opens 7 of 730 directories, so **partition pruning beats
  any index**. Partition **queryable** tables by **event date, not ingest date**, or a late event lands in the
  wrong day forever; raw stays on ingest date as the append-only replay source, so rebuilding `event_date=D`
  reads ingest partitions `D..D+N`. **Don't over-partition** — `dt/hour/country/event_name` makes millions of
  tiny files and the planner lists longer than it reads; aim **~256 MB–1 GB per file**.
- **Schema registry** (Avro/Protobuf), or a producer renames `price`→`amount` and the dashboard silently reads
  NULL — no error, a wrong number. **Backward** (new reader, old data — the default), **forward** (old reader,
  new data), **full** (both). So **add, never rename**; a breaking change is a new `purchase_v2`.

### CHECKPOINTS
- Picks **columnar** and proves it: one column of 200, not the whole row
- Ties columnar to **compression** (dictionary/RLE) and per-chunk min/max stats
- **Partitions by event date**, names **partition pruning**, plus the small-file failure mode
- Names a **schema registry** with backward/forward, and "add, never rename"

### TRAPS
- "Postgres with an index on `event_time`" — an index finds a few rows, it does not scan a billion
- Partitioning by `user_id` out of OLTP habit; no analytics query filters to one user

### FOLLOWUPS
- *"You partitioned by day, then country, then event type. Six months later queries got slower. Why?"*

## STEP 5 — Architecture — batch, stream, and the two named shapes
```
producers ──batched HTTP──▶ Collector (stateless, fail-open, validates against the registry)
   ▼
KAFKA — durable replayable log · partitioned by user_id · 7 d · per-consumer offsets
   ├─ stream ─▶ Flink (event-time windows) ─▶ ClickHouse ─▶ dashboards   (PROVISIONAL)
   └─ batch  ─▶ raw Parquet on S3 ─▶ Spark/dbt: dedup · conform · aggregate
                                  ─▶ silver + gold ─▶ analysts · ML      (OFFICIAL)
```

| | Batch | Stream |
|---|---|---|
| Unit of work | a **bounded** set (an hour, a day) | an **unbounded** sequence |
| Latency | minutes to hours | ~1–30 s — not "instant" |
| Cost per event | low: sequential scans, spot cluster | higher: always-on, per-event state |
| Correctness | easy — rerun a deterministic job | hard — state, windows, late data |
| Late data | trivial: the next run sees it | the entire watermark problem |

**Run both**: step 1 produced two SLAs — stream what a human watches now, batch what they read tomorrow.

| | **Lambda** | **Kappa** |
|---|---|---|
| Shape | batch + speed layer, merged at read | one stream layer; reprocess by **replaying the log** |
| Buys | correct history *and* a live view | **one codebase, one definition per metric** |
| Costs | **the same logic twice, in two engines, that must agree** | replaying two years at streaming prices |

**Kappa's discipline with Lambda's economics:** define each metric **once** (SQL/dbt), run it by the stream
engine for the live window and the batch engine for history, so the two cannot disagree on *logic*.

**ETL vs ELT:** ETL transforms on the way in, right when storage was costly; **ELT loads raw first** because
cheap storage plus elastic compute flipped that. The row that decides it: under ETL a transform bug is
unrecoverable, the input is gone; under ELT you **fix the SQL and rerun**. **ELT is what makes backfill possible.**

### CHECKPOINTS
- **Durable replayable log** at the front: decoupling, N consumers, replay
- Compares **batch vs stream** on latency, cost and correctness — and runs both
- Names **Lambda vs Kappa** and Lambda's real cost: the same logic twice
- Explains **ELT vs ETL** — keeping raw is what makes backfill possible

### TRAPS
- "I'll use Kafka" as a name, not a tradeoff — it buys replay, costs duplicates and per-partition-only ordering
- Speed and batch layers with **different definitions** of one metric — this is how Lambda actually fails

### FOLLOWUPS
- *"Your live dashboard says 1.2M active users and this morning's report says 1.15M. Which one is right?"*
- *"Sell me on Kappa. Now tell me why your company probably still runs Lambda."*

## DEEP DIVE — event time vs processing time: watermarks, late data, exactly-once, backfill
One question in four disguises: **the moment something happened and the moment you found out are different,
and you have to publish a number anyway.**

### 1. The two clocks
```
tap "purchase" 10:00:00 <- EVENT TIME · offline in a lift · job sees it 10:05:31 <- PROCESSING TIME
```
Metrics are defined in **event time**; systems run in **processing time**; the gap is unbounded. Bucket by
processing time and "revenue for 31 Aug" quietly includes an event from the 30th and excludes one landing on
the 1st — **wrong in a way no unit test catches**. Windows (tumbling / sliding / session) are buckets in
*event* time, which forces the real question: **when is a window complete?**

### 2. Watermarks — the answer, and it is a guess
```
watermark = max(event_time seen) − out_of_orderness_bound   "I believe I've seen everything ≤ T"
max seen 10:07, bound 2 min -> watermark 10:05 -> [10:00–10:05) may close and emit
small bound -> emits fast, more events arrive too late      large bound -> more complete, more state
```
A heuristic, not a fact. **Two dials:** the **bound** sets when a window closes; **allowed lateness** is the
grace after, during which a late event re-fires the window and the sink upserts the correction. **The
production stall:** a watermark is the **minimum across input partitions**, so one idle partition freezes every
window in the job — no output, nothing technically failing. Fix: an **idleness timeout**.

### 3. Data that arrives after the window closed
| Policy | What happens | Use when |
|---|---|---|
| **Drop** | discard, increment `late_events_dropped` | 0.1% is noise — but **measure** it |
| **Update/retract** | re-fire within allowed lateness; sink overwrites by key | the sink is keyed, idempotent |
| **Side output** | route to a side table for a later job | rare, high-value events |
| **Let batch fix it** | live number provisional; nightly job recomputes from raw | **the pragmatic answer** |

Say the last one as a decision: **the live number is provisional, the batch number is official.** That
dissolves the "which number is right" argument, and is why the two-runtime shape in step 5 works.

### 4. Exactly-once — what it actually is
**There is no such delivery mode:** an ack can be lost, so a sender either retries (duplicates) or doesn't
(loss). *"Exactly-once is a property of the end-to-end pipeline — **replayable source** (rewind on restart),
**checkpointed state** (window state and offsets snapshotted together, atomically), **idempotent sink** — not a
delivery mode. Underneath it is always at-least-once plus a dedup key."*

The sink is the only part touching the world: write under a deterministic key — `(window_start, metric,
dimensions)`, or `event_id` for a raw row, with `ON CONFLICT DO UPDATE` — so a replay **overwrites instead of
adding**. For `counter += 1` or "send an email" there is no fix but a dedup table in front of the side effect.
**Dedup at 23K/sec:** you cannot keep every `event_id` forever (2B/day × 16 B ≈ 32 GB/day of keys), so
**stream** = a bounded 24 h RocksDB set or Bloom filter, **batch** = the nightly rewrite dedups exactly.

### 5. Backfill without double-counting
Triggered by a **metric bug** or a **schema change**. A run's output must be a **pure function of (raw input,
code version, partition)**, written **idempotently**.
```
1. NEVER mutate raw — it is the replay source; edit it and nothing is reproducible again.
2. PARTITION OVERWRITE, not append:
      INSERT OVERWRITE daily_revenue PARTITION (dt='2026-08-14') SELECT …
   Rerun five times, same answer. Append is not idempotent: rerun and revenue doubles.
3. SHADOW table: build daily_revenue__v2, diff against v1, swap the pointer. Tag each
   partition with its code version, so "what needs reprocessing" is a query.
4. Separate, lower-priority pool, or 730 days at once starve the live path.
```
**A backfill changes numbers people have already seen** — which is why published reports get snapshotted.

### CHECKPOINTS
- Separates **event time from processing time**, with a concrete example
- Defines a **watermark** as a heuristic, and the **completeness-vs-latency** dial
- Gives a **specific late-data policy**, not "we handle late data"
- **Exactly-once = replayable source + checkpointed state + idempotent sink**
- Backfill is idempotent by **partition overwrite**, with **raw immutable**

### TRAPS
- Windowing by processing time and calling it "revenue for the 31st" — silently wrong, and no test fails
- Claiming a framework gives exactly-once "out of the box" without naming the sink requirement
- A backfill that `INSERT`s instead of `INSERT OVERWRITE` — every rerun inflates history further

### FOLLOWUPS
- *"An event timestamped 10:00 arrives at 10:19, and you published that window at 10:07. What happens to it?"*
- *"Your watermark hasn't moved for an hour but every partition looks healthy. What's going on?"*

## STEP 7 — Scale
- **Partition count is the parallelism ceiling** — one consumer per partition; ordering is per-partition only.
- **Hot partition** — one B2B customer at 20% of volume: composite key `user_id + bucket`. It also freezes
  every window, since the watermark is the minimum across partitions.
- **Small files** — compaction rewrites each day into **~256 MB–1 GB files**, in the same pass as the exact
  dedup rewrite, so that scan is paid for once.
- **Query cost** — materialise the top ~20 dashboard queries into gold; **bytes-scanned quota per team**.
- **Tiering** — 90 days fast storage · 2 years object storage · 7 years Glacier. Backfills get their own pool.

### CHECKPOINTS
- **Partition count is the parallelism ceiling**; ordering is per-partition only
- Names the **small-file problem** and **compaction**, folded into the dedup pass

### TRAPS
- Adding partitions mid-incident to "scale up" — you have rehashed the keys and broken per-key ordering

### FOLLOWUPS
- *"An analyst ran one query that cost $8,000. How do you stop the next one?"*

## STEP 8 — Failure
- **Stream job down 2 h** → **lag, not loss**: lag grows to ~2 h × 23K/s ≈ **165M events**, then drains. Safe while **lag < retention**.
- **Collector down** → producers buffer on device and retry the same `event_id`s; **fail open**.
- **Broker dies** → RF 3, `min.insync.replicas=2`, `acks=all`; weaker means an ack is "one disk somewhere has it".
- **Poison pill** → DLQ topic after N attempts, then continue and alert. Never `except: pass`.
- **Batch job fails halfway** → rerun it; partition overwrite means no compensation and no cleanup.
- **Silent corruption** → **data-quality gates** (row count vs the same weekday last week, null rate, revenue reconciled against OLTP) **fail the run and block publication**.

### CHECKPOINTS
- An outage is **lag, not loss** — and the real limit is **lag under retention**

### TRAPS
- Alerting on lag > 0 (it always is) instead of lag trending toward retention or the freshness SLA
- Publishing a table whose quality checks failed, because the dashboard would otherwise look empty

### FOLLOWUPS
- *"A producer starts sending prices in cents instead of rupees. When does anyone notice?"*

## STEP 9 — Wrap
- **Bottleneck:** not ingest — 23K/sec is routine. **Bytes scanned per query** on the read side, **stream state
  size plus watermark stalls** on the write side.
- **Tradeoffs:** freshness vs completeness (the out-of-orderness bound *is* this tradeoff) · stream vs batch
  cost · Lambda's duplicated logic vs Kappa's expensive reprocessing · keeping raw (backfillable, costs storage)
  vs ETL (cheap, unrecoverable) · approximate dedup live vs exact in the rewrite.
- **Monitoring:** **consumer lag** · watermark lag per partition · late/dropped counts · **table freshness =
  `now − max(event_time)`** · bytes scanned per team · data-quality pass rate.
- **Next:** feature store off the same log · GDPR deletion (needs Iceberg/Delta merge-on-read) · a semantic
  layer so "active user" is defined once.

### CHECKPOINTS
- Headline metrics are **consumer lag** and **table freshness**, not CPU or disk

### TRAPS
- Naming CPU and memory — nobody is paged for a pipeline's CPU, they are paged for lag and staleness

### FOLLOWUPS
- *"What would you build first, and what would you deliberately leave out of v1?"*

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | "events → Kafka → Spark → a database". No columnar or partitioning story, late data as an edge case, "exactly-once" as a checkbox, backfill never mentioned |
| **Senior** | durable log at the front · immutable raw, **ELT** into **columnar** files **partitioned by event date** · batch **and** stream, each tied to one SLA · **event time vs processing time**, watermarks, the completeness-vs-latency dial · exactly-once as **at-least-once + idempotent sink** · **backfill by partition overwrite** · schema registry |
| **Staff** | all that **+** picks Kappa vs Lambda on *economics* · separates the **bound from allowed lateness** · **two-tier dedup** · the **min-watermark-across-partitions stall** · shadow-table backfill with diff-and-swap · quality gates that **block publication** · "live is provisional, batch is official" as a **chosen decision** |

## REFERENCE
### One purchase event, end to end
Phone emits `{event_id: uuid-9f2, event_name: purchase, event_time: 10:00:00, amount: 499}` batched with 40
others; the collector validates it, stamps `ingest_time`, returns `202`, appends to Kafka. **Stream:** Flink
puts it in `[10:00–10:05)`; the watermark (max event time seen − a 2 min bound) closes that window at ~10:07
and **upserts by key** `(window_start=10:00, metric=revenue, country=IN) → 12,400` into ClickHouse, so a replay
overwrites rather than adds — ≈10 s latency, **provisional**. **Batch:** the same record lands as raw Parquet,
untouched forever; hourly, Spark dedups by `event_id` and writes `INSERT OVERWRITE silver.purchases PARTITION
(event_date='2026-08-31')`, then dbt rebuilds `gold.daily_revenue` — **official**.

### The late event, the backfill, the outage
**Late:** `event_time 10:00` arrives **10:19**, twelve minutes after that window closed. Revenue's policy is
*let batch fix it* — the nightly rerun reads it from raw and overwrites the partition. The dashboard was
briefly ₹499 light; the published table never was.
**Backfill:** three weeks later you learn tax was excluded from `amount`. Fix the dbt model, run 21 days into
`gold.daily_revenue__v2`, diff against v1 (expect ≈ +2.1% uniformly — a per-day anomaly means the fix is
wrong), swap the pointer. Every write is `INSERT OVERWRITE … PARTITION`, so three runs give the same answer
three times, and raw was never touched.
**Outage:** Flink dies 14:00, back 16:00; Kafka held everything (7-day retention, lag peaked ~165M). Flink
restores its checkpoint — state **and** offsets together — reprocesses, and the keyed sink overwrites rather
than double-counts. **Nothing lost, some numbers late:** the log **converts an availability incident into a
latency incident.**

## ONE-LINER
> *"Durable replayable log at the front, raw events landed immutably in **columnar files partitioned by event
> date** — that's **ELT**, and keeping raw is what makes backfill possible at all. Metrics are defined in
> **event time** while the system runs in **processing time**, so windows close on a **watermark** whose
> **out-of-orderness bound is a completeness-versus-latency dial** — which is why the live number is provisional
> and the nightly batch number official. And **exactly-once is end-to-end, not a delivery mode** — replayable
> source, checkpointed state, **idempotent sink keyed by `event_id`** — which is also why a backfill overwrites
> a partition instead of appending."*
