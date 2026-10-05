# Extraction at 50k documents a month

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Volume | 50,000/month | ~2,400 working-day |
| Fields | 20 | per document |
| 99% per field | 82% docs perfect | 9,104 imperfect/month |
| Needed for 99% per doc | 99.95% per field | not achievable unaided |
| Documents routed to review | <50% | at a 0.95 field threshold |
| Per-field vs per-doc routing | 15x reviewer time | for identical accuracy |

## 2. The pipeline

1. **Ingest and classify.** Sender, document type, template match against a cache.
2. **Template path** for known layouts — cheap, deterministic, high accuracy. Most of the volume.
3. **General extraction** for the rest.
4. **Deterministic validators.** Arithmetic, checksums, date sanity, enumerations.
5. **Cross-field consistency.** Subtotal + tax = total; line items sum to subtotal.
6. **Per-field confidence routing.** Below threshold → the queue, that field only.
7. **Review UI** showing one field with its source region highlighted.
8. **Corrections** flow to the output *and* to the eval set.

Steps 4 and 5 come before 6 deliberately: every deterministic catch is a review avoided, and
review is the expensive resource.

## 3. Reviewer throughput is the capacity model

Not GPU, not API spend — **reviewer-minutes**. Size it explicitly: fields routed per month ×
seconds per field ÷ reviewer-hours available. If that number exceeds the team, the SLA is not
achievable at the current threshold and the conversation is about the threshold or the headcount,
not about the model.

Prioritise the queue by **downstream error cost**. Bank account before payment terms. A queue
ordered by arrival time treats a fraud risk and a typo identically.

## 4. Cost structure

| Line | Per month |
|---|---|
| Model extraction | ~£550 |
| Review, everything | ~£21,000 |
| Review, confidence-routed | ~£9,600 |

Extraction is a rounding error. **The review queue is the product's cost**, which is why template
caching and validators — both of which remove review — pay for themselves faster than any model
change.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | SLA definition | Pin per-field vs per-document before designing |
| 2 | Reviewer throughput | Per-field routing, validators, priority by error cost |
| 3 | Confidence calibration | Reliability plots; structural signals, not just model logprobs |
| 4 | One hard field | Per-field dashboard; renegotiate or drop the field |
| 5 | Eval staleness | Corrections feed the set; alert on unrepresented senders |

## 6. Observability

**Per-field accuracy**, always — never an aggregate as the headline. Per-sender accuracy, because
a template change shows up there first. Confidence calibration by bucket. Review queue depth and
age. Fields routed per document, trending. Cost per document split into extraction and review.
And the reviewer's own disagreement rate on double-checked samples, because the SLA has no floor
below the reviewers' accuracy and almost nobody measures it.
