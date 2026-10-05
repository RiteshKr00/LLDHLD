# The platform, in practice

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Teams | 10 | |
| Duplicated build | ~530 engineer-weeks | 53 per team |
| Built once | ~106 engineer-weeks | 2x, platform quality is harder |
| DIY integration | ~8 weeks | the bar the paved road must beat |
| Target onboarding | < 1 week | ideally an afternoon |
| Spend concentration | 2 teams = 61% | invisible without attribution |

## 2. What to build, in order

1. **Gateway** — per-team keys, cost attribution, model registry enforcement, rate limits.
2. **SDK** — timeouts, retries with jitter, streaming, tracing. Thin, and opinionated.
3. **Cost dashboards and budgets**, with a degrading breaker.
4. **Eval harness as a service** — the highest-value component, and the one nobody builds alone.
5. **PII and guardrail middleware**, shared.
6. **Prompt and config registry** with versioning and canary.

Not first: a prompt-management UI, a routing optimiser, an internal model. Those are what
platform teams enjoy building and they do not move adoption.

## 3. The adoption strategy

Make the paved road **faster than DIY on day one**, then measure that as the primary metric.

- API-compatible with what teams already use, so migration is a base-URL and key change.
- A template repo: nothing to a traced, cached, budgeted call in an afternoon.
- Pre-decided model, provider account, retry policy, security review.
- Migrate the two most-in-pain teams **yourself**, publish the numbers, let the rest follow.

Migration by demonstration is slower to start and much faster to finish than migration by policy.

## 4. The escape hatch

Documented, available, mildly inconvenient, and **time-boxed**. Exempt teams lose cost
attribution, the shared eval harness and tracing — which are the things they want.

Treat the review queue as the roadmap. A capability requested three times should just be built.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Adoption | Measure time-to-first-call; fix the road, not the policy |
| 2 | Platform team velocity | Ten customers; say no publicly and consistently |
| 3 | Cost ownership | Attribution + budget + degrading breaker, all three |
| 4 | Registry staleness | Days-long approval path with published criteria |
| 5 | Escape-hatch creep | Expiry dates; review queue as roadmap |

## 6. Observability

**Adoption**: share of production LLM traffic through the gateway, with an estimate of what is
not. **Time-to-first-successful-call** for a new team — the leading indicator.

Then the outcome measures. Number of teams with an eval gate at all: this is the platform's real
product and the number to show leadership. Cost per team, trending, with budget-breaker events.
p50 and p99 gateway overhead, published, because "the gateway is slow" is the standard objection
and you want the answer to be a chart. Incidents attributable to a shared component, which is the
price of centralising and should be visibly low.

Not tracked: SDK lines of code, features shipped by the platform team.
