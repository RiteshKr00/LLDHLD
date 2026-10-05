# 10M records overnight — explained

**Your version of this:** the **dedicated Celery queues** on the dealership platform are the
bulkhead argument, and one level down, choosing **`acks_late` and making the task idempotent** is
exactly the replay-safety primitive a shard lease needs — Celery gave you retries, *you* made them
safe. **CSR-Exp caches by per-stage input fingerprint**, so changing one stage's inputs replays
that stage and not the run; that fingerprint *is* this scenario's cache key. You've used the
**Gemini Batch API for staleness-tolerant runs**, the lived half of the cost/deadline trade below.
And **per-call metering across five providers on one rate card** is what makes the cost ladder
measurable rather than a guess.

**Related:** topic 05 is the sibling — 10M documents *embedded* for search. Same resumability
spine, different bottleneck: there it's throughput, here it's a deadline you partly rent.

---

## 1. The numbers, and what they force

| Input | Value |
|---|---|
| Records / window | 10M support tickets in 8 h = **28,800 s** (22:00 → 06:00) |
| Required rate | **347 records/sec sustained** |
| Prompt / output | ~800 tokens in (subject, body, last three comments), ~150 out |
| Token volume | 8.0B in + 1.5B out = **9.5B tokens** |
| Sustained token rate | **~20M tokens/minute** |
| A good single key | 1–2M TPM → **you need 10–20 keys' worth of quota** |
| Per-call p50 / p95 | 3 s / 9 s |
| Little's Law, all-sync | 347 × 3 = **~1,050 concurrent in flight** |
| Naive vs engineered cost | **$35,000 → $2,463 per run** |
| Steady state after backfill | ~50k tickets/day ≈ **0.6/sec** |

**One — the loop is not slow, it is impossible.** A single-threaded `for` loop at 3 s a call is
30M seconds: **347 days**. Fully parallel against *one* key, quota caps you at ~26 records/sec
(1.5M TPM ÷ 950 tokens): **107 hours**. The window is 8. This is not a tuning problem.

**Two — the wall is TPM, not RPM and not CPU.** 20M tokens/minute against a 1–2M TPM key. Past the
quota, extra workers convert throughput into 429s — concurrency *becomes* the failure. The
orchestrator pushing 347 records/sec of bookkeeping is a beat scheduler and a few hundred
I/O-bound workers; compute never enters the top three bottlenecks.

**Three — steady state is 0.17% of the backfill rate.** Don't build a cluster for one night. Run
the backfill as a throttled, low-priority tenant of the *same* pipeline the nightly delta uses, or
the system you touch once a year is the one that's broken when you need it.

---

## 2. The cost ladder

Each row is the row above plus one lever. Same corpus, same output.

| # | Design | Effective work | Cost | The lever risks |
|---|---|---|---|---|
| A | Frontier model, sync, one key | 10M calls | **$35,000** | nothing — it never finishes |
| B | + content-hash dedup, 32% repeat | 6.8M distinct | **$23,800** | nothing — free and lossless |
| C | + cheap-first cascade, 12% escalate | 6.8M cheap + 816k frontier | **$4,284** | **accuracy** |
| D | + Batch API on the 85% that returns in time | 5.78M batched, 1.02M drained sync | **$2,463** | **the deadline** |

93% off, and the ordering is the answer to "cost as little as possible": **take the free lever
first, then the one that risks accuracy, then the one that risks the deadline** — because only the
last can make you miss the window, and section 3.4 buys insurance against it.

---

## 3. The layers, each named by the failure it prevents

### 3.1 Content-hash dedup on a *normalised* body
**Prevents:** paying twice for the same ticket. Support corpora are macro-driven and 30–40% of
bodies repeat — password resets, "order not received", the same auto-reply.

The trap inside the lever: hashing the raw body finds almost nothing, because every ticket carries
a unique id, timestamp and signature block. **Normalise first** — strip quoted replies, signatures,
ids and dates, lowercase, collapse whitespace — *then* SHA-256. `solution.py` measures 0.0% against
32% on the same corpus for exactly that reason. Second subtlety: near-duplicates (85–95% similar,
SimHash over shingles) are **safe to reuse for the label and unsafe for the summary**, because the
summary must be about *this* ticket. Dedup granularity is per output field, not per record — saying
that unprompted beats the rest of the lever.

### 3.2 Shards with leased checkpoints
**Prevents:** restarting six hours in.

2,000 shards × 5,000 records; one checkpoint row per **shard**, not per record —
`pending → leased → done | dlq`, with a TTL on the lease. A worker dies, its lease expires, the
shard returns to `pending`. Waste is bounded by *(workers in flight) × (shard size)*, not by how
far into the run you were. Size the shard in **seconds of work, not records**: 5,000 is under a
minute of one worker's throughput, so a replay costs less than a minute of the window. Too small
and the checkpoint store becomes the hot row you were avoiding.

### 3.3 Idempotent, batched writes
**Prevents:** a replay producing duplicates, and the sink becoming the second bottleneck.

Upsert keyed on `uuid5(record_id + prompt_version + model_id + schema_version)`. Replay is then
free, and the checkpoint write and the result write go in the **same transaction** — otherwise
there's a window where the work is done and the system doesn't know it. Batch the writes too: 347
upserts/sec is 0.7 batches/sec at 500 rows and utterly fine; row-at-a-time it's 10M round trips and
10M index updates, which is the second thing that breaks.

### 3.4 The Batch API in waves, with a cutover clock
**Prevents:** paying sync rates for async work — *without* betting the window on an SLA you don't
control. This is the crux of the question.

The Batch API is ~50% off and carries a **24-hour** SLA. Most jobs return far sooner; some sit
behind other customers, and you cannot know in advance which. So: **submit in hourly waves**, and
run a **cutover clock**. At T+5h anything not returned is cancelled and re-dispatched sync at full
price. On these numbers 85% returns in time; the 1.02M that don't cost $643 sync instead of $321
batched — **$322 of deadline insurance on a $2,463 run**. Quoting that as a number is the answer.

Waves matter for a second reason: escalations are discovered only when a batch result comes back.
One giant job means every escalation lands at T+5h with nowhere to go but the drain. Hourly waves
let wave 1's escalations ride wave 3.

### 3.5 Cheap-first cascade with an up-front difficulty router
**Prevents:** frontier pricing on easy classifications — 88% of tickets are a two-word label.

Two rules make it survive contact. **Escalate on a calibrated signal**, not self-reported
confidence, unless you've checked it correlates with correctness on a labelled sample. And
**pre-route the obviously hard** (20k-token threads, non-English, empty bodies) straight to
frontier, so the escalation tail isn't purely reactive and doesn't all land after the cutover.

### 3.6 Multi-key fan-out under one *shared* bucket that yields to daytime traffic
**Prevents:** one quota being the ceiling — and prevents your batch being the 09:00 outage.

Keys and providers are pooled; the token bucket is **shared state in Redis**, because N workers
with per-process buckets admit N× the rate and you get 429s anyway. Two buckets, both checked: one
per provider key, one for the *batch job as a tenant*. The batch and the interactive product share
a quota pool, so if the run overruns at full throttle the product takes the 429s and the incident
is filed against the product. The batch therefore runs as a **low-priority tenant whose bucket
shrinks on a schedule** — the dedicated-Celery-queue bulkhead argument, applied to quota.

### 3.7 DLQ with a per-shard failure budget
**Prevents:** one malformed record stalling a shard, and an infinite retry burning the window.

Three attempts, then the record goes to the DLQ with its raw response and the shard **completes
without it**. On top of that a per-shard failure budget: more than ~2% of a shard dead is not bad
luck, it's a schema change upstream, and retrying it 10M times is how you spend a night finding out.

### 3.8 Burn-down with a projected finish, not a progress bar
**Prevents:** discovering at 07:00 that you'll miss.

Plot records written against the **required-rate line** with a projected finish. And the honest
caveat: while work sits on the Batch API the bar reads *ahead of the line* right up to the final
hour, because completed-so-far says nothing about work whose completion time you don't own. **The
number that matters is the age of the oldest outstanding batch job against the cutover clock.**

### 3.9 A sampled quality gate, during the run
**Prevents:** shipping 10M confidently-wrong labels on time.

2,000 stratified records against a golden set plus a 1% shadow sample scored by the frontier model,
both evaluated *while the run is going* rather than after. A run that finishes at 05:00 and is 60%
accurate is worse than one that misses by an hour. This is the grounding-and-evaluation discipline
you own on CSR-Exp pointed at a batch — noise floor established first.

---

## 4. What breaks first, in order

1. **Provider quota — TPM before RPM.** First because it's the wall you hit on night one, and the
   only one you can't fix with workers: past the quota, extra concurrency *is* the failure.
2. **The write path.** 347 sustained upserts/sec plus an index on the label column. Second because
   it's invisible until quota stops being the limiter, and then it's the whole run.
3. **The tail of slow records.** The longest 1% — 20k-token threads — take 5–10× and are all that's
   outstanding at 07:30. Third because it only bites near the line. Fix: schedule long records
   **first**, not last.
4. **The checkpoint store.** Per-record checkpointing doubles write volume and serialises on a hot
   row. Fourth because a sane shard size hides it, until someone "improves" resumability.
5. **The synchronised retry storm.** Everything that failed all night returns in the last hour on
   the same backoff schedule. Jitter, plus a retry budget that **expires with the window**.

**Not compute.** Say that explicitly — it's the reframe that shows you've run one.

---

## The follow-ups, answered

**1 · "The Batch SLA is 24 h and your window is 8. Justify using it."**
Half price on the majority of the work, and its *observed* completion sits well inside the window —
but I plan for the SLA, not the observation. Hourly waves plus a cutover at T+5h: whatever hasn't
returned is cancelled and drained sync at full price. I'm buying an expected 50% discount and
capping the downside at one hour of drain and $322. Without the clock, batch is a bet; with it,
it's a hedge.

**2 · "The run dies at 62%."**
Nothing restarts except the shards leased when it died — results and checkpoints were committed
together, so `done` means done. Waste is workers × shard size, a few thousand records rather than
6.2M, and the replay is free anyway because the upsert key is `uuid5(record_id + prompt_version)`.
A loop with progress in a variable re-pays for 6.2M records and misses; `solution.py` measures both.

**3 · "It's 02:00. Will you finish by 06:00?"**
Two numbers, not one: the projected finish from the burn-down, *and* the age of the oldest
outstanding batch job. On a batch-heavy run the first is optimistic by construction. If the second
is approaching the cutover you cut over at 02:00 rather than 05:00 and pay for it — deciding early
is cheaper than deciding correctly at 05:30.

**4 · "200 malformed JSON responses."**
Validate on receipt, one repair attempt with the parse error in the prompt, two more plain
attempts, then the DLQ with the raw response attached — and the shard completes. 200 in 10M is
0.002%, a run-report line reprocessed tomorrow. But 200 in *one shard* trips the per-shard failure
budget and pages someone, because that's a schema change, not noise.

**5 · "A ticket is edited after processing."**
The hash changes, so the next run treats it as new — correct, and the reason the dedup key is
content rather than the ticket id. The real work is downstream: version results by
`(record_id, content_hash, prompt_version)` so an edit writes a new row instead of overwriting an
answer someone has already actioned.

**6 · "The prompt changes on Tuesday."**
The cache is invalid; the checkpoint is not. `prompt_version` and `model_id` are *in the cache key*,
so Tuesday's run misses every entry and re-pays — correctly, because Monday's labels answer a
different question. The checkpoint table is per-run and untouched. Getting this backwards is the
classic silent bug: an unversioned cache serves last week's prompt for a month.

**7 · "Where does the retry live?"**
Transport retries (429, 5xx, timeout) in the gateway with backoff **and jitter**, bounded. Business
retries — this shard failed, run it again — in the orchestrator. Never both: 3 × 3 = 9 calls for one
logical record, aimed at a provider already struggling. Plus the batch-specific rule: the retry
budget is **deadline-aware**. At T+7h a retry that would land at T+8h05 is not a retry, it's a DLQ
entry.

**8 · "At 09:00 the product starts getting 429s."**
My batch overran and is still drawing on the shared quota at full throttle; the provider sees one
tenant, so the fairness has to be mine. Fix: the batch holds its own bucket that steps down on a
schedule — full rate 22:00–06:00, 20% until 08:00, zero after — so the thing that overran is the
thing that suffers.

**9 · "Prove the labels are good."**
A stratified 2,000-record golden set scored during the run, agreement with the frontier model on a
1% shadow sample, and the confusion matrix **per label class**, because aggregate accuracy hides
the one class that collapsed. Then the honest part: that's a sample-based bound, not a guarantee,
and the low-confidence slice goes to a `needs review` queue with its record ids rather than being
shipped as if it were certain.

---

## One-line summary

> "Dedup on a normalised hash first because it's free, cascade cheap-to-frontier because 88% of
> tickets are a two-word label, put the bulk on the Batch API but run a cutover clock at T+5h so a
> 24-hour SLA can't eat an 8-hour window, and shard the work into leased checkpoints with
> idempotent upserts so a crash costs one shard rather than six hours — then watch the age of the
> oldest outstanding batch job, not the progress bar."

## The trap answer to avoid

A loop over 10M records with a single API key: 347 days, and it restarts from zero. The second
trap is subtler and catches better candidates — putting *everything* on the Batch API for the
discount, then finding at 06:00 that 15% is still queued behind someone else's job under a 24-hour
SLA with no way to hurry it. This question is about **throughput engineering and resumability
under a deadline you partly rent**, not about prompting.
