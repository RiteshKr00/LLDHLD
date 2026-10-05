# The fine-tuning pipeline in production

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Examples | ~8,000 | LoRA territory |
| Training | ~3.5 GPU-hours, ~£7 | 6% of the effort |
| Data work | ~60% of effort | plus 20% on eval and baseline |
| LoRA adapter | ~80 MB | vs ~14 GB full |
| 3 tasks, LoRA | 1 base + 3 adapters | vs 3 base copies |
| Rollback | pointer flip, seconds | base untouched |

## 2. The pipeline

1. **Justify** — format, style, latency or cost. Not knowledge. Written down.
2. **Fix the eval set and the held-out split.** Before anything else.
3. **Build the prompted baseline** and score it. This is the gate.
4. **Curate**: source, label, dedup, near-duplicate detect, **decontaminate by normalised hash**.
5. **Version the dataset** with content hashes, as an immutable artefact.
6. **Train** LoRA. Record dataset version, base revision, hyperparameters, seeds, library versions.
7. **Evaluate**: task metric **and** general-capability regression suite.
8. **Gate**: must beat the prompted baseline on the chosen axis, and not regress general capability.
9. **Serve** via vLLM behind the OpenAI-compatible gateway, addressed by task name.
10. **Keep the baseline live** as the rollback target.

Steps 2 and 3 before step 4 is the ordering that matters. A split chosen after seeing results is
not held out.

## 3. The gate

Two conditions, both required:

- Beats the **strongest** prompted baseline on the axis being bought — quality, or cost per call
  at equal quality, or p99 latency. Name the axis.
- No material regression on the general-capability suite, with refusal behaviour treated as a
  hard fail rather than a scored metric.

A candidate that passes one and fails the other does not ship.

## 4. Serving and rollback

One base model, adapters swapped per task. Call sites address a **task name**; the gateway maps
task → base + adapter. Consequences: A/B the fine-tune against the prompted path in production,
roll either way without a deploy, and retire the fine-tune later without touching a caller.

Keep the prompted path warm permanently. It costs a config entry and it is the rollback.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Data quality | Budget it as 60% of the project, not 10% |
| 2 | Eval contamination | Normalised-hash decontamination; split fixed before training |
| 3 | General capability | Standing regression suite, gating |
| 4 | Reproducibility | Version the dataset; record every run's inputs |
| 5 | Task drift | A retraining trigger and an owner, or it rots |

## 6. Observability

Per-task quality in production against the **live prompted baseline**, sampled continuously
rather than measured once at launch. Cost per call and p99, split by adapter. Adapter version on
every request, so a regression is attributable. Drift in the input distribution against the
training set, which is the early warning for task drift. And the date of the last retraining
alongside the date of the last task-definition change — when the second is more recent than the
first, the model is quietly out of spec.
