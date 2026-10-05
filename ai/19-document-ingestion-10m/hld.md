# Ingesting 10M documents — the scaled design

> Golden rule for this one: the run *will* be interrupted. Every design decision below is
> answering "and then what?"

## 1. Numbers first

| Input | Value |
|---|---|
| Documents | 10M, ~20 chunks each → **200M chunks** |
| Tokens | ~500/chunk → **100B tokens** to embed |
| Embed throughput | 1,000 chunks/sec → **~55 hours** pure embedding |
| Implied token rate | **~30M tokens/minute**, sustained for two days |
| After 30% content dedup | 140M chunks → **~39 hours** |
| Parse/OCR | 1.5 CPU-s born-digital, 20 CPU-s scanned, 15% scanned → **~12,000 CPU-hours** |
| Vector store | 768-dim float32 → **~600 GB** raw, ~150 GB int8 |
| Upserts | 200M at ~5k/s → **~11 hours**, roughly doubled during index build |
| Steady state after backfill | 50k docs/day → 1M chunks/day ≈ **12 chunks/sec** |
| Freshness SLO | new document searchable in **5 minutes p95** |

**Little's Law on the embed stage.** Batches of 96 chunks at a 600ms round trip: to sustain
1,000 chunks/sec you need λ = 10.4 requests/sec × W = 0.6s = **L ≈ 6 concurrent in-flight
requests**. Six.

**What that forces, and it is the whole reframing:** you are not compute-bound or
concurrency-bound. Six sockets saturate the stage. The wall is the provider's **tokens per
minute**, and every worker you add past six converts throughput into 429s. So capacity planning
here is a *procurement* exercise — more keys, more projects, or self-hosted GPUs — not a
Kubernetes one.

**And the second number that forces something:** steady state is 1.2% of backfill rate. Size
the cluster for steady state; run the backfill as a low-priority tenant of the same pipeline.

## 2. Topology

```
change feed ──► document ledger ──► content-hash check ──┬── seen ──► mark done (free)
                (durable, one row                        │
                 per source object)                      ▼
                       ▲                          [parse queue]
                       │                                 │
                       │                          parse / OCR  ◄── slow lane for giants
                       │  (fingerprint written           │
                       │   after each stage)         chunk (versioned)
                       │                                 │
                       │                       [embed queue — BOUNDED]
                       │                                 │   ▲ backpressure
                       │              shared token bucket │   │
                       │              (Redis, per key)  embed (batched by tokens)
                       │                                 │
                       └──────────────────────── idempotent upsert (uuid5)
                                                         │
                                              vector index + chunk rows
                                                         │
                     failures ──► DLQ (reason code) ──► run monitor ──► projected finish
```

## 3. The two real bottlenecks, and what buys you out of them

| Bottleneck | Ceiling | What does **not** help | What does |
|---|---|---|---|
| Embedding | ~30M tokens/min needed vs 1–5M per key | more workers, more pods | dedup first, then multi-key with a **shared** bucket, then self-host on GPU, then move the deadline |
| Vector writes | ~5k upserts/s, less during index build | bigger batches alone | defer the index build to after bulk load, write in batches of 500–1,000, then build once |

Dedup is listed first deliberately: it is the only lever that is free, and at 30% duplicate
content it removes 16 hours before you have spoken to a vendor.

## 4. Scheduling: one pipeline, two priority classes

Live ingest is strict-priority on both the queue and the shared token bucket. The backfill
consumes the remainder and is explicitly allowed to take longer. The reason this matters is
that the alternative — a separate backfill system — is code you run once a year, and it will be
broken when the embedding model changes and you need it back.

**Freshness is an SLO you protect; backfill completion is a deadline you negotiate.** Say which
is which before you are asked.

## 5. State: what must be durable, and where

| State | Where | Why there |
|---|---|---|
| Document ledger (stage, fingerprints, attempts) | Postgres | it is the resume index; needs transactions and range scans |
| Derived artefacts (text, chunks), keyed by content hash | object store | large, immutable, content-addressed — a resend hits it for free |
| Chunk rows and vectors | vector store, `uuid5` ids | idempotent by construction |
| Token buckets | Redis | shared or the limiter is decorative at ten workers |
| DLQ | queue + a table with reason codes | you need to *group* failures, which a queue alone can't do |

Ledger writes are 10M × 6 transitions = 60M updates, ~300/s over the run. Fine — but batch them
in groups of 500 anyway, because they sit in every stage's inner loop.

## What breaks, in order

1. **Embedding quota.** First because it is the only ceiling you cannot raise with machines.
2. **Vector-store write throughput.** Second because it is real (~11–22 hours) but smaller than
   39, and it yields to batching plus a deferred index build.
3. **The inter-stage queue, if unbounded.** Third because it only bites once 1 or 2 is lagging —
   but when it bites, the broker fills and the *whole* pipeline stops, not one stage.
4. **Parse/OCR CPU.** ~46 hours on 256 vCPU. Comparable to embedding, and the sleeper if you
   assumed born-digital documents.
5. **Ledger write contention.** Fatal only if each transition is a separate round trip.
6. **Silent quality drift.** A parser returning empty text for one document class raises nothing
   and embeds whitespace. No error rate moves. The corpus is just wrong.

## Degradation — and it differs per feature

| Under pressure | Degrade to |
|---|---|
| Embedding quota exhausted | **pause the backfill, keep live ingest** — freshness survives, the deadline slips |
| Vector store write-throttling | buffer in the bounded queue and slow embed; never drop, chunks are expensive |
| OCR pool saturated | shed the **slow lane** (giant scanned PDFs) to a nightly window, keep the fast lane |
| Parse failures spiking past 2% | **halt the run** — this is the one place you stop rather than degrade, because 200k bad documents indexed is worse than 200k missing |
| Vector store down entirely | keep parsing and embedding, park vectors in the object store, replay upserts later — the expensive stages must not idle |

That fourth row is the answer worth having ready. Everywhere else you degrade; on a systemic
parse failure you stop, because a silently wrong corpus is not recoverable by retrying.

## Observability

Per **stage**, never aggregate: documents/sec, queue depth and its trend, batch size actually
achieved, p95 stage latency, retry rate, DLQ rate **grouped by reason code**.

Per **run**: documents remaining by stage, and a **projected finish time** computed from the
trailing rate against the ledger — not a progress bar.

**Leading indicators**, which move before anything looks broken:
- the **ratio** between stage throughputs (embed falling behind parse = quota, not capacity)
- **queue depth trend**, not depth — a queue growing steadily at 200/s is 30 hours from a
  broker outage and looks perfectly healthy right now
- **achieved batch size** drifting down — it means token-budget packing is being defeated by
  long chunks, and throughput follows it
- **DLQ rate per reason code** — one code climbing is a class you have not handled
- **fraction of documents with a complete fingerprint chain** — anything under 100% is work you
  will silently redo on the next replay

Error rate is a lagging indicator here. A run can be error-free and still be forty hours too
slow, which is the failure mode that actually happens.
