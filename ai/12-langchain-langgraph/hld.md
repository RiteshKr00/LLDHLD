# LangGraph in production — the scaled view

## 1. What changes when a graph goes from demo to production

A graph on a laptop is a function call. A graph in production is a **long-lived, resumable,
budgeted, observable workflow** — and that is four separate problems.

| Concern | Demo | Production |
|---|---|---|
| State | in memory | checkpointed to Postgres/Redis, keyed by thread id |
| Failure | crash, rerun | resume from the last checkpoint |
| Cost | ignored | per-run token/cost cap with a breaker |
| Latency | whatever | per-step and per-run timeouts |
| Observability | printed output | per-node traces, step distribution, terminal-state counts |
| Concurrency | one run | N runs holding worker slots |

## 2. Numbers first

10k runs/day, average 8 LLM calls per run, ~4s each:

- **80k LLM calls/day** ≈ 1 QPS average, design for 10 QPS peak
- a run is ~32s of model time → **runs are long-lived**, so concurrency is bounded by
  **slots held**, not by QPS
- Little's Law: 10 runs/sec arrival × 32s = **320 concurrent runs in flight** at peak
- the tail matters more than the mean: a 50-step run is 6× the average, so **step-count
  distribution** is the number to watch, not the average

## 3. Where a graph actually runs

**Not in the request.** A graph run is minutes; an HTTP request is seconds. So:

```
API (accepts, returns a run id, 202) -> queue -> graph workers -> checkpointer
                                                       |
                                              SSE/poll for progress
```

The client polls or subscribes for progress; `stream_mode="updates"` is exactly the shape of
an SSE progress feed. **This is the same async decision as topic 01** — the caller isn't
waiting, so it doesn't belong in the request.

## 4. Checkpointing choices

| Backend | When |
|---|---|
| in-memory | tests only. Lost on restart |
| SQLite | single worker, dev, or a desktop app |
| **Postgres** | the default for production — durable, queryable, survives deploys |
| Redis | fast, but treat it as a cache unless persistence is configured |

**Thread id design matters:** it's the resume key and the isolation boundary. Scope it per
`(tenant, conversation)` — a global counter means one tenant can resume another's run, which
is the multi-tenancy failure from topic 03 wearing different clothes.

## 5. Budgets — enforced in code, not the prompt

Layered, cheapest check first:

1. **max steps** per run (framework `recursion_limit` is the backstop, not the policy)
2. **token/cost cap** per run, with a breaker that checkpoints and escalates
3. **repeat-state detection** — same state seen N times catches semantic loops the step cap
   catches too late
4. **per-step and per-run timeouts** — a hung tool call otherwise holds a slot forever

On breach: **checkpoint and escalate to a human**, don't silently truncate. A truncated agent
run that looks complete is worse than one that visibly stopped.

## 6. Tool calls are the dangerous part

Side-effecting tools need what any distributed write needs:

- **idempotency key per call** — a retried tool call must not double-write
- **least privilege, tenant-scoped credentials** — the graph is one prompt-injection away from
  the tool's permissions
- **validate the tool call before executing** — the model *requests*, your code *decides*
- **dry-run mode** for destructive operations

## 7. Observability specific to graphs

Per **node**, not per run: latency, error rate, retry count, and how often each conditional
edge is taken. Then per run: step count distribution, terminal state, cost, escalation reason.

**Leading indicators:** average step count creeping up · escalation rate rising ·
repeat-state detections · a conditional edge that suddenly always goes the same way (that
usually means the router's input changed shape).

## 8. Testing at this level

- **Node tests**: plain functions, dict in, dict out. No framework.
- **Graph tests**: the fake-model seam — real `BaseChatModel` subclass, so routing is tested
  deterministically with no network.
- **Golden runs**: fixed inputs with expected terminal states, gated in CI.
- **Trajectory evaluation**: not just "was the answer right" but "did it take a sensible path".
  A right answer via a wrong path is a latent bug.
- **Checkpoint replay** for debugging a production incident — resume the exact state.
