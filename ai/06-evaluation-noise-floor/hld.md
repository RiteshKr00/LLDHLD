# Evaluation as infrastructure

## 1. Why this is a platform problem, not a script
**Prompts and model ids are config, so they bypass code review.** They're also the most
frequently changed part of an LLM system. So the gate has to be *unavoidable* — which makes
evaluation infrastructure, not a notebook.

## 2. Numbers
4 features × 2 prompt edits/week × 50 weeks = **~400 config changes/year**, historically
unreviewed. Compare: every line of code reviewed. **That asymmetry is the whole argument.**

A golden set of 200 cases × 4 features = 800 scored generations per gate run. At 2s each
that's ~27 minutes serial — so **the harness must parallelise** or nobody will run it.

## 3. Determinism is the design constraint
| Metric type | Reproducible? | Use as a gate? |
|---|---|---|
| Recomputed from artifacts (structural, numeric, citation) | yes | **yes** |
| Embedding similarity | mostly | with a floor |
| LLM-as-judge | **no** | never — supplementary only |

A non-deterministic gate cannot distinguish a regression from variance. That's why the harness
is LLM-free.

## 4. Golden-set lifecycle — the part that rots
A golden set decays because production traffic drifts away from it. So:
- **source from sampled real queries**, not invented examples
- **version it in the repo** so a benchmark change is itself reviewed
- **refresh on a schedule**, and track *when* it was last refreshed
- **include known-bad cases**, not just happy paths
- keep a **held-out slice** you never tune against — and if you don't have one, say your
  numbers are directional

## 5. The gate contract
Three states — `pass` / `fail` / **`no-data`** — and no-data **blocks**. Thresholds as data
with hard/soft flags. Noise floor established before any comparison is believed.

## 6. Rollout after the gate
Offline gate → **canary** (small traffic share behind a flag) → guardrail metrics → full.
Because offline-good/online-bad is a real failure mode: your golden set is not your traffic.

Online guardrails: refusal rate, escalation rate, parse-failure rate, sampled groundedness,
and **user-edit rate** — the strongest implicit quality signal you get for free.

## 7. What to watch
Gate run duration (if it's slow it gets skipped) · flake rate (a flaky gate gets ignored, which
is worse than no gate) · golden-set age · **correlation between gate scores and production
signal** — if they don't correlate, you're gating on the wrong thing.
