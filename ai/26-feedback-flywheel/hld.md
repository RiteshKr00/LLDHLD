# The flywheel at scale

> Every layer here is sized by one number that has nothing to do with servers: **two reviewers.**

## 1. Numbers first

| Input | Value |
|---|---|
| Production calls | 600k/day → **7 QPS average, 70 peak** |
| Capture writes | one outcome record per call → **7/s, 70 peak**, fire-and-forget |
| Candidate writes | ~11.5k/day → **0.13/s, ~1.3 peak** |
| Redaction on the hot path | ~2ms in-process |
| Human review | 2 seats × 90s/case → **300 labels/day sustained** |
| Storage | 44 GB/year outcome records + 28 GB/year redacted text |

**Little's Law, twice, and only one of them matters.**

*Machine side:* the hot path gains 2ms of in-process redaction. At 70 peak QPS that is
`70 × 0.002 = 0.14` concurrent — against topic 16's ~140 concurrent LLM calls, **the flywheel adds a
tenth of a percent to the concurrency budget.** Everything downstream is async and runs at 0.13
events/second. Do not build Kafka for that.

*Human side:* `L = λW` with μ = 300/day. Admit 450/day and L grows by 150/day; by day 30 the backlog
is 4,500, so W = 4,500 / 300 = **15 days** — past two release cycles, and every label now describes a
prompt version you retired. **Admission must be a token bucket set at μ**; the priority score chooses
*which*, never *how many*.

**What those numbers force:** this is not a throughput problem, a storage problem or a cost problem.
72 GB/year is a rounding error and 0.13 writes/second is nothing. The binding constraints are
**reviewer-hours and legal exposure**, and every lever below aims at one of those two.

## 2. Topology — what sits where

- **In the request process:** the redactor and the checker results, nothing else. Redact here rather
  than in the worker and the queue, topic and worker pool have never held raw PII — queues get replayed.
- **On Celery, off the request path:** capture, candidate scoring, novelty embeddings. Your dealership
  platform already has the dedicated-queue bulkhead; same argument.
- **Two stores, deliberately split:** outcome records (every call, no text, 13 months) and redacted
  candidate text (~11.5k/day plus a control slice, 90 days). Rates from the first, cases from the
  second, and only the second is a liability.
- **The golden set is a content-addressed artefact**, not a table — its hash joins topic 22's
  `manifest.lock`, so a gate score is meaningless without a version.

## 3. The scaling levers, best first

| Lever | Buys you | Pull it when |
|---|---|---|
| **Widen deterministic checker coverage** | free labels at 93% precision, zero reviewer time | always, first |
| **Per-segment calibration** | yield per label, no extra hours | a tenant or surface is anomalous |
| **Tighter novelty threshold** | fewer duplicate labels | promotion rate drifts above 2% |
| **LLM as a pre-filter on the pool** | triage, never a label | reviewer time is the wall |
| **More reviewers** | linear capacity | last resort |

**More reviewers is the worst lever**, and saying so is the point. Inter-annotator agreement falls as
the pool grows and the rubric has to be re-taught; you buy hours and pay in kappa. Yield per label
beats hours, every time.

## 4. Multi-tenant fairness, and what a departing tenant costs you

A floor per strata cell, a cap per tenant at ~2× traffic share, and **per-tenant golden-set share
against traffic share** reported as a number with an alarm rather than a chart — over 2× is bias
arriving. Access is not a second system: the eval store is tenant-scoped by the authz layer you
already have (Casbin, on the HR platform), so a case drawn from tenant A never renders in tenant B's
queue.

**Offboarding degrades your eval set.** A departing tenant's promoted cases are derived personal data
and must go, silently removing regression coverage. Keep the **failure mode** as a first-class entity,
separate from the cases instantiating it: on deletion you lose the case and keep the knowledge that
the mode is now uncovered, which puts it straight back at the top of the priority queue.

## 5. Cost — all of it in a resource you cannot buy quickly

Human labelling at 2 × 4h/day and $30/h loaded is **$5,200/month**; quarterly calibration amortises to
~$300; novelty embeddings ~$7; 72 GB/year of storage under $5. **~$5,500/month, about 8% of the
$72k/month inference bill** — cheap enough that nobody refuses it, and entirely made of reviewer-hours.

## What breaks, in order

1. **The human queue** — the only queue here with no autoscaling. First because admission is under
   your control and capacity is not, so the mismatch stays silent until the labels are stale.
2. **Calibration staleness** — ship a "make this shorter" button and the edit signal's precision
   collapses that afternoon. Nothing errors, no dashboard moves, the sampler keeps last quarter's weights.
3. **Redaction on the hot path** — 2ms becomes 20ms the day someone loads the NER model per request
   instead of once per worker. The only part of this design that can hurt production latency.
4. **Golden-set version discipline in CI** — one unversioned addition and a dataset change reads as a
   three-point regression.
5. **Novelty-index drift** — change the embedding model (topic 33) and every novelty score is measured
   against a different geometry, so promotion rate spikes or collapses and looks like a quality event.
6. **Eval-store retention** — it outlives the retention policy of the system the data came from, and
   that is invisible until it is a legal question.
7. **Saturation** — pass rate at 98%, nothing discriminated, everyone reassured.

## Degradation — and it differs per component

| Down | Behaviour |
|---|---|
| **Redactor** | **fail closed** — drop the payload, keep the outcome record. Opposite of the gateway's fail-open on rate limits: a missed rate limit costs money, a missed redaction is a breach |
| **Reviewers** (holiday, backlog) | keep scoring and storing, **stop admitting**. Candidates expire at 21 days rather than accumulating. The gate keeps running on the versioned set; only *growth* pauses |
| **Deterministic checkers** | you lose the 93% signal, so pool precision falls from ~39% toward ~25%. Raise the co-firing weight and **lower** the admission rate rather than labelling noise |
| **Embedding service** | fall back to failure-mode-tag diversity for novelty. Coarse, but skipping the novelty term floods the queue with duplicates |
| **Golden-set store, in CI** | gate against the pinned local snapshot. Never skip — topic 22's rule |

## Observability

Per signal, per feature, per tenant — never aggregated. Volume, precision, co-firing rate, admission
rate, queue depth and age, promotion rate, per-tier pass rate, per-tenant golden-set share.

**Leading indicators, in the order they move:** **Cohen's kappa** on the 10% double-labelled slice,
which drops before labels are visibly wrong · **queue-age p95** in days from signal to label, alarmed
at 7 · **minimum cell occupancy** across the strata grid, where a zero is a blind spot forming ·
**promotion-rate drift** away from ~2%, meaning either the novelty index moved or the sampler is
starved · **per-signal precision delta** since the last calibration, the tell that a surface changed.

Lagging, and the ones everyone watches instead: production defect-signal rate, escalation rate,
golden-set pass rate. And the one that judges the whole loop — **the rank correlation between offline
gate deltas and 7-day production signal deltas over the last eight releases.** Below ~0.2 you are
maintaining an expensive dataset that measures something users never feel.
