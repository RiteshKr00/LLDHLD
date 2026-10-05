# The release gate at scale

> Every tier exists because a **number** demanded it; every check exists because a **failure**
> demanded it.

## 1. Numbers first

| Input | Value |
|---|---|
| Features gated | 4 — RAG chat, extraction, report generation, voice turn |
| Golden set | 800 cases (300 / 250 / 150 / 100) |
| Repeats per case | 3 |
| Full-tier run | 2400 calls · ~$0.0015/call · **~$3.60**, **~6 min** at 24-way |
| Smoke-tier run | 180 calls · **~$0.27**, **~30s** |
| PRs touching the manifest | ~8/day, ~4 pushes each → **32 gated runs/day** |
| Naive "full tier on every push" | **$115/day** and **3.2 hours** of CI wall clock |

**Little's Law, applied to CI rather than to production.** Peak merge rate is ~4/hour, each
holding a 6-minute full run: L = 4 × 0.1 = **0.4 concurrent runs**, each holding 24 provider
slots — so **~10 in-flight calls typically, 48 when a nightly overlaps a merge.** Production
holds ~140 concurrent (topic 16). The gate is a third of a production burst.

**What those numbers force:**

1. **Tiering.** $115/day and a 6-minute wait per push is how a gate dies — not deleted, bypassed.
2. **Content addressing.** An unchanged case must never be re-run.
3. **Quota isolation.** CI gets its own gateway key and bucket, or the release gate pages the
   on-call.
4. **3 repeats minimum.** At temperature > 0 a single run of a single case is a coin toss.

## 2. Tiers — what runs when

| Tier | Trigger | Scope | Cost / time | Blocks? |
|---|---|---|---|---|
| **Smoke** | every push | 60 stratified cases × 3 | $0.27 · 30s | yes, hard gates only |
| **Full** | merge to main | 800 × 3 | $3.60 · 6 min | yes |
| **Release** | RC tag | full + adversarial + cost/latency budgets | ~$5 · 10 min | yes |
| **Nightly** | cron, off-peak | full + noise floor (3 null pairs) + drift check | ~$25 | no, it files an issue |

Smoke cases are chosen for **coverage of failure modes**, not by volume — one per known
regression class. The noise floor is a nightly artifact, not a per-PR cost.

Tiered plus cached: **~$62/day, ~$700/month** at a 65 percent cache hit rate.

## 3. The manifest hash is both the trigger and the cache key

`manifest.lock` hashes every prompt template, model id and version, decode params, retrieval
params, chunker version, and the judge's own prompt and model. Two consequences fall out of one
hash:

- **Trigger:** manifest moved and no scorecard exists for the new hash → block. A prompt edit
  with no code diff is a gated change.
- **Cache key:** results stored on `(manifest_hash, case_id)`. A docs-only PR costs **zero
  calls**; an extraction-prompt change invalidates extraction only.

Production reads the pinned hash from the deploy artifact. That is also the answer to "who can
change a production model": not through a console.

## 4. The golden set is a maintained asset, not a fixture

Stratify by feature, tenant type and query class, in production's proportions. Every case carries
provenance — sampled query, bug report, incident id — plus the labeller and date. **Budget the
labelling**: 800 cases at ~4 minutes each is a person-week to build and roughly a day a month to
maintain. Say that out loud; teams that don't budget it are the teams whose set rots.

Refresh: a weekly stratified sample becomes a PR; every incident becomes a case; every canary
rollback donates its breaching sessions.

## 5. Baselines — "compared to what?"

The baseline is the scorecard pinned to main's current manifest hash, re-materialised on every
merge. Two rules that stop the common failures: **never compare against a run older than the last
merge** (you diff against a fortnight-old world), and **never re-baseline to make a red gate go
green** without a reviewed diff naming the cases you are accepting.

## 6. Canary and rollback

5 percent behind a flag → 25 → 100, with per-feature guardrails (see `diagrams.md` §4) and
automatic rollback on breach. Rollback is a **flag flip**, seconds, no deploy. The guardrail
thresholds need their own noise floors: online metrics are noisier than offline ones, and an
un-floored guardrail auto-rolls back on a quiet Tuesday.

Extraction and report generation get a **shadow** stage before the canary — run the candidate on
live traffic, score it, serve the incumbent — because a wrong extraction is worse than a slow one.
Chat and voice go straight to canary; a shadow can't measure interruption or perceived latency.

## What breaks, in order

1. **Golden-set rot** — silent, and it fails towards green. Everything else here is loud.
2. **Gate bypass** — cost and wall clock push people around it. A 40 percent override rate is
   theatre with a green tick.
3. **Flake** — one under-floored threshold, and the team stops believing any red build.
4. **Baseline staleness** — diffs against a world that no longer exists.
5. **Judge drift** — the provider rolls a floating alias and every historical score becomes
   incomparable overnight. Pin the version.
6. **Label rot** — the *right answers* go stale as intended behaviour changes, and the gate starts
   defending last quarter's spec.

## Degradation — and it differs by what failed

Separate the two things a naive design conflates:

- **A metric has no data** → the system is telling you it cannot see → **block.** Never a pass.
- **The harness could not run at all** (provider outage, CI runner died) → that is an
  infrastructure failure, not a quality signal. It blocks the *release*, but there is a signed
  break-glass: a named approver, a TTL, an audit entry, and the run queued to execute
  retroactively. The cache carries most of it anyway — unchanged cases need no provider.

Per feature, the degraded gate also differs. Extraction cannot ship un-evaluated at all. Chat can
ship on the smoke tier plus a tightened canary (1 percent, halved guardrail thresholds). Say which
and why; "we block everything" and "we wave it through" are both the wrong answer.

## Observability

Per feature and per gate, never aggregate: pass/fail/no-data counts, **coverage** beside every
metric, per-case churn (fixed vs broken, not net), run cost, wall clock, cache hit rate.

**Leading indicators — these move before anything shows up as a bad release:**

- **gate override rate** — the pipeline is being routed around
- **golden-set drift distance** — embedding distance between the set and a rolling production
  sample; it widens for weeks before the gate starts lying
- **flake rate on null re-runs** — thresholds slipping under their floors
- **judge-vs-human agreement** on the calibration set — the judge moving under you
- **per-case churn volume** — a release that fixes 20 and breaks 18 is not a stable release, even
  when the mean says it improved
