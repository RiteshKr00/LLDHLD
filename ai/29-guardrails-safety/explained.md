# Guardrails and content safety — explained

**Your version of this:** the multi-tenant voice/video persona product, where you are the
**Vapi custom-LLM provider** — every turn already passes through your code before it reaches
TTS, which is the only place an output guard can live. You run **fail-closed tenant scoping**
there, so you have already shipped the argument that enforcement belongs in the request path
rather than the prompt. And on the clinical generator you own **grounding and evaluation**,
which is where the cheapest guardrail in this design actually sits.

---

## 1. The numbers force the design

| | |
|---|---|
| Calls | **600k/day** ≈ 7 QPS average, ~70 peak |
| Voice share | ~40% of turns, hard **800 ms** time-to-first-audio budget |
| Raw outputs that touch a policy | **0.8%** ≈ **4,800/day** |
| Input guard budget | **≤ 20 ms** |
| Deterministic output rules | **~0.4 ms** |
| Safety classifier | **120 ms p50, 400 ms p99** |

Start with the arithmetic the interviewer is fishing for: **at 600k calls a day, a 0.01%
failure rate is 60 bad outputs a day.** So the design target is not "never". It is
**bounded, detected, and recoverable**.

Then push one step further, because that is where the design lives. To contain 98.75% of those
4,800 — which is what buys the 60/day figure — a **single classifier threshold** must sit low
enough that roughly **one in ten safe answers scores above it too**: tens of thousands of good
answers blocked per day. `solution.py` measures it on a 60,000-output sample.

**So the binding constraint is not recall. It is the false-positive bill at the recall you
need**, and every layer below pays that bill in something other than blocked answers.

---

## 2. Enforcement lives outside the model — say this before anything else

The trap answer is "I'd put *never discuss competitors* in the system prompt". That is
**advisory input to the thing you are trying to constrain** — a comment, not a policy engine.
You would not enforce your Casbin rules by asking the frontend nicely; same category error.

Three things break it, all cheap: **injection** ("ignore previous instructions"), **drift** (a
long conversation dilutes a system message from 40 turns ago), and **the model simply being
helpful** — no injection needed, ask a comparison question and it compares. `solution.py`
section 1 shows all three leaking under prompt-only enforcement and none once the same rule
runs on the output as code the model does not get a vote on.

---

## 3. The layers, each named by the failure it prevents

**1 · Input guard — *prevents:* instructions that override policy reaching the model at all.**
Injection patterns, abusive input, and the tenant/persona scope resolution you already do.
Cheap, ≤ 20 ms, and it also stops the case where someone pastes content in purely to have the
persona read it back in a recorded call.

**2 · Grounding — *prevents:* invention, which is the failure with no detector.**
A persona answering from an approved corpus — published statements, the persona brief, prior
approved answers — has far less room to freelance than one answering from weights. Same
grounding layer you own on the clinical generator, pointed at reputational risk instead of
clinical accuracy. **It is the only layer that reduces the base rate rather than catching the
consequence**, which makes it the highest-leverage item here and the one people skip because
it isn't called a guardrail.

**3 · Scope narrowing — *prevents:* having to detect a risk you could have declined.**
Decide what the persona may be *asked*, not just what it may say. A twin that answers on
product and strategy and hands financials, personnel and litigation to a fixed deflection has
removed the highest-severity classes from the detection problem entirely. Refusing a topic is
a product decision; refusing a sentence is a safety incident in progress.

**4 · Deterministic output rules — *prevents:* the enumerated classes, at zero latency and
with a citable reason.** Banned entities, forbidden claim patterns, no financial or legal
advice, no attribution of statements to named third parties. These resolve **~55% of all
containments** in ~0.4 ms.

Be precise about *why*, because the obvious answer is wrong: they are **not** a cost
optimisation — they fire on well under 1% of traffic and save almost no classifier calls. They
exist because you must be able to **prove** the block with a rule id, because they add no
latency to the voice budget, and because **they still work when the classifier is down**.

**5 · Safety classifier, banded — *prevents:* the semantic cases rules cannot express, without
turning every uncertainty into an outage.** A small model scoring the output. The design detail
that matters is that it emits **three dispositions, not two**:

| Score | Disposition | Why |
|---|---|---|
| ≥ 0.95 | hard block | high confidence; a block here is almost always right |
| deflect threshold … 0.95 | **deflect** | most of the mass, and most of the false positives |
| below | allow | untouched |

Same containment as a single threshold, by construction — the same outputs are stopped. What
changes is that the uncertain band becomes **a slightly dull answer instead of an error**.
`solution.py` measures the collapse: hard blocks drop by more than an order of magnitude at
*identical* containment.

**6 · Graceful deflection — *prevents:* a false positive being an outage.**
"I'd point you to the official statement on that" is a product. Silence, a spinner, or *"I
can't help with that"* in a live call is a defect someone reports. The deflection text belongs
in the persona brief and gets reviewed like copy, not written by an engineer in an `except`.

**7 · Sampled human review, then rule promotion — *prevents:* automating a judgement call, and
the policy freezing.** You cannot review thousands of items a day, so you review a
**stratified sample** — all tier-1 hits, a daily quota of band items, 100% of user-reported
turns — on a Celery queue like every other async job you run. Its output is **labels**, and
every labelled escape becomes a deterministic rule or a training example. A semantic case
promoted to a rule moves from "caught most of the time at a false-positive price" to "caught
every time at zero". This loop is the only thing here that makes the system better over time,
and it is what justifies the review queue's cost.

**8 · Hash-chained audit log — *prevents:* being unable to answer "what did it say?"**
Per turn: input, retrieved context, raw output, every verdict with its rule id or score, the
emitted text, persona, tenant, model version, **policy version** — chained so an entry cannot
be quietly edited later. When legal asks about 14 March at 09:12, "we log to stdout" is not an
answer.

**9 · Kill switch per persona — *prevents:* a slow incident.**
A flag read per turn, not per deploy, and scoped **per persona** — one executive twin going
wrong must not take down every other persona on the platform. And it is a ladder, not a
toggle: full persona → grounded-only → fixed deflections → off. Rehearse it, or you will
discover mid-incident that the flag is cached for five minutes.

---

## 4. The false-positive problem, priced

Here is the menu a single global threshold gives you, per day, at 600k calls (`solution.py`
prints the measured version):

| Operating point | Contained | Escapes/day | Hard blocks/day | Deflections/day |
|---|---|---|---|---|
| Paranoid | 98.75% | ~60 | ~900 | ~57,000 |
| Balanced | ~93% | ~340 | ~900 | ~7,700 |
| Permissive | ~80% | ~940 | ~900 | ~650 |

Every row is unacceptable to somebody. **You cannot reach 60 escapes a day by threshold tuning
without deflecting one turn in ten.** That is the honest finding, and stating it is the answer.

The way out is not a better threshold — it is to **stop treating all policy hits as one
population**. Tier by severity and run a different operating point per tier:

| Tier | Examples | Share of the 4,800 | Point | Escapes/day |
|---|---|---|---|---|
| **T1** unrecoverable | legal/financial claim, defamation, PII, attributed quote | 15% (720) | paranoid | **~9** |
| **T2** embarrassing | competitor comment, internal info, off-policy opinion | 35% (1,680) | balanced | ~120 |
| **T3** cosmetic | tone, over-familiarity, off-brand register | 50% (2,400) | log-only | not contained |

T1's risk surface is narrow — a few per cent of turns ever touch it — so a 10% deflection rate
*on that slice* costs a few thousand deflections a day, not fifty-seven thousand. **Tiering is
how you refuse the menu.** T3 isn't blocked at all: it's logged and fixed in the persona brief,
because blocking someone for being too chatty is a worse product than being too chatty.

The headline number changes shape as a result: **~130 escapes a day that could actually hurt
you, against ~2,400 tone wobbles you have deliberately chosen not to block.** Being willing to
say that second number out loud is the difference between a safety design and safety theatre.

---

## 5. Streaming: you cannot unspeak a sentence

The naive shape streams chunks straight to TTS and checks the output when the stream closes.
By then the damaging clause has been spoken aloud. There is no retract.

The fix is a **segment gate**: buffer to the next clause boundary — typically 8–15 tokens,
~200 ms of generation at 50 tok/s — check that segment, then emit. `solution.py` measures both:
32 unsafe characters reach TTS in the naive version, zero through the gate, and the gate costs
one segment of buffering on time-to-first-audio.

Two details that make it affordable inside an 800 ms budget:

- **rules gate the classifier per segment.** Segments that touch no risk surface emit after
  ~0.4 ms of regex. Only the ~14% that do pay the 120 ms.
- **only the first segment is on the critical path.** Every later one is checked while the
  previous is still being spoken, so the gate is free after the first clause.

Chat is easier and you should say so: stream optimistically and replace the bubble. A reader
who sees a flicker is annoyed, not screenshotted.

---

## 6. What breaks first, in order

1. **False positives.** First because it is the only failure whose *frequency rises with your
   safety effort*, and the only one users report — nobody files a ticket saying the persona was
   appropriately cautious.
2. **Deflection fatigue.** Even correct deflections, at 1% of turns, read as evasiveness in a
   live conversation. Measure deflections per *session*, not per turn.
3. **Review queue backlog**, which silently disables the review and rule-promotion layers while
   every dashboard stays green.
4. **Latency on the voice path**, then policy sprawl, then novel attack classes — a new
   language, a new phrasing, detectors fitted to last quarter's traffic. `hld.md` has the full
   ordering.

**Note the inversion against the PII gateway.** There, recall wins: a leak is unrecoverable and
a false positive costs you a redacted name. Here, precision wins for T2/T3 because
over-blocking is the product-killing failure. Same architecture, opposite tuning, and being
able to say *why* is worth more than either answer alone.

---

## The follow-ups, answered

**1 · "Your classifier blocks 8% of legitimate answers. Fix it without lowering recall."**
Bands, then tiers, then base rate. Move the mass from *block* to *deflect* — same containment,
and a deflection is a product state rather than an error. Split by severity so the paranoid
point applies only to the narrow T1 surface. Then cut the base rate upstream with grounding and
scope narrowing so there is less to score at all. Lowering the threshold is the one option I
would *not* take: it trades a visible cost for an invisible one.

**2 · "Prompt, gateway, or application?"**
Application, in the request path, at the custom-LLM boundary — the same place tenant scoping
already fails closed. The gateway is the wrong layer because the policy is per-persona and
needs the retrieved context to judge; the prompt is not a layer at all. Say plainly: **a system
prompt is advisory, and the injection that overrides it is one line long.**

**3 · "How do you check output you've already spoken?"**
You don't — you stop speaking it. Segment gate: buffer to a clause boundary, check, emit. ~200
ms once on the first segment, free after that.

**4 · "Someone gets it in Hindi."**
Concede the gap: rules are language-specific and the classifier is only as multilingual as its
training data. Short term, **narrow the scope** — answer in supported languages, deflect
otherwise, which converts an undetectable risk into a known limitation. Medium term,
translate-then-classify on the T1 surface only, plus non-English red-team probes. The wrong
answer is asserting the classifier generalises.

**5 · "The classifier is down."**
Differentiated, and this is the interesting part:

| Path | Behaviour | Why |
|---|---|---|
| **T1 surface** | fail **closed** — fixed deflection | unrecoverable risk, same call as your fail-closed tenant scoping |
| **T2/T3, voice** | rules only, persona narrowed to grounded answers | speech can't be retracted, so shed capability not safety |
| **T2/T3, chat** | rules only, serve, flag for review | a bubble can be replaced; availability wins |
| **Internal tools** | fail **open**, log loudly | no external reputation exposure |

**6 · "Prove what it said on 14 March at 09:12."**
The hash-chained log, with the **policy and model versions** on every entry. Versioning is the
part people forget: "why did we allow it" is unanswerable if you cannot reconstruct which
policy was live.

**7 · "Contrast with the PII gateway."**
Opposite trade, same architecture. PII: a leak is irreversible, a false positive redacts a name
nobody needed — **recall wins, fail closed everywhere**. Reputation: most escapes are
embarrassing rather than fatal and over-blocking destroys the product — **precision wins,
except on T1 where the asymmetry flips back**. The rule that generalises is *tune to the
recoverability of the failure*, which is exactly why tiering exists.

**8 · "Ship a threshold change without regressing containment."**
It is a release, not a config edit. Labelled golden set per tier, containment and FP rate as
hard gates in CI, then **shadow mode** — score live traffic with the new threshold, log the
would-be decision, change nothing — long enough to see the real deflection rate, then a canary
on one persona. And **establish the noise floor first**: on a few hundred positives a
two-point move is sampling noise, and you will read it as a regression. Same discipline as the
model bake-off.

**9 · "It said something damaging anyway. First thirty minutes."**
Kill switch on that persona down to grounded-only — not off, if a hard down is worse than a
dull persona. Pull the audit entry: what was *emitted*, not what was generated. Query the log
for the same pattern across every persona to size the blast radius, because a one-off and a
class are different incidents. Ship a deterministic rule for the exact phrasing within the
hour — that is what the rules layer is *for*. The slow work afterwards: why the classifier
scored it low, whether it belongs in the golden set, and whether scope narrowing should have
declined the question before detection ever ran.

---

## One-line summary

> "Enforcement outside the model, because a system prompt is advisory. Grounding and scope
> narrowing to cut the base rate, deterministic rules for the classes legal enumerated, a
> classifier that emits three bands so uncertainty becomes a deflection rather than an outage,
> thresholds tiered by severity because one global threshold forces you to choose between 60
> escapes and 57,000 blocked answers, a segment gate so nothing reaches TTS unchecked, and a
> hash-chained log plus a per-persona kill switch so the residual is detected and recoverable."

## The trap answer to avoid

Putting the guardrails in the prompt. "Never discuss competitors" in a system message is a
suggestion to the exact component you don't trust, and the injection that overrides it is
trivial. The second-worst answer is a single moderation call with a binary verdict: it forces
one global threshold, and every threshold on that curve is unshippable.
