# LLM observability at 600k calls/day — the scaled view

## 1. Numbers first

| Input | Value |
|---|---|
| LLM calls/day | 600k → **7 QPS average, 70 peak** |
| Spans per call | ~6 → **3.6M spans/day, 42/s average, 420/s peak** |
| Payload per trace | ~20 KB · **skeleton 400 B** |
| Log-everything write | 12 GB/day · 4.4 TB/year raw · **4.8 TB resident at 400 days** |
| Split write | **0.84 GB/day** · ~114 GB resident |
| Skeleton rows at 400 days | **240M** |

**Little's Law on the collector:** 420 spans/s × ~5 ms of work = **~2 concurrent**. The
collector is two cores; it is not the problem and never will be.

**The buffer is the problem.** Ten minutes of backend downtime is 420 × 600 × ~2 KB ≈ **500 MB
in flight**. That single number forces a *bounded* queue with disk spill and prioritised
drop-oldest, rather than the unbounded channel everyone reaches for first. An unbounded queue
here is a delayed OOM inside the application process — your observability outage becomes a
product outage.

**Neither store is throughput-bound.** 42 rows/s and 30k objects/day are nothing. They are
**retention-bound and query-bound**, which is why the design levers are retention policy,
partitioning and cardinality, not shards and replicas.

## 2. Topology

```
app + gateway ─► in-process redactor (FAILS CLOSED) ─► bounded async queue (spills to disk)
                                                              │
                                                    collector: tail sampling,
                                                    deterministic on trace_id
                                                              │
                        ┌─────────────────────────────────────┴──────────────────┐
                        ▼ skeleton, 100%                                ▼ payload, ~5%
              columnar store, 400 days                        object store, 30 days
              (240M rows = the cost ledger)                    partitioned by tenant+day
                        │                                                │
        ┌───────────────┼───────────────┐                        nightly LLM judge
        ▼               ▼               ▼                        on the UNBIASED slice
  metrics (256      hourly per-tenant   ad-hoc query                     │
  series/metric)    rollup rows         console  ◄─────────────── scores written back
        │
     alerts on leading indicators ◄──── change annotations overlaid on the timeline
```

## 3. Two stores, because they have two jobs

| | Skeleton store | Payload store |
|---|---|---|
| Contents | numbers and enums | prompt, chunks, response |
| Sampling | **never** — it is the cost ledger | ~5%, biased to rare outcomes |
| Retention | 400 days | 30 days hot, then gone |
| Shape | columnar, partition by day, sort by tenant | objects, partition by **tenant + day** |
| Deletion | tombstone the tenant id | **drop partitions** |
| Risk if lost | a billing gap you cannot reconstruct | one week of debugging convenience |

Partitioning the payload store by tenant *and* day on day one is what turns an erasure request
from a delete-by-predicate over 30 days of objects into dropping a handful of partitions. It
costs nothing to decide early and is close to unfixable late.

## 4. Cardinality is the scaling lever

500 tenants × 8 models × 4 features × 8 error classes = 128k series per metric name; twenty
metric names is **2.5M active series**. Fix it by destination, not by dropping the dimension:
bounded labels (model × feature × error_class = **256 series**) in the TSDB, per-tenant numbers
as **rows** in an hourly rollup (~12k/day), everything else answered ad hoc against the columnar
store. You lose per-tenant second-resolution alerting and nothing else.

## 5. Fairness in the sample

A flat 2% sample is unfair in both directions, and both directions hurt.

- **Small tenants vanish.** A tenant doing 50 calls/day contributes one trace, and zero most
  days. Give every tenant a **floor**: keep `min(all, max(20/day, 2%))`. At 500 tenants the
  floor costs at most 10k payloads/day, roughly doubling the random budget — cheap for the
  guarantee that no tenant is invisible when they raise a ticket.
- **Whales eat the budget.** A tenant at 40% of traffic takes 40% of the random slice. Cap each
  tenant's share of the payload budget.

Both changes make the sample rate **per stratum**, so the re-weighting must use the per-tenant
`1/p`, not a global one. Get that wrong and your fairness fix silently re-introduces the bias it
was meant to remove.

## 6. What breaks, in order

1. **Storage cost and PII exposure** — one cause, one lever (split, sample, redact at write).
   First because it is the only item here that can cost you a contract.
2. **Metrics cardinality** — 2.5M series. Second because it arrives a month later as an invoice
   rather than an alert, so it is always found late.
3. **Exporter backpressure onto the request path** — third because it is rare but total: it
   takes the product down, not the dashboards.
4. **Trace-store query latency** — 240M rows and a dashboard doing full scans. Fourth because it
   degrades gradually and partitioning buys you out of it.
5. **Sampling bias** — no error, no alert, you simply believe a false number. Fifth because it
   fails with no signal at all.
6. **Clock skew and orphan spans** — last because it is annoying rather than dangerous, but it
   ends with people not opening the tool.

## 7. Degradation — and it differs per signal

| Signal | Under pressure | Why that order |
|---|---|---|
| Metrics | **never dropped** | tiny, and they are what pages you — including `spans_dropped` |
| Skeleton | buffer to disk, replay, drop **last** | it is the cost ledger; a gap is a billing gap |
| Payload | cut the sample rate adaptively, drop **first** | expensive, sensitive, least urgent |
| LLM judge | allowed to lag hours or a day | offline by design |
| Dashboards | serve stale rollups | better a stale number than a query storm mid-incident |

The rule underneath the table: **observability degrades before the application does, and it
tells you it did.** A silent drop is worse than no telemetry, because you go on trusting the
graph.

## 8. Observability of the observability

Meta-health, all of it alertable: **trace completeness** (percentage of requests with a whole
trace — anything under 100% is a named blind spot), **tenant attribution** (under 100% means the
cost report is wrong), exporter queue depth and `spans_dropped` by priority,
`redaction_failed` rate, rollup lag, and count of spans with negative duration or a child
starting before its parent. Plus a **representativeness check in CI**: the sampled slice's
distribution over model, feature and tenant must match the population within sampling error.

**Leading indicators for the product this platform watches** — every one of them moves before
the error rate does: fallback rate · escalation-to-large-model rate · parse-failure rate ·
refusal rate · retrieval top-score p50 falling · cache hit rate falling · groundedness on the
unbiased slice. Alert on those. Error rate and p99 are lagging indicators; by the time they
move, someone has already opened a ticket.
