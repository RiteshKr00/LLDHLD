# Cost control that catches it on the day

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Normal | 240k calls/day at £0.0021 | ~£504/day |
| Cache 78% → 5% | 4.3x the bill | identical user traffic |
| Agent, no step budget | mean +20%, worst 50x | the tail is the damage |
| Rate-of-change alert | fires hour 2 | |
| 80%-of-budget alert | fires hour 20 | or never, on a quiet month |

## 2. The telemetry

Compute cost **at request time** from your own token counts. Do not wait for the provider's
billing export — it is a day behind, and this problem operates hourly.

Every call is tagged at the gateway with tenant, feature, model, and whether it was a cache hit,
a retry, or a fallback. Those four tags are what make a spike attributable in minutes.

Track **volume and cost-per-call as separate series**. The alert should already tell you which
half of the problem you are in.

## 3. The alerts

| Alert | Condition |
|---|---|
| Spend rate | this hour > 2x trailing mean, per tenant and per feature |
| Cost per call | > 1.5x trailing mean, any model |
| Cache hit rate | absolute drop of 10 points, or below a floor |
| Retry ratio | retries / calls above baseline |
| Fallback ratio | share of traffic on the secondary provider |
| Agent steps | p99.9 steps-per-run, not the mean |

All derivative-based except the cache floor. Derivative alerts need no per-tenant threshold
maintenance and do not go stale as traffic grows.

## 4. The breakers

**Per-run**: step budget and cost cap on every agent. A run that hits either stops and reports,
rather than continuing to a hard cap hundreds of calls later.

**Per-tenant**: a daily budget that **degrades** — cheaper model, smaller context, cache-only —
before it refuses. Crossing a budget should be a quality event the team notices that day.

**Global**: a gateway-level rate limit that can be dropped to 1.5x normal in one config change.
This is the mitigation you reach for before you know the cause.

## 5. The runbook

1. **Divide spend by calls.** Volume or cost-per-call. Thirty seconds.
2. **Slice by tenant, feature, model.** A spike is rarely uniform; if it is, suspect pricing or routing.
3. **Sharp edge or ramp?** Sharp is config or routing. A ramp is a loop or growing retries.
4. **Cap first, diagnose second.** Rate-limit at 1.5x normal; the meter stops while you work.
5. Then the specific checks: cache hit rate, retry ratio, fallback ratio, mean prompt tokens,
   mean completion tokens, steps-per-run tail.

## 6. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Detection latency | Hourly cost telemetry; alert on the derivative |
| 2 | Attribution | Tag every call at the gateway |
| 3 | Cache visibility | Hit rate as a first-class alert |
| 4 | Agent tails | Per-run step and cost caps with a breaker |
| 5 | Budget enforcement | A breaker that degrades, not a monthly report |
