# The support copilot at scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Human-handled ticket | £6.20 | baseline |
| AI-handled | £0.04 | |
| Wrongly deflected, re-handled | 2.4x a fresh ticket | customer arrives annoyed |
| Expected churn per wrong deflection | ~£24 | 4% × £600 LTV — the term that decides it |
| Optimal threshold | ~0.70 | interior, not at either extreme |
| Saving at the optimum | ~27% | against 14% for deflect-everything |

## 2. The request path

1. **Intent classification.** Some intents are never handled by the model — cancellations,
   complaints, anything legal.
2. **Retrieval** against the KB, with a relevance floor.
3. **Grounded generation.** No retrieved support above the floor → escalate, do not improvise.
4. **Confidence gate** on retrieval strength, groundedness and sentiment.
5. **Answer, or escalate with full context.**
6. **Actions** only within the tier, behind confirmation and an idempotency key.
7. **Always-visible escape hatch**, at every step.

## 3. Action tiers

| Action | When | Why |
|---|---|---|
| Answer questions | freely | reversible; the KB is the ceiling |
| Read account state | freely | no side effect |
| Resend a receipt | narrowly | idempotent, harmless repeated |
| Apply account credit | with confirmation | reversible by a human |
| Issue a refund | confirmation + idempotency key + amount cap | money moves |
| Cancel a contract | never | irreversible, and a retention decision |

The idempotency key is derived from ticket id and action, so a retry after a payment-gateway
timeout is safe. Retries are the normal case, not an edge case.

## 4. The handoff payload

Transcript · actions attempted · KB articles retrieved · confidence and escalation reason ·
account state.

Five fields, none of them hard, and together they are worth more than a point of CSAT on a ticket
the AI has already failed.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | CSAT | Threshold is a CSAT dial; roll it back first, investigate second |
| 2 | A wrong KB article | Reopen clustering by retrieved article |
| 3 | Handoff quality | Audit the payload; measure customer repetition |
| 4 | Action safety | Idempotency keys, amount caps, confirmation |
| 5 | Metric gaming | Never report deflection without reopen and CSAT |

## 6. Observability

The headline is **true deflection** — deflected and not reopened within the window — never raw
deflection. Beside it: reopen rate, CSAT on AI-handled tickets, and CSAT on escalated tickets
tracked separately, because those are different products.

Then: escalation reasons by frequency, which is the roadmap. Reopen rate **by retrieved KB
article**, which finds wrong articles. Distribution of confidence near the threshold, which tells
you whether the signal separates anything. Escape-hatch usage rate — a spike means the agent is
failing in a new way. Action counts by tier, and any idempotency-key collision, which should be
rare and is interesting when it happens.

## 7. The feedback loop

Every escalation is a free labelled example. Escalations where the human's answer differed
materially go into the eval set. Cluster by intent: a repeated cluster is either a missing article
or an intent that should be handled deterministically. If the escalation-reason mix is unchanged
month on month, the system is not learning and that is a process problem.
