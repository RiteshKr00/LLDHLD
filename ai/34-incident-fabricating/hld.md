# Detection and prevention at scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Time to detection, as it happened | 4 days | users reported it |
| Time to detection, with groundedness | same day | the alert fires on the fault day |
| Sampling rate needed | 1–2% | enough signal at production volume |
| Cost of the judge pass | ~1% of inference spend | at 1% sampling |
| Technical fix | one line | which is the point |

## 2. The detection layer

**Groundedness on a sample.** Take 1–2% of responses, ask a judge model whether each claim is
supported by the chunks that were actually retrieved for that request. Alert on a drop against
a rolling baseline, not against an absolute threshold — the absolute level varies by tenant and
query mix, and a fixed number will either never fire or never stop firing.

**Free counters that need no judge.** Empty-retrieval rate, truncated-context rate, retrieved
chunk count distribution, resolved prompt length. All are cheap, all moved sharply in this
incident, and all are the kind of metric that only gets added after the first outage.

**Refusal rate, two-sided.** A rise means retrieval or the corpus is degrading. A fall means
the model stopped admitting ignorance. Both are alerts. This is the one people build as a
single-sided KPI and then drive in the dangerous direction.

## 3. The forensic record

Every request logs: resolved prompt **version**, retrieved chunk **ids**, model **version**,
tenant, and whether truncation occurred. Five fields. Without them an incident is not
debuggable after the fact, and this one specifically does not reproduce in staging.

Retention long enough to cover "it was fine last week" — 30 days minimum, because that is the
window in which someone notices.

## 4. Prevention

**Prompt assembly is a pure function** with the inputs as arguments and the string as the
return. Test it with each input present and absent — for persona, style and chunks that is
eight cases, and the either/or bug cannot survive any of them. This is the actual fix.

**Prompts are config, and config bypasses review** unless you build the gate. Version control,
review, eval suite in CI with a hard gate, canary by percentage with groundedness as the canary
metric.

**Cap by tokens at a chunk boundary**, never by characters mid-string. If you must drop
content, drop **whole chunks** lowest-relevance-first and count what you dropped.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Time to detection | Groundedness on sampled traffic; the counters underneath it |
| 2 | Debuggability | Log prompt version, chunk ids, model version per request |
| 3 | Unreviewed config | Gate prompt changes like code; canary them |
| 4 | Silent truncation | Token-aware packing at chunk boundaries, with a counter |
| 5 | Staging fidelity | Seed staging with realistic tenant state, styles included |

## 6. The incident runbook

1. Scope: all tenants or one, all surfaces or one, when exactly.
2. Mitigate: roll back recent config; raise the relevance floor.
3. Bisect by prior over cost, starting with empty retrieval.
4. Print the **resolved prompt** for a failing request. This single artefact separates most of
   the branches.
5. Fix, then write the detector that would have caught it — before closing the incident, not in
   a follow-up ticket that never gets picked up.
