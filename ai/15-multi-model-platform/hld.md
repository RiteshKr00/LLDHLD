# The multi-model platform at scale

> `11-multi-model-architecture/hld.md` covers the scaled topology from the topic side. This is
> the routing, quota and lifecycle shape.

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Per-minute limit | 6,000 | 30% headroom at peak — green all day |
| Daily limit | 2,000,000 | the day wants 3.05M, 1.5x |
| Cap blows at | 15:36 | 504 minutes of the day left |
| Cascade at 10% escalation | 96% saving | £420 vs £10,000 per million calls |
| Cascade at 90% escalation | 15% saving | plus an extra call on every request |
| Blind fallback | 3 of 4 features break | all returning 200 |

## 2. The request path

1. **Gateway** — one schema, per-provider adapters behind it.
2. **Capability registry** — tools, context, structured output, streaming, per model. Consulted
   before routing, not after a failure.
3. **Router** — cascade cheapest-capable first; escalate on failure or low confidence.
4. **Shared token bucket** (Redis, atomic) — per-second *and* per-day, per provider.
5. **Circuit breaker**, per provider, per model.
6. **Fallback chain, resolved per feature** — including "refuse" as a rung.
7. **Validate on receipt** — schema, types, enums, invariants.
8. **Usage ledger** — tokens and cost attributed to tenant, feature and model.

Steps 2 and 4 are the ones a component list omits, and they are the first and fourth things to
break.

## 3. Quota accounting

Track both windows. The per-second bucket protects the provider from your burst; the **daily**
counter protects your afternoon. Alert on projected daily exhaustion — current burn rate against
remaining quota — rather than on the breach, because the breach is not actionable.

Ten instances mean the bucket must be shared and atomic. A local limiter configured with the full
rate admits ten times it, and the provider enforces the difference as 429s.

## 4. The cascade

Cheapest **capable** model first — capability, not price, decides eligibility. Escalate on:
a transport failure, a schema-validation failure, or a low self-reported confidence where the
task supports one.

Instrument the **escalation rate per feature** and alert on it. It drifts with prompt changes,
corpus changes and traffic mix, and it is the number that decides whether the cascade is saving
anything.

## 5. Model lifecycle

| Event | Response |
|---|---|
| New model available | Registry entry, per-feature eval, shadow, then consider |
| Provider version string changes | Alert. Pin, then re-run the per-feature suite |
| Behaviour changes with no version change | Caught by a scheduled canary eval, not by a deploy gate |
| Deprecation announced | Migration project: pin, evaluate candidate, shadow, cut over per feature |

The scheduled canary eval — the same fifty prompts, daily, scored — is the only control that
catches a silent update. It is cheap and it is routinely absent.

## 6. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Daily rate limits | Shared daily counter; alert on projected exhaustion |
| 2 | Tail latency | Per-provider breakers; retries on transport errors only |
| 3 | Cost | Alert on escalation rate per feature |
| 4 | Provider outage | Capability-checked fallback, per feature |
| 5 | Deprecation | Version pins, per-feature eval suites, scheduled canary |

## 7. Observability

Per **model** and per **feature**, separately — an aggregate hides the one pairing that is
broken. Escalation rate per feature. Quota burn against both windows, with projected exhaustion.
Schema-validation failure rate by model, which is the registry going stale. Breaker state
transitions. Cost per feature per model from the ledger, not from the provider's invoice, which
is a day behind.

The one chart worth a wall: **projected daily quota exhaustion time, per provider.** It should
read "never", and the day it starts reading 17:00 you have a fortnight to act.
