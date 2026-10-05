# The feedback flywheel — explained

**Related:** topic 06 is the noise floor and the deterministic harness; topic 22 is the CI gate this
feeds; topic 30 is the redaction layer it reuses. This is the thing that stops topic 22's golden set
becoming a museum.

**Your version, and the boundary.** On CSR-Exp you own the grounding and evaluation layers: five
deterministic metrics, gates declared as data with hard/soft flags, a measured noise floor. Those
metrics are the 93%-precision signal at the top of the table below — **you already have the best
signal in this design and it isn't a user signal at all.** The honest gap: that golden set is
`gold_facts.yaml`, curated by hand, with nothing feeding it from production. Say that plainly.

---

## 1. The numbers that force the design

| Input | Value |
|---|---|
| Production calls | **600k/day** — chat 400k, voice 120k, extract 50k, report 30k |
| Genuine defect rate | ~1.5% → **9,000 bad answers/day** |
| Signal events | **~13k/day**, collapsing to **~11.5k distinct requests**, just under 2% of traffic |
| Precision of that pool | **~39%** — three in five candidates are not defective |
| Recall of that pool | **~50%** — half your defects emit no signal at all |
| Feedback-widget engagement | 440 down + 900 up = **0.22%** |
| Review capacity | 2 reviewers × 4 productive hours, 90s/case → **300 labels/day** |
| Selection ratio | 300 of ~11,500 = **2.6%. You discard 37 candidates in 38.** |
| Labelling cost | 8 h/day × $30/h loaded ≈ **$5.2k/month**, ~7% of the $72k/month inference bill |
| Golden set | **800 cases**, net growth ~10/week |

**What those numbers force:**

- **A 2.6% selection rate means the sampler *is* the system.** Collection is a logging call.
- **39% precision means a golden set built straight off the signal is 60% noise** — and noise in an
  eval set doesn't average out, it silently redefines "good".
- **50% recall means the pool can never tell you your defect *rate*.** That comes from deterministic
  checkers on 100% of traffic; the pool tells you *what* is wrong, not *how often*.
- **$5.2k/month against a $72k/month bill.** Labelling is cheap in dollars and scarce in hours — solve
  this with more budget and you have misread which resource binds.

> **You are not collecting feedback. You are spending a fixed labelling budget, and every layer
> exists to stop that budget being wasted on the wrong 300 cases.**

---

## 2. Signal capture — the best signal has no user in it

**Failure it prevents:** waiting for a user to tell you something a program could have told you free.

Run the deterministic checkers on **100% of traffic**: grounding rate, schema validity, citation
resolution, numeric support. Microseconds each, they fire on every call, and measured against human
labels they are the most precise signal you own. Then the user signals — each **calibrated**, never
trusted raw:

| Signal | Events/day | % of traffic | Precision | What it actually means |
|---|---|---|---|---|
| **Deterministic checker fail** | 1,900 | 0.32% | **93%** | no user involved — the cheapest signal you own |
| Downstream correction (a field fixed later) | 480 | 0.08% | 81% | delayed ground truth |
| Escalated to a human | 620 | 0.10% | 74% | strongest *user* signal, and the rarest |
| Semantic edit — chat + report only | 1,000 | 0.17% | 68% | a real content change |
| Regenerate within 60s | 3,200 | 0.53% | 42% | often just "make it shorter" |
| Thumbs-down | 440 | 0.07% | 25% | the angry minority, self-selected |
| **Any manual edit** — chat + report only | 3,300 | 0.55% | **22%** | **the trap** — four in five are style |
| Abandonment | 2,000 | 0.33% | 16% | the noisiest thing you can log |
| Copied / sent verbatim | 21,000 | 3.5% | — | the *positive* class, and you need it |

**Note the surface column.** Edit signals cannot fire on a voice turn — no edit box. Instrument on
edits alone and **20% of your traffic contributes nothing to the eval set**, structurally, for a year
before anyone notices.

**Co-firing is the free win.** Edit alone is 22% and regenerate alone is 42%, but **edit AND regenerate
on the same request is over 90%** — nobody regenerates something they merely wanted shorter. Two weak
signals agreeing beat any single strong one, and the feature costs nothing. Combine them as calibrated
likelihoods, not as a vote count — with two caveats. It assumes conditional independence given the
defect, which real signals only approximate, so you **measure** the co-fire precision rather than
deriving it. And **a blended number can be a lie told by one tenant**: edits calibrate at ~27% for a
normal tenant and ~4% for the loud one, blending to the 22% above.

### Where those precision numbers come from

**Failure it prevents:** treating "the user edited it" as a label — the golden set becomes a style
guide, the gate blocks releases for being terse, and nobody can work out why.

Quarterly, take **~150 events per signal type**, have a reviewer label them
*defective / stylistic / neutral*, compute per-signal precision. At n=150, p≈0.25 that's ±7 points at
95% — coarse is fine; you need to know edits are 22% and not 90%. Cost: ~1,200 labels ≈ **four days of
budget a quarter**, 5% of the annual total, and the highest-return week you will spend. **Re-run it
whenever a surface changes** — ship a "make this shorter" button and the edit signal's precision
collapses, because you just gave stylistic dissatisfaction its own channel.

---

## 3. Redaction at capture, failing closed

**Failure it prevents:** your eval store becoming your worst liability. It is the one datastore that
deliberately keeps your ugliest outputs, forever, outside the retention policy of the system they came
from.

1. **Redact in-process, before the payload leaves the request.** ~2ms on the hot path buys a queue and
   a worker pool that have never held raw PII. Redact in the worker instead and the queue is a PII
   surface — and queues get replayed.
2. **Typed reversible placeholders, not deletion.** `<PERSON_1>`, `<DATE_2>`, `<DOSE_3>`: structure and
   the failure survive, identity does not. Scrub numbers and a hallucinated dose is indistinguishable
   from a correct one — you destroyed the case you were keeping. *In your clinical-report work the bug
   **is** the number.*
3. **Fail closed.** Redactor down → drop the payload, keep the outcome record. The opposite of the
   gateway's fail-open on rate limiting (topic 16); the asymmetry is the argument, since a missed rate
   limit costs money and a missed redaction is a breach — the same reasoning as your fail-closed
   tenant scoping.

Store two things: an **outcome record** (200 bytes, no text) for all 600k calls, and **redacted text**
only for the ~11.5k candidates plus a random control slice — 44 GB/year and 28 GB/year. Storage is not
the constraint here; exposure is.

---

## 4. Stratified sampling, the admission bucket, and the priority score

**Failures it prevents:** three, and they are different.

*Bias.* Your loudest tenant is **4% of traffic and ~13% of the candidate pool** — their users click,
edit and bail an order of magnitude more than anyone else's. Filter on thumbs-and-edits, the
instrumentation everyone actually ships, and they take **a fifth of your labelling budget**, on the two
surfaces that have an edit box. Now your gate enforces one tenant's house style on 500. Fix: quota per
**feature × tenant tier × model × confidence band**, a **floor per cell** so the long tail is never
zero, a **cap per tenant at ~2× traffic share**. The cap is not redundant with a good score — the score
is calibrated globally, so it under-penalises a tenant whose base click rate is anomalous.

*The landfill.* If admission outruns review the queue grows without bound: capacity 300/day against
admission 450/day is a 4,500 backlog by day 30, a **15-day wait**, past the point where the prompt
version that produced the case still exists. **A stale label is worse than no label, because it still
counts.** So **admission is a token bucket set at review capacity** — the score decides *which* cases
get in, never *how many*. Hard-expire at 21 days, roughly two release cycles.

*Redundancy.* Labelling the four-hundredth variant of a bug you fixed last sprint. That is what the
score is for:

```
priority = calibrated_posterior × novelty × strata_deficit
```

**posterior** = P(defective | this exact signal set), from §2, not a vote count. **novelty** =
embedding distance to the nearest case already in the set *and* already picked this batch, decayed hard
on repeats. **strata_deficit** = distance below quota, recomputed as the batch fills. Add
**disagreement** where it is free — in a cascading router, "cheap model and escalation model answered
differently" is uncertainty you already compute, and boundary cases are worth more per label.

---

## 5. The review queue — a rubric, not a text box

**Failure it prevents:** unscoreable labels. "This is bad" cannot gate a release.

Three axes, three points each — **factual correctness** (grounded / unsupported / contradicted),
**completeness**, **format compliance** — plus a mandatory **failure-mode tag** from a closed
vocabulary, plus a **corrected output** wherever the reviewer can produce one. The corrected output is
what turns a complaint into an eval case. Double-label **10% of the queue** and track Cohen's kappa:
**below 0.6 the rubric is broken, not the reviewers**, an instruction problem no amount of extra
labelling fixes. Kappa is the leading indicator on label quality — it moves before the set is
measurably wrong.

---

## 6. The golden set has four tiers, and only one comes from the flywheel

**Failure it prevents:** a set of nothing but failures — the mistake that survives longest, because it
looks rigorous.

| Tier | Cases | Source | Runs |
|---|---|---|---|
| Regression | 420 | promoted from the signal pool | every gate |
| **Must-not-break** | 260 | **uniform random from the accepted class** | every gate, **hard gate at 97%** |
| Adversarial | 120 | hand-written against known risks | every gate |
| Archive | ~150, growing | retired from regression after 8 clean weeks | monthly only |

Without the must-not-break tier, **a model that refuses everything scores brilliantly** — it never
makes an ungrounded claim, so it passes most of your regression cases. `solution.py` measures it: on a
negatives-only set the degenerate model beats the genuinely better one by 45 points, and only the
must-not-break tier as a *hard* gate blocks it — blend it into a composite and the maths still lets it
through. That tier is sampled **uniformly at random from the copied/verbatim class**, not from the
signal pool: different sampler, different purpose.

---

## 7. Promotion, quarantine, retirement, versioning — and the loop's own metric

**Failure it prevents:** silent benchmark drift, its quieter twin saturation, and optimising a metric
users cannot feel.

- **Promotion** — 1,500 labels/week, novelty and strata admit ~2% → **~30 cases/week**. The other 98%
  aren't wasted: they feed the SFT and few-shot pool, which wants volume and tolerates noise the
  gating set cannot.
- **Quarantine** — two weeks in a tier that runs nightly and **does not gate**, catching the case that
  is itself mislabelled before it can block a merge.
- **Retirement** — pass 3/3 for 8 consecutive weeks and a case drops to the monthly archive. Net
  ~10/week, so 800 → ~1,300 in a year rather than 3,000. **Saturation is why this exists**: a pass rate
  climbing to 98% and staying there means the set stopped discriminating, not that you got better.
- **Versioning** — immutable, content-addressed, hash joins topic 22's `manifest.lock`. Scores read
  `score @ goldenset-v34` and a cross-version comparison is **refused by the harness, not warned
  about**. Otherwise someone adds 50 hard cases, the score drops three points, and a week goes into
  hunting a regression that was a dataset change.
- **Feedback on the feedback** — per release, record the offline composite delta and the 7-day
  production defect-signal delta; rank-correlate over eight releases. **Above ~0.5 the gate earns its
  keep; below ~0.2 your eval set measures something that isn't happening to users**, and the fix is
  coverage, not thresholds. This is the metric that says whether to keep running any of the rest.

---

## 8. What breaks first, in order

1. **Signal quality.** "Edited" conflates *wrong* with *I'd have said it differently* at 22% precision.
   First because it is **silent** — the pipeline runs, the queue fills, labels arrive, and the set
   quietly becomes a style guide. Everything else here produces a symptom.
2. **Labelling throughput.** 300/day against ~11,500 candidates: the queue becomes a landfill and
   reviewers label a model version that no longer exists.
3. **Golden-set drift.** Unversioned additions turn a dataset change into a phantom regression.
4. **Class imbalance.** All negatives, so the gate cannot see a refuse-everything regression.
5. **PII in the eval store.** Slow, invisible, then a legal problem all at once.
6. **Saturation.** 98% pass rate, nothing discriminated, everyone reassured.
7. **Reviewer drift.** Kappa decays as reviewers grow private conventions the rubric never named.

---

## The follow-ups, answered

**1 · "Thumbs-down engagement is 0.07%."** One weak feature, never the dataset. Replacements in
precision order: checkers 93%, downstream corrections 81%, escalations 74%, semantic edits 68%. How
do I know they're better? I measured all of them against human labels on the quarterly calibration
sample. That number *is* the evidence; without it every signal is a guess with a dashboard.

**2 · "Wrong versus stylistic preference."** Measure the base rate — raw edits are 22% defective, so
the signal is a prior, not a label. Use the **semantic** diff rather than the character diff: 68%
against 22% for the same user action. Exploit co-firing: edit *plus* regenerate is over 90%. Then the
rubric forces the reviewer onto an axis, so the distinction is recorded rather than inferred.

**3 · "Which 300, and why not the worst 300?"** Because "worst" in practice means "tripped the two
signals we happened to instrument", and those are the least precise ones we have.
`posterior × novelty × strata_deficit`, capped per tenant, floored per cell. `solution.py` measures the
swing on the same 30-label budget: yield roughly 20% → 90%, the loud tenant 20% → under 7%, four
surfaces represented instead of two.

**4 · "The loudest tenant."** Uncapped they take a fifth of the budget and you gate releases on their
house style. Cap at ~2× traffic share, floor every cell — then investigate rather than only cap. A
tenant signalling 3–4× base either has a genuinely worse experience (a retrieval corpus problem, a
prompt that doesn't fit their domain) or a UI that makes editing cheap, and their edit signal
calibrating at 4% against everyone else's 27% points hard at the second.

**5 · "Pass rate is 98%."** Something is wrong: either the set saturated — everything in it is a solved
failure mode — or it drifted easy because novelty scoring decayed. Check the pass-rate trend (flat-high
is the tell), the age distribution of the regression tier, and the gate-to-production correlation.
Retire the solved tier, then go find the cells the sampler has been starving.

**6 · "Offline improved, production got worse."** **Production wins, always** — offline is a proxy, the
signal is the thing. Roll back first, diagnose second: either the set doesn't cover what regressed (a
coverage gap, the usual answer, and an argument *for* the flywheel) or the metric is gameable and the
change gamed it. Concretely, pull the last 7 days of new candidates and check whether their failure
modes exist in the set at all. If not, they are the top of the priority queue.

**7 · "You may not store prompts or responses."** It still runs, on less. Outcome records only: signal
fires, feature, tenant, model version, checker results, embedding vector, latency, tokens — enough for
defect-rate tracking, calibration, drift and strata coverage, everything except the review queue. For
labelling you then get two options: **human-in-place review**, where the reviewer scores inside the
production surface and only the score leaves, or a **synthetic golden set** hand-written to match the
observed failure-mode distribution rather than the observed text. Both are worse; name which, and name
what you lose.

**8 · "Half the labels are from a retired prompt version."** Admission exceeded capacity, so the queue
head aged past two release cycles. Cap admission with a token bucket, hard-expire at 21 days, and
**stamp every candidate with the resolved prompt and model version at capture** so staleness is
queryable rather than discovered. Alarm on queue-age p95 — the leading indicator.

**9 · "Stop the golden set changing under a comparison."** Content-address it; the hash goes in the same
`manifest.lock` as prompts and model ids. Every score carries its version, and the harness **refuses** a
cross-version comparison rather than warning — a warning gets ignored the first busy afternoon. New
cases land in quarantine, which gates nothing, so adding data can never move a gating number.

---

## One-line summary

> "Deterministic checkers on all 600k calls give me a 93%-precision signal with no user in the loop;
> user signals get *calibrated* per type before they're trusted, because raw edits are only 22%
> defective; a stratified, novelty-weighted sampler spends the 300-label/day budget on the 2% of
> candidates that are uncertain and under-represented; labels arrive through a rubric with a corrected
> output; cases promote through quarantine into a versioned golden set that keeps a must-not-break
> tier — and then I check whether the gate's deltas actually predict the production signal, because
> otherwise the whole loop is decorative."

## The trap answer to avoid

Collecting thumbs up/down and calling it an eval set. Engagement is 0.22% and self-selected toward the
angry, so you'd be gating on a biased sample of a rounding error. The subtler version — the one that
catches good candidates — is treating "the user edited it" as ground truth. It is 22% precise. Build
the calibration step before anything downstream of it, or everything downstream is measuring taste.
