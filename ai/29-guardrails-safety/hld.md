# The safety layer at scale

## 1. Numbers first

| | |
|---|---|
| Turns | **600k/day** ≈ 7 QPS average, **~70 peak** |
| Voice share | ~40%, hard **800 ms** time-to-first-audio |
| Segments per turn | ~4 clauses → **2.4M segment decisions/day** |
| On a risk surface | ~14% of segments → **~336k classifier calls/day**, ~39/s peak |
| Classifier | **120 ms p50, 400 ms p99** |
| Rules | **~0.4 ms**, run on 100% of segments |
| Policy-relevant outputs | 0.8% of turns = **4,800/day** |

**Little's Law on the classifier:** 39 calls/s × 0.12 s = **~5 in flight**; at p99 and a burst
to 60/s, ~24. That is two small replicas with headroom.

**What that forces, and it is the counter-intuitive part: this is not a capacity problem.**
Nobody's safety layer falls over from load at 600k/day. The scarce resources are the
**false-positive budget** (spent in blocked answers, not CPU) and **human review capacity**
(~250 items per reviewer per day, so a two-person rota gives you **500 reviews/day** against
~3,000 daily T1 dispositions). Every design decision below is rationing one of those two.

## 2. Topology — where each layer physically runs

- **Input guard and deterministic rules: in-process**, at the custom-LLM webhook. They are
  regex and set lookups; a network hop would cost 30× their execution time.
- **Classifier: sidecar or same-node small model**, never a remote service. On the voice path
  a cross-AZ hop is 5–15 ms of an 800 ms budget you will want back.
- **Policy pack: config, cached in memory**, refreshed on a pub/sub signal — banned entities,
  claim patterns, tier map, thresholds, deflection copy, all versioned together and shipped as
  one artefact so a rollback is one version number.
- **Decision log: append-only store, async write with a local buffer.** Off the critical path.
- **Review queue and rule promotion: Celery**, like every other async job on the platform.

## 3. The scaling levers, in order of leverage

| Lever | Moves | Cost of pulling it |
|---|---|---|
| **Grounding + scope narrowing** | the base rate itself | product surface area |
| **Severity tiering** | which volume pays the expensive point | policy work with legal |
| **Rule promotion** | semantic load → deterministic | review capacity |
| **Segment size** | classifier calls, deflection granularity | coarser segments = worse TTFA |
| **Thresholds** | escapes ↔ deflections along one curve | nothing free here |

Thresholds are last on purpose. They are the lever everyone reaches for and the only one that
cannot improve both sides at once.

## 4. Per-persona fairness — the multi-tenant shape of this problem

One classifier, **per-persona policy packs and thresholds**. Three consequences:

- **Per-persona kill switch and per-persona deflection SLO.** An aggregate dashboard hides the
  one executive twin currently deflecting a fifth of its turns, and that persona's owner is the
  one who calls.
- **Per-persona review quotas.** A persona under a red-team probe generates thousands of band
  items; without a quota it starves the queue and every other persona's review stops silently.
- **Policy versions are per persona, pinned per turn**, and written into the log. Otherwise
  "why did we allow it" is unanswerable after the next policy push.

## 5. What breaks, in order

1. **False positives and deflection rate.** First because it is the only failure whose
   frequency *rises* with safety effort, and the only one users report.
2. **Review capacity at ~500/day.** Second because it fails silently — the queue ages, rule
   promotion stops, and every dashboard stays green while the system quietly stops improving.
3. **Voice time-to-first-audio**, once the classifier lands on the first segment of on-surface
   turns. Third because it is bounded and visible, unlike the two above.
4. **Policy sprawl.** Rules accumulate, nobody deletes any, and the FP rate creeps up over a
   quarter with no single change to blame. Needs a hit-count per rule and a retirement review.
5. **Classifier score drift** as the persona mix and traffic change. Silent, no error, and the
   thresholds you tuned last quarter now sit somewhere else on the curve.
6. **Log volume and retention.** 2.4M decisions/day against a legal retention horizon is a
   storage and cost conversation, not an afterthought.

## 6. Degradation — and it genuinely differs per path

| Path | Classifier unavailable | Why that call |
|---|---|---|
| **T1 surface** | fail **closed**: fixed deflection | unrecoverable risk; same call as fail-closed tenant scoping |
| **T2/T3 voice** | rules only, persona narrowed to grounded answers | you cannot retract speech, so shed capability |
| **T2/T3 chat** | rules only, serve, flag for review | the bubble can be replaced; availability wins |
| **Internal tools** | fail **open**, log loudly | no external reputation exposure |

Separately: if the **decision log** is unavailable, buffer locally and apply backpressure. Only
when the buffer fills do you fail closed on T1 — serving output you cannot later account for is
the failure that makes an incident unbounded.

## 7. Observability

Per persona, never aggregate: deflection rate **per session** (not per turn), hard-block rate
split by rule id vs score, band-population share, classifier score distribution, escapes found
by review, user reports per 10k turns, review-queue age, and **percentage of turns with a
chain-verified decision record** — anything under 100% is a blind spot, not a rounding error.

**Leading indicators, which all move before anyone complains:**
**band-population share rising** (the model is drifting toward the surface) · **classifier
score distribution shifting** · **one rule's hit count jumping 10×** (an attack, or a rule that
now matches something innocent) · **review-queue age growing**.

**Lagging:** user reports and comms escalations. By the time those move, the screenshot exists.
