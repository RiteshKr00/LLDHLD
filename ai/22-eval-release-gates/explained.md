# Eval and release gates in CI — explained

**Related:** topic 06 is the deep dive on the noise floor and the tri-state gate; topic 11
treats the eval gate as one layer of a multi-model platform. This scenario is the pipeline that
wraps both.

**Your version of this:** the evaluation and grounding layers of CSR-Exp are yours — five
deterministic metrics, gates declared as data with hard/soft flags, a measured noise floor, and
the `n/a`-counted-as-pass bug that shipped a regressed figure under *"all hard gates pass"*. The
8-stage pipeline skeleton around it is a colleague's. State that boundary before you claim
anything.

**And the honest gap.** On the voice-persona product and the HR platform you have prompts and
retrieval config moving through PRs, but no gate on them. Say that plainly — "I have the harness
on one system and I'd generalise it" is a stronger answer than implying you run this everywhere.

---

## 1. The numbers that force the design

| Input | Value |
|---|---|
| Features gated | 4 — RAG chat, extraction, report generation, voice turn |
| Golden set | **800 cases** (chat 300, extraction 250, report 150, voice 100) |
| Repeats per case | **3** — one run cannot see past its own variance |
| Full-tier run | 2400 calls ≈ **6 min** at 24-way concurrency, **~$3.60** |
| Smoke-tier run | 60 stratified cases × 3 = 180 calls ≈ **30s**, **~$0.27** |
| PRs touching the manifest | ~8/day, ~4 pushes each → **32 gated runs/day** |
| Naive cost of "full tier on every push" | 32 × $3.60 = **$115/day** and **3.2 hours of CI** |

**What those numbers force, in order:**

- **$115/day and a 6-minute wait per push is how a gate dies.** Not by being deleted — by being
  bypassed. So the pipeline is **tiered** (smoke on push, full on merge, floor nightly) and
  **content-addressed** (an unchanged case is never re-run). Cache hit rate on real traffic is
  60–70 percent, which takes the bill to roughly **$700/month**.
- **3 repeats × 800 cases is the minimum honest run**, because at temperature > 0 a single run
  of a single case is a coin toss dressed as a measurement.
- **Peak CI concurrency is ~24 in-flight provider calls, bursting to 48** when a nightly overlaps
  a merge. Production holds ~140 concurrent (topic 16's Little's Law figure). **Your release gate
  is a third of a production burst**, so it needs its own gateway key, its own token bucket and a
  hard concurrency cap — or the gate becomes the incident.

---

## 2. The framing: prompts are config, and config bypasses review

A code change gets a diff, a reviewer and a test suite. A prompt change gets a text edit, and if
it lives in a database it gets nothing at all. Same for `model="…"`, `temperature`, `top_k`,
`chunk_size`, and the embedding model id.

**So the first thing the pipeline needs is not a metric. It's a definition of "what changed".**

Everything that can move the output goes into a `manifest.lock`: a content hash of every prompt
template, the model id and version, decode params, retrieval params, the chunker version, and the
judge's own prompt and model. The gate keys on that hash. If the manifest moved and no eval ran
against the new hash, the merge blocks — even if not a single line of Python changed.

This also answers "who can change a production model": nobody, through a console. Production
reads the pinned hash from the deploy artifact. There is a break-glass path (§ *degradation* in
`hld.md`), and it auto-opens a PR.

---

## 3. The layers, each named by the failure it prevents

### Manifest lock — *prevents:* the most frequent change bypassing the most review
Covered above. Without it your gate is a code gate, and code is not what moves quality.

### Golden set per task, versioned in the repo, with provenance — *prevents:* "it feels better"
Each case carries where it came from — sampled production query, a bug report, a specific
incident — plus who labelled it and when. Provenance is not bookkeeping: it's how you argue about
a case six months later, and it's how you spot that 60 percent of your set came from one tenant's
onboarding week.

### Deterministic scorers first — *prevents:* judge variance masking a regression
Schema conformance, reference resolution, numeric support, exact-match on extracted fields,
refusal correctness, citation grounding. No model, no network, same input → same score forever.
Reach for a judge only for the residue that genuinely cannot be computed.

### The noise floor, measured under a *null* change — *prevents:* reading variance as a result
Re-run the identical config and diff it against itself. The spread is the floor; anything smaller
is not a result. On CSR-Exp that was `0.675 / 0.677 / 0.677` → **0.002**, which is how you know a
four-model spread of one point was noise and retrieval was the real lever.

Two refinements this pipeline adds: you need **a per-case floor as well as a composite floor**
(the composite floor is √n smaller and will not protect an individual case), and you set the
threshold at **two to three times** the observed spread. A floor set at exactly the observed
maximum flags one case in two.

### Paired per-case comparison — *prevents:* an aggregate hiding equal amounts of fix and break
This is the one most candidates miss. A candidate that fixes six cases and breaks seven leaves
the composite score **unchanged to four decimal places**. `solution.py` demonstrates exactly that.

So the gate is not "did the mean go down". It's: **any case that passed at baseline and fails now,
by more than the per-case floor, is a hard block regardless of the aggregate.** Report fixes
separately as a win. A mean is a summary; a release is a set of behaviours.

### Gates declared as data, with hard/soft flags — *prevents:* a warning nobody reads
Thresholds in config, not scattered assertions. Each gate declares `hard | soft`, its threshold,
its owner and its metric. A soft gate annotates the PR; a hard gate blocks the merge. If every
gate is an assertion buried in a test, you cannot answer "what are we currently gating on?" —
and nobody can change a threshold with a reviewed diff.

### Tri-state — pass / fail / **no-data**, and no-data blocks — *prevents:* the gate that fails open
Your bug, and the best story in this scenario. Gold facts keyed to the wrong study id →
the metric returned `n/a` → `n/a` was coerced to a boolean `True` → a regressed enrolment figure
shipped under *"all hard gates pass"*.

**The generalisable lesson: the bug was collapsing three states into two.** With a boolean, "no
data" must become pass or fail, and the comfortable default makes every un-evaluable gate silently
green. Same shape as fail-closed tenant scoping on the voice product — **when the answer is
unknown, the safe default is the restrictive one.** Connecting those two is the signal.

Add the second half of it: **coverage is itself a gate.** A metric that reports 0.95 over a third
fewer cases than baseline has not held steady; it has stopped looking.

### The harness imports the production module — *prevents:* scorecard drift
Do not reimplement the grounding rule in the harness. Import it. Reimplemented scoring is how
scorecards start lying: the runtime changes, the metric doesn't, and the number stays green while
meaning nothing. On CSR-Exp the harness calls the same grounding code the pipeline calls.

### Cost and latency are gates, not dashboard panels — *prevents:* buying quality with p95
A prompt that adds 800 tokens of few-shot examples can genuinely improve quality and simultaneously
raise cost per call 27 percent and p95 by 18 percent. If only quality is gated, that ships.
Gate `tokens/request`, `cost/request` and `p95` with their own thresholds, against the same baseline.

### Tiering and a content-addressed cache — *prevents:* the gate people bypass
Smoke tier (60 stratified cases, ~30s) on every push; full tier on merge to main; noise floor and
drift checks nightly. Results are cached on `(manifest_hash, case_id)`, so re-running an unchanged
config costs **zero calls**, and a change to the extraction prompt invalidates extraction only.

**Feedback latency is a design constraint, exactly like p95.** Thirty seconds gets used; twenty-five
minutes gets a `skip-eval` label, and then you have no gate and a false sense of one.

### Canary with guardrails, defined per feature — *prevents:* offline-good, online-bad
The golden set is a sample of a past distribution. Passing it is necessary, never sufficient.
Ship behind a flag at 5 percent with guardrail metrics that differ per feature:

| Feature | Online guardrails |
|---|---|
| RAG chat | refusal rate, empty-retrieval rate, thumbs-down rate |
| Extraction | schema-parse failure rate, repair-prompt rate |
| Report generation | grounding rate on sampled sections, human-edit distance |
| Voice | p95 time-to-first-token, barge-in rate, call-abandon rate |

Auto-rollback on breach, and **the breaching sessions become golden cases**. That loop is what
keeps the set alive.

### LLM-as-judge as a supplementary signal only — *prevents:* gating on a coin toss
A judge is useful for subjective quality on sampled traffic. It is not a gate, because it is
non-deterministic: you cannot separate a regression from judge variance, which is the entire job.
If you use one anyway: pin the judge model **version**, put its prompt in the manifest, calibrate
it against human labels on a held-out set and publish the agreement rate, and keep the gate **soft**.

---

## 4. What breaks first, in order

1. **Golden-set rot.** It stops representing production traffic — new tenants, new document types,
   new phrasings — so the gate passes while users suffer. **It's first because every other failure
   here is loud and this one fails silently, in the direction of a green board.** Fix: a weekly
   stratified sample of real traffic becomes a refresh PR, and every incident becomes a case.
2. **Gate bypass.** Cost and wall clock make people route around it. A gate with a 40 percent
   override rate is theatre.
3. **Flakiness.** One under-floored threshold produces a red build on a null change; two of those
   and the team stops believing any red build.
4. **Baseline staleness.** "Compared to what?" is unanswered — main moved, the baseline scorecard
   didn't, and you're diffing against a fortnight-old world.
5. **Judge drift.** The provider rolls the judge model under a floating alias and every historical
   score becomes incomparable overnight.
6. **Label rot.** The *right answers* go stale as the product's intended behaviour changes, and the
   gate starts defending last quarter's spec.

---

## The follow-ups, answered

**1 · "Where did the 800 cases come from, and how do you keep them representative?"**
Three sources, in this order: stratified sampling of production traffic (by feature, tenant type
and query class), every incident and bug report, and hand-written adversarial cases for the failure
modes you know about. Keep it alive with a weekly refresh PR and a **drift check**: embed a rolling
sample of production queries, embed the golden set, and track the distance between the two
distributions. When it widens, the set is rotting — that's a leading indicator, not a post-mortem.

**2 · "The composite moved 0.4 percent. Ship or block?"**
"I can't answer that without the noise floor." If the floor is 0.2 percent it's a result worth
investigating; if it's 0.5 percent it's nothing. And **the composite is the wrong number to decide
on anyway** — show me the paired per-case diff. Six fixed and seven broken looks identical to zero
change in the mean, and the seven are what your users will feel.

**3 · "Why not LLM-as-judge as the gate?"**
Because it is non-deterministic, so the gate cannot distinguish a regression from judge variance —
and the whole point of a gate is that distinction. It also drifts silently when the provider updates
the model, and it correlates with response length more than with correctness. Where it belongs:
a **soft**, supplementary signal on subjective quality, version-pinned, calibrated against human
labels, with the agreement rate published. Placing it correctly is a better answer than dismissing it.

**4 · "A hard gate has no data for a third of the cases."**
It blocks. `no-data` is a third state and it is never a pass — that's the bug I shipped once and
wrote the rule down for. Practically the PR gets: *"grounding gate: no data for 150 of 800 cases
(report feature, gold key mismatch) — BLOCKED"*, which is a diagnosis rather than a red cross.
Coverage is reported next to every metric for exactly this reason.

**5 · "The provider is down. Do you block every merge in the company?"**
Distinguish two things that a naive design conflates. **A metric with no data blocks** — the system
is telling you it can't see. **A harness that could not run at all** is an infrastructure failure,
not a quality signal: it blocks the *release*, but there's a signed break-glass with a named
approver, a TTL and an audit entry, and the run is queued to execute retroactively. The cache also
carries you: unchanged cases need no provider at all. Being able to separate "unknown quality" from
"unknown infrastructure" is the senior half of this answer.

**6 · "Offline is up, the canary's thumbs-down rate is up."**
Online wins, always — offline is a proxy and online is the thing. Roll back first, diagnose second.
Then the important move: the disagreement means **your golden set is missing the cases users care
about**, so mine the thumbs-down sessions, label them, add them, and confirm the new set reproduces
the regression offline. A canary catch that doesn't feed the golden set will happen again.

**7 · "How do you stop the harness drifting from production?"**
Import the production modules rather than reimplementing them, run the harness against the same
container image as the deploy, put the manifest hash in both the scorecard and the deploy artifact,
and assert at startup that the harness's resolved config hash equals the one under test. A scorecard
that can't name the exact configuration it scored is a rumour.

**8 · "Someone hotfixes a prompt in the admin UI at 2am."**
If that's possible, the design already lost — but you handle it: the change is written to the
config store **with a TTL**, it emits a loud event, it auto-opens a PR with the diff, and it expires
back to the pinned manifest unless that PR merges through the gate within 24 hours. Break-glass with
an expiry and an audit trail beats a policy that says "please don't".

**9 · "The gate takes 25 minutes and people bypass it."**
Then the gate is the problem, not the people. Tier it (30-second smoke on push, full on merge),
cache on the manifest hash so unchanged cases cost nothing, parallelise to 24-way, and cut the smoke
tier to a stratified 60 cases chosen for coverage of failure modes rather than volume. Then measure
**override rate** as a first-class metric and treat a rise in it as a pipeline defect.

---

## One-line summary

> "Prompts and model ids are config, so I hash all of it into a manifest and gate on that hash;
> the golden set is versioned with provenance and refreshed weekly from real traffic; scorers are
> deterministic and imported from production; I measure the noise floor before believing any delta;
> gates are data with hard/soft flags and three states, where no-data blocks; and I compare per case,
> because a candidate that fixes six and breaks seven has an identical mean."

## The trap answer to avoid

Naming an LLM judge as your release gate. It is non-deterministic, so you cannot separate a
regression from variance — you have built a report and called it a gate. The close second is
gating on the aggregate score alone: it is the specific mistake that lets a change through which
breaks seven cases and improves six.
