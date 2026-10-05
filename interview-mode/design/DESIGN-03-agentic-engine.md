# DESIGN-03 — agentic workflow engine that can't loop or overspend

## META
- difficulty: hard
- time: 20 min
- tags: architecture, agents, state-machine, budgets, tools, safety
- source: `AI-design-scenarios.md` #4

## PROMPT

> "Design an engine that runs multi-step LLM agents in production. It must never loop forever,
> never blow a cost budget, and never take a destructive action it shouldn't. Go."

## CLARIFY

- **"How many steps typically?"**
  → *"5-15, occasionally 50."*
- **"Do tools have side effects?"**
  → *"Yes — some write to customer records."*
- **"Human in the loop available?"**
  → *"For low-confidence cases, yes."*
- **"Is partial progress useful?"**
  → *"Yes, and a run may take minutes."*

## STEP 1 — Clarify and scope

### CHECKPOINTS
- Establishes side-effecting tools exist -> **idempotency becomes mandatory**, not optional
- Establishes partial progress matters -> **checkpointing** is in scope
- Establishes human escalation is available -> low-confidence path has somewhere to go

## STEP 2 — Numbers

### CHECKPOINTS
- 8 calls/run average x 10k runs/day = **80k LLM calls/day**
- **Names the core insight: an agent's cost is its step count, and step count is unbounded by default**
- Notes the tail: a 50-step run is 6x the average, so the *distribution* matters more than the mean
- Long-running runs -> concurrency is bounded by **slots held**, not QPS

## STEP 3 — Architecture

### CHECKPOINTS
- **Typed state machine** with explicit nodes and edges — control flow in code, not in the prompt
- **Max-step budget** per run
- **Per-run token/cost cap with a breaker**
- **Loop/repeat detection** — same state seen N times (catches semantic loops the step cap catches too late)
- **Timeouts per step and per run**
- **Checkpointing** after each node -> crash resume, no lost work
- **Critic/verify node with the authority to terminate**
- **Human escalation queue** on low confidence
- **Least-privilege tools** + **idempotency keys** on side-effecting calls
- **Structured tool-call validation** before execution — never execute an unvalidated model-chosen action

## STEP 4 — What breaks first

### CHECKPOINTS
- **Cost** first — an unbounded loop is a bill, not a crash
- Then **tool side effects**: a retried non-idempotent write duplicates a customer record
- Then **slot exhaustion**: long runs holding worker slots starve new runs
- Then **prompt injection** reaching a destructive tool
- Mitigation for each named

## STEP 5 — Safety and degradation

### CHECKPOINTS
- **Control flow belongs in code; the model gets judgement, your code gets the budget**
- Cites the pattern: a decision table in code that the model may only push toward the *safer* side *(the PII filter's strictness ladder)*
- Degradation: on budget breach, **checkpoint and escalate to a human** rather than silently truncating
- Destructive tools behind an explicit confirmation or a dry-run mode
- Injection defence: separate instructions from data, filter tool inputs, scope tool credentials per tenant

## STEP 6 — Observability and evaluation

### CHECKPOINTS
- Per run: step count **distribution** (not average), cost, terminal state, escalation reason
- **Leading indicators:** rising average step count, rising escalation rate, repeat-state detections
- Trajectory evaluation, not just final-answer scoring — a right answer via a wrong path is a latent bug
- Golden set of runs with expected terminal states, gated in CI
- Replay from checkpoints for debugging

## TRAP

Relying on the prompt to say "don't loop, don't spend too much." Prompts are advisory; budgets
must be **enforced in code**. Any answer where the safety mechanism lives inside the model's
instructions has missed the question.
