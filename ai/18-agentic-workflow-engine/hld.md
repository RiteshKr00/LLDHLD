# The agentic engine at scale

## 1. Numbers first

| Input | Value |
|---|---|
| Runs/day | 10k |
| Steps per run | 8 mean · 5–15 typical · **50 at the tail (5% of runs)** |
| LLM calls/day | **80k** |
| Wall clock per step | ~5.6s (model call + tool round trip) |
| Median run | ~45s · tail run ~280s |
| Arrival | 0.116 runs/s average, **1.16/s at a 10× peak** |
| Cost | $0.09 median run · $1.84 tail run · **~$900/day, ~$27k/month** |

**Little's Law:** 1.16 runs/s × 45s = **~52 concurrent runs** at peak. And because a running run
holds exactly one in-flight provider call, 52 runs is also 52 concurrent provider calls — the
slot count and the provider concurrency limit are the *same* number, which is convenient and
easy to forget.

**What it forces:** the engine is **slot-bound, not CPU-bound and not QPS-bound**. Work out the
tail's share: 5% of arrivals × 280s = **16 slots, ~31% of the pool, held by 5% of traffic**. So
capacity planning is a question about the *distribution* of step counts, and any drift in mean
step count is a capacity event before it is a cost event.

## 2. Topology

```
submit ──► Run API (202 + run id) ──► run registry (state, budget, cursor)
                                            │
                admission control ──────────┤   per-tenant concurrency cap
                                            ▼
                     ┌── slot pool: SHORT runs ──┐        ┌── slot pool: LONG runs ──┐
                     └───────────┬───────────────┘        └────────────┬─────────────┘
                                 └──────────► step executor ◄──────────┘
                                                   │
              pre-flight guards ── steps · projected cost · repeat-state · clock
                                                   │
                       LLM gateway (topic 16) ── tool broker ── tools
                                                   │
                    checkpoint store  ◄── after EVERY node ──►  run ledger
                                                   │
                         done  ·  halted (resumable)  ·  suspended for a human
```

## 3. What scales how

| Component | Scaling | Why |
|---|---|---|
| Run API | horizontal, stateless | accepts and returns; never holds a run |
| Step executor | horizontal, **workers hold slots** | the real capacity unit; two pools as a bulkhead |
| Run registry | one row per run, updated per step | 80k small updates/day — fine, but it is the source of truth for budget, so the read must be cheap |
| Checkpoint store | **blob, keyed by run + step** | writes 80k/day; the growth problem, see below |
| Guards | in-process, pure functions | they must not add a network hop to every step |
| Human queue | bounded, with an SLA | reviewer throughput is a hard capacity ceiling |
| Ledger | append-only, async | never in the step's critical path |

**Two slot pools, split by expected run length.** One pool means a burst of 50-step runs starves
every 6-step run behind them — the same bulkhead argument as the dedicated Celery queue for LLM
work on the dealership platform, applied to run duration rather than task type.

## 4. Multi-tenant fairness

At any tenant count above one, this is the operational problem:

- **per-tenant concurrent-run cap** (e.g. 10 of the 52 slots) — one tenant's 500-run backfill
  cannot own the pool
- **weighted fair dequeue**, not FIFO — FIFO means the backfill is served in submission order
  and everybody else waits behind it
- **per-tenant daily budget** with a breaker, because the per-run cap stops one runaway and does
  nothing at all about a thousand small ones
- **tool credentials resolved per tenant at the broker** — fail closed, exactly as the voice
  persona product resolves tenant scope

## 5. What breaks, in order

1. **Cost.** Quadratic in steps, silent, and nothing pages you. First because it is the only
   failure with no error signal at all.
2. **Slot exhaustion.** A 20% rise in mean step count is a 20% rise in slot residency, which is
   a queue, which is an outage for new runs. Second because it is the fastest-moving.
3. **Non-idempotent tool writes.** The moment retry or redelivery exists (`acks_late` plus a
   visibility timeout will do it for you), one logical action happens twice.
4. **Checkpoint growth.** 80k checkpoints/day at ~20KB is ~1.6 GB/day. Store deltas plus a blob
   pointer, and set retention on day one — 30 days of resumable history, then trajectory
   summaries only.
5. **The human review queue.** Escalation rate × review time is a throughput, and if it exceeds
   reviewer capacity the "safe" path becomes the outage. Cap the queue and degrade explicitly.
6. **Ledger cardinality.** Per-step rows tagged by run, tenant, workflow, node and terminal state
   will overwhelm a metrics backend long before they overwhelm a database.

## 6. Degradation — and it differs per workflow

| Workflow | On a budget halt or a failed critic |
|---|---|
| Research / summarisation agent | return **partial findings**, plus what was and was not covered. Genuinely useful |
| Extraction agent | **fail loudly.** A partial extraction presented as complete is worse than none |
| Customer-action agent (writes) | halt **before** the write, escalate. Never a half-applied side effect |
| Interactive copilot | drop to **single-shot RAG with citations** — no tool loop, still answers |

Naming a *different* degradation per workflow is what separates this from "add a try/except".
Note also that the cheap degradation for the copilot is a whole product, not a fallback — which
is the argument for building the non-agentic path first.

## 7. Observability

Per **workflow** and per **tenant**, never aggregate: **step-count distribution** (p50/p95, never
the mean alone), terminal-state mix, cost per *successful* run, slot residency, queue wait,
escalation rate and reason, repeat-state detections per 1k runs, per-step timeout rate.

**Leading indicators — they all move before the error rate does:**
mean step count creeping up · repeat-state detections rising · escalation rate rising ·
halted-to-done ratio rising · slot residency p95 rising.

**One alert that should never fire:** terminal state `context_overflow`. It means every guard
above it was absent or misconfigured, and you found out from the provider.

And evaluate the **trajectory**, not just the answer: a golden set of runs with expected terminal
states and expected tool sequences, gated in CI, with the noise floor measured first — otherwise
run-to-run variance reads as a regression and you will chase it for a week.
