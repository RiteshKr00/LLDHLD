# Agent memory, context and runtime — explained

**Source material:** `Scrap/Agents_Interview_Prep/05_PRODUCTION_CONCERNS.md`,
`06_EVALS_FOR_AGENTS.md`, `Scrap/AI coding Agents Architecture/module_04_memory_systems.md`
and `module_05_context_engineering.md`.

---

## The gap between a demo and production, in one sentence

A demo agent is a function call. A production agent is a **long-lived, resumable, budgeted,
observable workflow** — and those are four separate systems you have to build.

---

## 1. Context engineering — the skill that replaced prompt engineering

**Prompt engineering** is wording. **Context engineering** is deciding *what goes in the
window at all*, given a hard token budget and a model that attends unevenly.

Three facts that drive every decision:

- The window is a **hard cap**, and overflow either errors or **silently truncates** — the
  silent case is the dangerous one, because grounding disappears with no error
- Models attend most reliably to the **start and end** — the "lost in the middle" problem. So
  critical instructions and the best-matching chunks go at the **edges**, never buried
- **Every token costs money**, so context is a cost lever, not just a quality one

**The budget, allocated explicitly:**

```
[system + guardrails]  fixed, small, always present
[retrieved context]    the tunable part - chunk count x chunk size
[recent history]       verbatim, last N turns
[summary]              compressed older history
[current input]        never truncate this
```

**The insight worth saying:** *"Retrieval precision is a cost lever. Better retrieval means
fewer chunks for the same answer quality — so improving retrieval reduces the bill."* Most
candidates treat quality and cost as a trade-off; here they move together.

---

## 2. Memory — three tiers, not one bucket

Naively resending the whole conversation makes cost grow **quadratically** with length: turn
50 resends 49 turns. The fix is tiering:

| Tier | What | When it's written |
|---|---|---|
| **Recent** | last ~10 turns, verbatim | every turn |
| **Summary** | rolling compression of older turns | on a **token threshold**, not per turn |
| **Facts** | structured, durable, queryable | when something durable is learned |

**Why facts must be structured, not prose:** "user prefers metric units" as a row is
queryable, verifiable and *deletable*. The same thing buried in a summary paragraph is none of
those.

**Retrieval per turn** by `recency × relevance` — otherwise a two-month-old preference
outranks today's correction.

**Contradiction is the hard part:** the user changed their mind and you now hold both facts.
Store with timestamps and let recency win, and expose the conflict rather than silently
picking.

**And the one people forget — deletion.** A right-to-erasure request must actually erase. If
facts were baked irreversibly into summaries, you cannot honour it. That's a design
constraint on day one, not a feature later.

---

## 3. Runtime — what makes a run survivable

**Checkpoint after every step.** Buys three things: crash resume, human-in-the-loop (stop,
wait, continue), and **replay for debugging** — resume the exact state from three steps ago
instead of guessing.

**Thread id is a security boundary**, not just a key. Scope it per `(tenant, conversation)`.
A global counter means one tenant can resume another's run.

**The partial-side-effect problem** — the question that separates candidates:

> A tool call succeeded, then the run crashed before recording it. On resume, does it run
> again?

The answer is **idempotency keys**: the tool call carries a deterministic key, so the second
attempt is a no-op that returns the first result. Without it, resume duplicates writes — and
"resume" becomes more dangerous than "restart".

**Timeouts at both levels**: per step (a hung tool holds a slot forever) and per run (an agent
that never terminates).

---

## 4. Failure and degradation

| Failure | Response |
|---|---|
| Budget exceeded | **checkpoint + escalate to a human**, never silently truncate |
| Tool unavailable | retry with backoff+jitter, then a degraded path or escalate |
| Model unavailable | fallback chain (topic 11) |
| Low confidence | human review queue — *your PII filter's verify node* |
| Injection detected | block, log, and alert. Don't try to sanitise and continue |

**The principle:** a run that stops visibly is always better than one that completes wrongly.

---

## 5. Evaluating agents — trajectory, not just answers

Final-answer scoring misses the bug class that matters: **a right answer via a wrong path**
will fail on the next input.

Measure:
- **step-count distribution** (p95, not mean)
- **tool-selection accuracy** — did it pick the right tool?
- **terminal-state mix** — completed / escalated / budget-exceeded / errored
- **cost per successful outcome**, not per run (failed runs still cost)

**Golden runs**: fixed inputs, expected terminal states, gated in CI.

---

## 6. What to alert on — leading indicators

Error rate and latency will not tell you an agent has degraded. These will:

- **average step count creeping up** — the agent is struggling before it starts failing
- **escalation rate rising**
- **repeat-state detections**
- **a conditional edge that suddenly always resolves the same way** — usually means the
  router's input changed shape
- **cost per successful outcome**, which catches "still works, costs 3× more"

---

## The follow-ups, answered

**"Context window fills up mid-run."**
Don't let it. Budget the window explicitly, summarise on a token trigger, and cap retrieved
chunk count. If it still overflows, drop the *oldest summary* first and never the current
input — and log it, because silent truncation is how grounding vanishes without an error.

**"Tool succeeded, run crashed before recording it."**
Idempotency key on the call, so resume is a no-op returning the first result. This is the
answer, and it's the difference between a resumable agent and a dangerous one.

**"How do you debug a run that went wrong three steps ago?"**
Checkpoint replay — resume the exact state at step 3 with the recorded inputs. Which requires
having stored per-step traces: the prompt, retrieved chunks, the tool call, the observation.

**"Right-to-erasure against memory?"**
Only possible if durable facts are stored **structured and separately** from prose summaries.
Delete the rows, and re-derive summaries from what remains. Design for it up front, because
retrofitting it is close to impossible.

---

## One-line summary

> "Production means four things a demo doesn't have: an explicit context budget, tiered memory
> so cost doesn't grow quadratically, a checkpointed runtime where every side-effecting tool
> call is idempotent, and trajectory-level evaluation — because a right answer via a wrong path
> is a bug you haven't hit yet."

## The trap answer to avoid

Talking about prompts. At this level the interesting problems are **context budgeting, memory
tiering, idempotency on resume, and what you alert on** — none of which are prompt problems.
