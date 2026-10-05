# Design scenario 15: guardrails and content safety layer

## The prompt

> "Your persona assistant speaks as a real executive. Design the layer that stops it saying
> something reputationally damaging."

*The interviewer is not asking for a moderation API call. They are asking whether you know
that a system prompt is not an enforcement point, and whether you can price a false positive.*

---

## Clarifying questions to ask FIRST

1. **Which risk actually matters — offensive content, legal/financial claims, competitor
   comment, or leaking internal info?** *(Four different mechanisms. Three of them are a
   lawyer's list and a regex; only one needs a classifier.)*
2. **Is the output spoken or read?** *(Voice removes the retract option and puts every check
   inside a streaming budget. A chat bubble can be replaced before anyone reads it.)*
3. **Is a human review path acceptable, and at what daily volume?** *(A few thousand items a
   day is not a review queue, it is a department. Decides whether "escalate" is real at all.)*
4. **On an uncertain output — block, deflect, or escalate?** *(Decides whether a false positive
   is an outage or a slightly dull answer. This is the whole product risk.)*
5. **Who owns the policy — legal, comms, or engineering?** *(Decides whether a threshold change
   is a config push or a change-control process with sign-off.)*
6. **What is the escape budget?** *(There is no "never". Make someone name the number, because
   the design that gets you to 60 escapes a day and the one that gets you to 6 are different
   systems at different cost.)*

---

## The follow-up bank

1. Your classifier blocks 8% of legitimate answers. Fix it *without* lowering recall.
2. Where do the guardrails live — prompt, gateway, or application layer? Defend it.
3. It streams to TTS. How do you check output you have already spoken?
4. A user gets the persona to say the banned thing by asking in Hindi. Now what?
5. The safety classifier is down. What does the product do — and is that the same answer for
   voice and for chat?
6. Prove to legal what the persona said on 14 March at 09:12, and why the system allowed it.
7. Contrast this with a PII redaction gateway. Why is the precision/recall trade the opposite way?
8. How do you ship a threshold change without silently regressing containment?
9. It says something damaging anyway. Walk me through the first thirty minutes.

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
