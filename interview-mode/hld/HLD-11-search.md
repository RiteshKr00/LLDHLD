# HLD-11 — Search & Ranking (Elasticsearch)

## META
- difficulty: hard
- time: 45 min
- tags: inverted-index, scatter-gather, bm25, deep-pagination, segments, analysers, re-ranking
- why-it-matters: the round where the **query is unpredictable**, so nothing can be precomputed — and
  the home of two facts every search cluster lives with: **every query touches every shard**, and
  **page 1000 is a bomb**.

## PROMPT
> "Design search for a large product catalogue — a user types a phrase in a box and gets the most
> relevant items back."

## CLARIFY
- **Full text, or exact matching on titles?**
  → **Full text.** "noise cancelling headphones" must match *"Sony WH-1000XM5 wireless headphones with
  active noise cancellation"* — which kills `LIKE` on the spot.
- **How big is the corpus?**
  → **500M documents, ~1 KB indexable text each.** Sharding is forced, and *how* you shard is the round.
- **How fresh must the index be?**
  → **Seconds, not instant.** Get this concession explicitly — it buys you segments.
- **How deep can users page?**
  → Push back and **cap it**. Nobody buys from page 1000. Ask in minute two, not minute forty.
- **Ranking, or just matching?**
  → **Ranking is the job.** Matching 40,000 documents is easy; ordering the top 20 is the product.
- **Filters, typos, personalisation?**
  → Brand/price/stock are **filters**: boolean, cacheable, unscored. Fuzzy and personalisation are v2.

## STEP 1 — Requirements
**Functional:** free-text query over title + description · **rank by relevance** · filter by
brand/price/stock · facet counts · paginate · index new/updated/deleted documents.
**Non-functional:** p99 < 300 ms · **near-real-time indexing (seconds)** · corpus exceeds one machine ·
read-heavy · **partial results acceptable, and must be labelled**.
**Out of scope:** personalisation · learning-to-rank · vector search (the obvious v2) · spell correction.

### CHECKPOINTS
- Extracts the concession that the index may be **stale by seconds**
- States the product is **ranking, not matching**
- Decides **in requirements** whether partial results are acceptable

### TRAPS
- Promising a document is searchable the instant it is written — that costs the segment design
- Scoring brand / in-stock instead of filtering them; they are boolean and cacheable

### FOLLOWUPS
- *"Why not `WHERE description LIKE '%noise cancelling%'` in Postgres?"*

## STEP 2 — Capacity
```
corpus    500M docs × ~1 KB text = 500 GB raw
index     delta-encoded INTEGER postings -> 30-40% of raw = 150-200 GB; take the TOP of my
          own band -> 200 GB   (positions for phrase search roughly DOUBLE it)
searches  50M/day ÷ 86,400 ≈ 600/sec, peak ~1,500/sec
indexing  2M changes/day ÷ 86,400 ≈ 25 docs/sec    <- writes are NOTHING here
shards    30-50 GB each (fits the OS page cache) -> 200 ÷ 40 = 5 primaries, ×2 = 15 copies
          10 primaries = 20 GB each: headroom I don't need at DOUBLE the tail exposure, so
          headroom goes into REPLICAS and at 400 GB I reindex behind an alias

THE NUMBER THAT DECIDES THE DESIGN
          1,500 QPS × 5 shards = 7,500 shard-searches/sec inside the cluster
          ** your shard count MULTIPLIES your own QPS **
```

### CHECKPOINTS
- Picks the **shard count from a target shard size**, not a round number
- States **query load is multiplied by the shard count**
- Notices the **write rate is trivial** (~25/sec) — a latency problem, not a write one

### TRAPS
- Sizing for 1,500 QPS when the cluster serves 7,500 shard-searches/sec
- Picking a shard count casually; the **primary count is fixed at index creation**

### FOLLOWUPS
- *"Five shards. Why not 100? More parallelism has to be faster. Then why not one big shard?"*

## STEP 3 — API
```
GET /api/v1/search?q=noise+cancelling+headphones&filter=brand:sony&filter=price:[100 TO 300]
      &size=20&cursor=<opaque>&timeout_ms=200      <- a budget, enforced PER SHARD
  -> 200 {hits: [...], cursor: "<opaque search_after token>", partial: false,
          shards: {total: 5, successful: 5},
          total: {value: 9000, relation: "gte"}}   <- an ESTIMATE, not an exact count

POST /api/v1/documents/_bulk -> 202  (searchable after the NEXT refresh)
GET  /api/v1/documents/{id}  -> 200  (by-id read is real-time; it bypasses search)
```

### CHECKPOINTS
- **Cursor pagination, never `page`/`offset`** — deep offsets are slow *and* drift under the reader
- Returns `total` as an **estimate with a relation**; an exact count means scoring every match

### TRAPS
- `?page=1000&size=10` in the public contract — the deep-pagination bomb shipped as a feature
- No per-shard timeout budget, so one sick shard hangs every caller

### FOLLOWUPS
- *"Your API returns `total: 9432`. Where did that come from and what did it cost?"*

## STEP 4 — Data structure — the inverted index
```
doc 7: "Sony wireless headphones with active noise cancellation"
  analyse (lowercase, tokenise, stopwords, stem) -> [sony, wireless, headphon, activ, nois, cancel]

TERM -> POSTING LIST, sorted by doc id, delta-encoded:
  headphon -> [(7, tf=1, pos=[2]), (12, tf=2, pos=[0,9]), ...]
  nois     -> [(7, tf=1, pos=[4]), (88, ...), ...]

query --same chain--> [nois, cancel, headphon] -> intersect the lists (a linear merge, skip
  pointers to leapfrog) -> score the survivors
```

| vs round 06 | trie (typeahead) | inverted index |
|---|---|---|
| Question | completes a **prefix** | documents **containing terms** |
| Ranking | **precomputed top-k per node** | per query — never seen before |
| Sharding | leading chars, **one** shard | by document, **every** shard |

**The query must run exactly the same analysis chain as the document.** Index `headphon`, search
un-stemmed `headphones`, match nothing — and it fails **silently**, as an empty page. So **an analyser
change means a full reindex** (exception: query-time synonyms). Dropping `the` kills a colossal posting
list but also kills *"The Who"* — keep stopwords, let IDF de-weight them.

### CHECKPOINTS
- Draws **term -> posting list sorted by doc id**; sorted order makes intersection a linear merge
- **Contrasts trie with inverted index** — a curated prefix set vs terms over a huge corpus
- Query and document share the **same analysis chain**, so an analyser change is a reindex

### TRAPS
- Reaching for the round-06 trie — it cannot answer "documents containing these three words"
- Analysing the document but not the query — it looks like an empty catalogue, never like an error
- A SKU or status enum in an analysed `text` field instead of a `keyword` one — exact filters go fuzzy

### FOLLOWUPS
- *"We want a stemmer on the title field. What has to happen before it takes effect?"*

## STEP 5 — Architecture
```
WRITE  product DB --CDC/outbox--> Kafka --> Indexer --> route hash(doc_id) % 5
         shard: buffer + TRANSLOG (durable, NOT searchable)
                refresh (~1 s) -> new IMMUTABLE segment = searchable
                flush -> truncate translog  |  merge (bg) -> small segments into big

READ   Client --> Coordinator (stateless)
         SCATTER  all 5 shards: intersect postings -> BM25 -> local top-k (ids+scores ONLY)
         GATHER   merge 5 sorted lists -> global top-k
         FETCH    stored fields, from the WINNING shards only
         RE-RANK  business model over the top ~200 -> response
```
- A **segment is an immutable mini-index**. **Two clocks: refresh = visibility, flush = durability.**
- Documents are never edited: update = **delete + reinsert**, the delete a **tombstone** whose old copy
  still counts toward document frequency until merged.
- **Merging is the background tax** — a query visits every segment, so 500 tiny ones are slow. Refresh
  at 1 s = fresh and merge-heavy, at 30 s = cheap and stale; bulk load = refresh off, replicas zero.

### CHECKPOINTS
- A document is **not searchable until the next refresh**
- Segments are **immutable** — update is delete-plus-tombstone — and **merging** is the cost

### TRAPS
- Indexing synchronously on the product write path — checkout latency coupled to a merge storm
- Refresh at 100 ms because fresher sounds better — a permanent merge backlog nobody asked for

### FOLLOWUPS
- *"I indexed a document 200 ms ago and search can't find it. Is that a bug?"*

## DEEP DIVE — scatter-gather, deep pagination, and relevance

### 1. Why you shard by document
Each shard scores its own subset and returns its **local top-k**; the coordinator merges. That works
because **top-k is mergeable** — the global top 20 sits inside the union of the local top 20s, as with
round 10's per-region leaderboards.

**Why not shard by term?** A 3-term query would touch 3 shards instead of 5 — but **posting lists must
cross the network to be intersected** (`wireless` may have 40M entries, per query), **term frequency is
Zipfian** so hot shards are guaranteed rather than accidental, and **scoring needs a document's
statistics in one place**. By document, each shard is a complete mini-index that ranks alone.

**What the fan-out costs:**
- **Latency is the slowest shard, not the average.** With 5 shards a 1-in-100 slow shard makes ~**1 in
  20 queries slow** (with 10, 1 in 10) — *tail amplification*. So **fewer, bigger shards for latency,
  more for corpus**: five of 40 GB, not ten of 20.
- **IDF is computed per shard**, so a document scores differently depending where it landed; a pre-round
  gathering global term statistics fixes it, at one extra round trip.

### 2. Deep pagination
```
page 1000  from=9990, size=10   each shard returns from+size = 10,000 docs
                                5 × 10,000 = 50,000 sorted at the coordinator, for TEN results
```
Cost is `shards × (from + size)` — it grows with **depth**, not results returned. A self-inflicted DoS:
one crawler looping to page 500 downs a cluster human traffic never could.

| Fix | What it does | Cost |
|---|---|---|
| **Cap the depth** (10,000) | turns the bomb into a `400`; Google stops near page 100 too | an owned product call, not silent truncation |
| **`search_after` cursor** | page N+1 resumes *after* the last sort key, so each shard returns only `size` — O(1) at any depth | forward-only; the key must be **unique and total**, `(score, doc_id)`, or rows skip and repeat |

**Nobody buys from page 1000.** Deep paging is a symptom of failed relevance and missing facets.

### 3. Relevance — what BM25 is doing
- **TF with diminishing returns.** Five "headphones" beat one; 100 is stuffing. **BM25 saturates TF,
  TF-IDF does not** — substantially why it replaced it.
- **IDF: rare terms carry the signal.** `the` says nothing; `sony`, in 0.1% of documents, says almost
  everything.
- **Length normalisation:** a 10,000-word page contains any term by chance and must not win on that.
- **A score is comparable only within one query** — never threshold on it, never show it.

### 4. Retrieve cheap, re-rank expensive
`BM25 over the whole index -> top ~500/shard`, then `the expensive model over ~200 -> top 20`. The
re-ranker is where the business lives — conversion, stock, margin, personalisation — **none of which
belongs in the index**: per-user, changes hourly, not a term. This saves **CPU**; the query-then-fetch
two-phase above saves **network**.

### CHECKPOINTS
- Describes **scatter-gather** — each shard returns a **local top-k**, and why that is sufficient
- Rejects **term sharding**: posting lists on the wire, Zipfian hot shards, doc-local scoring
- Names **tail amplification** — latency is the slowest shard, so more shards is not faster
- Works out deep pagination's `shards × (from + size)`, with the number for page 1000
- Fixes it with **`search_after` on a unique tie-broken sort key** plus an owned depth cap
- Explains BM25 as **saturating TF + IDF + length normalisation**, and splits retrieval from re-ranking

### TRAPS
- "Shard by term so a query only hits the shards holding its words", with no account of why it fails
- Solving deep pagination with a cache — every page is a different key, and a crawler never repeats one
- A non-unique cursor key, so rows silently skip and repeat between pages

### FOLLOWUPS
- *"A user is on page 1000. Walk me through exactly what the cluster does."*
- *"The same product scores 8.1 on one shard and 7.4 on another. Explain."*

## STEP 7 — Scale
| Knob | Fixes | Costs |
|---|---|---|
| **More replicas** | query throughput | more indexing work, more disk |
| **More primaries** | corpus, indexing parallelism | more fan-out, worse tails, **fixed at creation** |
| **Custom routing** | fan-out collapses to **one shard** for tenant/seller/locale-scoped queries | a giant tenant becomes a hot shard — round 01's celebrity |
| **Aliases** | analyser or shard-count change with no downtime: build alongside, replay Kafka, **flip** | a full reindex, double disk while it runs |

Append-only data goes in **time-based indices** behind the alias, so old data is dropped by dropping an
index rather than by tombstones that cost merges. The cache that matters is the **OS page cache** —
which is why shards are sized to fit it.

### CHECKPOINTS
- Separates **replicas scale queries** from **primaries scale corpus**
- Names **routing by a query-scoped key** to turn a fan-out into a single-shard query

### TRAPS
- Adding shards to fix query latency — you added fan-out and made the tail worse
- Assuming the primary count can change in place, rather than by reindexing behind an alias

### FOLLOWUPS
- *"You need a new synonym file and a new stemmer in production, with no downtime. How?"*

## STEP 8 — Failure
**One shard is down: fail the query, or serve four shards' worth with a flag?** Own it per surface:

| Surface | Call | Why |
|---|---|---|
| Product search / browse | **partial + flag** | 80% of a catalogue beats an error page |
| Counts, facets, aggregations | **degrade the number** | a partial count is silently wrong and looks authoritative |
| Compliance, "does this exist?" | **fail the query** | an incomplete answer to an existence question is worse than an error |
| Mid-pagination | **fail, or restart the cursor** | a changed shard set mid-scroll makes pages skip and repeat |

**Never cache a partial response**; always return `shards: {total, successful}`.
- **Indexing down:** serve staler results — **degrade freshness, never availability.** Kafka holds the backlog.
- **One slow shard:** per-shard timeout, prefer the fastest healthy replica, take the partial over a hang.
- **Shard lost:** the index is derived — replay Kafka or the product DB.

### CHECKPOINTS
- **Owns the partial-results decision per surface**; a partial response is flagged and never cached
- **Degrades freshness rather than availability**, treating the index as rebuildable derived data

### TRAPS
- "Return whatever came back" with no flag — the caller can't tell 9,000 from 10,000-minus-a-shard
- Failing the whole query on any missing shard — a 20% content gap turned into a 100% outage

### FOLLOWUPS
- *"One shard out of five is down. What does the user see, and what happens to the facet counts?"*

## STEP 9 — Wrap
- **Bottleneck:** the **fan-out** — latency is the slowest shard, internal load is QPS × shard count, and
  both worsen as you add shards. Not write throughput; 25 docs/sec is nothing.
- **Tradeoffs:** more shards (parallelism, corpus) vs fewer (better tails) · refresh often (fresh,
  merge-heavy) vs rarely (cheap, stale) · positions (phrase search) vs half the disk · exact totals (a
  full scan) vs estimates.
- **Monitoring:** **p99 per shard**, not per query — one bad shard hides in the average · partial-result
  rate · **segment count and merge backlog** · indexing lag · **zero-result rate**.
- **Next:** hybrid retrieval (vector recall merged with BM25), learning-to-rank on click logs, spell
  correction, per-locale analysers.

### CHECKPOINTS
- Names the **fan-out** as the bottleneck, and picks **p99 per shard** and a **relevance metric** as headline numbers

### TRAPS
- Naming only system metrics — relevance is an SLO here, and no latency dashboard shows a ranking regression

### FOLLOWUPS
- *"How would you know your ranking got worse after a deploy?"*

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | "use Elasticsearch", `LIKE` on a SQL table, no index structure, `from`/`size` pagination, no ranking story |
| **Senior** | inverted index as term -> posting list · one analysis chain for query and document · document sharding with scatter-gather · BM25's three intuitions · `search_after` and a depth cap · near-real-time refresh |
| **Staff** | all that **+ rejecting term-sharding with real reasons** · **tail amplification** and the fewer-vs-more-shards tradeoff, shard count derived from a target shard size · per-shard IDF skew · segments and merge pressure as an operational cost · retrieve-then-re-rank with business signals out of the index · **owning the partial-results decision per surface** |

## REFERENCE
**A product is updated:** the DB commit emits a CDC/outbox row to Kafka — the DB stays the source of
truth. The indexer analyses it and routes by `hash(doc_id) % 5` to one shard, which appends to its buffer
plus the **translog**: durable, **not searchable yet**. **Refresh** (~1 s) seals the buffer into an
immutable segment and *now* it is searchable; **merges** later fold segments and drop tombstones.

**"noise cancelling headphones", filtered to `in_stock:true`:**
1. The coordinator analyses the query with **the same chain**: `[nois, cancel, headphon]`.
2. **Scatter** to all 5 shards: intersect the posting lists, apply `in_stock` as a cached bitset
   (**unscored**), score with **BM25**, return the **local top 200 as ids and scores only**.
3. **Gather** into a global top 200; **fetch** stored fields from the winning shards only.
4. **Re-rank** those ~200; return 20, plus a `search_after` cursor on `(score, doc_id)` and
   `total: {value: 9000, relation: "gte"}`.

**Page 2** returns that cursor: every shard resumes *after* the sort key and returns 20 rows, at
identical cost to page 1 — which is the whole point, and why `from=9990` is banned.

## ONE-LINER
> *"The answer is an **inverted index** — term to a sorted posting list of doc ids — a different question
> from round 06's trie, because the query has never been seen and there is nothing to precompute. I shard
> **by document**, not by term, so every shard is a complete mini-index that scores alone; a query
> scatters to all of them and the coordinator merges their local top-ks. The price is that latency is the
> **slowest shard**, which is why I take five shards of 40 GB rather than ten of 20. Ranking is **BM25** —
> saturating term frequency, IDF, length normalisation — and I re-rank only the top couple of hundred with
> the expensive business model. The trap I'd raise unprompted is **deep pagination**: page 1000 makes
> every shard return 10,000 documents, so I use a `search_after` cursor on a unique sort key and cap the
> depth."*
