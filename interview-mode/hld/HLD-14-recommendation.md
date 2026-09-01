# HLD-14 — Recommendation Serving

## META
- difficulty: hard
- time: 45 min
- tags: two-stage-funnel, embeddings, ann, vector-search, feature-store, cold-start, model-rollout
- why-it-matters: the only **ML-infrastructure** round in the set, and deliberately about serving a
  model, not building one. Stage one is the same machinery as a vector store in a RAG pipeline, which
  makes it the most transferable round you own.

## PROMPT
> "Design the recommendation system behind a home page — a personalised row for each user, and a
> 'people who liked this also liked' row on every item page."

## CLARIFY
- **Where is the boundary — can the ML team ship a new model without deploying my service?**
  → **Yes, and that boundary is what you are designing.** The ranker sits behind a versioned interface in its own service; you own orchestration, they own the model. Fix this in the first minute and every later question — Friday model ship, shadow traffic, rollback — has a home.
- **What is the latency budget?**
  → The row renders inside the page: **p99 < 100 ms end-to-end**, so ~50 ms for the recommender.
- **How big is the catalogue, and how many items in a row?**
  → ~10M items. The row shows **20**.
- **How fresh must the recommendations be?**
  → Day-fresh for the general home row. Get this concession — it moves almost all the work offline.
- **Does the click the user just made have to change the row?**
  → For "because you watched X", **yes, immediately**. For the general home row, no. **That asymmetry is the design.**
- **Brand-new users and brand-new items?**
  → Both exist, and neither may see an empty row.

## STEP 1 — Requirements
**Functional:** a personalised row per user · item-to-item "more like this" · exclude already-seen and
unavailable items · a sensible row for a brand-new user · **log every impression and click**.
**Non-functional:** p99 < 100 ms on the render path · **availability > freshness > personalisation** —
never an empty row · a new model shippable without redeploying the serving path.
**Out of scope (say it):** **model training and quality** · feature engineering · the ranking objective
(CTR vs watch-time) · ads and auctions.

### CHECKPOINTS
- Draws the **model boundary** in the first minute — ranker behind a versioned interface, so shipping a model never deploys this API
- States the **latency budget as a number**, and that the row is on the critical render path
- Ranks priorities so **a stale non-personalised row beats no row** — fail-open declared here, not discovered in step 8

### TRAPS
- Spending the round on model architecture (matrix factorisation vs two-tower) — the failure mode of this round
- Promising "fully personalised, computed fresh per request" before doing the arithmetic
- Forgetting the impression log, then being unable to answer "how do you know it works?"

### FOLLOWUPS
- *"The model is a black box someone else owns, costing 0.05 ms per item scored. Design around it."*
- *"Under load, which do you drop first: freshness, personalisation, or the row itself?"*

## STEP 2 — Capacity
```
users        100M registered, 10M DAU         catalogue   10M items
requests     each DAU opens home 4×/day -> 40M/day ÷ 86,400 ≈ 460 req/s (peak ~1,000)
             each request produces ONE row of 20 items
score everything online:
   10M items × 460 req/s = 4.6 BILLION model scores/sec    <- impossible. THIS is the motivation.
two-stage funnel:
   500 candidates × 460 req/s ≈ 230K scores/sec            <- 4 orders of magnitude cheaper
   500 items × 0.05 ms, batched ≈ 25 ms of ranking         <- fits inside the 50 ms budget
item embeddings  10M × 128 dims × 4 B ≈ 5 GB  -> ANN index fits in RAM on ONE box (so replicate it)
user embeddings  100M × 128 × 4 B    ≈ 51 GB  -> a KV store, NOT resident next to the index
impression log   10M DAU × 200/day ≈ 2B events/day ≈ 23K/sec × 200 B ≈ 400 GB/day
```

### CHECKPOINTS
- Does the **"score every item online" multiplication** and shows it is impossible — the funnel is derived from a number, not asserted
- Sizes the **item embedding index** (~5 GB), concludes it fits in memory, so it is replicated not sharded

### TRAPS
- Quoting request QPS and stopping — 460 req/s is trivial; **the scale here is items-per-request**, and only that number makes the problem hard
- Assuming 100M user vectors sit in RAM beside the item index without checking (51 GB says otherwise)

### FOLLOWUPS
- *"460 requests a second is nothing. Why isn't this easy?"*
- *"How many bytes is one embedding, and how did you get that?"*

## STEP 3 — API
```
GET  /api/v1/users/{id}/recommendations?surface=home&limit=20
       -> 200 {items:[{item_id, score, reason}], model_version, request_id, is_fallback}
GET  /api/v1/items/{id}/similar?limit=20
       -> 200   user-independent -> ONE cache entry serves everyone -> CDN-able
POST /api/v1/events   {user_id, item_id, type: impression|click, request_id, position, ts}
       -> 202   fire-and-forget, never on the render path
GET  /api/v1/users/{id}/recommendations?debug=1
       -> 200 {candidate_sources[], features_used[], stage_timings_ms}
```

### CHECKPOINTS
- **`/similar` is user-independent** — one cacheable answer per item (CDN-able), unlike the personalised row's one answer per user
- Response carries **`model_version` + `request_id`** so an impression joins back to the exact model and candidate set that produced it — without this the step-7 A/B is unreadable; `is_fallback` makes degradation a metric instead of invisible

### TRAPS
- Returning a bare list of ids: you can never attribute an outcome to a model version afterwards
- POSTing impressions **synchronously** before rendering — logging is now on the critical path, and a slow logger becomes a slow page

### FOLLOWUPS
- *"Two users got different rows. A month later someone asks why. What must you have stored?"*

## STEP 4 — Data model — the offline/online split, and the feature store

| Artifact | Where it lives | Refreshed | Plane |
|---|---|---|---|
| item embeddings | ANN index, RAM, **immutable versioned blob** | hourly / nightly | offline |
| user embeddings | KV store, key `user_id` | nightly | offline |
| precomputed candidates | Redis `recs:{user_id}`, TTL 6-24 h (jittered) | nightly | offline |
| item→item neighbours | Redis `similar:{item_id}` | nightly | offline |
| item metadata (stock, region-lock) | KV store, streaming updates | seconds | **online** |
| already-seen set | per-user Bloom filter, TTL days | per impression | **online** |
| features (counts, item CTR, session) | **feature store**: lake table + online KV | batch + streaming | **both** |
| impressions & clicks | Kafka → data lake (Parquet/S3) | continuous | writes online, reads offline |

### The feature store, and training/serving skew
A **feature** is one number the ranker consumes ("action films finished in 30 days", "this item's 7-day
click rate"). A **feature store** owns each feature's *definition* and serves two readers:
```
offline (training):  a lake table computed over history, joined AS OF the event's timestamp
online  (serving):   a KV lookup returning the same number for the same entity at that instant
                     ^^ both generated from ONE definition, never two implementations
```
**Training/serving skew** is those two diverging — training computes "30-day count" from a nightly
snapshot, serving from a Redis counter that resets weekly. **Nothing errors. No test fails.** The model
is fed a distribution it was not fitted on and quietly gets worse. Hence **one definition, two readers**
— and why the offline join is **point-in-time**, never joining a feature computed *after* the event.

### CHECKPOINTS
- Draws an explicit **offline vs online split**, giving every artifact a refresh schedule
- Names the **feature store** as one definition with two readers, and **training/serving skew** as a *silent* failure — no error, no alarm, just a worse model

### TRAPS
- Embeddings as rows in Postgres with `ORDER BY cosine(...)` — a full scan of 10M vectors per request
- Baking "in stock" into a nightly candidate list; by serving time it is simply wrong
- Two teams writing the same feature twice, once in Spark and once in the service — that *is* skew

### FOLLOWUPS
- *"The model works great offline and badly in production. Where do you look first?"*

## STEP 5 — Architecture
```
OFFLINE PLANE (hours)                    ONLINE PLANE (milliseconds)
──────────────────────────────           ───────────────────────────────────────────
Kafka ─▶ data lake (impressions,clicks)  Client │ GET /users/42/recommendations
   │                                            ▼
   ├─▶ training job  ─▶ ranker artifact ─┐  Rec Service (orchestrator, trains nothing)
   ├─▶ embedding job ─▶ item vectors ────┤   ├─▶ Redis recs:{uid} ─hit─▶ re-rank+filter ─▶ out
   │                   user vectors      ├─▶ ├─▶ Candidate Gen ─▶ ANN index + similar/trending
   ├─▶ feature job   ─▶ offline features ┤   ├─▶ Feature Store — ONE batched multi-get
   │        └── same definition ─────────┘   ├─▶ Ranker / model server — ONE batched call
   └─▶ candidate job ─▶ recs:{uid} Redis     └─▶ Filter + diversity ─▶ top 20 ─▶ response
                                                                     └─▶ Kafka (async log)
```
- The **Rec Service is an orchestrator**: fetch, score, filter, respond. It owns no model and no
  training — the ranker sits **behind an interface in its own service**, so a new model is a deploy of
  *that* service, never of this API.
- **Stage order is fixed and load-bearing:** candidate generation → feature fetch → rank → filter, and
  **a cache hit skips the middle two entirely** — a re-sort of a list the batch already ranked.

### CHECKPOINTS
- Gives the per-request path as **candidate generation → batched feature fetch → rank → filter**, in that order
- Fetches features in **one batched multi-get** — 500 sequential 1 ms round trips is 500 ms, ten times the whole budget (the network N+1)

### TRAPS
- A feature-store call per candidate — the commonest way this design misses its budget
- The model living inside the API process, so shipping a model means shipping the API
- Filtering before ranking (see the deep dive) — it looks like an optimisation and is a bug

### FOLLOWUPS
- *"Where does the model live, and what happens when the ML team ships a new one on Friday?"*

## DEEP DIVE — the two-stage funnel, and approximate nearest neighbour

### 1. The funnel is the shape of the whole answer
```
10,000,000 items
     │  CANDIDATE GENERATION — cheap, RECALL-oriented, ~5-10 ms; a LOOKUP, no model per item
     ▼
   ~500 candidates
     │  RANKING — expensive, PRECISION-oriented, ~25 ms; the real model, full features
     ▼
   ~500 scored & sorted   <- ALL of them, not a truncated 50; see §4
     │  FILTER — already seen, unavailable, blocked
     ▼
   ~100 survivors ── DIVERSITY (cap per creator) ──▶ 20 shown
```
Two stages because **scoring cost is per item**: none is both cheap enough for 10M items and precise
enough for the top 20, so **buy recall cheaply, precision expensively**. Same shape as round 11's
retrieve-then-rerank, but stage one is a **vector lookup, not a term match** — an inverted index needs a
shared token; ANN returns items *similar* with no shared word at all.

### 2. Embeddings, and why exact search is unservable
128 floats standing in for an item or a user, trained so that interchangeable things land close
together. No dimension is nameable; **only distance is meaningful** — so "items like this" and "what
this user likes" are one lookup in **one index**.
```
exact:  cosine over all 10M items -> the ENTIRE 5 GB index read, per query
        5 GB ÷ ~20 GB/s single-core bandwidth ≈ 250 ms per core, × 460 req/s -> a fleet
        memory-BANDWIDTH bound, not FLOP bound — the 1.3 GFLOP is the easy half
ANN:    ~1 ms — a few thousand vectors, not ten million; ~95-98% of the true top-500
```
The trade: **exactness, for two to three orders of magnitude of latency.** Give the *bandwidth* reason;
"a lot of FLOPs" names the wrong bottleneck. Safe here — the stage over-fetches 500 to show 20, so a
missed neighbour near position 400 is imperceptible. *(Round 10's "approximate only where it is
harmless", on a neighbour set rather than a count.)*

| Index | The idea | What it costs |
|---|---|---|
| **HNSW** (graph) | small-world graph, greedy walk down layers | best recall-per-ms, **large in RAM**, **deletes awkward** — rebuild, don't mutate |
| **IVF** (clustering) | probe only the `nprobe` nearest centroids | smaller and tunable, but **recall drops at cluster boundaries** |

**`efSearch` / `nprobe` is a recall-vs-latency dial turnable at runtime** — under load turn it down and
serve slightly worse recommendations instead of shedding requests.

**The transfer — say it out loud:** this is the machinery of a **vector store in a RAG pipeline** —
chunk embeddings in an ANN index, top-k by cosine, then an expensive reranker over the survivors.
**Candidate generation is retrieval; the ranker is the reranker.**

### 3. Candidate generation is plural, not one ANN call
```
ANN on the user vector                200   "things like what you generally like"  (a day old)
neighbours of the last 3 items seen   150   "because you watched X"                (instant, no user vector)
trending in region/segment            100   fresh, and covers cold users
explicit signals (follows, wishlist)   50   cheap, high precision
                                     ─────
                                      500   deduped, then ranked together
```
This is **session freshness without recomputing a user embedding per request**: the item-neighbour
source reacts to a click two seconds old, the user-vector source is a day old, the ranker sorts the
union out. **The mix of sources is the design decision** — and the diversity and cold-start story too.

### 4. Filter AFTER ranking — which is why you over-fetch
Filters: **already seen** (the same 20 items tomorrow is the #1 complaint) · **unavailable** · **blocked**.
After ranking, because the exclusion set is **per-user and volatile** — pushing it into the ANN query
means a personalised index per user — and the model knows nothing about stock, a business rule, not a
learned signal.

The consequence is arithmetic: **rank meaningfully more than you show.** Rank 50 at a 60% filter rate and
exactly 20 survive with nothing spare; one more takedown and the row is short. Hence hundreds of
candidates for 20 slots, plus a **top-up rule**: survivors < row length → fill from the popular list.
Seen-state is a **Bloom filter per user** — a false positive merely hides one item, which is harmless.

### CHECKPOINTS
- States the funnel as **millions → hundreds → tens**, because **scoring cost is per item**
- Defines an **embedding** plainly — a learned vector in which **only distance is meaningful**
- Justifies ANN with **arithmetic**: 5 GB ÷ ~20 GB/s ≈ 250 ms, so **bandwidth bound, not FLOP bound**
- Names **HNSW or IVF** *and* its cost (RAM, awkward deletes, boundary misses), and knows `efSearch`/`nprobe` is a **runtime** lever
- Connects stage one to **vector search in a RAG pipeline** (retrieve then rerank), and names the difference from round 11: **vector lookup, not term match**
- Makes candidate generation a **union of cheap sources** so the row reacts to the last click
- Puts **filters after ranking** and over-fetches, because filters remove some

### TRAPS
- Naming a vector database product but not what an ANN index gives up — it is a *chosen* trade, and you must say where it is safe
- A single candidate source: the row cannot then respond to the item just clicked
- Retrieving 20 candidates because the row shows 20 — the filters will empty it
- Filtering before ranking to "save work": you discard items the ranker would have loved, and still cannot express "in stock" in a vector query

### FOLLOWUPS
- *"Your ANN index has 96% recall. Should I care? Where would I care?"*
- *"You've built RAG pipelines. What is the same here, and what is different?"*
- *"Traffic triples. Give me one dial you can turn in 30 seconds."*

## STEP 7 — Scale, cold start, and shipping a new model

**Caching the row.**
```
fully online   ANN + ~450 feature fetches + ~450 model scores        ~50 ms, 100% of cost
cached list    batch precomputes ~200 candidates per ACTIVE user -> recs:{uid}, TTL 6-24 h;
               per request just read, session re-rank, filter —
               NO feature fetch, NO model call                       ~6 ms, ~1/10 of cost
```
- **Precompute for the head, compute on demand for the tail** — 10M active, not 100M registered;
  precomputing for everyone is 90% wasted batch.
- **The light re-rank stops a cached row feeling dead** — a *sort*, not a scoring pass: promote items
  sharing a creator/category with this session's clicks, demote what was shown today. No features, no
  model — which is *why* it costs a tenth.
- **TTL, do not invalidate** (a rec list has no correctness deadline), and **jitter it**, or 10M keys
  expire in the same minute and you have built a stampede.

**Cold start — two problems, two answers.**

| Case | Missing signal | Fallback, in order |
|---|---|---|
| **new user** | no history → no user vector | popular-in-region/segment → interests declared at signup → after the first click the item-neighbour source works |
| **new item** | no interactions → no collaborative signal | **content-based**: embed title/category with the same encoder into the item space within the hour → plus an **exploration budget** forcing it into a small share of rows so it earns interactions |

**A new user is solved by popularity, a new item by content** — naming both separately is the check.
Popularity is not a hack: it is the honest answer with no signal, and it is the same list you fall back
to when the model tier is down, so you get it for free.

**Shipping a new model — offline cannot tell you whether it is better.**
```
1. SHADOW  real traffic to the new model, score it, LOG it, SERVE the old one
           -> catches latency regressions, crashes and skew at zero user risk
2. A/B     1-5% of users, until the ONLINE metric moves with significance
           -> CTR / watch-time. NOT offline AUC.
3. RAMP    5% -> 25% -> 50% -> 100%, auto-rollback on guardrails
           (p99, error rate, FALLBACK RATE, coverage)
```
Offline accuracy up while online engagement is down is routine — which is why step 3's response carries
`model_version` and `request_id`; without them the experiment is unreadable. **Ship the ranker and the
index as one versioned bundle**: a ranker trained against embedding version N scoring candidates from
index N+1 is training/serving skew wearing a hat.

**Scaling.** The ANN index is ~5 GB, read-only, identical everywhere → **replicate, do not shard**,
until the catalogue outgrows RAM; then shard by item and merge per-shard top-k. **Rebuilds are
blue/green** — load the new blob beside the live one, health-check, flip the pointer, never mutate a
serving index. The offline pipeline is a scheduled job: idempotent reruns, DLQ, and an alert on **lag**,
not just failure — a batch that silently stopped is the usual cause of "recommendations feel stale".

### CHECKPOINTS
- Chooses **precomputed per-user lists plus a light online re-rank**, and states what each costs
- Gives the **two cold-start cases separately** — popularity for a new user, **content embedding** for a new item
- Ships a model **shadow → A/B → ramp**, decided on **online engagement, not offline accuracy**

### TRAPS
- Precomputing rows nightly for all 100M registered users when 10M are active
- Invalidating rec caches on every user event — that is a stampede; TTL with jitter is the answer
- Shipping a model because offline AUC improved
- Rebuilding or mutating the ANN index in place while it is serving traffic

### FOLLOWUPS
- *"The new model's offline accuracy is 4% better. Do you ship it?"*
- *"A user clicks an item. When, exactly, does their home row change?"*

## STEP 8 — Failure
- **Model service down or slow** → **FAIL OPEN.** Serve the cached candidate list in its stored order,
  filtered; if that is empty, `trending:{region}`. **Never render an empty row** — an empty row reads as
  *broken*, a mediocre row does not. The fallback is **derived data** the batch already computes, so
  unlike a stocked house artefact it can never run out.
- **Timeout per stage, not per request**: candidate gen 10 ms, features 15 ms, ranking 25 ms. Blow a
  stage → drop its contribution and continue. **A degraded row on time beats a perfect row late.**
- **Feature store down** → score with imputed defaults **and count it**; a spike in
  `missing_feature_rate` is the leading indicator that the model is being fed garbage.
- **ANN index blob corrupt** → keep serving the previous version. It is **derived data**, rebuildable
  from the lake — roll the pointer back, don't rebuild under pressure.
- **Bad model in the ramp** → guardrail rollback fires automatically; the previous version stays warm,
  so rollback is a pointer flip, not a deploy.
- **Event pipeline down** → serving is unaffected (logging is async, `202`), but you are **blind**: no
  training data, no A/B readout. Buffer in Kafka, alert on consumer lag.
- **The silent one: training/serving skew** → nothing throws, nothing pages, the model just rots.

### CHECKPOINTS
- Says **fail open** explicitly and names the chain: personalised → cached → popular → never empty
- Puts a **timeout on each stage**, degrading stage-by-stage instead of failing the request

### TRAPS
- Returning `500` or `[]` when the ranker times out — the page now has a hole in it
- One global timeout for the pipeline: the ranker eats it and the earlier stages get blamed
- Treating a stale ANN index as an outage — it is derived data, keep serving the old blob

### FOLLOWUPS
- *"Your fallback popular list hasn't been rebuilt for two days. What does the user see, and what told you?"*

## STEP 9 — Wrap
- **Bottleneck:** not request rate — **work per request**. The funnel exists to cut it; after that the
  first thing to saturate is the ranker's batch scoring, then the feature store's multi-get.
- **Tradeoffs:** ANN (~97% recall, ~1 ms) vs exact (100%, ~250 ms/query, unservable) · cached lists
  (~1/10 the cost, hours stale) vs online personalisation (fresh, 10×) · more candidates (higher
  ceiling, linear cost) vs fewer (fast, but filters can empty the row) · a bigger ranker vs the 50 ms
  budget.
- **Monitoring:** headline is **online engagement (CTR / watch-time) per `model_version`**. Then
  **fallback rate** (the health signal for the model tier), **coverage**, **candidate recall** against
  an offline exact-NN sample, **`missing_feature_rate`**, **batch lag**, **p99 per stage**.
- **The one to name out loud: training/serving skew.** Log the feature vector used at serving time,
  sample it, and diff it against the offline computation for the same entity and timestamp. No test and
  no error rate will ever show you this.
- **Next:** diversity within a row · an exploration budget (bandits) · multi-objective ranking (clicks
  vs retention) · per-surface models.

### CHECKPOINTS
- Names the headline metric as **online engagement per model version**, plus **fallback rate** as the health signal for the serving tier

### TRAPS
- Monitoring only p99 and error rate: this system's characteristic failure produces neither
- Reporting one average CTR across model versions — the A/B becomes unreadable

### FOLLOWUPS
- *"Everything is green and engagement is down 3%. Where do you look?"*

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | one model, "score all the items and sort them", a vector database named but not explained, no latency arithmetic, no story for a new user |
| **Senior** | **two-stage funnel with the numbers behind it**, ANN with its recall tradeoff stated, an explicit offline/online split, precomputed lists + light re-rank, filter after ranking with deliberate over-fetch, cold start for users *and* items, fail open to a popular list |
| **Staff** | all that **+ the feature store and training/serving skew named as a silent failure**, per-stage timeouts with graceful degradation, `efSearch`/`nprobe` as a runtime load-shedding lever, shadow → A/B → ramp judged on **online** metrics, model+index shipped as one versioned bundle, and drawing the model boundary in the first minute so a new model ships without redeploying the serving path |

## REFERENCE

### One request — `GET /users/42/recommendations?surface=home&limit=20`
```
 0 ms  request arrives with session context (last 3 item ids);   1 ms  Redis GET recs:42

=== HIT (the common case) — the batch already ranked this list; do NOT rank it again ===
 2 ms  200 precomputed candidates, ~4 h old
 3 ms  Light session re-rank: a SORT over 200 rows — no feature fetch, no model call
 4 ms  Filter: already-seen (Bloom), out-of-stock, region-locked -> ~90 survivors
 5 ms  Diversity (max 3 per creator), take the top 20
 6 ms  Respond {items, model_version:"ranker-v7", request_id, is_fallback:false}
          a tenth of the miss path, because the two stages it skipped are the expensive ones

=== MISS — new user, expired TTL, or the long tail ===
 3 ms  Candidate gen, four sources in parallel: ANN on the user vector 200 (HNSW,
          efSearch ~1 ms), similar:{last 3 items} 150 <- what makes it feel live,
          trending:{region} 100, follows 50  -> dedupe -> ~450 candidates
 5 ms  Feature Store: ONE batched multi-get — 450 item rows + the user's row
20 ms  Ranker: ONE batched scoring call over 450 candidates -> 450 scores
          ~25 ms: the biggest line in the budget (step 2: 500 × 0.05 ms batched)
45 ms  Filter over ALL 450 scored items, then diversity, then take the top 20
49 ms  Respond — 49 of the 50 ms. No slack, which is why the hit path exists and why
          the ranking stage gets a hard 25 ms timeout.
async  20 impression events -> Kafka -> lake   (never on the response path, either path)
```

### Every night, offline
**Training job** → a new ranker artifact · **embedding job** → a new immutable versioned index blob ·
**feature job** → offline features, publishing the same values online (one definition, two readers) ·
**candidate job** → `recs:{user_id}` for the ~10M active users, TTL 24 h with jitter. The new index and
ranker load **beside** the live ones, get health-checked, then the pointer flips.

### The model service dies at 3 pm
The 25 ms ranking timeout fires; serve the cached list filtered, and if that is empty
`trending:{region}`. `is_fallback:true`, `fallback_rate` spikes, the user sees a slightly worse row and
**no error**. Fail open.

## ONE-LINER
> *"First the boundary: the ranker is another team's service behind a versioned interface, so I'm
> designing the **serving path** around it and they ship models without deploying me. The shape is a
> **two-stage funnel** — ten million items down to a few hundred **candidates** via a cheap,
> recall-oriented **ANN lookup over embeddings**, then an expensive **ranker** over just those hundreds,
> then filters, then twenty shown. The arithmetic forces it: scoring 10M items at 460 requests a second
> is billions of scores a second; scoring 500 is not. Stage one is the same machinery as a vector store
> in a **RAG** pipeline — retrieve, then rerank — approximate on purpose, because missing a true
> neighbour at position four hundred costs nothing. Most of the work is **offline**: embeddings,
> features and per-user candidate lists are precomputed, so the request pays only a light re-rank and
> the filters. The two things I'd watch are **training/serving skew** — the same feature computed
> differently in training and in serving makes the model silently rot — and the fallback: if the model
> tier is down I serve a popular list and **never an empty row**."*
