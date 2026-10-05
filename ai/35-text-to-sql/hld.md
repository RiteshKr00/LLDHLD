# Text-to-SQL at scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Schema | 12,000 columns | 168k tokens — does not fit |
| Retrieved per query | ~6 tables | 3,360 tokens, 2.6% of the window |
| Fan-out error observed | +30% | no error raised |
| Unfiltered scan | 4 TB, ~£20 | one question |
| Same scan, partition pruned | 8 GB, £0.04 | 500x |

## 2. Topology

**Offline.** Schema embeddings, refreshed on every migration. Metric store, owned by analytics
engineering, not by this team. A library of verified exemplar queries. A regression suite of
question-to-expected-number pairs.

**Request path.** Retrieve schema → resolve metrics → generate SQL → **parse to an AST** →
validate → `EXPLAIN` → execute under the user's credentials → return with SQL, row count,
metric definition and freshness.

**Never in the request path.** A privileged connection. Any write grant. An unparsed string
reaching the database.

## 3. The metric store is the product

It is not a component of this feature so much as the thing that makes the feature possible.
Named metrics with owners, documented definitions, and — critically — **the joins encapsulated**,
so the model selects a metric rather than writing the arithmetic that computes it. That single
property removes the fan-out class of bug rather than detecting it.

If the organisation has no metric store, say plainly that building one is the first phase, and
that a text-to-SQL feature shipped without one will produce inconsistent numbers and lose trust
within a quarter.

## 4. Defence in depth for writes

Four layers, listed in order of how much I would rely on them:

1. **Read-only connection**, enforced by the database. Holds even if everything above fails.
2. **No write grant** on the user's role.
3. **AST validation** rejecting DML, DDL and stacked statements.
4. Prompt instructions saying read-only.

Note that the layer I wrote and tested myself is third. Layer 4 is worth almost nothing on its
own and is included only because it cheaply raises the base rate.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Silently wrong joins | Metric store owns the joins; show SQL and row count; CI regression suite |
| 2 | Metric ambiguity | Named metrics with owners; ask when ambiguous |
| 3 | Cost | EXPLAIN gate, injected LIMIT, per-user daily cap, separate reservation |
| 4 | Trust | One wrong number ends it — hence provenance on every answer |
| 5 | Schema drift | Re-embed on migration; version the cache key |

## 6. Observability

Query success rate, and separately the **refusal reasons** broken down by cause — a rise in
"unknown column" is a *retrieval* quality alert, not a validation statistic. Bytes scanned per
query and per user per day. Cache hit rate by schema version. Time from question to answer, p50
and p99. The CI regression suite's pass rate over time.

The metric worth reviewing weekly with a human: **questions where the user re-asked immediately
after seeing the SQL.** That is the closest available signal for "the number looked wrong", and
it is the failure this whole design exists to prevent.
