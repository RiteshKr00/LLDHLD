# HLD — Optimum Steps (fast revision)

The ordered walk for any HLD interview. At each step, pull the applicable methods from
`HLD-method-bank.md`. Keep it minimal — every component must earn its place.

## The 9-step spine (~45 min)

| # | Step | ~Time | Must produce |
|---|---|---|---|
| 1 | **Requirements** | 5m | Functional · Non-functional · Constraints · Assumptions · **out-of-scope** |
| 2 | **Capacity estimate** | 5m | write QPS, read QPS (ratio!), storage, cache size → *these drive everything* |
| 3 | **API** | 3m | endpoints; mark idempotent writes; sync vs async |
| 4 | **Data model + DB choice** | 5m | schema (PK from access pattern) + *why this DB* |
| 5 | **High-level architecture** | 8m | draw boxes; trace **one read** + **one write** path |
| 6 | **Deep dive on the crux** | 8m | the 1–2 hard parts (ID gen, hot key, consistency…) |
| 7 | **Scale it** | 6m | cache → replicas → shard → multi-region; show the evolution |
| 8 | **Reliability & failure** | 3m | for each component: "what if it dies?" |
| 9 | **Wrap** | 2m | bottlenecks, tradeoffs, monitoring, DR, cost — rapid-fire |

## The reasoning pattern (say it this way every time)

```
Business requirement → traffic pattern → identify bottleneck
     → choose simplest solution → explain tradeoff
     → describe failure handling → how it evolves at 10×
```

## DB scaling mental flow (never jump to the end)

```
Vertical → Read Replicas → Partitioning → Sharding → Multi-Region
```
Start simple. Show the design *evolves with scale* — that's the Senior signal.

## One-page checklist (tick before you finish)

✓ Functional & Non-functional reqs ✓ Capacity estimate ✓ API ✓ DB choice + schema
✓ Architecture + request flow ✓ Component responsibilities ✓ Caching ✓ Scaling
✓ Reliability ✓ Availability ✓ Security ✓ Monitoring ✓ DR ✓ Tradeoffs ✓ Bottlenecks ✓ Cost

## Golden rules

- **The estimate drives the design** — reason from numbers to boxes.
- **Junior explains how it works; Senior explains why they rejected the alternatives.**
- **Never fail the core path** (e.g. redirect) for non-core work (e.g. analytics).
- **Don't optimize for 1B users on day 1.** Simplest thing that meets the numbers.

> Deeper menus for any step live in `HLD-method-bank.md`. A fully worked example is `01-url-shortener/hld.md`.
