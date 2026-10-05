# Cost governance at 500 tenants — the scaled view

## 1. Numbers first

| Input | Value |
|---|---|
| Tenants | 500 |
| LLM calls/day | 600k → **7 QPS** average, ~70 peak |
| Mean cost per call | $0.004 blended · $0.006 frontier · $0.00027 mid |
| Platform spend | **$2,400/day · ~$72k/month · $100/hour** |
| Ledger rows | 600k × ~5 line items = **3M/day**, 35 writes/s avg, 350/s peak, 1.1B/year |
| Spend skew | top 10 tenants ≈ 40% of spend; largest ≈ 40× the median |
| Worst plausible runaway | 10 calls/s on the frontier model = **$216/hour from one tenant** |

**Little's Law, applied to money rather than threads.** 70 peak QPS × 2s service time = **140
calls in flight**, and every one of them is holding a reservation that has not yet been
reconciled against an actual cost. So the *precision* of a hard cap is not a property of your
accounting, it is:

```
overshoot  =  calls in flight  ×  worst-case cost per call
           =  140 × $0.063  =  $8.82   platform-wide, at any instant
```

Per tenant it is the useful version: cap a tenant at 20 concurrent calls and its budget can
only ever be overshot by 20 × $0.063 = **$1.26**. Which means **a concurrency cap is a
cost-precision lever, not only a fairness one** — not the usual reason people give for having
one, and worth saying out loud.

**The second derivation, and the one the whole design hangs off:**

```
detection_window  ≤  tolerated_excess / (runaway_rate − baseline_rate)
                  =  $50 / ($216 − $4 per hour)  =  14 minutes
```

**What that forces:** 5-minute buckets confirmed over two windows fits with margin; an hourly
rollup does not; a daily job misses by two orders of magnitude. You pick the alerting window
from a money budget, not from a dashboard default.

## 2. Topology

```
                      ┌──── live reservation counters (Redis, per tenant/hour) ────┐
                      │                          ▲            │                    │
call ─► admission ─► estimate worst case ─► budget gate ─► gateway ─► provider      │
        (tag or            (prompt +          soft/hard        │                    │
         refuse)           max_tokens)        tiers)           ▼                    │
                                                          commit actual ────────────┘
                                                               │
                                                    usage ledger (append-only, async)
                                                               │
                            ┌──────────────────────────────────┤
                            ▼                                  ▼
              5-min buckets (48h) ─► hourly (30d) ─► daily (13m) ─► monthly (kept)
                            │                                  │
                     burn-rate detector                 showback / chargeback
                     (3x own baseline AND               (one rate card, versioned)
                      >$10/hour excess)
```

## 3. Scaling levers, and what each costs

| Lever | Effect | The cost of pulling it |
|---|---|---|
| Reservation as one atomic Redis op | cap enforced in the request path | ~1ms on every call; must be a Lua check-and-increment, never read-then-write |
| High-resolution buckets for **big tenants only** | 34k rows/day instead of 576k | the long tail gets no burn alert — its monthly cap is its protection |
| Tighter `max_tokens` per feature | shrinks the worst-case reservation, so the cap gets more precise | truncated outputs if set below real demand |
| Tenant concurrency cap | bounds overshoot, bounds blast radius | a legitimate burst queues |
| Batch API for staleness-tolerant work | ~50% off | hours of latency, so only for nightly work |

## 4. Fairness at 500 tenants

Per-tenant **reservation counters**, per-tenant **concurrency caps**, and async queues drained
**weighted by remaining budget rather than by depth** — a tenant near its cap drains last, so a
runaway cannot starve 499 well-behaved ones while it burns itself out. Same containment
argument as per-tenant ingest queues in scenario 3: a tenant's own bad day degrades that tenant.

## 5. Self-hosted breaks the rate card

Self-hosted inference costs $/GPU-hour, not $/token, so per-call cost is an **amortisation, not
a measurement** — and idle capacity has to be charged to somebody. Two defensible rules: charge
reserved capacity to whoever reserved it and on-demand at a marginal rate, or amortise the hour
across the calls it actually served and accept that a quiet hour looks expensive. Say which one
you picked and why; the wrong answer is pretending a GPU-hour is a token price.

## What breaks, in order

1. **Detection latency** — the invoice is monthly, the runaway is hourly. The only entry here
   measured in six figures; everything below costs accuracy, this one costs $212/hour.
2. **Attribution completeness** — you cannot detect per-tenant what you never tagged, and the
   untagged slice is disproportionately background jobs and retries, which is what loops.
3. **Rollup lag vs enforcement** — a gate reading minutes-old aggregates over-permits by
   construction. Hence the live counter, reconciled by the rollup rather than replaced by it.
4. **Estimate accuracy** — capping a cost you do not yet know. Too optimistic leaks 11×; too
   pessimistic refuses legitimate traffic.
5. **Rate-card drift** — hand-maintained against providers who change prices; ledger and
   invoice diverge and nobody can say which is right.
6. **Alert fatigue** — 500 × 4 = 2,000 thresholds. Static limits get muted, and the real one is
   missed inside the noise.
7. **Cost of the cost system** — 3M rows/day, 1.1B/year. Keep raw rows to 30 days and it stays
   comfortably under 1% of the $72k it is watching; skip retention and it will not.

## Degradation, and it differs per feature

| Feature | At the soft ceiling | At the hard cap |
|---|---|---|
| RAG chat | mid model, top-3 chunks instead of top-8 | extractive retrieval-only answer with citations |
| Voice persona | shorter system prompt, cheaper voice | text channel only — **never cut a live call** |
| Bulk extraction | queue it, drain at a fixed rate | refuse and say so; a wrong extraction beats no extraction only in a demo |
| Nightly reports | move to the batch API | skip the run, alert the owner |
| Agent runs | halve the step budget | refuse new runs, let in-flight ones finish |

And the rule that spans all of them: **the budget is checked at admission, never mid-stream.**
A half-generated response costs you the tokens *and* delivers nothing.

## Degradation of the governance system itself

**Fail open on the soft ceiling, closed on the contractual hard cap.** A missed soft ceiling
costs recoverable money; refusing 500 tenants because Redis blinked is an outage you built. But
a prepaid tenant contracted to a hard cap must be refused, because letting them through is a
commercial promise you cannot unmake. Same reasoning as failing open on rate limiting and
closed on tenant scope — the test is which error is irreversible, not a house preference.

## Observability

**Leading indicators**, all of which move before total spend does:

- **$ per unit of work** — per conversation, per document, per resolved ticket. A quiet week
  hides a 40% more expensive prompt in the daily total; the unit cost does not.
- **tokens per call, p50 and p95** — moves the instant a prompt or a retriever config changes.
- **attribution completeness %** — anything under 100 is the shape of your blind spot.
- **reservation-to-actual ratio** — if estimates drift, cap precision drifts with them.
- **fallback rate and retry rate** — a fallback to a pricier provider is a cost event, not only
  an availability one.
- **cache hit rate falling** — spend rises with a lag of about a day.
- **share of spend on the frontier model** — the router drifting expensive.
- **breaker trip count per tenant** — rising trips mean your budgets are wrong, not your tenants.

**Lagging, and useless alone:** total daily spend, and the invoice.
