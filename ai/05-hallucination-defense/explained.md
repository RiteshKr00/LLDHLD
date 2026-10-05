# Hallucination control — explained

**Your code:** the Dealership AI Insights validator chain (no repo on this machine), and the
directly analogous CSR implementation in `CSR-Exp/csr/generate/grounding.py` — **study the
CSR one**, it's yours and it's on disk.

---

## The three distinct things people conflate

| | What it does | Where it runs |
|---|---|---|
| **Grounding** | supply the facts, so the model doesn't need to invent | *before* generation |
| **Validation** | check the output's shape and numbers mechanically | after, deterministic |
| **Verification** | judge whether the output is *right in context* | after, model-based |

They are three layers, not three names for one thing. Defining them separately is half the
answer.

---

## Why deterministic first — three reasons

1. **Cost.** The validator is free; the LLM check costs tokens on every call.
2. **Infallibility.** Code can't hallucinate. A schema check has no false confidence.
3. **Ordering economics.** If the LLM check ran first and passed something the validator then
   rejected, you paid for a judgement that was overruled by a regex.

**The rule: filter with the cheap infallible layer, then spend the model on what survives.**

---

## What each layer actually catches

**Layer 1 — deterministic validator.** Everything mechanically checkable:
- schema conformance — missing fields, wrong types
- **numeric grounding** — does every number in the prose appear in the source rows?
- range sanity — a percentage over 100, a negative count
- forbidden content — the LLM meta-labels that leaked into ResumeFlow resumes

**Layer 2 — maker-checker LLM.** What code can't judge:
- *"Sales grew strongly"* when the figure is +0.4%. Schema-valid, numerically grounded, and
  **misleading**. Code has no opinion on "strongly"; a model does.
- tone and audience violations
- internally contradictory statements that are individually true

That contrast — **"strongly" vs +0.4%** — is the single best example to give. It makes the
layering obviously necessary rather than belt-and-braces.

---

## The numeric-grounding detail worth stealing from CSR

From your own CSR work, the sharpest version of layer 1:

> A sentence whose salient numbers are supported by **none** of the chunks it cites is
> dropped before assembly. Number extraction **strips citation tags first** and bounds
> matches by non-alphanumerics, so digits inside an identifier like `BNT162b2` — or inside a
> chunk id — cannot falsely "support" a fabrication. Bare integers under 100 are exempted on
> purpose, with a test asserting the exemption.

Every clause there is a real defensive decision. If asked "how do you check a number is
grounded?", that's the answer — and the `BNT162b2` detail proves you actually hit the
false-positive problem rather than reading about it.

---

## The follow-ups, answered

**"How do you stop the checker rubber-stamping?"**
Three things: give it the **source data**, not just the output; ask it to **justify a verdict**
rather than emit a boolean; and **don't show it the maker's reasoning**, which otherwise
anchors it. The honest long-term answer is that you *measure* it — hold out a set of known-bad
outputs and check the catch rate. Which brings us to the gap.

**"Have you measured the catch rate?"**
No — and that's the real weakness, so volunteer it:
> *"I know the layers catch different classes of error because I can construct examples of
> each. I never quantified the LLM checker's catch rate on a labelled set, so its value is
> argued rather than measured. On CSR-Exp I did build that harness, and that's the discipline
> I'd bring back."*

**"Isn't this just two chances to be wrong?"**
No, because they fail **independently and in different directions**. The validator has no
false confidence — it either matches or it doesn't. The checker can be wrong, but only on the
subset the validator already passed. Errors compound when layers share a failure mode; these
don't.

**"Schema in the prompt, or provider-enforced?"**
Provider-side constrained decoding where available, because prompt-only compliance drifts
across model versions. **Either way, validate on receipt** — never trust the model to have
honoured its own contract. That last sentence is the one to say.

**"Grounding vs validation?"**
Grounding is preventative — supply the facts. Validation is detective — check what came back.
You need both: grounding alone still lets the model embellish, validation alone means you're
rejecting a lot of generations you could have prevented.

---

## One-line summary

> "Deterministic first because it's free and can't hallucinate; the LLM layer second for the
> semantic problems code can't judge — like 'grew strongly' on a 0.4% change."

## The trap answer to avoid

Saying it "eliminates hallucination." It **reduces frequency and bounds the damage.** Claiming
elimination is the fastest way to look naive about LLMs, and the follow-up will be brutal.
