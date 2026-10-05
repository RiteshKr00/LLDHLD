# AI-05 — evaluation, gates and the noise floor

## META
- difficulty: hard
- time: 15 min
- tags: evaluation, gates, noise-floor, ablation, honesty
- source: `06-evaluation-noise-floor/`

## PROMPT

> "You published two *failing* gates on your own benchmark. Walk me through why — and tell me
> about the bug you found in your own evaluation."

## CLARIFY

- **"Do you want the harness design or the bug?"**
  → *"The bug, then how the design prevents it."*
- **"Is this your code?"**
  → *(this is the boundary question — answer it before it's asked)*

## STEP 0 — Boundary (before anything else)

### CHECKPOINTS
- **States the boundary unprompted**: the 8-stage pipeline is a colleague's; the grounding, evaluation and inference-backend layers are mine
- Can name what's greenfield: `csr/eval/` ~640 lines plus tests, `eval/gold_facts.yaml`

## STEP 1 — Scope & stakes

### CHECKPOINTS
- Regulated document (ICH E3 clinical study report) → "looks good" is not a standard
- The stake: a wrong number in a regulatory draft
- Therefore reproducibility beats nuance

## STEP 2 — Mechanism

### CHECKPOINTS
- Harness is **LLM-free** and recomputes from **on-disk artifacts** — no model, no network
- **Why**: an LLM judge is non-deterministic, so you can't separate a regression from judge variance
- **Imports the production grounding module** so the scorecard can't drift from the runtime
- Gates declared as **data** with hard/soft flags → a gate can **block**, not just warn
- Names the five metrics and the failure mode each catches

## STEP 3 — The bug

### CHECKPOINTS
- Three compounding failures: gold facts keyed to the **wrong study id** → `n/a`; **`n/a` counted as a pass**; a regressed enrollment figure shipped under *"all hard gates pass"*
- The rule written down: **a hard gate with no ground truth must fail or block, never pass**
- **Generalises it**: the bug was **collapsing three states into two** — pass / fail / **no-data**
- Bonus: connects it to fail-closed — when the answer is unknown, the safe default is restrictive
- Says what triggered the check: *"too clean for a system I knew had rough edges — a green suite is a claim, not a fact"*

## STEP 4 — The noise floor

### CHECKPOINTS
- Re-ran **one** model **three times** on a shared index → numeric F1 0.675 / 0.677 / 0.677, spread **0.002**
- **Anything smaller than that is not a result**
- States the general principle: establish variance under a null change **before** attributing a delta
- Bake-off was controlled: only `generate → cite → assemble` re-run; retrieval, prompts, embeddings held constant → **model was the sole variable**
- Reports the **negative result**: all four within ~1 point; the retrieval scaffold moved quality more
- Explains why a negative result is valuable: it **reallocated effort** from model selection to retrieval

## STEP 5 — Precision about what the numbers mean

### CHECKPOINTS
- `185/185` proves **no fabricated citations** — every reference resolves to a really-indexed chunk
- **Does not** prove the cited chunk *supports* the claim — that's number support, 96.8% vs a 98% gate
- Content similarity was originally draft-vs-whole-536-page-PDF → cosine **0.087**, noise; fixed by scoring **per section**
- *"A metric that can't distinguish candidates isn't measuring quality"*

## STEP 6 — Honesty

### CHECKPOINTS
- Volunteers: grounding rate **58% against an 85% gate** — the system doesn't pass its own bar, and the harness's job is to say so
- No held-out split; a single gold set
- Wrote the harness *and* the gates — no independent review of thresholds
- Found the failed-open gate by **instinct, not by a test on the harness itself** — the harness needs its own tests
- Places LLM-as-judge correctly: supplementary signal on sampled traffic, never the gate

## TRAP

Quoting the metrics without their limitations. The strength of this whole story is knowing
exactly what each number does and doesn't cover — leading with "185/185" as a headline
undersells it and invites the takedown.
