# The fabrication incident — explained

> This is the incident genre. The interviewer is testing **method under pressure**. A list of
> things that could be wrong scores badly; a bisection with a stated order and a reason for
> the order scores well.

---

## 1. The first thing you say

Not a hypothesis. A **scoping question**, because it halves the search space before you touch
anything:

> "All tenants or one? All surfaces or one? And what shipped near the hour it started?"

One tenant means a scoping or namespace bug. All tenants means a shared path. Chat but not
voice narrows it to a code path. And "nothing shipped" is almost always wrong, because
**prompt and config changes do not feel like shipping** — which is precisely why they are the
most likely cause and the least reviewed.

---

## 2. The triage order, and why the order

Order by **prior probability divided by cost to check**. Say that rule out loud, then walk it.

| # | Hypothesis | Prior | Minutes |
|---|---|---|---|
| 1 | Retrieval returns nothing | 34% | 3 |
| 2 | Prompt template changed | 9% | 5 |
| 3 | Context not reaching the prompt | 22% | 8 |
| 4 | Context truncated | 14% | 8 |
| 5 | Model version changed | 8% | 15 |
| 6 | One tenant only — scoping bug | 3% | 12 |
| 7 | Corpus changed | 10% | 25 |

`solution.py §1` prices it: this order reaches the cause in a third of the time of an
intuition-led order that starts with the deepest dive. The top two hypotheses are over half the
probability mass and eleven minutes of work.

The reason empty retrieval is first is not that it is most likely — it is that it is **three
minutes**. When retrieval returns nothing, the model answers from general knowledge and sounds
exactly as confident as when it is grounded. That is the single most common cause of this
symptom.

---

## 3. Mitigate before you diagnose

Two moves, in this order, before you know the cause:

1. **Roll back the most recent config change.** If several are candidates, roll back all of
   them. You can re-apply later; you cannot un-fabricate.
2. **Raise the relevance floor and let it refuse more.** This is the important one, and it is
   the sentence that shows you have thought about the asymmetry: **a refusal is recoverable, a
   fabrication is not.** A user who is told "I don't know" is mildly annoyed. A user who acts
   on an invented refund policy is a support case, or a legal one.

Deliberately trading availability for correctness under uncertainty is the judgement being
tested here.

---

## 4. The two bugs, both silent

**The either/or.** Prompt assembly took a saved writing style and a set of retrieved chunks,
and used the style **instead of** the facts rather than alongside them. `solution.py §2`: with
a style set, zero of two facts reach the prompt; with no style set, both do. That is why it
passed every test — nobody had a style saved in staging.

**The cap.** A 300-character truncation applied to chunks of 320–430 characters, cutting facts
out of the middle. `solution.py §3`: one of three facts silently lost.

What both share is the property that makes this incident hard: **the prompt is well-formed**.
No error, no exception, no anomaly in any latency or error-rate dashboard. The model receives a
coherent instruction with the facts absent, and does what models do.

---

## 5. What should have caught it

| Control | Prevents |
|---|---|
| **Groundedness on sampled production traffic**, alerting on a drop | users being your monitoring |
| **Empty-retrieval and truncation counters** as first-class metrics | silent context loss |
| **Resolved prompt version + retrieved chunk ids logged per request** | an undebuggable incident |
| **Prompt assembly as a pure, tested function** | the either/or recurring |
| **Refusal rate as a guardrail metric** | the disguised version of this incident |
| **Config changes gated and canaried** | an unreviewed prompt edit reaching everyone |

`solution.py §4` runs the counterfactual: a groundedness alert fires **on day 7**, the day the
fault landed. Users reported it on day 11. The entire cost of the incident was those four days.

---

## The follow-ups, answered

**1. Give me your triage order, and justify the order.**

Prior divided by cost. Empty retrieval first because it is three minutes and a third of the
probability. Prompt template second because it is five minutes and config is the most likely
recent change. Then context-not-reaching-the-prompt and truncation, which are the same eight
minutes but carry more prior than the model or corpus branches. Corpus last, because a re-index
check is twenty-five minutes and only ten percent. The point of stating the rule is that it
survives being wrong: if the first two miss, I have not burned an hour to learn it.

**2. Immediate mitigation, before you know the cause?**

Roll back the most recent config change, and raise the relevance floor so the system refuses
more. The second one is the answer that matters. It trades availability for correctness, on
purpose, because the two failure modes are not symmetric — a refusal is recoverable and a
fabrication is not. I would also start sampling and storing full request context immediately,
because whatever I learn in the next hour depends on data I may not currently be keeping.

**3. Retrieval returns chunks and the answer is still ungrounded. Where next?**

The chunks exist but are not reaching the model, or not intact. Print the **resolved prompt** for
a failing request — the actual string sent, not the template. That one artefact distinguishes
assembly bugs from truncation from a template change, and it is the reason to log it. In this
incident it would have shown a prompt containing a persona and a writing style and no facts at
all, which is unmistakable. If the prompt is correct and the answer is still ungrounded, then
the model changed, and I would diff the provider's reported version against last week's.

**4. How would you have detected this before users did?**

Groundedness on sampled production traffic — take a sample of responses, check with a judge
model whether each claim is supported by the retrieved chunks, alert on a drop. That fires on
day 7 here. Underneath it, two counters that are nearly free: empty-retrieval rate and
truncated-context rate. Both would have moved sharply, and both are cheap enough that there is
no excuse for not having them. The general principle is that you cannot alert on "is the answer
right", but you can alert on "did the inputs to being right arrive".

**5. Why is a fall in refusal rate a warning sign?**

Because refusals are the system admitting ignorance, and ignorance does not spontaneously
decrease. If the refusal rate drops from 9% to 2% with no change to the corpus, the model has
not become better informed — it has stopped noticing that it is uninformed. This is the trap in
the metric set: on every dashboard you own, fewer refusals looks like an improvement. It should
be a **guardrail** with a two-sided alert, not a KPI to be driven down.

**6. The prompt template changed and nobody reviewed it. Fix the process.**

Prompts and model versions are **config, so they bypass code review unless you build a gate**.
The fix: prompts live in version control, changes go through the same review as code, each
change runs the eval suite in CI with a hard gate, and rollout is canaried by percentage with
groundedness as the canary metric. Every request logs the resolved prompt version. None of that
is exotic — it is just noticing that the most frequently changed part of an LLM system is the
least governed part.

**7. How do you prove which prompt version served a given request?**

Log the resolved version identifier on every request, alongside the retrieved chunk ids and the
model version. Without those three fields an incident like this is not debuggable after the
fact — you are reduced to reproducing it, and this one does not reproduce in staging because it
needs a tenant with a saved style. It is a small amount of data and it is the difference between
a four-hour investigation and a four-day one.

**8. Same symptom, one tenant only. Does your triage order change?**

Yes, substantially. Scoping and per-tenant configuration jump to the top: their namespace, their
corpus, their saved settings, their feature flags. Shared-path hypotheses drop, because a shared
path would affect everyone. Concretely I would diff that tenant's resolved config against a
healthy tenant's before checking anything else — and in this incident that diff would have shown
the saved writing style immediately, which is a nice illustration of why the scoping question
comes first.

**9. You cannot reproduce it in staging. What now?**

Take that as **information**, not an obstacle: the difference between staging and production is
now the prime suspect, and the list is short — data, config, scale, tenant state. Here it is
tenant state, because no staging tenant had a saved style. So: capture a real failing request's
full context from production, replay it against staging, and bisect the difference. If you
cannot capture that context, you have found the actual gap and the first fix is logging, not
code.

---

## One-line summary

Scope it first, then bisect by prior over cost starting with empty retrieval, mitigate by
raising the relevance floor because a refusal is recoverable and a fabrication is not — and
recognise that the technical fix here is one line while the whole cost was four days of
detection lag, which is a monitoring problem and not an engineering one.

---

## The trap answer to avoid

Producing a list of everything that could cause fabrication. It sounds thorough and it is
unordered, which is the opposite of what an incident needs. The second trap is jumping to the
model — "the provider must have changed something" — which is an 8% branch that takes fifteen
minutes, checked fifth. And the quiet one: treating a fall in refusal rate as good news on the
dashboard you built to watch for exactly this.
