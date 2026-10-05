# Evaluation & the noise floor — explained

**Your code:** `CSR-Exp/csr/eval/` — `__init__.py` (+248/−0), `metrics.py` (+234/−0),
`tests/test_eval.py` (+160/−0), `eval/gold_facts.yaml` (+47/−0). All greenfield, all yours.

**Say your boundary first:** the 8-stage pipeline skeleton is a colleague's; the grounding,
evaluation and inference-backend layers are yours.

---

## Why the harness is LLM-free — and why that's the interesting choice

An LLM-judged evaluation is **itself non-deterministic**. Run it twice on identical input and
the score moves. That means you cannot distinguish a **regression** from **judge variance** —
which destroys the entire purpose of a release gate.

So the harness recomputes five metrics purely from the pipeline's on-disk artifacts: **no
model, no network.** Same inputs → same score, every time, forever.

**It imports the production grounding module directly**, rather than reimplementing the
grounding rule. That's the detail to lead with: reimplemented scoring logic is how scorecards
start lying — the metric drifts from the runtime and nobody notices until the number is
meaningless.

**Where LLM-as-judge does belong:** as a *supplementary signal* for subjective quality, on
sampled traffic, never as the gate. Say that — it shows you're not dismissing the technique,
you're placing it correctly.

---

## Gates declared as data, not assertions

Thresholds live in config with hard/soft flags, so a gate can **block a release** rather than
print a warning nobody reads. And the reported result is honest:

```
structural conformance      100%          PASS
references resolving        185/185       PASS
grounding rate               58%  (gate 85%)   FAIL
number support             96.8%  (gate 98%)   FAIL
```

**Two failing gates, published rather than retuned.** The instinct to lower the threshold
until it goes green is the thing this design exists to prevent. A green board with no ground
truth is worth less than a red one with it.

---

## The bug: a hard gate that failed open

This is your best story. Three failures compounding:

1. **Gold facts keyed to the wrong study id** → headline-fact accuracy returned `n/a`
2. **`n/a` counted as a pass** → the gate went green
3. → **a regressed enrollment figure shipped** under the verdict *"all hard gates pass"*

**The rule you wrote down:** *a hard gate with no ground truth must FAIL or BLOCK, never pass.*

**The generalisable lesson, and this is what an interviewer is buying:** the bug was
**collapsing three states into two.** A gate has *pass / fail / no-data*. If you model it as a
boolean, "no data" has to become one of the other two — and defaulting it to pass makes every
un-evaluable gate silently green.

Same shape as fail-closed in the multi-tenancy topic: **when the answer is unknown, the safe
default is the restrictive one.** Being able to connect those two is a strong signal.

---

## The noise floor — the senior move most candidates skip

Before comparing four models, you re-ran **one** model three times against a shared index:

```
numeric F1:  0.675 / 0.677 / 0.677   → spread 0.002
```

**Anything smaller than 0.002 is not a result.** Without that number you'd read a 1%
difference as a finding and reorganise a sprint around noise.

The general principle: **establish variance under a null change before attributing a delta to
your intervention.** It's the same instinct as a control group.

---

## The bake-off, and why a negative result is a good result

Four local models, holding retrieval, prompts and embeddings constant by re-running only
`generate → cite → assemble` against an already-indexed corpus. **The generation model was the
sole variable** — that's what makes it controlled rather than a vibe check.

**Finding:** all four landed within about a point of composite score, while the
retrieval-and-grounding scaffold moved quality far more.

**Why that's valuable:** it redirected effort from model selection to retrieval. A negative
result that reallocates a team's attention is worth more than a positive one that confirms a
prior. Interviewers at this band are specifically listening for someone who has produced one.

---

## The five metrics, and why those five

Each covers a distinct failure mode:

| Metric | Catches |
|---|---|
| structural conformance | wrong document shape |
| reference resolution | invented citations |
| numeric support | unsupported numbers |
| section coverage | missing sections |
| per-section content similarity | wrong content in the right place |

**And the metric you had to fix first:** content similarity was originally computed
draft-vs-the-entire-536-page-reference, which drove cosine to **0.087** — noise. Scoring
**per matching section** made it meaningful. *A metric that can't distinguish candidates isn't
measuring quality* — that's the line.

---

## The follow-ups, answered

**"`185 of 185` — what does it prove?"**
Every reference in the draft resolves to a chunk that was really indexed and retrieved. So:
**no fabricated citations.** It does **not** prove the cited chunk supports the claim — that's
the separate number-support metric, sitting at 96.8% against a 98% gate. Being precise about
what a green metric *doesn't* cover is the answer.

**"What made you check a passing test?"**
The result was too clean for a system I knew had rough edges. **A green suite is a claim, not
a fact.**

**"How do you prevent the `n/a`-as-pass class of bug?"**
Make the tri-state explicit in the type, so "no data" can't be coerced into a boolean, and
make no-data blocking for any hard gate.

---

## One-line summary

> "The harness is deterministic and LLM-free so a score change means a real change, gates are
> data so they can block, and I established the noise floor before comparing anything —
> which is how I knew the four-model spread was noise and retrieval was the real lever."

## The trap answer to avoid

Quoting your metrics without their limitations. The strength of this whole story is that you
know exactly what each number does and doesn't cover — throwing "185/185" out as a headline
undersells it.
