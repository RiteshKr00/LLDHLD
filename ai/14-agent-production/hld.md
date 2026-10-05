# Agents as a platform — the multi-team view

The other topics scale one agent. This one is the question you get for a senior or lead role:
**ten product teams want to ship agents. What do you build once?**

## 1. The number that justifies a platform

Ten teams × (runtime + memory + budgets + evals + observability + secrets) =
**ten implementations, nine of them wrong.** Not because those teams are bad, but because
every item on that list has a non-obvious failure mode — idempotency on resume, quadratic
memory cost, silent context truncation, no-data eval gates.

The platform's value is the difference between one correct implementation and nine
approximations.

## 2. What belongs in the platform, and why

| Component | The failure it prevents once, centrally |
|---|---|
| **Agent runtime** (graph exec + checkpointer) | nine hand-rolled `while` loops around mutable dicts |
| **Budget enforcement** (steps, cost, timeouts) | one team's runaway loop becoming a finance incident |
| **Tool registry** with schemas + scoped credentials | a tool with more permissions than the task needs |
| **Idempotency helper** | duplicate writes on every resume, in every team |
| **Memory service** (tiered, with a deletion path) | nine memory designs, none of which can honour erasure |
| **Context assembler** with a token budget | silent truncation destroying grounding |
| **Eval harness + gates** | nine teams shipping prompt changes with no gate |
| **Trace store** (prompt, chunks, tool calls, observations) | undebuggable incidents |
| **Gateway** (from topic 11) | unattributable cost, nine key-management schemes |

## 3. The thing that decides whether it works

**Adoption.** A platform teams bypass is worse than none, because you now have a false sense
of central control.

So the first design question is not technical:

> *"Why would a team choose this over calling the API directly?"*

And the answer has to be **"because it's faster"** — a golden-path SDK where timeouts,
retries, tracing, budgets and idempotency are the *defaults*, not a checklist. Make the paved
road genuinely easier than DIY, and provide an escape hatch with a review rather than a wall,
or teams will route around you and you'll learn about it during an incident.

## 4. Governance without becoming a blocker

- **Approved tool registry** — a team can add a tool; a destructive tool needs review
- **Per-team budgets and cost showback** — the team that spends it sees it
- **Eval gate required to promote**, not to experiment. Never gate the sandbox
- **Model/prompt changes go through the same reviewed, versioned path** as code — this is the
  one that's always missing

## 5. Numbers to have ready

Ten teams, 10k runs/day each = **100k runs/day**, ~8 calls per run = **800k LLM calls/day**.
At that volume:

- **cost attribution is mandatory** — per team, per feature, per model
- run concurrency is bounded by **slots held**, so partition workers per team to prevent
  noisy-neighbour starvation
- the trace store is the biggest storage line item — **sample and redact**, because full
  prompt/response logging at 800k/day is both expensive and a data-protection liability

## 6. Observability the platform owns

Per team, per agent: run volume · step-count distribution · terminal-state mix · cost per
successful outcome · escalation rate · tool-call error rate.

And one platform-level number worth defining explicitly: **cost per successful outcome across
all teams**. It's the only figure that catches "everything still works and we're spending
three times as much", which is the failure mode of a healthy-looking AI platform.
