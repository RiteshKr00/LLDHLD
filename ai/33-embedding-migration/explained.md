# Zero-downtime embedding-model migration — explained

---

## 1. The numbers force the design

100M chunks. At a sustained 1,000 chunks/sec — which already assumes batching and a healthy
API — that is **28 hours of pure embedding**, before index build, before verification.

- **28 hours is the floor.** No failures, no re-runs, no index construction, no throttling.
- **Double storage** for the whole transition, and the transition is measured in weeks, not
  the 28 hours.
- **Two indexes live at once**, which is not a phase of the plan — it *is* the plan.

This is a project with a rollback plan, not a deploy. Say that in the first thirty seconds.

---

## 2. Say this before anything else: there is no in-place migration

Two independently trained embedding models produce **incomparable vector spaces**. Not
differently scaled, not rotated by some matrix you could learn — unrelated. The same document
embedded by both lands in two positions with no meaningful geometric relationship.

`solution.py §1` demonstrates it: **60 of 60** document pairs, same text through both models,
have `|cosine| < 0.35`. And a half-migrated index does not degrade gracefully — recall@5 falls
from 0.68 to 0.41, because the two halves cannot be ranked against each other at all. A
similarity computed across the boundary is noise being sorted.

That single geometric fact rules out every "re-embed chunk by chunk" plan, and everything below
is a consequence of it.

---

## 3. The layers, each named by the failure it prevents

**Dual-write, dual-index** — *prevents:* a cutover with no rollback. Build the new index
alongside the old and keep both fed with live writes. While both exist, rollback is a routing
change.

**Backfill as a resumable, checkpointed job** — *prevents:* restarting 20 hours in.
`solution.py §2`: a failure at hour 20 costs **48 hours** without checkpoints and **28 hours**
with them.

**Shadow reads** — *prevents:* discovering a regression in production. Query both, log the
comparison, serve the old one.

**Recall@k on an independently labelled set** — *prevents:* a regression shipped as an upgrade.
The labels must not come from either index; see below, because this is the part people get
subtly wrong.

**Per-tenant progressive cutover** — *prevents:* a global blast radius. The first tenant to
move should be one you can call.

**Cache keys versioned by embedding model** — *prevents:* the cache serving answers from the
previous universe. `solution.py §4`.

**Keep the old index until confidence, then delete** — *prevents:* an unrecoverable mistake.
Storage is cheap relative to re-running the backfill.

**Never mix spaces in one index** — the constraint the other seven exist to respect.

---

## 4. The labelled set is the part people get wrong

"No quality regression" is unprovable without a labelled set, and the obvious way to build one
is **circular**: take the old index's top-5 as ground truth. Do that and the old index scores
1.000 by construction, every new model looks like a regression, and the gate blocks every
upgrade forever.

The labels have to be **independent of both systems under test** — human judgements, click
data, or at minimum a lexical relevance proxy computed from the documents themselves.
`solution.py §3` uses the last of those, and both indexes then score around 0.30 with a delta
of −0.015, which is a result you can actually act on.

If the labelled set does not exist yet, building it is the **first task of the project** and it
adds weeks. Say so early, because the alternative is a migration whose success criterion is
"it seems fine".

---

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Cost and time of the backfill** | 28 hours is the floor; the realistic figure is several days with re-runs, and it is API spend nobody budgeted. |
| 2 | **The cache serving stale-space results** | The quietest failure here — hit rate stays high, so nothing looks wrong. |
| 3 | **Partial-state bugs** | One code path reads the new index, another the old. Symptom: inconsistent results for the same query. |
| 4 | **Storage** | Double, for weeks. |
| 5 | **The other consumers** | Dedup, clustering, analytics, a recommendation feature nobody mentioned. Each is its own cutover. |

---

## The follow-ups, answered

**1. Why can you not re-embed in place, chunk by chunk?**

Because during the migration the index would contain vectors from two incomparable spaces, and
a nearest-neighbour search over it is meaningless — not degraded, meaningless. The distance
between an old-space vector and a new-space vector carries no information, so ranking mixes
real similarities with noise. `solution.py §1` shows recall@5 falling from 0.68 to 0.41 on a
half-migrated index, and even that understates it, because the failure is not a smooth
degradation you could ride out. This is also why "same dimensionality" is a red herring: two
768-dimensional spaces are just as incomparable as a 768 and a 1536.

**2. The backfill dies at hour 20 of 28.**

With checkpointing, you resume from the last committed offset and lose minutes. Without it, you
start again and the job now costs 48 hours — plus you pay the embedding API twice for the same
20 hours of work. So: checkpoint the offset transactionally with the writes, make the job
idempotent per chunk so a replayed batch is harmless, and shard it so a poison document blocks
one shard rather than everything. Rate-limit against the provider quota too, because the
fastest way to discover your throughput ceiling is to be throttled at hour 12.

**3. How do you know the new model is better before serving it?**

Shadow reads against an independently labelled set. Run live queries through both indexes, serve
the old result, log both, and compare recall@k offline. Two properties matter: the traffic is
**real** rather than a synthetic query set, and the labels come from **neither index**. Slice
the comparison by tenant and by query type before you accept an aggregate — a flat average
routinely hides one segment falling off a cliff, and that segment is somebody's whole product.

**4. Your semantic cache is warm after cutover. What does the user get?**

Answers grounded in the old vector space, indefinitely, with a healthy-looking hit rate. This is
the quietest failure in the whole migration: nothing errors, latency improves, and the answers
are quietly from the previous universe. The fix is one line — put the **embedding model version
in the cache key** — and then cutover invalidates the cache automatically by making every key
miss. `solution.py §4`. Budget for the cold-cache cost spike on the day; it is real and it is
brief.

**5. One tenant's recall drops 8% after cutover.**

Roll that tenant back — which is a routing change, and free, because the old index still exists.
That is the entire reason for per-tenant progressive cutover. Then investigate before moving
anyone else: is it their corpus (domain vocabulary the new model handles worse), their query
shape (short keyword queries versus natural language), or their chunk size interacting with the
new model's context? A per-tenant regression is usually a corpus property, and the fix is often
re-chunking rather than reverting the model. If it cannot be fixed, that tenant stays on the old
index — which is an acceptable end state, and one you can only offer because you kept it.

**6. What does this cost and how long does it take?**

Embedding 100M chunks is the visible cost, and at 28 hours of continuous throughput it is
several days of wall clock with re-runs. Double storage for the transition. Then the invisible
costs, which are larger: building the labelled set if it does not exist, a week or more of
shadow running to gather enough comparison data, and a progressive cutover measured in weeks
because you want a full business cycle per cohort. Calendar time, honestly: **six to ten weeks**.
The 28-hour figure is the one people quote and it is the smallest line in the budget.

**7. Two code paths, one reading each index. What breaks?**

The same query returns different results depending on which path served it, and it is
intermittent, so it gets closed as unreproducible. Prevention: **one retrieval client**, with
index selection resolved centrally from the tenant's cutover state — never a config flag read
independently in two places. Detection: log the index version on every retrieval and alert if a
single tenant is seen hitting both within a window. And search for the paths that are easy to
forget — the batch jobs, the eval harness, the admin tools, the notebook someone runs monthly.

**8. When do you delete the old index?**

After a full business cycle on the new one with no regression, all tenants migrated, and an
explicit decision — not a cleanup ticket. Concretely: 30 days past the last tenant's cutover.
While the old index exists, every failure mode above is a routing change away from resolution;
the moment it is gone, the only remedy is another 28-hour backfill. Storage for a month is the
cheapest insurance in the project. Do snapshot it before deleting.

**9. Halfway through, the new model is deprecated too.**

First, do not panic-migrate to a third model on top of a half-finished second — that is two
concurrent migrations and the state space is unmanageable. Assess: how long until the
deprecation actually bites, and is the third model available now? If there is runway, **finish
the current migration**, then start a clean second one; the pipeline you just built makes the
second cheaper. If there is not, **abort to the old index** — which costs you the work but is
safe, because you never stopped serving from it — and go directly to the third model. The
decision is easy precisely because dual-index gave you a position you can hold. It is a good
moment to point out that this is *why* you keep the old index, rather than as a general
principle.

---

## One-line summary

Two embedding models produce incomparable vector spaces, so there is no in-place migration —
you build the new index alongside the old with a resumable checkpointed backfill, prove parity
with shadow reads against independently labelled data, cut over per tenant with the model
version in every cache key, and keep the old index until a full business cycle says you do not
need it.

---

## The trap answer to avoid

Proposing an in-place migration — re-embedding chunk by chunk and updating rows as you go. It
sounds efficient and it produces an index that cannot be searched, because half its vectors are
in a space unrelated to the other half. The second trap is subtler and shows up in otherwise
strong answers: building the labelled set **from the old index's own results**, which scores the
incumbent 1.000 by construction and turns the quality gate into a machine for rejecting every
upgrade.
