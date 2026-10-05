# Metrics discipline — surviving "how did you measure that?"

**The rule: for every number, know what it measured, how you measured it, and what it
didn't measure.** Three sentences. If you can't produce all three, take the number off
your resume — an unjustified metric is worse than no metric, because it invites a
takedown and calls your other claims into question.

## Your numbers, audited

| Number | Verifiable from code? | Risk |
|---|---|---|
| `17` cross-tenant probes | **Yes** — count them in `isolation.test.ts` | none, own it |
| `five` providers metered | **Yes** — `usageRoutes.ts` + rate card | none |
| `185 of 185` references resolve | **Yes** — re-run the CSR harness | none |
| `0.002` F1 noise floor | **Yes** — three runs, same index | none |
| `2,169`-line routes file | **Yes** — `wc -l server/routes.ts` | none |
| `25,000+` dealerships | Not on this machine, but a platform fact | low |
| `37+` migrations | Not on this machine | low |
| `45%` latency cut | **No repo** | **HIGH** |
| `85%` sync time cut | **No repo** | **HIGH** |
| `68.9 → 79.1` F1, `96.67%` recall | **No repo** | **MEDIUM** |

## The two high-risk numbers — pick a lane before your next interview

### `45%` latency cut

**Option A — keep it, and answer like this:**

> *"Median, on the main reporting endpoints, measured application-side before and after on
> the same query set. I didn't capture p95, which in hindsight is the number that would
> have mattered more — averages hide tail latency."*

That is a complete, honest answer: scope, method, and the limitation volunteered. Most
interviewers stop there because you've already said the thing they were going to catch you
with.

**Option B — downgrade the claim:**

> "cut reporting-endpoint latency materially through composite indexing and query-plan
> analysis"

No number, nothing to attack, and the mechanism still lands.

**Never do this:** invent p95, invent a load test, or say "about 45%, I don't remember how."
The last one is worse than either option above.

### `85%` sync time cut

Same structure. Method: nightly job wall-clock before vs after parallelising the S3 pulls.
Limitation: one workload, one night, not a benchmark.

## The follow-ups every metric attracts

1. **"Of what — median, p95, p99?"** Have a specific answer. Vagueness here reads as fabrication.
2. **"Measured how?"** Application timing, DB slow-query log, load test — say which.
3. **"Under what load?"** If you don't know, say "comparable but uncontrolled."
4. **"What did it cost?"** Every optimisation trades something. Indexes cost writes. Caching costs consistency. Batching costs latency.
5. **"Would it still hold at 10×?"** Usually no, and saying so is the senior answer.

## Numbers you should add because they're free and verifiable

- **94 test files** in ResumeFlow, **23** in digital-twin. Testing discipline, countable.
- **327 of 733 commits, largest of 8 contributors** — `git shortlog -sne --all`. Use in
  conversation, not on the page.
- **Four suites** in `isolation.test.ts`: users, personas, conversations, RAG.

## The one-line discipline

> *"I'd rather give you the method than a number I can't defend."*

Say this and mean it. It ends the line of questioning in your favour every time.
