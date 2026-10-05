# The four agent patterns — explained

**Source material:** `Scrap/Agents_Interview_Prep/02_CORE_PATTERNS.md`,
`03_TOOL_USE_DEEP_DIVE.md`. Your own instance: the PII filter's 5-node graph with a verify
node that escalates.

---

## The question that picks the pattern

> **Are the steps known in advance?**

- **Yes** → it's a **pipeline**. Don't use an agent. This is the answer more often than
  candidates admit, and saying it first is a strong signal.
- **No, and the model must decide** → now pick from the four below.

---

## Pattern 1 — ReAct (Reason + Act)

**Shape:** think → act → observe → think → … until done.

```
Thought: I need the user's plan tier.
Action:  get_user(id=42)
Observation: {"tier": "free"}
Thought: Free tier can't export. I should explain the limit.
Answer:  Exports are a paid feature...
```

**Fits:** open-ended tasks where the next step genuinely depends on what you just learned —
debugging, research, exploratory Q&A over tools.

**Breaks:** it's the **most expensive shape** — one model call per step, and the whole
conversation is resent each time, so **cost grows quadratically with step count**. It also
wanders: with no plan, nothing stops it re-treading ground.

**Senior cue:** *"ReAct is the default people reach for and usually the wrong one. If I can
enumerate the steps, a pipeline is cheaper, faster and testable."*

---

## Pattern 2 — Plan-and-Execute

**Shape:** plan once → execute each step (often in parallel) → optionally replan.

**Why it's often better than ReAct:**

| | ReAct | Plan-and-execute |
|---|---|---|
| Model calls | one per step | one plan + one per step |
| Parallelism | none — sequential by construction | steps can fan out |
| Predictability | wanders | you can *see the plan* before spending |
| Cost | grows with history resent | bounded, and inspectable up front |

**The underrated benefit:** the plan is an **artifact you can validate, log and show a human
before executing.** That's how you get approval gates and auditability.

**Breaks:** when the plan is wrong and there's no replan step, it executes confidently into a
wall. And it can't adapt mid-flight to a surprise.

**Senior cue:** *"I'd rather spend one call on a plan I can inspect than N calls discovering
the plan implicitly."*

---

## Pattern 3 — Reflection (self-critique)

**Shape:** generate → critique → revise → (repeat, bounded).

**Fits:** when there is a **verifiable signal** to reflect against — tests that run, a schema
that validates, a linter, a numeric check. Reflection over a *checkable* artifact genuinely
improves it.

**Breaks — and this is the important half:** with no external signal, the critic is the same
model that produced the output, so it mostly **agrees with itself**. You pay 2–3× the tokens
for a rewording. Self-critique without ground truth is theatre.

**How to make it work:** give the critic something the generator didn't have —
the source data, test results, a validator's output. **Your two-layer hallucination defence is
exactly this**: the deterministic validator is the external signal, and the maker-checker only
sees what survived it.

**Senior cue:** *"Reflection only pays when the critic has information the generator lacked.
Otherwise it's the same model marking its own homework."*

---

## Pattern 4 — Multi-agent (orchestrator + workers)

**Shape:** a coordinator decomposes and delegates to specialised agents.

**Why people reach for it:** it maps to how human teams work, and specialised prompts do beat
one giant prompt asked to do everything.

**Why it usually doesn't pay off:** every agent boundary is a **serialisation boundary** —
context has to be summarised to cross it, and summarising loses information. You pay more
tokens, more latency, and more failure modes for a modest gain.

**The failure mode nobody mentions, and this is the one to volunteer:**

> Independent agents over a shared corpus each retrieve *a* defensible answer, but **nothing
> enforces that they answered about the same subject.** In the 16-agent CSR platform, the
> narrative agents described the adult trial while the table agents used the adolescent
> cohort — so the report contradicted itself. Each section was individually correct and the
> document was wrong.

**The fix:** a **pinned-facts contract** (the shared entities every agent must use) or a
**consistency gate** after fan-out. Fan-out without one produces confidently inconsistent
output.

**When it actually fits:** genuinely independent subtasks with a wide fan-out where
specialisation is real — 16 regulatory sections, or a review where you want *different lenses*
rather than redundant reviewers.

**Senior cue:** *"Perspective diversity beats redundancy. Three reviewers with three different
lenses find defect classes three copies of one reviewer never will — which is also why a
fan-out needs a consistency gate on top."*

---

## Tool use — the part that spans all four

The model **never executes anything.** It emits a *request*; your runtime validates and runs
it. Everything about tool safety follows from that separation:

- **validate the call before executing** — schema, allowed values, tenant scope
- **idempotency key** on anything with side effects, because retries happen
- **least privilege** per tool, scoped to the caller's tenant
- **the docstring is the spec** — a vague tool description is why the model picks the wrong
  tool
- **dry-run** for destructive operations

---

## Choosing, in one table

| Situation | Pattern |
|---|---|
| Steps known | **not an agent** — pipeline |
| Steps unknown, adaptive, few tools | ReAct |
| Steps discoverable up front, want parallelism and an inspectable plan | Plan-and-execute |
| Output is checkable against a real signal | Reflection (bounded) |
| Wide fan-out over genuinely independent subtasks | Multi-agent **+ consistency gate** |

---

## The follow-ups, answered

**"How do you stop any of them looping forever?"**
Max-step budget, per-run cost cap with a breaker, repeat-state detection, per-step timeouts, a
critic that can terminate. **All in code.** A prompt instruction is advisory.

**"Where does control flow live?"**
In code. The model contributes *judgement* — which branch looks right — but the graph, the
budget and the termination conditions are yours. Any design where safety lives in the system
prompt has missed the point.

**"When is the answer 'don't use an agent'?"**
Whenever you can enumerate the steps. Agents buy flexibility and cost determinism,
debuggability and money. Only pay that when the flexibility is genuinely required.

---

## One-line summary

> "Pick by whether the steps are known. If they are, it's a pipeline. If not: ReAct for
> adaptive exploration, plan-and-execute when you want an inspectable plan and parallelism,
> reflection only when there's an external signal to critique against, and multi-agent only
> for wide independent fan-out — with a consistency gate, because independent agents over one
> corpus will contradict each other."

## The trap answer to avoid

Listing the patterns without saying when each is wrong. Every one of these has a failure mode,
and naming it is what distinguishes someone who has shipped an agent from someone who has read
about them.
