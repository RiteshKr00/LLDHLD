# 10M records overnight — the scaled design

## 1. Numbers first

| Input | Value |
|---|---|
| Records / window | 10M tickets in 8 h = 28,800 s (22:00 → 06:00) |
| Required rate | **347 records/sec sustained** |
| Tokens per record | ~800 in, ~150 out → **9.5B tokens** for the run |
| Sustained token rate | **~20M tokens/minute** |
| One good provider key | 1–2M TPM → **10–20 keys' worth of quota** |
| Per-call p50 / p95 | 3 s / 9 s |
| Little's Law, all-sync | 347 × 3 = **~1,050 concurrent in flight** |
| Little's Law, hybrid drain | 1.02M + its escalations in 3 h ≈ 105/s × ~3.3 s = **~340 in flight** |
| Drain pool provisioned | **450 workers** — 340 plus head-room for the 9 s p95 tail |
| Sink writes | 347 upserts/sec = **0.7 batches/sec at 500 rows** |
| Naive vs engineered cost | **$35,000 → $2,463** |
| Steady state after backfill | ~50k/day ≈ **0.6/sec** |

**What those numbers force.** 20M TPM against a 1–2M TPM key means the wall is **quota, and TPM
before RPM** — you cannot buy your way past it with workers, because beyond the quota extra
concurrency *is* the failure. 347 rec/s of orchestration is nothing, so this is not a compute
problem. And 0.6/sec steady state against 347/sec backfill means **do not build a second system**:
run the backfill as a throttled tenant of the nightly pipeline.

## 2. Topology

```
ticket store (10M) ─► shard planner ─► checkpoint store [pending|leased|done|dlq]
                                        2,000 shards × 5,000 records, TTL leases
        │
        ▼
normalised-hash dedup ──► 32% answered from cache, never sees a model
        │ 68% distinct
        ▼
difficulty router ─► wave submitter ─► Batch API (½ price, 24h SLA)
                                              │
                                   cutover clock at T+5h
                          ┌───────────────────┴───────────────────┐
                    returned 85%                          cancelled 15%
                          │                        sync drain pool, 450 workers
                          │                        multi-key SHARED token bucket
                          └───────────────┬───────────────────────┘
                                          ▼
                          validate + confidence ─► escalate 12% / dlq after ×3
                                          ▼
                          idempotent batched upsert ─► burn-down + projected finish
```

## 3. The three levers, and what each one costs

| Lever | Effect | The risk it takes on |
|---|---|---|
| Normalised-hash dedup | 10M → 6.8M calls | none — free and lossless |
| Cheap-first cascade | 12% reach the frontier model | **accuracy**, bounded by the escalation threshold |
| Batch API + cutover | ½ price on 85% of the work | **the deadline**, bounded by the cutover clock |

They compose in that order deliberately: the free one, then the one an eval can measure, then the
one that can make you miss. The cutover converts an unbounded schedule risk into a **known $322**.

## 4. Shard sizing and the checkpoint store

Two failure modes pull opposite ways. Shards too large and a crash replays minutes of work per
in-flight worker; too small and the checkpoint table becomes a hot row taking two writes per
record — you'd have doubled your write volume to protect against a crash. Size it in **seconds of
work**: 5,000 records is under a minute of one worker's throughput, so worst-case waste is
*workers in flight × 5,000*. Write the result and the checkpoint in the **same transaction**, or
there's a window where the work is done and the system doesn't know it — which on a replay means
paying for it twice.

## 5. Fairness — the batch is a tenant, and it is the rude one

The provider sees one account. Your overnight batch and your daytime product draw on the same TPM
pool, so an overrun at full throttle gives the product the 429s and files the incident against the
product. The batch therefore holds its own bucket on a schedule — 100% overnight, 20% until 08:00,
zero after — and **degrades itself** rather than its neighbour. Same bulkhead argument as a
dedicated Celery queue, applied to quota instead of workers. If the 10M spans tenants, interleave
shards per tenant so partial output spreads across them rather than concentrating in whoever sorts
first by id.

## 6. What breaks, in order

1. **Provider quota, TPM before RPM** — the wall you hit on night one, and the only one that adding
   workers makes *worse*.
2. **The write path** — 347 sustained upserts with an index on the label column. Invisible until
   quota stops being the limiter, then it is the whole run.
3. **The tail of slow records** — the longest 1% take 5–10× and are all that's outstanding at 07:30.
   Only bites when you're near the line. Fix: schedule long records **first**.
4. **The checkpoint store** — only a bottleneck if someone "improves" resumability by checkpointing
   per record.
5. **The synchronised retry storm** — everything that failed all night returns in the last hour on
   the same backoff schedule. Jitter, plus a retry budget that **expires with the window**.

Not compute. Say it out loud; it's the reframe that shows you have run one of these.

## 7. Degradation — and it differs per output field

| Output | Behind at T+5h |
|---|---|
| **Label** | ship the cheap model's answer unescalated; a noisier label beats none, and the low-confidence slice re-runs tomorrow |
| **Summary** | skip it. A missing summary degrades a screen; a rushed one is wrong prose a human will trust |
| **Priority / auto-routing** | fail closed — leave the ticket unrouted rather than route it wrong |
| **The low-confidence tail** | park it in a `needs review` queue with record ids. That's a *result*, not a failure |

Partial output is only a degradation strategy if the consumer can use it — which is why that's a
clarifying question. If the run is atomic, the whole cutover calculus changes: you start earlier
and buy more sync capacity instead.

## 8. Observability

Per shard and per model: records/sec against the required-rate line, projected finish, cost so far
against the ceiling, escalation rate, dedup hit rate, DLQ growth, shard lease age, error rate split
by class (429 / 5xx / timeout / parse).

**Leading indicators** — they move before the run is in trouble:

- **Age of the oldest outstanding batch job**, against the cutover clock. This is the one. A
  progress bar built on completed-so-far reads *ahead of the line* for seven of the eight hours and
  still misses, because it says nothing about work you don't own the clock on.
- **Dedup hit rate falling** — the normaliser broke on an upstream format change and your cost has
  silently doubled.
- **Escalation rate rising** — the corpus shifted or the confidence signal broke. Moves cost and
  time before it moves accuracy.
- **Shard lease age** — a shard leased twenty minutes ago and not done is a stuck worker, not a slow
  one.
- **DLQ growth as a step change**, not as a level. A step is a schema change upstream.
