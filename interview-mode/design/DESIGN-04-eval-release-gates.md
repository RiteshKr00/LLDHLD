# DESIGN-04 — eval and release gates for LLM features

## META
- difficulty: hard
- time: 18 min
- tags: architecture, evaluation, ci, gates, canary, config-safety
- source: `AI-design-scenarios.md` #8, `06-evaluation-noise-floor/`

## PROMPT

> "Your team ships prompt and model changes weekly. Design the system that stops a quality
> regression reaching production."

## CLARIFY

- **"Are prompts versioned in the repo or edited in a UI?"**
  → *"A UI today. That's part of the problem."*
- **"Who can change a production model?"**
  → *"Any engineer, via config."*
- **"Do you have a golden set?"**
  → *"No. You're designing that too."*
- **"Is there a human review step?"**
  → *"Not currently."*

## STEP 1 — Name the real problem

### CHECKPOINTS
- **States the insight up front: prompts and models are config, so they bypass code review entirely**
- The most frequent change in an LLM system is the least reviewed
- A quality regression is invisible to latency and error-rate monitoring — the two things already alerted on
- So this is a **change-management** problem as much as an evaluation problem

## STEP 2 — The golden set

### CHECKPOINTS
- Per **task**, not one global set — chat, summarisation, extraction fail differently
- Versioned **in the repo**, so a change to the benchmark is itself reviewable
- Sourced from **sampled real production traffic**, not invented examples
- Includes **known-bad** cases, not just happy paths
- Names the decay problem: **golden-set rot** — it stops representing traffic, so refresh it on a schedule
- Notes the honest limit: no held-out split means numbers are directional *(your own CSR caveat)*

## STEP 3 — The metrics

### CHECKPOINTS
- **Deterministic where possible** — recomputed from artifacts, no model, no network
- Why: an LLM judge is non-deterministic, so you cannot separate a regression from **judge variance**
- **Import the production module** into the harness, so scorecard semantics can't drift from runtime
- Metrics chosen per failure mode: structural conformance, citation resolution, numeric support, coverage, per-section similarity
- **LLM-as-judge as a supplementary signal on sampled traffic — never the gate**

## STEP 4 — The gate

### CHECKPOINTS
- Thresholds declared as **data** with hard/soft flags, not assertions buried in test code
- **Tri-state: pass / fail / no-data — and no-data BLOCKS**
- Explains why with the concrete bug: gold facts keyed to the wrong id returned `n/a`, `n/a` counted as a pass, and a regressed figure shipped under "all hard gates pass"
- **Generalises it: the bug was collapsing three states into two**
- Connects it to fail-closed: when the answer is unknown, the safe default is restrictive
- **Noise floor established first** — re-run one config N times; anything smaller than the spread is not a result

## STEP 5 — Rollout

### CHECKPOINTS
- Offline gate -> **canary behind a flag** -> guardrail metrics -> full rollout
- One-config-change rollback
- Guardrail metrics online: refusal rate, escalation rate, parse-failure rate, sampled groundedness, user-edit rate
- Recognises **offline-good/online-bad** is a real failure mode, hence the canary
- Prompt changes get the **same** pipeline as model changes — that's the point

## STEP 6 — Making config reviewable

### CHECKPOINTS
- Move prompts **into the repo** (or make the UI write a reviewed, versioned artifact)
- Every prompt/model change gets a diff, a reviewer, and a gate run
- Audit trail: who changed which prompt when, and what the gate said
- The A/B harness as the human-judgement layer *(your dual-prompt system)* — and the honest framing: it's a **controlled comparison**, not a statistically significant A/B test

## TRAP

Designing the metrics and forgetting the **change-management** half. A perfect eval harness
nobody is required to run before flipping a config changes nothing. The gate has to be
**unavoidable**, which means prompts and models must flow through a reviewed, versioned path.
