# LLM observability — explained

**Where you have actually done this:** per-call metering across five providers on one rate card
in the dealership platform, and the **grounding + evaluation layers** of the ICH E3 report
generator — which is local-first, so there is no observability vendor to hide behind and the
storage bill is a disk you can see. The persona product supplies the other half: the tenant id
is resolved once at the edge and fails closed, and every trace inherits it. The honest gap:
you have metering and offline evaluation, not **tail sampling** or a **cardinality budget** —
which is what this scenario is about.

---

## 1. The numbers, and what they force

| Input | Value |
|---|---|
| LLM calls/day | **600k** (chat 400k, summarise 150k, extract 50k) |
| Average / peak | ~7 QPS / **70 QPS** |
| Spans per call | ~6 (retrieve, rerank, build, generate, validate, post) |
| Span rate | 3.6M/day ≈ 42/s average, **420/s peak** |
| Full trace payload | prompt + 8 chunks + response ≈ **20 KB** |
| Skeleton row | ids, model, prompt_version, tokens, cost, latency, outcome ≈ **400 B** |

- **Log everything: 600k × 20 KB = 12 GB/day = 4.4 TB/year raw**, ~13 TB with replication and
  indexes, **4.8 TB resident** at a 400-day retention.
- **Skeleton only: 240 MB/day.** Fifty times smaller, and it contains no prose.

And the cardinality, missed until the invoice: 500 tenants × 8 models × 4 features × 8 error
classes = **128,000 series per metric name**. Twenty metric names is **2.5M active series**,
which is where a managed TSDB stops being a line item.

**What that forces:** split the record — the cheap non-sensitive half at 100% forever, the
expensive sensitive half sampled and expiring — and keep the high-cardinality dimensions out of
the metrics backend entirely.

---

## 2. Trace context minted at the edge — *prevents:* six unlinked log lines

Without one id created at the gateway and propagated through retrieval, generation, validation
and the ledger write, you can answer "are requests slow" and never "why was **this** request
slow". Mint it where the tenant is resolved, so `trace_id` and `tenant_id` travel together and
neither can be attached later by guesswork. Then a span arriving with no tenant is **a bug you
can alert on** rather than a row you quietly accept.

---

## 3. The span schema — *prevents:* a generic APM telling you "the POST took 4s"

| Generic APM span | What an LLM span must carry |
|---|---|
| duration | duration **split**: retrieval, queue wait, time-to-first-token, generation |
| status 200 | `outcome`: ok / refusal / parse_failure / validation_failure / guardrail_block |
| route | `model`, `model_version`, `prompt_version`, `retriever_version` |
| — | tokens in / out / cached, and cost from **one rate card** |
| — | retrieved doc ids and scores, and the score of the top chunk |
| — | `finish_reason`, and whether a fallback or escalation happened |

`prompt_version` and `model_version` are the two fields that make a quality regression
attributable. Without them the timeline shows a drop and offers no candidates.

---

## 4. Split the record — *prevents:* 12 GB/day, and your biggest PII surface

The trace store is the only place holding every prompt and every answer for every tenant. It is
a larger data-protection liability than the application database, and nobody treats it that way
because it is "just logs".

- **Skeleton, 100%, 400 days.** Numbers and enums only. It doubles as the cost ledger, so it has
  to be complete — a sampled cost record is not a cost record.
- **Payload, sampled, 30 days hot.** Prose. Expires by policy, not by disk pressure.

Write rate drops 12 GB/day → **~0.84 GB/day**; resident 4.8 TB → **~114 GB**. `solution.py`
derives both from the sampling policy rather than asserting them.

---

## 5. Sampling — *prevents:* keeping 2% of nothing useful

**Sample on the `trace_id`, deterministically.** Sample each span independently at 2% and you
keep 2% of spans and 0% of complete traces. A waterfall missing four of six spans is not a
debugging artefact.

**Decide at the root, propagate the decision.** A downstream service choosing for itself
produces orphans.

**Bias the sample, because errors are rare.** Errors are 3% of traffic; uniform 2% sampling
keeps 0.06% of them — about 12 examples a day across four classes. You cannot characterise a
failure mode from three examples.

| Kept | Rate | Why |
|---|---|---|
| errors, all classes | **100%** | 3% of traffic and 100% of the debugging |
| validation failures, refusals, guardrail blocks | **100%** | the outcomes an LLM system fails at |
| thumbs-down and human escalations | **100%** | the only free ground truth you get |
| everything else | **2%** | the unbiased baseline |

~5% of traffic kept, ~30k payloads/day, errors fully represented, bill 14× smaller.

---

## 6. Re-weight, or the dashboard lies — *prevents:* reporting a 61% error rate

The half of stratified sampling that gets skipped. Keep every error and 2% of successes, compute
the error rate over what you kept, and you get about **61%** — you have measured your sampling
policy, not your system.

Every retained trace carries a weight: `1` if kept by rule, `1/p` if randomly sampled.
Aggregates are weighted sums. The estimate comes back to 3.00% and mean latency to the truth;
the script asserts both.

Corollary: **quality scores go on the unbiased 2% slice, not the whole retained set.** Judging
the retained set means judging a corpus you deliberately filled with failures.

---

## 7. Redact at write, fail closed — *prevents:* erasure being impossible

Redact in-process, before the span leaves the application. Redaction on read is not redaction —
the raw text is already on disk, in the replicas and in last night's backup.

The redactor is on the hot path: a bounded regex pass over known shapes (email, phone, card,
national id) plus tenant deny patterns, with a hard time budget. Then the decision that
separates a design from a diagram: **if it throws or times out, drop the payload and keep the
skeleton**, and increment `redaction_failed`. Failing open would write raw PII during exactly
the incident where you are least able to notice.

Same asymmetry as everywhere: a dropped payload costs one trace, a leaked one costs a
notification to a regulator.

---

## 8. Error taxonomy — *prevents:* "error rate 3%" meaning nothing

| Class | What it means | Owner | Action |
|---|---|---|---|
| `rate_limited` | you exceeded a provider quota | capacity | more keys, spill to provider 2 |
| `timeout` | provider tail, or your budget is too tight | capacity | hedge, re-tune the timeout |
| `parse_failure` | the model stopped emitting your format | the prompt | bisect the annotations |
| `validation_failure` | it parsed and was wrong against the schema | the contract | repair or pin |
| `guardrail_block` | you stopped it deliberately | safety | usually correct — track the rate |
| `refusal` | the model declined | product | **not an error.** Track separately |

Counting refusals as errors cuts both ways: a rising refusal rate looks like an outage, and a
*falling* one — the model becoming compliant about things it should decline — looks like an
improvement.

---

## 9. Cut by model and prompt_version — *prevents:* an average hiding a broken model

A model serving 8% of traffic degrades from 90% groundedness to 55%. The global number moves
**about 3 points** and never crosses a 5-point threshold. Cut by model and it is a **35-point
collapse**, visible on day one. Latency and error rate say nothing at all — that is the trap in
this scenario, and `solution.py` measures it rather than claiming it.

So every quality and latency metric is cut by `(model, model_version, prompt_version, feature,
tenant)` — which immediately collides with §10.

---

## 10. Cardinality budget — *prevents:* the monitoring bill beating the inference bill

Three destinations, chosen by cardinality:

| Destination | Dimensions | Size | Use |
|---|---|---|---|
| **Metrics / TSDB** | model × feature × error_class | **256 series per metric** | alerts, 1s resolution |
| **Hourly rollup table** | + tenant, prompt_version | ~12k rows/day | per-tenant reporting, billing |
| **Columnar trace store** | everything | 240M skeleton rows | ad-hoc: "tenant X, validation failures, last week" |

Rows are cheap; **active series are not**. An hourly per-tenant rollup buys per-tenant
visibility at 1/500th the cost of a per-tenant label, and the only thing it costs you is
second-resolution alerting per tenant, which nobody has ever needed.

---

## 11. Quality proxies on the unbiased slice — *prevents:* the regression nothing else sees

Online and cheap, on every trace: retrieval top-score distribution, groundedness (fraction of
output sentences with a supporting retrieved chunk), refusal rate, escalation rate, schema pass
rate, output-length distribution, and user signals — thumbs, copy, edit, escalate-to-human.
Offline and expensive, batched nightly: an LLM judge on the 2% slice.

**And the number that sets your ceiling.** For a proxy at p ≈ 0.85, standard error is
`sqrt(p(1-p)/n)`:

| Daily sample | Standard error | Smallest detectable drop (2σ) |
|---|---|---|
| 200 | 0.025 | **5.0 points** |
| 12,000 | 0.0033 | **0.65 points** |

Your sample rate is not only a cost decision — it sets the **minimum quality regression you can
detect at all**. Say that out loud; it reframes sampling from thrift into measurement design,
and it is the same argument as establishing a noise floor before a model bake-off.

---

## 12. Change annotations — *prevents:* "it got worse Tuesday" with no candidates

Every prompt edit, model version pin, retriever config change, index rebuild and flag flip
writes a timestamped annotation onto the same timeline as the metrics; otherwise you bisect by
memory. You have lived this one: in the report generator the prompt **and** the grounding config
are versioned together, because either will move the groundedness number and you cannot
attribute the movement afterwards.

---

## What breaks first, in order

1. **Storage cost and PII exposure** — both, from one cause. 12 GB/day of prose is expensive
   *and* the largest concentration of tenant content you own. First because one lever (split,
   sample, redact at write) fixes both, and because nothing else here can lose a contract.
2. **Metrics cardinality** — 2.5M series. Second because it bites at the same volume but arrives
   a month later as an invoice rather than an alert, so it is always discovered late.
3. **Exporter backpressure onto the request path** — a synchronous exporter, or an unbounded
   queue and a dead collector, turns an observability outage into an application outage. Third
   because it is rarer but total: it takes the product down, not the dashboards.
4. **Trace-store query latency** — "every trace for tenant X with a validation failure last
   week" over 240M rows. Fourth because it degrades gradually and you can partition your way
   out: by day, sorted by tenant, columnar.
5. **Sampling bias making the quality numbers wrong** — no error, no alert, you simply believe a
   number that is false. Fifth because it fails with no signal at all, which is also why the
   representativeness check belongs in CI.
6. **Clock skew and orphan spans** — negative durations, broken waterfalls. Last because it is
   annoying rather than dangerous, but it destroys trust in the tool and people stop opening it.

---

## The follow-ups, answered

**"600k calls/day with full payloads — what is that, and what do you do?"**
12 GB/day, 4.4 TB/year raw, 4.8 TB resident at 400 days. Split the record: skeleton at 100% for
400 days (240 MB/day, doubling as the cost ledger), payload sampled at ~5% for 30 days. ~0.84
GB/day written, ~114 GB resident — and the saving is concentrated on the sensitive half.

**"You sample 2%. How is the error analysis still usable?"**
It is not a 2% sample. It is 100% of errors, refusals, validation failures and thumbs-down, plus
2% of successes as an unbiased baseline. Then every trace carries a weight and aggregates are
weighted, or the dashboard reports a ~61% error rate.

**"2.5M active series. Fix it."**
They came from putting `tenant` and `prompt_version` on every histogram. Move them: the TSDB
keeps model × feature × error_class (256 series per metric), an hourly rollup table keeps
per-tenant numbers as rows, the columnar store answers the rest ad hoc. You lose per-tenant
second-resolution alerting and nothing else.

**"Latency flat, errors flat, answers worse on Tuesday. Find it."**
Neither signal can see it, which is why the proxies exist. Pull groundedness and refusal rate
cut by `prompt_version` and `model_version`, overlay the change annotations, find the version
boundary at Tuesday's deploy. If the proxies show nothing, judge 50 traces from Monday against
50 from Tuesday — then add whatever distinguished them as a proxy, so next time it is a graph.

**"A tenant invokes erasure."**
Skeleton rows are pseudonymous and survive with the tenant id tombstoned; you need them for the
cost ledger. Payloads are deleted — which is why the payload store is partitioned **by tenant
and day** from day one, so this is dropping partitions rather than a delete-by-predicate over 30
days of objects. Then the parts people forget: the quality-scoring corpus, judge outputs that
quote the content, and backups. If you cannot delete from backups, say so and state the window.

**"The collector goes down for ten minutes."**
Nothing user-visible, by construction. The exporter is asynchronous behind a **bounded** queue —
420 spans/s × 600 s × 2 KB is ~500 MB, which is exactly why it is bounded and spills to local
disk. When it fills it drops by priority: payloads first, then skeletons, never metrics, and a
`spans_dropped` counter goes out on the path that never drops. An unbounded queue here is not
resilience, it is a delayed OOM inside the application process.

**"Refusal versus error?"**
An error means the system failed; a refusal means the model declined, which is often correct.
Different owners — errors to the platform, refusals to product. Track the refusal rate as a
first-class series in both directions: rising means over-restriction, falling can mean a
guardrail regression.

**"Is the quality sample representative?"**
Only the unbiased slice is, and only if it is drawn by a hash of the trace id rather than "first
N per hour", which correlates with time of day and therefore with tenant geography. Check it:
the slice's distribution over model, feature and tenant should match the population within
sampling error. That check belongs in CI on the sampler, because it breaks silently.

**"Smallest regression you can detect?"**
`sqrt(p(1-p)/n)`. At p = 0.85 and 12k samples/day, 2σ is 0.65 points; at 200 samples/day it is 5
points, so a 4-point drop is invisible. Pick the sample rate from the regression you need to
catch, not from the storage budget alone.

---

## One-line summary

> "Split every trace into a 400-byte skeleton kept at 100% and a 20 KB payload that is redacted
> at write, sampled deterministically on the trace id with all the errors kept, and re-weighted
> so the aggregates stay honest — then cut every metric by model and prompt version, because a
> global average is exactly what hides a broken model."

## The trap answer to avoid

Tracking latency and error rate and calling it observability. In an LLM system the regression
that loses you users moves **neither** — the model still answers in 1.8 seconds with a 200, and
the answer is worse. Describe a very good APM setup and you have described the monitoring for a
system that is not the one you were asked about.
