# Search at 10M documents

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Corpus | 10M documents | |
| Budget | 200ms | end-to-end matters; confirm which |
| Serving path total | ~112ms | 88ms headroom |
| One LLM generation | ~900ms | 4.5x the whole budget |
| Rerank depth | top 100 | ~28ms, the best-value stage |
| Head queries | ~40% of traffic | cacheable |

## 2. Topology

**Offline (hours before the query).** Document enrichment — summaries, keywords, synthetic
questions. Query-expansion dictionaries mined from logs. Training pairs for the reranker.
LLM-as-judge relevance sampling. This is where every LLM call in the system lives.

**Index.** Inverted index for BM25; HNSW for vectors. Both updated on publish, so a document is
findable in seconds even though it is not well-ranked until enrichment lands.

**Serving.** Query understanding → BM25 and ANN in parallel → **signal-gated** RRF → cross-encoder
over top 100 → business rules → render. No LLM.

**Feedback.** Click and dwell logging with position information, feeding learning-to-rank.

## 3. The stage that earns its cost

The cross-encoder. 28ms for 100 query/document pairs, and it is the only component that sees the
query and document *jointly*. Retrieval decides what is possible; the reranker decides what is
good. If you can afford one expensive thing in the path, it is this.

Rerank depth is a dial: 100 is a reasonable default, 50 halves the cost for a modest quality
loss, 200 rarely pays. Tune it against the latency budget rather than picking a round number.

## 4. Freshness has two clocks

**Findable** — seconds. BM25 and a standard embedding, on publish.
**Well-ranked** — minutes to hours. After enrichment.

Track the gap as a metric. "New content ranks badly for six hours" is invisible in aggregate
relevance and very visible to whoever published it.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Latency, if generation goes inline | It cannot. Move the LLM offline. |
| 2 | Tail relevance | Offline enrichment, synthetic questions, query expansion |
| 3 | Enrichment lag | Index unenriched; alert on lag |
| 4 | Click feedback loops | Randomisation or position-bias correction before training |
| 5 | Business rules in embeddings | Keep them as separate, tunable features |

## 6. Evaluation

Offline nDCG on a judged set, **sliced by query type** — head/tail, navigational/informational,
exact-token/paraphrase. Then interleaving online, which is far more sensitive than A/B for
ranking. Guardrails: no-click rate, reformulation rate, page abandonment. A change that lifts
click-through while lifting reformulation has made search worse and will pass a naive A/B test.

## 7. Observability

p99 per stage, separately — the budget is a sum and you need to know which term grew. Retrieval
signal rate per arm, i.e. how often BM25 or the vector arm returns nothing rankable; a rise means
a corpus or embedding problem. Rerank depth and its latency. Cache hit rate on head queries.
Enrichment lag. And the metric worth reviewing with a human weekly: **queries with a
reformulation and no click**, which is the closest thing to "search failed" you can measure
directly.
