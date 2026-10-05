# AI-06 — the metrics cross-examination

## META
- difficulty: brutal
- time: 12 min
- tags: metrics, honesty, measurement, risk
- source: `AI-metrics-discipline.md`

> **Do this one first.** It's the least enjoyable and the most likely to cost you an offer.
> Two of your numbers have no repository behind them.

## PROMPT

> "Let's go through the numbers on your resume one at a time. For each: what did it measure,
> how did you measure it, and what did it *not* measure?"

## CLARIFY

There are no clarifying questions here. That's the point — you either have the three
sentences or you don't.

## STEP 1 — The verifiable ones (warm-up)

State what/how/didn't for: `17 probes` · `five providers` · `185 of 185` · `0.002 F1` · `2,169 lines`

### CHECKPOINTS
- **17** — count of probes in `isolation.test.ts`; cross-product of 4 surfaces × 4 access shapes; **doesn't** prove isolation, only that known surfaces regress loudly
- **five providers** — countable in the usage ledger and rate card; **doesn't** include infra cost
- **185/185** — references resolving to really-indexed chunks; re-runnable from the repo; **doesn't** prove the chunk supports the claim
- **0.002** — F1 spread across three runs of one model on a shared index; **doesn't** generalise to other metrics
- **2,169** — `wc -l server/routes.ts`; a complexity signal, not a quality one
- Says "re-runnable / countable" for each — that's the whole strength of this group

## STEP 2 — `45%` latency cut

### CHECKPOINTS
- **What**: median, on the main reporting endpoints
- **How**: application-side timing, before and after, same query set
- **Didn't**: no p95, not a controlled load test → **directional**
- **Volunteers the limitation before being asked**
- Knows the mechanism even without the query: `EXPLAIN` showed sequential scans; composite index with equality/most-selective columns first, range and ORDER BY last
- Knows the cost: indexes slow writes; those tables are read-heavy so it was acceptable
- **Does not** invent a p95, a load test, or a specific endpoint they can't name

## STEP 3 — `85%` sync time cut

### CHECKPOINTS
- **What**: nightly job wall-clock
- **How**: before vs after parallelising the S3 pulls with multiprocessing
- **Didn't**: one workload, one night, not a benchmark
- Can defend the design choice: processes not threads because per-file work included CPU-bound parse/transform (GIL); **concedes** threads or async would suffice for fetch-only

## STEP 4 — The PII numbers

### CHECKPOINTS
- `68.9% → 79.1%` F1 from **interval-logic reconciliation with no new model** (false positives 37 → 18)
- `85% → 96.67%` recall after adding the LLM extractor, at 76.3% precision
- **What it didn't measure**: 15 synthetic documents, 60 labels, **no held-out split** → directional, enough to rank interventions against each other
- Leads with the *reasoning*: **recall over F1 deliberately**, because a false negative is an unrecoverable leak and over-redaction is only noise

## STEP 5 — The decision

For `45%` and `85%`, pick a lane and commit.

### CHECKPOINTS
- **Option A** — keep them, answer exactly as scripted above (scope + method + volunteered limitation)
- **Option B** — downgrade to *"cut reporting-endpoint latency materially through composite indexing and query-plan analysis"* — no number, nothing to attack
- Recognises **Option C is fatal**: "about 45%, I don't remember how" — worse than either
- Has actually decided **before** the interview, not during

## STEP 6 — The closing line

### CHECKPOINTS
- Can say, and mean: *"I'd rather give you the method than a number I can't defend."*
- Understands why this **ends** the line of questioning in their favour
- Knows the free verifiable numbers available instead: **94 test files** (ResumeFlow), **23** (digital-twin), **327 of 733 commits, largest of 8**

## TRAP

Any vague metric. "Roughly 45%, I think on the dashboard endpoints, I don't remember exactly
how we measured it" reads as **fabricated** even when it's honest — and it retroactively
casts doubt on every other number you gave. **An unjustified number is worse than no number.**
