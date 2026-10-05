# Prompt and config management — explained

**Related:** topic 08 is the eval pipeline this platform calls at promote time; topic 11 treats
the registry as one layer of a multi-model platform; topic 21 shares the cache-key problem, since
a prompt version is part of the key.

**Your version of this.** The voice/video persona product already runs per-tenant prompt
overrides under fail-closed tenant scoping — so you have lived the precedence problem, which is
the one that actually breaks here. On the HR platform prompts and retrieval config move through
PRs: reviewed, but rollback is a redeploy. On CSR-Exp you own the grounding and evaluation
layers — gates declared as data, a measured noise floor — which is precisely the component a
promotion service calls; the pipeline around it is a colleague's. State that boundary.

**The honest gap:** none of them has a promotion service, a live pointer or an audit trail.
Rollback is a deploy. Naming that is stronger than implying otherwise.

---

## 1. The numbers that force the design

| Input | Value |
|---|---|
| Tenants | 500, of which **~40 have a tuned chat prompt** |
| Features | 4 — RAG chat, summarisation, extraction, voice |
| LLM calls/day | 600k → **7 QPS average, 70 peak** |
| Config resolutions/day | **600k** — one bundle resolved per call |
| Config changes/year | 4 features × ~2 edits/week × 50 weeks = **~400** |
| Of those, reviewed today | **0** |
| Spend | $0.004/call → **$2.4k/day, $72k/month** |
| Input token rate | **$2 per 1M** |
| Whole config corpus | 400 versions/yr × 3 yr × ~4 KB ≈ **5 MB** |

**What those numbers force, in order:**

- **400 unreviewed changes a year against a codebase where every line is reviewed.** That
  asymmetry *is* the problem. It is not a storage problem and it is not a UI problem.
- **600k resolutions/day is 7 QPS** — trivial, so resolution is never a capacity question. The
  argument against a database read per request is **availability**: it makes the config store a
  hard dependency of every LLM call, 100% blast radius, to serve 5 MB that changes eight times a
  week. Ship the corpus to every pod as an immutable snapshot; resolve in memory.
- **Little's Law: 70 QPS × ~2s = ~140 requests in flight**, each holding a resolved bundle for
  its whole lifetime. So during a promotion **two snapshot generations are live simultaneously**.
  That is not a race to eliminate, it is a fact to design for: immutable snapshots, an atomic
  pointer swap, and generation N−1 kept alive for at least one service time.
- **+500 tokens on the chat prompt = 400k × 500 = 200M extra input tokens/day = $400/day =
  ~$12k/month**, a sixth of the bill, from a text box, with every test still green. Cost is a
  gate criterion, not a monthly surprise.

---

## 2. The framing: change management, not storage

Every weak answer here is a schema: `prompts(id, version, text, is_active)`, a dashboard, done.
That design is *correct* and solves nothing, because the failure was never "we could not find the
prompt". The failures are that nobody reviewed it, nobody can say which one ran, and nobody can
put it back in under ten minutes.

> The gate must be **unavoidable, not available.**

An available gate is a CI job the dashboard write path never triggers. The structural version:
**the live pointer has exactly one writer — the promotion service — and no human credential can
write it.** The dashboard does not update config; it opens a change request.

---

## 3. The layers, each named by the failure it prevents

### 3.1 Versioned artifacts — *prevents: the untracked change*

The failure: quality dropped on Tuesday and there is no diff to look at, because the change was
a text edit in a table with an `updated_at` column and no history.

A version id is the **content hash of the whole bundle**, not a row counter:

```
bundle_id = sha256(prompt_template + model_id + decode_params
                   + tool_schema + retrieval_params + safety_thresholds)
```

Content addressing buys the property that matters: two environments on the same id are provably
running the same thing, and republishing an unchanged prompt is a no-op, not a "version 7".

### 3.2 The bundle is the unit — *prevents: shipping a combination nobody evaluated*

Version the prompt separately from the model id and someone promotes prompt v9 — written and
evaluated against the cheap model — onto a binding still pointing at the frontier one. Neither
pairing was ever measured. Decode params belong in the bundle for the same reason: `temperature`
moves the output distribution as surely as a rewrite, and it is the easiest field to nudge.

### 3.3 Immutable versions + a mutable pointer — *prevents: rollback being a rewrite*

Versions are write-once. One small mutable thing exists: the **binding** `(feature, env, scope)
→ bundle_id`. Rollback is a pointer flip, so it is **~30 seconds** (push plus worst-case poll
skew) rather than **~12 minutes** (revert PR, CI, build, deploy) — and, more importantly, it
restores the exact bytes. In a mutable store, "put it back" means someone retyping a prompt from
memory into a text box, at the worst possible moment, and the result is a *third* prompt.

### 3.4 Deterministic precedence — *prevents: a global edit silently clobbering 40 tenants*

This is the layer that earns the question. Overrides need a **total order**, written down once:

| Rank | Scope | Typical use |
|---|---|---|
| 4 | request pin | replay, debugging, an eval run pinning a bundle |
| 3 | tenant + environment | a tenant's staging experiment |
| 2 | tenant | the 40 tuned tenants |
| 1 | environment | staging defaults |
| 0 | global default | everyone else |

Two rules that matter more than the table:

- **Highest rank wins outright — never merge.** A deep-merge of prompt fragments across scopes
  produces a prompt that no one wrote and no one evaluated.
- **A tie at the same rank is an error, not a coin toss.** Refuse to publish a binding set with
  two rules of equal specificity. Determinism you cannot state is not determinism.

The bug is subtle because it lives on the happy path: append a new global row to a naive
last-write-wins resolver and all 500 tenants get it, including the 40 whose prompts were tuned.
No error, no alert — just 40 accounts quietly getting worse answers until someone complains three
weeks later. `solution.py` measures exactly that.

### 3.5 Log the resolved bundle id on every request — *prevents: the unexplainable drop*

Not a nice-to-have; it is the thing that makes every other layer investigable. Every trace, log
line, eval record and cache key carries the resolved `bundle_id` **and the rule that won**
(`tenant:t017`, not just the id). Without it, a quality drop leaves you with the whole week's
changes as suspects; with it you group scores by bundle id and the culprit is one row.

It also disambiguates rollouts: two pods serving two versions for 40 seconds is *fine* — and
indistinguishable from a canary — only if requests say which one served them.

### 3.6 The promotion gate — *prevents: shipping a regression*

One writer, one code path, three checks before the pointer moves.

| Check | Blocks on | Why it is at promote time |
|---|---|---|
| **Eval gate** (topic 08) | hard-gate metric below threshold, noise floor accounted for | offline quality is cheap to measure and expensive to skip |
| **Token budget** | projected cost delta > 10% of the feature's daily spend | +500 tokens is $12k/month and no test fails |
| **Schema/contract** | tool schema or output contract changed without a consumer bump | extraction consumers break on a silent field rename |

The token check is the one candidates never mention, and it is arithmetic: tokenise the new
template, multiply by the feature's call volume, price it, put the number in the diff.

### 3.7 Canary by traffic share — *prevents: offline-good, online-bad*

The golden set is 800 cases; production is 600k a day of things nobody thought of. So promotion
is staged: 1% → 10% → 50% → 100%, with guardrail metrics per arm and automatic revert on breach.

Two details separate a real canary from a sketch. **Bucket deterministically on a stable key** —
conversation id, not request id — or a user gets prompt A on turn 1 and prompt B on turn 3, and
the multi-turn metric measures the seam rather than the change. And **guardrails are per
feature**: extraction watches parse-failure rate, voice watches time-to-first-audio, chat watches
refusal rate and thumbs-down. One shared "error rate" catches none of them.

### 3.8 Audit trail — *prevents: an unanswerable question six months later*

Append-only, one row per promotion: who, when, from bundle → to bundle, the diff, the gate
verdict with scores, the canary result, the reason string. Rollbacks are rows too. This turns "we
think it was the prompt change" into a timestamp — and in a regulated context, which the ICH E3
report generator is, it is the difference between an audit finding and a paragraph.

### 3.9 Break-glass — *prevents: the gate becoming the outage*

If the only path to production runs through an eval gate that calls a provider, that provider's
outage freezes your ability to fix a live incident. So break-glass exists: it skips the eval gate,
**pages, demands a written reason, and auto-expires after 4 hours** back to the previous binding.
Loud and temporary, never disabled.

---

## 4. What breaks first, in order

1. **Precedence confusion.** First because it is the only failure on the happy path: no
   exception, no alert, and it worsens with every override added. Ask any team with tenant
   overrides "which prompt ran for this request" and watch the pause. Fix: a total order, plus
   the resolved bundle id on every request.
2. **A pod stuck on a stale snapshot.** A push is missed, the pod never polls, one instance
   serves last month's prompt forever, nothing errors. Detect with *distinct bundle ids serving
   one (feature, env)* — should be 1, briefly 2 during a flip.
3. **The gate becomes a bottleneck and people route around it.** A six-minute wait on a
   one-sentence fix is how a gate dies: bypassed, not deleted. Smoke tier on the change request,
   full tier on promote.
4. **Version sprawl.** 400 bundles a year plus per-tenant forks. Track *override drift* — how
   many versions behind global each override sits — and expire stale ones deliberately.
5. **Canary contamination.** Bucketing per request rather than per conversation, so both arms
   measure a mixture and the canary reports "no difference" forever.
6. **Audit gaps at rollback.** The promote is logged, the emergency revert is not, and the
   timeline has a hole exactly where the incident is.

---

## The follow-ups, answered

**1 · "Which prompt actually ran?"**
Every request logs the resolved `bundle_id` and the winning rule. At 3am: filter traces by
feature and time, group by bundle id, and the drop localises to one id and one first-seen
timestamp. If less than 100% of requests carry a bundle id, that percentage is your blind spot —
track it as a metric.

**2 · "Global edit versus tenant override."**
Highest specificity wins outright — request pin > tenant+env > tenant > env > global. Never
merge. Equal-rank ties are rejected at publish time, not resolved at read time. And the resolver
returns *why*, so the answer is auditable rather than remembered.

**3 · "Rollback in under a minute."**
The binding flips to the previous bundle id, the control plane publishes a new immutable snapshot
over pub/sub, and pods swap an in-memory pointer atomically while keeping generation N−1 alive
for one service time so in-flight requests never see a torn config. Target 30s p99, and **drill
it monthly** — an untested rollback path is a plan, not a capability.

**4 · "PM edits a prompt at 6pm Friday."**
It lands as a change request, not a write: smoke eval in ~30 seconds, the token-cost delta shown
in the diff, then 1% of traffic behind guardrails. None of that is slower than the text box was —
the *reviewer* was the latency, and the gate is automated. Safe without slow.

**5 · "Eval gate is down. Can anyone ship?"**
No, by default — a gate that fails open is not a gate. Break-glass exists, pages, demands a
reason, and auto-expires in 4 hours. Note this is the opposite of the fail-open decision for rate
limiting in topic 16, and the asymmetry is the reason: a missed rate limit costs money, a missed
quality gate ships a regression to every user of that feature.

**6 · "Two pods, two versions, 40 seconds."**
Not a bug — that is what a rolling snapshot push looks like, and cross-pod atomicity would need a
global barrier you do not want. It becomes a bug if it *persists* (a stuck pod) or if requests do
not record which bundle served them, in which case the canary and the incident analysis are both
measuring a blend.

**7 · "Six few-shot examples. What did it cost?"**
Roughly 500 tokens × 400k chat calls/day × $2/1M = **$400/day, ~$12k/month, a sixth of the
bill** — and latency, because prompt length moves time-to-first-token too. The promote-time
budget check prices it in the diff and blocks anything over 10% without explicit sign-off.

**8 · "Canary a prompt mid-conversation."**
Bucket on conversation id, hashed once at turn one and pinned in the session, so a thread never
straddles arms. Store the arm with the conversation, not recomputed per request — a resize of the
canary share must not re-bucket live conversations.

**9 · "Prove it to an auditor six months later."**
The output record stores the bundle id; the bundle is immutable and content-addressed, so
re-hashing the stored template proves it is the same bytes; the audit row names who promoted it,
when, and with which gate scores. Three joins, no recollection. That is also why versions are
never deleted, only unbound.

---

## One-line summary

> "Prompts, model id, decode params and retrieval settings are one content-addressed bundle;
> bundles are immutable and a binding table points to the live one, so rollback is a pointer flip
> in 30 seconds; overrides resolve by a total precedence order with ties rejected at publish
> time; the only writer to that pointer is a promotion service that runs the eval gate and a
> token-cost check; and every request logs the resolved bundle id, because otherwise nothing else
> is investigable."

## The trap answer to avoid

Designing a table with a `version` column and a nice dashboard. That is a storage answer to a
**change-management** question — it leaves the gate *available* rather than unavoidable, and it
still cannot tell you which prompt ran. The second trap is the opposite over-correction: putting
prompts in git only. That is safe and slow, it hands every copy change to an engineer, and the
PMs will quietly build their own dashboard six weeks later.
