# Two sources, one answer — at scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Vector top-10 vs true SUM | 7% of the answer | aggregation is structurally impossible |
| 45 min since index build | ~6,300 unseen writes | why you cannot embed rows |
| Routing 100% + retrieval 0.80 | 0.80 end-to-end | |
| Routing 80% + retrieval 0.92 | 0.79 end-to-end | routing dominates |
| Misrouted question | no partial credit | unanswerable, not degraded |

## 2. Topology

**Planner.** Classifies documents / database / both, and for "both" decomposes into sub-questions.
A small trained classifier over a few hundred labelled questions beats a prompt-only router and is
much cheaper to improve.

**Document path.** Vector RAG with a relevance floor. Returns clauses with document version and
section.

**Structured path.** Text-to-SQL with every guard from scenario 21 — schema retrieval, semantic
layer, AST validation, `EXPLAIN` cost gate, and the **user's own credentials**. Returns rows plus
the SQL and a row count.

**Synthesis.** Composes with per-source attribution, performs any arithmetic explicitly, and
detects conflicts rather than resolving them.

## 3. Caching, asymmetrically

| Source | Cache? | Key |
|---|---|---|
| Documents | yes | question + corpus version + permission set |
| Aggregates over closed periods | yes | question + period + schema version |
| Live operational state | no | show "as of HH:MM" instead |

Caching the structured side reintroduces exactly the staleness that ruled out embedding it.

## 4. Conflicts

Detect, surface, route. Never adjudicate. Log every conflict with both values and both sources —
this becomes a report on where the policy and the system of record have drifted, and it is
frequently the most valuable by-product of the whole system.

## 5. Partial failure

| Situation | Behaviour |
|---|---|
| Both available | Full answer, both attributions |
| Database down | Policy answer + "live order data unavailable" — no guess |
| Documents down | Figures + "policy text unavailable, rule not applied" |
| Both down | Refuse, and say which |

Partial failure is the normal case for a two-source system. It needs a designed answer, not a
fallback path nobody has read.

## 6. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Routing | Labelled set, trained classifier, monitor per-class accuracy |
| 2 | Synthesis on conflict | Plant conflicts in the eval set; assert they surface |
| 3 | Structured freshness | Do not cache live state; show the timestamp |
| 4 | Partial failure | Designed degraded answers per source |
| 5 | Permission asymmetry | Enforce per path; documents and rows differ |

## 7. Observability

**Router accuracy per class** — docs, db, both — never aggregate, because "both" is the class that
degrades first and is the smallest. Per-path retrieval quality, measured independently. Conflict
rate, trending, with the top conflicting fields — a rising conflict rate is a business signal.
Partial-answer rate by cause. Structured-path freshness lag. And the share of answers a user
re-asked after seeing the attribution, which is the closest available signal for "this looked
wrong".
