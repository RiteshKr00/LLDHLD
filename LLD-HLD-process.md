# How to Solve — LLD vs HLD (side by side)

The two processes, one page. **LLD reasons _requirements → classes_. HLD reasons _numbers → boxes_.**
Both start from requirements; connect them at the end with the LLD ↔ HLD mapping.

| # | **LLD** — design the classes | **HLD** — design the system at scale |
|---|---|---|
| 1 | **Clarify & scope** — functional + non-functional; say what's **out of scope** | **Requirements** — functional + non-functional + constraints + assumptions |
| 2 | **Find entities** — underline nouns → classes; verbs → methods | **Capacity estimate** — write/read QPS (ratio!), storage, cache size *(drives everything)* |
| 3 | **Relationships & APIs** — write method **signatures before bodies** | **API design** — endpoints; mark idempotent writes; sync vs async |
| 4 | **Apply SOLID / patterns** — only where a real pain shows up (no pattern-dumping) | **Data model + DB choice** — schema (PK from access pattern) + *why this DB* |
| 5 | **Edge cases, concurrency, extensibility** — "two threads?", "add feature X later?" | **High-level architecture** — draw boxes; trace one **read** + one **write** path |
| 6 | — | **Deep dive on the crux** — the 1–2 hard parts (ID gen, hot key, consistency) |
| 7 | — | **Scale it** — vertical → replicas → partition → shard → multi-region |
| 8 | — | **Reliability & failure** — for each component: "what if it dies?" |
| 9 | — | **Wrap** — bottlenecks, tradeoffs, monitoring, DR, cost (rapid-fire) |

## Reasoning pattern (say it out loud, every time)

| LLD | HLD |
|---|---|
| requirement → noun → responsibility (SRP) → pattern *only if a pain demands it* → edge cases | business req → traffic pattern → bottleneck → simplest fix → tradeoff → failure → 10× |

## Golden rules

- **LLD:** signatures are the design; a pattern must earn its place (YAGNI); each class = one reason to change.
- **HLD:** the estimate drives the design; start simple, show it *evolves* with scale; never optimize for 1B users on day 1.
- **Both:** junior explains *how it works*; senior explains *why they rejected the alternatives*.

## Connect the two rounds

The highest-signal move is the **LLD ↔ HLD mapping**: an interface/method in the LLD *is* a component/primitive
at scale (e.g. a `save_if_absent` repository method **is** a DB unique constraint / `PutItem(attribute_not_exists)`).
See `01-url-shortener/hld.md` for a worked mapping.

## Where the depth lives

- LLD framework, SOLID, patterns → `README.md`
- HLD **flow** → `HLD-revision.md` · **menu** → `HLD-method-bank.md` · **depth** → `HLD-reference.md`
