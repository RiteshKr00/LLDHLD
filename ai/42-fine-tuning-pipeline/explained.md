# Fine-tuning pipeline — explained

---

## 1. Reopen the decision first

The prompt says "you've decided". Reopen it, politely, because the answer determines whether any
of this is worth building.

**Fine-tune for format, style, latency and cost. Never for knowledge.** Knowledge belongs in
retrieval, for three reasons that are worth stating: a fine-tune cannot be updated without
retraining, it has no attribution so you cannot show a source, and it fails silently when the
world changes rather than returning nothing.

If nobody can say why fine-tuning rather than prompting, **that is the finding**, and reporting
it is more valuable than building the pipeline.

---

## 2. Where the effort actually goes

| Phase | Share |
|---|---|
| Sourcing and labelling data | 34% |
| Cleaning, dedup, decontamination | 26% |
| Building the eval set and baseline | 20% |
| **Training runs** | **6%** |
| Serving and rollout | 14% |

LoRA on a 7B with 8,000 examples is about **3.5 GPU-hours — £7**. Training is the cheap, fast,
reliable part. Data work is 80%.

Say this early, because the plan people arrive with allocates the time exactly the other way
round, and the schedule slips in the phase nobody budgeted.

---

## 3. Eval contamination is the commonest self-deception

`solution.py §2`, averaged over 40 runs:

| Overlap with eval set | Reported | After decontamination | Inflation |
|---|---|---|---|
| 0 of 500 | 70.9% | 71.1% | −0.2% |
| 25 of 500 | 73.0% | 70.9% | +2.2% |
| 100 of 500 | 76.8% | 70.8% | +6.0% |
| **250 of 500** | **85.2%** | 71.0% | **+14.2%** |

A 71% model reports 85%. And **nothing looks wrong**: the split was made, the numbers went up,
and the model genuinely is better at the examples it memorised.

Two defences. **Decontaminate by normalised hash** — lowercase, strip, hash, exclude. And **fix
the held-out split before any training**, because a split chosen after you have seen results is
not held out.

One detail worth noticing: at 25 examples of leakage the effect is +2.2 points, which is smaller
than the ~2-point standard error of a single 500-example eval. A single run **cannot detect a
small leak**. That is an argument for the hash check rather than for eyeballing the numbers.

---

## 4. The prompted baseline is a gate, not a formality

`solution.py §3`:

| Approach | Task score | Training cost |
|---|---|---|
| Prompted, zero-shot | 68% | £0 |
| Prompted, 8 few-shot | 79% | £0 |
| **Prompted + a stronger model** | **86%** | £0 |
| Fine-tuned 7B | 83% | £7 |

The fine-tune **loses**. This is a common and unwelcome result, and the reason the baseline must
be a gate you can fail.

It does not automatically mean abandon the project — the fine-tuned 7B may still win decisively
on **cost per call and latency at volume**, which is often why you started. But say *which axis
you are buying*, and prove the trade rather than assuming it. "Cheaper per call at equal quality"
is a good outcome. "Better quality" needs to be demonstrated against the strongest prompt you can
write, not against a lazy one.

---

## 5. Catastrophic forgetting

| Capability | Base | Tuned | Delta |
|---|---|---|---|
| Instruction following | 82% | 61% | −21% |
| Multi-turn coherence | 79% | 55% | −24% |
| **Refusing out-of-scope** | 88% | 34% | **−54%** |
| Arithmetic | 74% | 71% | −3% |
| **The tuned task** | 66% | **93%** | +27% |

`solution.py §4`. The task improved 27 points and out-of-scope refusal collapsed by 54. A model
that no longer declines out-of-scope requests is a **safety regression the task eval cannot
see** — every number on the metric you were watching went the right way.

So: a general-capability regression suite runs on every candidate, and it gates the release
alongside the task metric. LoRA helps here too, since the base weights are untouched and the
adapter can simply be detached.

---

## 6. The layers, each named by the failure it prevents

**Justify it first** — *prevents:* months spent on the wrong technique.
**Data curation with dedup and decontamination** — *prevents:* eval-set leakage inflating your numbers.
**Versioned dataset, treated as code** — *prevents:* an unreproducible model.
**Held-out split fixed before training** — *prevents:* tuning against your test set.
**LoRA over full fine-tuning** — cheaper, swappable per task, base untouched.
**Comparison against a strong prompted baseline** — *prevents:* shipping something worse than a prompt.
**General-capability regression suite** — *prevents:* great at one task, broken at the rest.
**vLLM with the adapter behind an OpenAI-compatible interface** — *prevents:* call-site changes.
**Rollback as a pointer flip** — *prevents:* an incident becoming a retraining project.

---

## 7. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Data quality** | 60% of the effort, and it sets the ceiling. |
| 2 | **Eval contamination** | Invisible, flattering, and it survives review. |
| 3 | **General capability** | The task metric cannot see it. |
| 4 | **Reproducibility** | An unversioned dataset means an unrebuildable model. |
| 5 | **Task drift** | The spec changes; the model does not. |

Note that training is not on the list.

---

## The follow-ups, answered

**1. When is fine-tuning the wrong answer?**

When the goal is knowledge — that is retrieval, because a fine-tune cannot be updated, cannot
cite, and degrades silently as the world moves. When the task definition changes monthly, since
retraining becomes a treadmill. When you have under a few thousand good examples. When a stronger
model with a good prompt already clears the bar and the volume does not justify the cost saving.
And when nobody will own the model afterwards — a fine-tune is a codebase with a retraining
trigger and a deprecation plan, not an artefact you ship once.

**2. The commonest way numbers get inflated?**

Eval contamination. Training examples that also appear in the eval set, usually through
near-duplicates rather than exact ones — the same ticket rephrased, the same document in two
sources. The score rises, nothing looks wrong, and the model really is better at what it
memorised. Defend with normalised-hash decontamination and near-duplicate detection, and fix the
split before training. Worth knowing: a small leak is smaller than eval noise, so you cannot
detect it by looking at the numbers.

**3. LoRA or full fine-tuning?**

LoRA, in almost every case at this scale. It is far cheaper, the adapter is under a hundred
megabytes against fourteen gigabytes so you can serve many tasks from one base, the base weights
are untouched so catastrophic forgetting is bounded and reversible, and rollback is a pointer flip
rather than a redeploy. Full fine-tuning earns its place when you need to shift the model's
behaviour deeply — a genuinely different output distribution, a new language — and you have the
data volume to justify it. For "make a 7B do our classification task in our format", LoRA is
correct.

**4. Four points above the prompted baseline. Ship it?**

Not on that number alone. First: is the four points real — outside the eval's noise band, on a
decontaminated set, and does it hold per slice rather than only in aggregate? Then: is the
baseline strong, or did we compare against a lazy zero-shot prompt? Then: what did it cost
elsewhere — run the general-capability suite, because four points on the task next to twenty lost
on instruction-following is a bad trade. And finally: four points might not be the point at all.
If the fine-tune is five times cheaper per call at equal quality, that is the case, and it should
be argued on cost rather than dressed up as quality.

**5. Great at the task, worse at everything else. How would you know?**

Only by testing for it, which is the point — the task eval improves, so every number you were
watching says success. Keep a standing regression suite of general capabilities: instruction
following, multi-turn coherence, refusing out-of-scope requests, format adherence, and basic
reasoning. Run it on every candidate before the task metric is even discussed. The refusal
behaviour is the one to watch hardest, because losing it is a safety regression rather than a
quality one, and it is exactly what narrow tuning erodes.

**6. How do you make this reproducible in six months?**

Treat the dataset as code. Version it, with content hashes, in the same repository or an artefact
store with immutable references. Record for every run: dataset version, base model and exact
revision, hyperparameters, random seeds, library versions, and the resulting eval scores. Store
the adapter with that metadata attached. The test is simple and worth actually performing — can
someone else rebuild this model and get the same numbers, from the recorded information alone? If
the answer involves asking you, it is not reproducible.

**7. How do you serve it without changing call sites?**

vLLM with the LoRA adapter loaded, behind the same OpenAI-compatible interface every other model
uses. Call sites reference a **task name** that the gateway maps to a model plus an adapter, so
placement is configuration. That indirection is what lets you A/B the fine-tune against the
prompted baseline in production, roll forward or back without a deploy, and — most usefully —
abandon the fine-tune later without touching a single caller.

**8. It regresses in production. Rollback?**

Point the task back at the previous adapter, or at the prompted path. Seconds, no deploy, base
untouched. Keep the prompted baseline **live and warm** rather than deleting it once the fine-tune
ships, precisely so this is available — the cost of keeping it is a config entry. Then investigate
with the production examples that failed, which become eval cases for the next candidate. A
regression should cost you a pointer flip and give you labelled data.

**9. Where does the effort go?**

Sixty percent on data — sourcing, labelling, cleaning, dedup, decontamination — and another
twenty on building an eval set and a baseline honest enough to gate against. Training is six
percent and costs about seven pounds. The single most useful thing to say in this interview is
that the expensive part is the part nobody plans for, and that a team which budgets three weeks
for training and a week for data has the schedule inverted.

---

## One-line summary

Fine-tune for format, style, latency and cost but never for knowledge; the work is 80% data
curation and 6% training, the commonest failure is eval contamination inflating a 71% model to
85% with nothing looking wrong, the gate is a genuinely strong prompted baseline that the
fine-tune is allowed to lose to, and LoRA makes the whole thing swappable with rollback as a
pointer flip.

---

## The trap answer to avoid

Fine-tuning to add knowledge. It does not work reliably, it cannot be updated, it has no
attribution, and it fails silently. The second trap is shipping without beating a strong prompted
baseline on the same eval — and "strong" is load-bearing, because comparing against a lazy
zero-shot prompt is how a worse system gets shipped with a chart. The third is quieter: reporting
a task-metric win without running a general-capability regression, when the model has quietly
stopped refusing things it should refuse.
