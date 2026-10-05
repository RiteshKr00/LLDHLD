# Design scenario bank II — ten more "architect it" problems

Continues [`AI-design-scenarios.md`](AI-design-scenarios.md) (scenarios 1-10). Same shape:
clarify, numbers, layers-by-failure, what breaks first, the trap.

Diagrams for the major ones: [`AI-architecture-diagrams.md`](AI-architecture-diagrams.md).

---

## 11 - Prompt and config management platform

**The prompt:** *"Prompts and model choices are changed weekly by anyone with dashboard
access. Design the system that makes that safe without making it slow."*

**Clarify:** who changes prompts — engineers or PMs? per-tenant overrides needed? is rollback
measured in minutes or seconds?

**Numbers:** 4 features x ~2 prompt edits/week x 50 weeks = **~400 config changes/year**, none
currently reviewed. Compare to code: every line reviewed. **That asymmetry is the problem.**

**Layers:**
- **Prompts as versioned artifacts** (repo, or a UI that writes a reviewed artifact) — *prevents:* untracked change
- **Immutable versions + a pointer to "live"** — *prevents:* editing history; rollback becomes a pointer flip
- **Per-tenant / per-environment overrides with clear precedence** — *prevents:* a global change breaking one tenant's tuned prompt
- **Eval gate on promotion** — *prevents:* shipping a regression
- **Canary by traffic share** — *prevents:* offline-good/online-bad
- **Audit trail: who, when, what diff, what the gate said** — *prevents:* an unexplainable quality drop
- **Prompt-token budget check at promote time** — *prevents:* a longer prompt silently raising cost per call

**Breaks first:** **precedence confusion.** Global vs tenant vs environment overrides interact,
and nobody can answer "which prompt actually ran for this request?" — so log the resolved
prompt **version id** on every request.
**Trap:** treating this as a storage problem. It's a **change-management** problem — the gate
must be unavoidable, not available.

---

## 12 - The feedback flywheel: turn user signal into eval data

**The prompt:** *"You have 600k LLM calls a day and no labelled data. Design the system that
turns production traffic into an evaluation set that keeps improving."*

**Clarify:** what implicit signals exist (edits, retries, thumbs, abandonment)? can you store
prompt/response given PII? is there budget for human labelling?

**Numbers:** if 2% of responses get an implicit negative signal, that's **12k candidates/day**
— far more than you can label. So the design is about **sampling and prioritisation**, not
collection.

**Layers:**
- **Implicit signal capture**: user edited the output, retried, abandoned, copied it, escalated to a human — *prevents:* depending on thumbs, which almost nobody clicks
- **Stratified sampling** (by feature, tenant, model, confidence band) — *prevents:* a golden set that over-represents your loudest tenant
- **Active learning priority**: label the *uncertain* and *disagreed* cases first — *prevents:* wasting labelling budget on easy examples
- **Human review queue** with a rubric, not free-text — *prevents:* unscoreable labels
- **Promotion path into the golden set**, versioned — *prevents:* silent benchmark drift
- **PII redaction before storage** — *prevents:* your eval store becoming your worst liability
- **Feedback on the feedback**: track whether gate scores predict production signal — *prevents:* optimising a metric that doesn't matter

**Breaks first:** **signal quality.** "User edited the output" conflates *wrong* with *stylistic
preference*, and if you train on that conflation you optimise for the wrong thing.
**Trap:** collecting thumbs up/down and calling it an eval set. Click-through on feedback
widgets is ~1% and heavily biased toward the angry.

---

## 13 - Conversation memory at scale

**The prompt:** *"Your assistant needs to remember prior conversations. Design memory for
100k users with month-long histories."*

**Clarify:** within-session or cross-session? must it remember facts, preferences, or full
transcripts? any right-to-erasure requirement (yes)?

**Numbers:** 100k users x 50 turns/month x ~200 tokens = **1B tokens of history**. You cannot
put that in a context window. So memory is a **retrieval problem**, not a storage problem.

**Layers:**
- **Tiered memory**: recent turns verbatim -> rolling summary of the session -> extracted long-term facts — *prevents:* context-window overflow and linear cost growth
- **Summarise on a trigger** (token threshold), not every turn — *prevents:* paying an LLM call per message
- **Fact extraction into structured storage**, not prose — *prevents:* unqueryable, unverifiable "memory"
- **Retrieve relevant memory per turn** (embedding search over facts) — *prevents:* stuffing everything in
- **Recency + relevance scoring** — *prevents:* a two-month-old preference outranking today's correction
- **Per-user namespace** — *prevents:* the worst possible leak
- **Deletion path that actually deletes** — *prevents:* an erasure request you cannot honour because facts were baked into summaries

**Breaks first:** **cost per turn growing with history length**, if you naively resend context.
Then contradiction — the user changed their mind and both facts are stored.
**Trap:** "I'd put the conversation in the prompt." Fine at 10 turns, broken at 500, and the
cost grows quadratically as history is resent each turn.

---

## 14 - Offline batch LLM processing: 10M records overnight

**The prompt:** *"Classify and summarise 10M support tickets. It must finish in an 8-hour
window and cost as little as possible."*

**Clarify:** hard deadline or best-effort? is partial output useful? can records be reprocessed
if a batch fails? accuracy bar?

**Numbers:** 10M records / 8h = **~350 records/sec sustained**. At 1 LLM call each that's 350
QPS — well past a single provider key. **The numbers immediately force batching + parallelism
+ multi-key.**

**Layers:**
- **Provider Batch API** where available — *prevents:* paying sync rates for async work (~50% saving)
- **Chunk into work units with checkpointed progress** — *prevents:* restarting 6 hours in
- **Content-hash dedup** — *prevents:* reprocessing identical tickets (support data is very repetitive; often the biggest win)
- **Cheap-model-first cascade** with escalation on low confidence — *prevents:* frontier pricing on easy classifications
- **Multi-key / multi-provider fan-out** — *prevents:* one quota being the ceiling
- **Dead-letter queue + poison-record isolation** — *prevents:* one malformed record stalling a batch
- **Idempotent writes keyed on record id** — *prevents:* duplicates on retry
- **Progress + ETA telemetry** — *prevents:* discovering at 07:00 that you'll miss the window

**Breaks first:** **quota**, then the write path to your datastore, then the tail of slow
records. Not compute.
**Trap:** designing it as a loop over 10M records with a single API key. The question is
about **throughput engineering and resumability**.

---

## 15 - Guardrails and content safety layer

**The prompt:** *"Your persona assistant speaks as a real executive. Design the layer that
stops it saying something reputationally damaging."*

**Clarify:** what's the actual risk — offensive content, legal/financial claims, competitor
comment, or leaking internal info? is a human review path acceptable? is blocking or
deflecting preferred?

**Numbers:** at 600k calls/day, even a 0.01% failure rate is **60 bad outputs a day**. So the
design target is not "never" — it's *"bounded, detected, and recoverable."*

**Layers:**
- **Input filtering** — *prevents:* prompt injection and obviously abusive input reaching the model
- **Grounding as the primary defence** — *prevents:* invention. A grounded twin has less room to freelance
- **Deterministic output rules** (banned topics, forbidden claim patterns, no financial/legal advice) — *prevents:* the known-bad classes, cheaply
- **Model-based safety classifier** — *prevents:* the semantic cases rules miss
- **Refusal path with a graceful deflection** — *prevents:* an awkward hard block. "I'd point you to the official policy on that"
- **Human escalation on low confidence** — *prevents:* automating a judgement call
- **Immutable audit log of every output** — *prevents:* being unable to answer "what did it say?"
- **Kill switch per persona** — *prevents:* a slow incident

**Breaks first:** **false positives.** Over-blocking makes the product useless, and it's the
failure you'll actually be asked to fix. Tune for it explicitly — and note this is the
*opposite* trade from the PII filter, where recall wins because a leak is unrecoverable.
**Trap:** putting the guardrails in the prompt. "Never discuss competitors" in a system
message is advisory; the injection that overrides it is trivial. **Enforcement belongs
outside the model.**

---

## 16 - PII redaction gateway in front of every LLM call

**The prompt:** *"Nothing containing customer PII may reach a third-party model. Design the
gateway that guarantees it."*

**Clarify:** which entity types? is a local model available for the sensitive path? is
over-redaction acceptable (yes)? must redaction be reversible for the response?

**Numbers:** in the sync path this must add **under ~50ms**, or it destroys your latency
budget. That single constraint rules out an LLM-based detector on every call.

**Layers:**
- **Deterministic detection first** (Presidio + custom recognisers, checksum-validated) — *prevents:* paying model latency on every request
- **Checksum validation** (Aadhaar Verhoeff, PAN structure) — *prevents:* a huge false-positive class from bare regex
- **LLM extractor only on ambiguous chunks** — *prevents:* the latency cost of running it everywhere
- **Never ask the model for character offsets** — return substring + type, **re-find the span in code** — *prevents:* a hallucinated span silently corrupting text
- **Reversible tokenisation** (placeholder -> vault) — *prevents:* an unusable response when the answer must reference the redacted entity
- **Treatment policy in a code data table**, model may only push *stricter* — *prevents:* prompt-driven policy drift
- **Recall-optimised, deliberately** — *prevents:* the unrecoverable failure. A false negative is a leak; over-redaction is noise
- **Fail closed** — if the detector errors, **block the call**

**Breaks first:** **latency**, then recall on entity types you didn't enumerate. Then the
reversal path, when a response references an entity you tokenised.
**Trap:** relying on the LLM to redact. It's the thing you're protecting *from*, and it can't
be verified. *You already solved the offsets sub-problem — cite it.*

---

## 17 - Multi-region serving with data residency

**The prompt:** *"EU customer data may not leave the EU. Design LLM serving across three
regions."*

**Clarify:** does residency apply to prompts, embeddings, logs, or all three (all three)? is
the same model available in every region? is cross-region failover permitted (usually not)?

**Numbers:** three regions x the full stack = 3x infrastructure and **3x the eval surface** —
you must validate each region's model separately because provider model versions differ by
region.

**Layers:**
- **Region as a hard boundary**, routed at the edge on tenant residency — *prevents:* an accidental cross-border call
- **Per-region vector store and per-region cache** — *prevents:* embeddings (which are derived personal data) crossing
- **Region-local provider endpoints, pinned** — *prevents:* a global provider silently serving from elsewhere
- **Logs and traces stay in-region**, aggregate metrics only cross — *prevents:* PII exfiltration via observability
- **No cross-region failover for regulated tenants** — degrade **in-region** instead
- **Per-region eval runs** — *prevents:* assuming model parity across regions
- **A residency test in CI** that asserts no client is configured cross-region

**Breaks first:** the **failover design**. Your instinct is to fail over to another region, and
for regulated tenants that's the compliance breach. Degradation must stay in-region.
**Trap:** thinking embeddings and logs are exempt. Both are derived from personal data and both
count.

---

## 18 - Hybrid self-hosted GPU + API inference

**The prompt:** *"You're spending too much on API inference. Design a hybrid platform that
uses your own GPUs where it makes sense."*

**Clarify:** what's the current spend and volume? is there GPU ops capability on the team? is
latency or throughput the constraint? which tasks need frontier quality?

**Numbers:** the crossover is the whole answer. An A100-class GPU at ~£2/hr is ~£1,400/month
**whether you use it or not**. If your API spend on a task is below that, self-hosting *loses*
— you're trading a variable cost for a fixed one, and you must be able to fill it.

**Layers:**
- **One OpenAI-compatible interface** across both (vLLM speaks it) — *prevents:* call sites knowing where inference runs. *You built exactly this in CSR-Exp*
- **Task-based placement**: high-volume, low-complexity, latency-tolerant -> self-hosted; frontier quality -> API — *prevents:* self-hosting the thing you can't match
- **Utilisation-based routing** — *prevents:* paying for idle GPUs
- **Continuous batching** on the self-hosted side — *prevents:* terrible GPU utilisation at low concurrency
- **API as overflow/failover** — *prevents:* a GPU outage becoming downtime
- **Quality parity eval per task** — *prevents:* a silent quality drop when you move a task in-house
- **Cost dashboard comparing actual £/1k tokens** on both paths — *prevents:* believing the projection instead of the bill

**Breaks first:** **utilisation.** Self-hosting only wins if the GPU is busy; a 20%-utilised
GPU is more expensive than the API it replaced. Then ops burden, which is the cost nobody puts
in the spreadsheet.
**Trap:** framing it as "self-hosting is cheaper." It's cheaper **above a volume threshold**,
and the honest answer names the threshold and the ops cost.

---

## 19 - Zero-downtime embedding-model / vector-DB migration

**The prompt:** *"You need to change embedding models across 100M chunks with no search
downtime and no quality regression. Plan it."*

**Clarify:** is a quality *improvement* expected or is this forced (deprecation)? can you
afford double storage temporarily (you must)? is a brief recall dip acceptable?

**Numbers:** 100M chunks to re-embed. At 1k/sec that's **~28 hours** of pure embedding, plus
index build, plus double storage during transition. This is a **project**, not a deploy.

**Layers:**
- **Dual-write, dual-index** — build the new index alongside the old — *prevents:* a cutover with no rollback
- **Backfill as a resumable, checkpointed job** — *prevents:* restarting 20 hours in
- **Shadow reads**: query both, compare, don't serve the new one yet — *prevents:* discovering a regression in production
- **Compare recall@k on a labelled set** across both indexes — *prevents:* a quality regression shipped as an upgrade
- **Per-tenant progressive cutover** — *prevents:* a global blast radius
- **Cache keys versioned by embedding model** — *prevents:* the cache serving old-space answers
- **Keep the old index until confidence, then delete** — *prevents:* an unrecoverable mistake
- **Never mix spaces in one index** — vectors from two models are not comparable, they're meaningless together

**Breaks first:** **cost and time** of the backfill, then the cache serving stale-space
results, then partial-state bugs if one code path reads the new index and another the old.
**Trap:** an in-place migration. There is no in-place — the two vector spaces are
incomparable, so you need both indexes live simultaneously.

---

## 20 - Incident: "the assistant started fabricating in production"

**The prompt:** *"Users report your assistant is confidently making things up. It was fine
last week. Walk me through the incident, then design what should have caught it."*

*This is the incident-response genre. They're testing method under pressure, not architecture.*

**Clarify (out loud, as triage):** all tenants or one? all surfaces or one? when did it start?
what shipped near then? is retrieval returning anything at all?

**The triage order — say it as a bisection, not a guess list:**
1. **Is retrieval returning chunks?** Empty retrieval -> the model answers from general knowledge and sounds confident. Fastest thing to check, and the most common cause
2. **Is the retrieved context reaching the prompt?** *This is your actual bug — a saved writing style was replacing the retrieved facts instead of adding to them*
3. **Is it being truncated?** *Also your bug — a 300-char cap cutting facts out of 1,000-char chunks*
4. **Did the corpus change?** A re-index, a failed ingest, a deleted document
5. **Did the model change?** A provider silently rolled a version, or a config flipped
6. **Did the prompt change?** Unreviewed config is the most likely recent change
7. **One tenant only?** -> scoping/namespace bug. All tenants -> shared path

**Immediate mitigation:** roll back the most recent config change; if unclear, **raise the
relevance floor and let it refuse more** — a refusal is recoverable, a fabrication isn't.

**What should have caught it — design the fix:**
- **Groundedness metric on sampled production traffic**, alerting on a drop — *prevents:* users being your monitoring
- **Empty-retrieval and truncation counters** as first-class metrics — *prevents:* silent context loss
- **Log the resolved prompt version + retrieved chunk ids per request** — *prevents:* an undebuggable incident
- **Prompt assembly as a pure tested function** — *prevents:* the either/or bug recurring. *This is the fix you actually shipped*
- **Refusal rate as a guardrail metric** — a *fall* in refusals can mean the model stopped admitting ignorance
- **Config changes gated and canaried** — *prevents:* an unreviewed prompt edit reaching everyone

**Breaks first (as a process):** **time to detection.** The technical fix is easy once found;
the failure was that users noticed before you did.
**Trap:** jumping to "the model got worse." Model drift is rare; **your pipeline changed** is
overwhelmingly more likely. Bisect the pipeline before blaming the provider.

---

## The generic answer skeleton, if you're handed something you've never seen

1. **Clarify** 3-5 things; state assumptions for the rest
2. **Numbers**, out loud. Then say **what the numbers force**
3. **Layers, each named by the failure it prevents**
4. **What breaks first**, in order — and be specific about *why that one*
5. **Degradation per feature**, cost levers, tenant fairness, security
6. **Leading indicators** you'd alert on
7. **One honest limitation** of your own design, volunteered
