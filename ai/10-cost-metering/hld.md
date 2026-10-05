# The usage ledger at 600k calls/day

## 1. Numbers first
600k calls/day × ~5 provider line items each = **3M ledger rows/day**, ≈ **35 writes/second**
average, 350/s at peak. A year is **1.1 billion rows**.

Modest write volume, but the retention and query patterns are what actually shape the design.

## 2. The ledger must never be on the critical path
A cost write failing must **never** fail the user's request. So: write asynchronously
(queue or fire-and-forget with a local buffer), and accept that a small loss is better than a
failed request.

**And say the trade explicitly:** this is a billing-adjacent system where you have chosen
availability over completeness. If it must be exact — because you bill customers from it —
then it becomes a durable queue with at-least-once delivery and idempotent writes, which is
what your call-id key already gives you.

## 3. Write path — append-only, never update
Rows are immutable facts: `(call_id, source, units, ts, tenant, feature, model)`.
Late-arriving webhook truth is a **new row**, not an update to an old one. Cost is then
`sum(units × rate)` over the rows.

Append-only buys idempotency (dedupe on `(call_id, source)`), auditability, and no write
contention on hot rows.

## 4. Read path — pre-aggregate, don't scan
Nobody queries 1.1B raw rows. Roll up on a schedule:

```
raw rows (7-30 day retention)
   -> hourly per (tenant, feature, model)
      -> daily
         -> monthly (kept indefinitely, this is the billing record)
```

Dashboards read the rollups; the raw rows exist for **dispute resolution and debugging**, and
age out. That tiering is what keeps a cost system affordable — an observability system that
costs more than the thing it observes is a real failure mode.

## 5. Rate-card versioning — the part people miss
Prices change. A rollup computed last month must **not** change when the rate card is edited,
or your historical bills silently rewrite themselves.

So the rate card is **versioned and effective-dated**, and each row is priced with the version
in force at its timestamp. Store the resolved cost on the rollup, not just the units.

## 6. From visibility to enforcement
Metering is the prerequisite; the enforcement layer is:
- **near-real-time per-tenant spend** (from the hourly rollup plus the current buffer)
- **budget breaker** that **degrades** — cheaper model, text instead of voice — rather than
  cutting off
- **anomaly alerting on rate of change**, not absolute spend, because the invoice is monthly
  and the runaway is hourly

## 7. What breaks, in order
1. **Detection latency** — hourly problem, monthly invoice
2. **Raw-row storage** if retention isn't enforced
3. **Rollup lag** — budgets enforced on stale numbers over-permit
4. **Rate-card drift** between the ledger and the dashboard (one card fixes this)
5. **Attribution gaps** — a call with no tenant tag is unbillable and invisible; make the tag
   required at the gateway, not optional

## 8. Observability of the cost system itself
Ledger write lag · rollup freshness · **percentage of calls with complete attribution** (this
is the health metric — anything under 100% means blind spots) · webhook-vs-pull reconciliation
rate · count of calls still awaiting authoritative cost.
