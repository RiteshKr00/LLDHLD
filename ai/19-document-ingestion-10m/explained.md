# Ingesting 10M documents — explained

**Your version of this:** the **Mongo Atlas vector RAG** corpus on the FastAPI HR platform is
this pipeline three orders of magnitude smaller; the **dedicated Celery queues** on the
dealership analytics platform are the bulkhead argument; and **CSR-Exp caches by per-stage input
fingerprint**, so changing one stage's inputs replays that stage and not the run. You lean on
that last one every time you re-run the grounding and evaluation layers you own — it is the
difference between a two-minute iteration and a forty-minute one, and it is the exact mechanic
this question is about.

---

## 1. The numbers, and what they force

| Input | Value |
|---|---|
| Documents | 10M |
| Chunks/doc | ~20 → **200M chunks** |
| Tokens/chunk | ~500 → **100B tokens embedded** |
| Embed throughput | 1,000 chunks/sec → **~55 hours of pure embedding** |
| Implied token rate | 100B / 55h = **~30M tokens/minute**, sustained |
| Vectors | 768-dim float32 = 3 KB → **~600 GB** raw (150 GB at int8) |
| Parse | 1.5 CPU-s born-digital, 20 CPU-s scanned, 15% scanned → **~12,000 CPU-hours** |
| Steady state after backfill | 50k changed docs/day = 1M chunks/day ≈ **12 chunks/sec** |

Three conclusions, and say all three out loud:

**One.** 55 hours means the run *will* be interrupted — a deploy, a spot reclaim, an expired
credential, a provider incident. The design question is not throughput, it is **what state
survives the interruption**.

**Two.** 30M tokens/minute is 6–30× a single provider key. Your wall is **quota, not
concurrency**: Little's Law on the embed stage says a batch of 96 at a 600ms round trip needs
only ~6 concurrent in-flight requests to hold 1,000/sec. Six. Workers past that convert
throughput into 429s.

**Three.** Steady state is **1.2% of the backfill rate**. Do not size a cluster for the
backfill — run it as a throttled, low-priority tenant of the *same* pipeline the steady state
uses. Otherwise you build two systems, and the one you use once a year is the one that is broken
when you need it.

---

## 2. The layer that must exist before any of the others

**Prevents:** "it died at 60%" being unanswerable except by starting again.

Before a single document is fetched, write a **document ledger** — one durable row per source
object: key, etag, content hash, current stage, per-stage fingerprint, attempt count, last
error. Everything below is a consequence of that table existing.

Without it the unit of resumability is *the job*, and the job is 55 hours long. With it the unit
is *the document*, and a restart is a scan for rows whose stage is behind. That sentence is the
whole answer to the headline follow-up.

---

## 3. The layers, each named by the failure it prevents

### Stage-per-step pipeline, durable queue between stages
**Prevents:** one failure discarding the work of every earlier step.

`fetch → parse/OCR → chunk → embed → upsert → index`. As one Celery task doing all six, a 429 on
the embed call throws away the 20 CPU-seconds of OCR you just paid for. Stages also scale
independently, which matters because they are bound by different things — parse is CPU, embed is
quota, upsert is I/O. One pool sized for the union of three profiles is sized wrong for all
three.

### Content-hash dedup
**Prevents:** paying to embed the same bytes twice. Usually the single biggest win.

Hash the raw object, and hash the normalised extracted text too so the `.doc` and its `.pdf`
export collapse. Real corpora run **20–40% duplicate** — resent attachments, template contracts,
one policy filed by six departments. At 30% the 55 hours becomes **39**, for a `sha256` and a
lookup.

Be precise about what it saves: the **embedding**, not the row — each document still needs its
own retrievable chunks. Content-address the vector and keep a `doc → chunk` map if you want the
index smaller too, at the price of a join on read.

### Per-stage input fingerprinting
**Prevents:** a one-stage config change costing a full reprocess.

Each stage stores `fingerprint = hash(upstream_fingerprint, stage_version, stage_params)` and
skips itself when the stored value matches. The chain makes replay surgical:

| What changed | parse/OCR | chunk | embed | upsert |
|---|---|---|---|---|
| new document | run | run | run | run |
| parser or OCR upgrade | run | run | run | run |
| chunk size / overlap | **skip** | run | run | run |
| embedding model | **skip** | **skip** | run | run |
| nothing (re-run the job) | **skip** | **skip** | **skip** | **skip** |

Point at the bottom row: **re-running a finished pipeline must cost nothing.** If it doesn't,
you have logs, not fingerprints.

### Batched embedding calls, sized by tokens
**Prevents:** per-request overhead dominating, then a 400 on oversized input.

200M individual calls at 40ms round trip is not a pipeline, it is a decade; batches of ~96 make
it 2M calls. Batch by **token budget, not item count** — one 8k-token chunk in a batch of 96
blows the request limit, and that failure is a hard 400 no retry will fix.

### Backpressure from the index
**Prevents:** the broker becoming the outage.

Embed outruns upsert. Unbounded, the queue between them grows for hours and the broker's disk
fills at 3am, taking down the *whole* pipeline rather than slowing one stage. Bound it, and let
depth throttle upstream. A pipeline that cannot slow down can only fall over.

### Dead-letter queue with a reason code — and a ceiling on it
**Prevents:** one corrupt PDF stalling a 55-hour run.

Failures carry *why*, so they cluster by cause. Then cap it: past ~2% failures over a rolling
10k documents, **halt the run**. 2% of 10M is 200,000 files — never a set of one-offs, always a
class you haven't handled, and finding it at hour 3 costs less than at hour 50.

### Idempotent upsert with deterministic ids
**Prevents:** at-least-once delivery becoming duplicate chunks.

`uuid5(namespace, doc_hash + chunk_index)`. A replay overwrites; it does not append. Not a
storage nicety — duplicates change **retrieval**: top-k returns the same passage three times and
the context window fills with one document. A quality bug in a storage bug's clothes.

The corollary people miss: after a re-chunk producing *fewer* chunks, the old high-index ids are
**orphans**, still in the index and still matching queries. The upsert must delete the ids it no
longer owns for that document.

### Priority lanes, and per-document caps
**Prevents:** the backfill making fresh documents 55 hours stale; and one pathological input
consuming the run.

Live ingest and backfill share the pipeline and the quota, with live ingest at strict higher
priority — freshness holds, the backfill simply takes longer, which is the right trade. And cap
the outliers: a 4,000-page scanned PDF is ~10,000 chunks and 40 minutes of OCR on one core, so
route it to a slow lane with its own workers and give every document a spend cap, or one
malformed file that expands to a million tokens becomes the bill.

---

## 4. What breaks first, in order

1. **Embedding throughput against provider quota.** 30M tokens/minute versus a key giving you
   1–5M. First because it is the only ceiling you cannot raise with more machines — you raise it
   with more keys, or by self-hosting.
2. **Vector-store write throughput.** 200M upserts at ~5k/s is ~11 hours, roughly doubled by
   HNSW graph maintenance under a concurrent index build. Second because it is real but
   smaller than 39 hours, and it yields to batching plus a deferred index build.
3. **The inter-stage queue, if unbounded.** Third because it only bites once 1 or 2 is already
   lagging — but when it bites it takes everything down, not one stage.
4. **Parse/OCR CPU**, if the corpus is scan-heavy. ~12,000 CPU-hours is ~46 hours on 256 vCPU —
   comparable to embedding, and the sleeper if you assumed born-digital.
5. **Ledger write contention.** 10M × 6 transitions = 60M state writes. Fine at 300/s, fatal as
   60M separate round trips from a hot loop. Batch them.
6. **Silent quality drift.** A parser returning empty text for one document class errors nowhere
   and embeds whitespace. Nothing alerts; the corpus is just quietly wrong.

---

## The follow-ups, answered

**1 · "It dies at 60%."**
Nothing is lost. Stage and fingerprints are durable per document, so the restart scans for rows
behind target and drains those; work in flight replays through idempotent upserts to the same
rows. The crash costs the in-flight batch, not 33 hours. **If your answer is "we'd rerun it",
you have failed the question.**

**2 · "5M tokens/minute, you need 30M."**
Dedup first — 30% duplicate content takes the requirement to 21M before any procurement
conversation. Then multiple keys or projects behind a **shared** token bucket in Redis, or ten
workers each admit 5M. Then self-host: a GPU running a small open embedding model prices by the
instance rather than per token, and at 200M chunks that is cheaper by an order of magnitude.
Failing all three, negotiate the deadline — 72 hours becomes 120 and the problem evaporates.

**3 · "A 4,000-page scanned PDF."**
Size-checked at fetch, tagged oversize, routed to the slow lane with its own pool and a longer
timeout, OCR'd page-range by page-range with per-range checkpoints so a failure at page 3,500
doesn't restart at page 1, chunked to ~10,000 chunks, embedded in the normal batches, upserted.
Past the per-document cost cap it goes to the DLQ as `oversize` and a human decides. What it
must never do is hold a general-pool worker for 40 minutes.

**4 · "The embedding model is replaced. How much do you pay again?"**
Embed and upsert only. Parse and chunk fingerprints are unchanged, so the ~12,000 CPU-hours of
OCR are reused in full: ~39 hours of embedding, not 55 plus parse. Operationally it is a
dual-index migration — build alongside, shadow-read, compare recall@k on a labelled sample, cut
over per collection, keep the old index until the comparison holds. Replayability is what makes
that a scheduled job rather than a project.

**5 · "Backfill starving live ingest."**
Same pipeline, two priority classes. Live ingest is strict-priority on the queue *and* the
shared token bucket; the backfill takes the remainder and is allowed to run longer. Freshness is
an SLO you protect; backfill completion is a deadline you negotiate.

**6 · "2% fail to parse."**
Not acceptable as an aggregate, and the aggregate isn't the interesting part. 2% of 10M is
200,000 documents — a *class*: one encoding, one producer, one password-protected template.
Group the DLQ by reason code and the top reason is most of it. Halt at the threshold, fix the
class, replay the DLQ. Then state explicitly what residual failure rate ships, because
"searchable" quietly meaning 98% of the corpus surfaces as a customer escalation, not a
dashboard.

**7 · "At-least-once, so why no duplicates?"**
Chunk ids are `uuid5` of content hash plus chunk index, so a redelivery writes the same key and
the store overwrites — the write is a SET, never an append. And a re-chunk deletes the ids the
document no longer owns, or the orphans match queries forever.

**8 · "How do you know at hour 3 that you'll miss the window?"**
The run monitor publishes **documents/sec per stage and a projected finish time** from the
trailing rate against the remaining ledger count, not a progress bar. The leading indicators
move first: the ratio between stage throughputs (embed behind parse means quota, not capacity),
DLQ rate per reason code, queue depth *trend*. Error rate is lagging here — a run can be
perfectly healthy and still be forty hours too slow.

**9 · "Someone re-chunks with a smaller window."**
Chunk fingerprint changes, parse is reused, chunk/embed/upsert replay. The trap is the orphans:
20 chunks became 16, ids 16–19 are still indexed and still returned, now describing text the
document no longer has in that shape. The upsert must diff the id set per document and delete
the difference in the same transaction as the write.

---

## One-line summary

> "At 10M documents this is a resumable pipeline, not a job: a durable per-document ledger,
> stages separated by bounded queues, content-hash dedup, per-stage input fingerprints so an
> embedding-model change replays embed and not OCR, batched calls sized by tokens, idempotent
> `uuid5` upserts, and a DLQ with a rate ceiling. The wall is embedding **quota**, not
> concurrency."

## The trap answer to avoid

Treating it as a single job — a big Celery task, a `for` loop, a progress bar. It will die
somewhere past halfway and the only honest recovery is to start again. "What happens if it dies
at 60%?" is not a follow-up; it is the question you were asked from the beginning.
