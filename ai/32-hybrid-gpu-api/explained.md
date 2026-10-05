# Hybrid self-hosted GPU + API inference — explained

---

## 1. The numbers force the design

An A100-class GPU at roughly £2/hour is about **£1,460 a month, whether you use it or not.**
Add the fraction of an engineer it takes to keep a serving stack alive — call it £1,800 — and
the fixed cost is **£3,260 before a single token is served.**

Against a small API model at £0.0009/1k tokens, that is a break-even of about **3.6 billion
tokens a month, per card.** `solution.py §1`.

Two consequences fall straight out:

- Most tasks are nowhere near it. A 500M-token/month task costs £450 on the API and £3,260
  self-hosted. Self-hosting loses by 7x.
- The decision is therefore **per task**, not per platform. The output of this design is a
  routing table, not a verdict.

---

## 2. Say this before anything else: the trap is "self-hosting is cheaper"

It is cheaper **above a volume threshold**, at **a utilisation you can actually sustain**, for
tasks that **do not need frontier quality**. Every one of those three qualifiers is load-bearing,
and an answer that omits them is the one the interviewer is waiting to hear.

There is a specific arithmetic error underneath the trap, and it is worth naming out loud:
**per-token price is a ratio, and the bill is a product.** At 70% utilisation the GPU costs
£0.00033/1k against the API's £0.0009/1k, so it is genuinely 3x cheaper per token. A 500M-token
task is still four times more expensive to self-host, because you buy the whole card and use a
tenth of it. Only one of those two numbers arrives at the end of the month.

---

## 3. The layers, each named by the failure it prevents

**One OpenAI-compatible interface across both** — *prevents:* call sites knowing where inference
runs. vLLM speaks the OpenAI protocol, so the same client library points at either. Without
this, placement becomes a code change and you will never move a task back.

**Task-based placement** — *prevents:* self-hosting the thing you cannot match. High-volume,
low-complexity, latency-tolerant work goes in-house. Frontier-quality work stays on the API at
any volume.

**Utilisation-based routing** — *prevents:* paying for idle GPUs. Fill the card first, overflow
to the API. The routing rule is "is there a free slot", not "is this task's home the GPU".

**Continuous batching** — *prevents:* terrible utilisation at low concurrency. `solution.py §3`:
at one concurrent request, static batching delivers 300 tok/s against 1,035 — you are throwing
away two thirds of the card in exactly the regime a first self-hosting attempt runs in.

**API as overflow and failover** — *prevents:* a GPU outage becoming downtime. This is the
single feature that makes the whole thing safe to attempt.

**Quality parity eval per task** — *prevents:* a silent quality drop when a task moves in-house.
The move is a model change; treat it like one.

**A cost dashboard comparing actual £/1k on both paths** — *prevents:* believing the projection
instead of the bill. Projections in this area are wrong in a predictable direction.

---

## 4. Utilisation is the business case, not an optimisation

| Utilisation | Tokens/month | £/1k | vs API |
|---|---|---|---|
| 5% | 315M | 0.01034 | **dearer** |
| 20% | 1.26B | 0.00258 | **dearer** |
| 40% | 2.52B | 0.00129 | **dearer** |
| 70% | 4.42B | 0.00074 | cheaper |
| 95% | 5.99B | 0.00054 | cheaper |

`solution.py §2`. Note where the line falls: you need **north of 50% sustained** before the
card beats the API at all. That is a demanding target for interactive traffic, which is spiky
by nature — you size for the peak and idle through the trough.

Which is why the real unlock is **batch work**. Overnight classification and backfills have no
latency requirement, so they fill the trough. A fleet serving only interactive traffic will
struggle to clear 40%; the same fleet with a batch queue behind it clears 80%.

---

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Utilisation** | A 20%-utilised GPU is dearer than the API it replaced. Everything else is downstream of this. |
| 2 | **Ops burden** | The cost nobody puts in the spreadsheet. `solution.py §4`: it moves the headline saving by 8 points. |
| 3 | **Quality drift on moved tasks** | Nobody re-evaluates after the migration, and the regression is attributed to the prompt. |
| 4 | **Capacity during a spike** | A fixed fleet cannot absorb one. Without API overflow, the spike is an outage. |
| 5 | **Model upgrades** | The API's model improves for free. Yours improves when someone does the work. |

---

## The follow-ups, answered

**1. At what monthly volume does self-hosting a 7B model start winning?**

About 3.6 billion tokens a month per card, on these numbers — £1,460 for the GPU plus £1,800 of
ops, divided by £0.0009/1k. Give the arithmetic rather than the number, because the number moves
with your actual prices and the *method* is what transfers. And state the two hidden assumptions
while you are there: that you can sustain the utilisation, and that the smaller model is good
enough for the task. Neither is free.

**2. Your GPU sits at 20% utilisation. Is it still cheaper?**

No. At 20% it costs £0.00258/1k against the API's £0.0009 — nearly 3x dearer. The card bills
for 730 hours a month regardless. Fixes in order: add batch work to fill the trough, consolidate
more tasks onto the same card, drop to a smaller instance, or shut it down and go back to the
API. That last one is a real answer and you should be willing to give it.

**3. Which tasks would you move in-house first?**

High volume, low complexity, latency-tolerant, stable prompt. Classification, extraction,
summarisation of routine text, reranking, embeddings. What they have in common: a small model
is genuinely competitive, the output is short, and nobody notices 200ms. Move the single
highest-volume one first, prove the utilisation and the quality parity on it, then add the
second — because the second task is nearly free once the card is running, and that is where the
economics actually come from.

**4. The self-hosted model scores 3 points lower. Do you ship it?**

Depends entirely on what the 3 points are made of, and you have to look. If it is 3 points on an
aggregate over a task where the floor is what matters — say extraction accuracy on a
contractual field — no. If it is 3 points on a summarisation rubric where the difference is
stylistic, probably yes, and the saving is real. The wrong answers are both reflexes: shipping
it because it is cheaper, and blocking it because a number went down. Decompose the metric,
find out which slice regressed, and decide against that.

**5. A GPU node dies at 2am. What does the user see?**

Nothing, if you built the overflow path. The router marks the node unhealthy and the task falls
through to the API — more expensive per token, and the alert is a cost alert rather than a
page. That is the correct shape: a hardware failure should degrade your margin, not your
service. Without the overflow path it is an outage, and this is the main reason to keep the API
integration live even for tasks that have fully moved in-house.

**6. How do you stop call sites knowing where inference happens?**

One OpenAI-compatible interface in front of both. vLLM implements the protocol, so the
self-hosted path and the API path present the same client surface, and placement becomes
configuration rather than code. Call sites pass a **task name**, not a model name — the router
maps task to placement. That indirection is what lets you move a task in either direction on a
config change, and being able to move it *back* is what makes the experiment safe.

**7. Your projection said 60% and the bill says 15%. Where did it go?**

Four usual suspects, in order of likelihood. **Utilisation** below the projection — you modelled
70% and are running 30%, which alone accounts for most gaps. **Ops** was never in the model.
**Overflow** to the API is firing more than expected, because you sized for average rather than
peak. And **the API price dropped** while you were building, which happens on a timescale
shorter than a self-hosting project. Instrument actual £/1k on both paths per task from day one;
without that you are debugging a spreadsheet rather than a system.

**8. When would you recommend not doing this at all?**

Say this plainly, because it is the answer that demonstrates judgement. Do not do it when: your
total spend is under roughly £5k/month, where the ops cost swamps the saving; when nobody on the
team will own GPU operations, and "we'll figure it out" means it lands on whoever is least able
to refuse; when traffic is spiky and there is no batch work to fill the trough; when the tasks
genuinely need frontier quality; or when the team's next six months should go into the product
instead. The cost saving is real and it is not always the best use of the same engineering
time.

**9. Batch and interactive share the fleet. How do you stop batch starving interactive?**

Interactive gets a reserved share of the batch slots and strict scheduling priority; batch runs
on what is left and is preemptible mid-request. Concretely: cap the number of concurrent batch
sequences, admit interactive requests ahead of queued batch, and let a batch sequence be
evicted and resumed rather than blocking a slot. Then alert on interactive queue depth, not on
GPU utilisation — utilisation will look wonderful right up to the moment interactive latency
falls over, because batch is very good at hiding exactly this failure.

---

## One-line summary

Self-hosting is cheaper above a per-task volume threshold, at a utilisation you can sustain, for
tasks that do not need frontier quality — so the answer is a routing table behind one
OpenAI-compatible interface, with continuous batching to make the utilisation reachable, batch
work to fill the trough, and the API kept live as overflow and failover.

---

## The trap answer to avoid

"Self-hosting is cheaper, so we should move inference in-house." It is cheaper per token and
that is the wrong unit. The specific error is comparing a **ratio** to a **product**: a task can
be 3x cheaper per token and four times more expensive per month, because you bought a whole card
and filled a tenth of it. The second trap is quieter — leaving **ops** out of the model, which
is worth 8 points of the headline saving here and is the line most likely to be missing from a
real business case.
