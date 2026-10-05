# Support copilot with escalation — explained

---

## 1. The brief is the second sentence

"Deflect support tickets" is easy. "Don't make customers angrier" is the actual problem, and it
is the constraint that makes every design decision below non-obvious.

State the trade explicitly and early:

> If you deflect 40% but 10% of those are wrong, you have created 4% badly-handled tickets that
> arrive at a human **already annoyed** — and those cost more than the 40% saved.

**Deflection rate alone is the wrong metric.** It is trivially optimisable — deflect everything —
and optimising it is how you ship something that wins the dashboard and is hated.

---

## 2. The optimum is interior, and what makes it so

`solution.py §1`:

| Threshold | Deflection | Of those, wrong | True deflection | Saving |
|---|---|---|---|---|
| 0.00 | **100%** | 14% | 86% | 14% |
| 0.50 | 89% | 12% | 78% | 23% |
| **0.70** | 58% | 8% | 53% | **27%** |
| 0.85 | 22% | 5% | 21% | 15% |
| 0.95 | 3% | 3% | 3% | 2% |

Two findings, and the second is the honest one.

**The optimum is interior.** Not deflect-everything, not deflect-nothing. That shape is the whole
argument, and it means the threshold is a real decision rather than a direction to push in.

**On ticket-handling cost alone, greedy deflection wins** — which is exactly why teams build it.
What makes the optimum interior is the **churn cost**: a badly-handled ticket carries a risk of
losing the customer, and expected churn against lifetime value dwarfs the handling cost. Leave
that term out of the model and the arithmetic genuinely recommends deflecting everything.

If you cannot get a churn number from the business, say so and use a placeholder — but do not
build the business case without the term, because that is the case that justifies the bad
product.

---

## 3. The layers, each named by the failure it prevents

**Confidence-gated deflection** — *prevents:* the 4% problem. Answer only when grounded and
confident; escalate otherwise.

**Always-available "talk to a human"** — *prevents:* trapping people, which is the single biggest
CSAT killer. `solution.py §3`: being unable to reach a human scores **1.0** against **2.9** for
being told no and offered a person immediately.

**Full context handoff** — *prevents:* the customer repeating themselves, which is what actually
makes them angry. Worth more than a point of CSAT on a ticket the AI already failed.

**Actions behind confirmation and idempotency** — *prevents:* a double refund.
`solution.py §5`: without an idempotency key, one timeout retry applies two refunds.

**Tiered scope** — answer freely, act narrowly, never act irreversibly.

**Metrics that pair** — deflection *with* reopen rate *and* CSAT. Never one alone.

**Escalated tickets become eval cases** — *prevents:* a static system that never learns from its
own failures.

---

## 4. Escalation is not the failure. A bad escalation is.

This reframing is the most useful thing to say in this scenario.

A ticket the AI escalates cleanly — with the transcript, what it tried, the articles it
retrieved, the account state — costs a human a normal ticket's work and the customer nothing
extra. A ticket that escalates badly makes the customer start over, and `solution.py §4` puts
that at **1.8 against 2.9** CSAT.

So the target is not fewer escalations. It is escalations that cost the customer nothing. Five
fields do most of that work, and none of them is hard: transcript, actions attempted, retrieved
articles, confidence and reason, account state.

---

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **CSAT, not accuracy** | A confident wrong answer plus a hard-to-escape loop. Invisible in accuracy metrics. |
| 2 | **The knowledge base** | A deflection engine on a stale KB industrialises the wrong answer. |
| 3 | **Handoff quality** | Escalation without context is worse than no AI at all. |
| 4 | **Action safety** | Retries are normal; without idempotency they are expensive. |
| 5 | **Metric gaming** | Deflection reported alone always improves. |

---

## The follow-ups, answered

**1. You deflect 40%. Why might that be bad?**

Because the number that matters is the fraction deflected **correctly**. If a tenth of those
answers are wrong, you have manufactured 4% of tickets that come back with a customer who has
already been told the wrong thing and now has to explain it twice. Those cost more than double a
fresh ticket to handle, and some fraction of those customers do not come back at all. Deflection
without reopen rate beside it is a number that only goes up, which is a reliable sign it is not
measuring anything.

**2. What is your escalation trigger, and what happens at the boundary?**

Escalate when retrieval is weak — nothing above the relevance floor — when the model's answer is
not grounded in what was retrieved, when the intent is one of the classes we have chosen not to
handle, when the customer's sentiment is negative, or when they ask for a human. At the boundary,
prefer escalating: the asymmetry is that a needless escalation costs one ticket of human time,
while a wrong deflection costs a re-handled ticket plus the churn risk. And make the boundary
observable — track how many tickets land within a few points of the threshold, because a large
mass there means the confidence signal is not separating anything.

**3. A customer wants a human immediately.**

They get one. No qualification questions, no "let me try to help first", no three-attempt gate.
`solution.py §3` prices the alternative: not being able to reach a human is the worst outcome in
the set, worse than being told no. An always-visible escape hatch does reduce deflection somewhat,
and that is the cost of the product being tolerated rather than resented. Where there is a genuine
queue, say the wait honestly and offer a callback.

**4. What does the human receive?**

Five things: the full transcript, what the agent already tried, the KB articles it retrieved, the
confidence and the reason it escalated, and the customer's account state. The first prevents the
customer repeating themselves. The second prevents the human repeating the agent — which is
almost as annoying. The third lets the human see *why* it said what it said, which is how they
spot a bad article. The fourth tells them what to distrust. The fifth removes "can I take your
order number?" from a conversation that has already been going for five minutes.

**5. The agent can issue refunds. Design that.**

Tier the scope. Answering and reading account state: freely. Idempotent harmless actions such as
resending a receipt: narrowly. Reversible actions such as account credit: with explicit customer
confirmation. Refunds: confirmation **plus an idempotency key** derived from the ticket and action,
plus an amount cap above which it escalates. Irreversible actions such as cancelling a contract:
never — that is a retention conversation, not a support task. The idempotency key is not
theoretical: a timeout on a slow payment call is the normal case, an agent that retries is doing
the right thing, and `solution.py §5` shows the same retry applying two refunds without one.

**6. Which metrics would you refuse to report on their own?**

Deflection rate. It only goes up, and the way to make it go up is to make the product worse. I
would report it only as a triple with **post-deflection reopen rate** and **CSAT on AI-handled
tickets**, and I would put true deflection — deflected and not reopened — next to it as the
headline. Similarly, "resolution rate" without a reopen window attached, and average handling time
without CSAT, since the fastest way to close tickets quickly is to close them badly.

**7. Your KB article is wrong. What happens?**

The agent answers confidently and consistently wrong, at scale, which is worse than a human being
wrong occasionally — you have industrialised it. You find out from **reopen clustering**: group
reopened tickets by the article that was retrieved, and an article with an anomalous reopen rate
is a wrong article. That signal is one of the more valuable by-products of the whole system,
because it finds KB errors that were quietly costing human agents time long before the AI existed.
Then: correct the article, and re-answer the affected customers proactively if the answer
mattered.

**8. How do escalated tickets make the system better?**

Every escalation is a labelled example, free. The ones where the human's answer differed from what
the agent would have said go into the eval set. Cluster them by intent: a cluster that escalates
repeatedly is either a missing KB article — write it — or an intent that should be handled
deterministically rather than by a model. Track the mix over time. A system whose escalation
reasons stay identical month after month is not learning, and that is a process failure rather
than a model one.

**9. CSAT drops two points while deflection rises ten.**

Roll back the threshold change, then investigate — in that order, because CSAT is the constraint
in the brief and deflection is the optimisation. Then find where it went: is it concentrated in
one intent, one customer segment, or one KB article? It usually is. Check whether the escape
hatch got harder to find, since that is a common accidental cause when someone tunes a funnel.
And use it as the moment to fix the incentive: if deflection is reported alone, this will happen
again, and the fix is the metric definition rather than the threshold.

---

## One-line summary

Deflection rate is trivially optimisable and optimising it ships a product people hate, so gate
deflection on grounded confidence, keep an always-visible route to a human, hand off full context
because a bad escalation rather than an escalation is the failure, tier actions behind
confirmation and idempotency, and report deflection only alongside reopen rate and CSAT — noting
that on handling cost alone greedy deflection wins, and it is the churn cost of a badly-handled
customer that makes the optimum interior.

---

## The trap answer to avoid

Optimising deflection rate. It is easy to build, it always improves, and the way to improve it is
to answer more questions you should not have answered. The related trap is treating escalation as
the failure to minimise — it is not; a **bad** escalation is, and the fix for that is context
rather than accuracy. And leaving churn out of the business case, which produces an arithmetic
that sincerely recommends deflecting everything.
