# Agents in production — the scaled view

## 1. The number that governs everything

**An agent's cost is its step count, and step count is unbounded by default.**

10k runs/day at 8 calls each = **80k LLM calls/day**. But the mean lies: a 50-step run is 6×
the average, so you budget for the **distribution**, not the mean. Watch p95 step count.

Little's Law with long runs: 10 runs/sec arrival × 32s service = **320 concurrent runs in
flight**. Concurrency is bounded by **slots held**, not QPS — which is different from every
request/response system you've scaled.

## 2. Where agents actually run

Never in the request. A run is minutes.

```
API (202 + run id) -> queue (per task type) -> agent workers -> checkpointer
                                                    |
                                          SSE / poll for progress
```

Same reasoning as topic 01: the caller isn't waiting.

## 3. The five budgets, layered cheapest-first

| Budget | Catches |
|---|---|
| **max steps** per run | runaway loops |
| **token/cost cap** with a breaker | one run costing a fortune |
| **repeat-state detection** | semantic loops the step cap catches too late |
| **per-step + per-run timeout** | a hung tool call holding a slot forever |
| **critic that can terminate** | confidently-wrong completion |

On breach: **checkpoint and escalate to a human.** Never silently truncate — a truncated run
that looks complete is worse than one that visibly stopped.

## 4. Tool side effects are the real risk at scale

At 80k calls/day, retries are constant. So:

- **idempotency key per tool call** — a retried write must not duplicate
- **tenant-scoped, least-privilege credentials** — the agent is one injection away from the
  tool's permissions
- **validate before executing** — allow-list, schema, scope
- **dry-run + confirmation** for destructive operations
- **an audit row per tool call**, because "what did it do?" is the first incident question

## 5. Memory at scale

Naively resending history makes cost grow **quadratically** with conversation length. Tiered
instead (topic 13 of the scenario bank):

`recent turns verbatim` → `rolling session summary (on a token trigger, not per turn)` →
`extracted structured facts, retrieved per turn by recency × relevance`

And a deletion path that genuinely deletes — facts baked irreversibly into summaries make an
erasure request impossible to honour.

## 6. Evaluating agents — different from evaluating answers

**Trajectory evaluation, not just final-answer scoring.** A right answer via a wrong path is a
latent bug that will surface on the next input.

Measure: step-count distribution · tool-selection accuracy · terminal-state mix
(completed / escalated / budget-exceeded / errored) · cost per successful outcome — not cost
per run, since failed runs still cost.

**Golden runs** with fixed inputs and expected terminal states, gated in CI. **Checkpoint
replay** for debugging a production incident by resuming exact state.

## 7. Multi-agent at scale needs a consistency gate

The fan-out failure compounds with width: 16 workers over one corpus, and the chance all 16
agreed on the subject is low. Either **pin the shared facts** before fan-out, or **gate the
assembled output** for cross-section consistency. Fan-out without one produces confidently
inconsistent documents — and each section will pass its own review.

## 8. Observability

Per **node/step**: latency, error rate, retry count, which conditional edge was taken.
Per **run**: step count, cost, terminal state, escalation reason.

**Leading indicators** — these move before anyone complains:
average step count creeping up · escalation rate rising · repeat-state detections ·
a conditional edge that suddenly always resolves the same way (usually the router's input
changed shape).

## 9. When to take the agent out again

Worth saying out loud, because it's the most senior version of this answer:

> "Once you know the steps the agent settled on, replace it with a pipeline. Agents are how
> you *discover* the workflow; they're an expensive way to *run* one you already know."
