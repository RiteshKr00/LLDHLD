# LLM-powered search and ranking — explained

---

## 1. The budget is the question

200ms, and a single LLM generation call is 200ms–2s on its own. `solution.py §1` lays out a
budget that actually fits:

| Stage | ms |
|---|---|
| network in + out | 25 |
| query understanding | 3 |
| BM25 over 10M | 18 |
| ANN vector search | 22 |
| fusion + dedup | 4 |
| cross-encoder rerank 100 | 28 |
| business rules + render | 12 |
| **Total** | **112**, leaving 88ms of headroom |

One generation call is **4.5x the entire budget**. So the LLM cannot be in the synchronous
path — not "should not", *cannot*. Say that in the first minute; it is the answer, and
everything else is a consequence.

---

## 2. "Embed everything and use vector search" is a worse search engine

This is the trap, and it is worth being concrete about why. `solution.py §2` measures whether
each retriever has any *signal* — whether it separates documents at all:

| Query | BM25 spread | Vector spread | Who has signal |
|---|---|---|---|
| `E4471` | 3.96 | **0.00** | BM25 only |
| `locked out` | **0.00** | 0.55 | vector only |

An embedding has never meaningfully seen a rare error code, so it scores every document the
same. And no document contains the words "locked out", so BM25 has nothing to rank on at all.

Each is blind exactly where the other sees. Site-search traffic is full of both: error codes,
SKUs, part numbers and people's names on one side, and natural-language paraphrase on the
other. Vector-only loses the first category entirely, and that category is usually the majority.

---

## 3. Hybrid buys a floor, not an average — and naive fusion is worse than one arm

`solution.py §3`:

| Query | BM25 | Vector | Plain RRF | **Gated RRF** |
|---|---|---|---|---|
| locked out | 0.25 | 0.95 | 0.89 | **0.95** |
| E4471 | 1.00 | 0.00 | **0.00** | **1.00** |
| cant get into my account | 1.00 | 0.72 | 0.82 | 0.82 |
| how do i get my money back | 0.93 | 0.69 | 0.93 | 0.93 |
| **Mean** | 0.80 | 0.59 | 0.66 | **0.93** |
| **Worst query** | 0.25 | 0.00 | 0.00 | **0.82** |

Two findings, and the second is the one worth having.

**Read the worst row, not the mean.** Each single retriever has a query type it scores near zero
on, and which type that is depends entirely on your traffic mix.

**Plain RRF is worse in the worst case than BM25 alone.** On `E4471` it averages a correct
ranking with an arbitrary one, and the noise displaces the signal. The fix is to **gate each
retriever on whether it actually ranked anything** before fusing. That detail is easy to miss and
it is the difference between fusion helping and fusion hurting.

Then a **cross-encoder over the top 100** — small, distilled, ~28ms. It sees the query and the
document *together*, which a bi-encoder structurally cannot. It is the highest-leverage 28ms in
the system.

---

## 4. Similarity is not usefulness

`solution.py §4`, for "how do i get my money back":

- by semantic similarity, "Billing and invoices" ranks near the top
- by what users clicked, it got **7 clicks against 62** for "Refund policy"

"Billing and invoices" is topically adjacent and nobody wants it. Similarity is a proxy for
relevance, and relevance is a proxy for usefulness. **Click data measures the thing itself**,
which is why learning-to-rank on clicks beats tuning an embedding — and why "is click data
available?" is one of the first questions to ask.

---

## 5. Where the LLM actually earns its place: offline

| Job | What it does | What it buys |
|---|---|---|
| Document enrichment | summary, keywords, synthetic questions per doc | recall on paraphrase queries |
| Query-expansion dictionary | mined from logs, applied as a lookup | tail recall, **0ms** at serve time |
| Training-pair generation | query/document pairs for the reranker | ranking quality before click data exists |
| Relevance judging | LLM-as-judge on a sample | a metric that is not click-through |

Every one runs hours before the query. The LLM makes the index and the ranker better; it never
touches the request. **That is the design**, and it is a stronger answer than any way of
squeezing generation into 200ms.

Synthetic questions per document deserve a special mention: indexing "how do I get a refund?"
alongside the refund policy is the cheapest recall win available, and it works precisely because
it moves the paraphrase problem offline.

---

## 6. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **The latency budget** | If you put generation inline. It is 4.5x the whole budget. |
| 2 | **Tail relevance** | Click data is sparse exactly where you need it most. |
| 3 | **Freshness** | New documents are findable before they are enriched or ranked well. |
| 4 | **Feedback loops** | Ranking trains on clicks, clicks come from ranking; the rich get richer. |
| 5 | **Business rules** | Baked into embeddings, they become untunable. |

---

## The follow-ups, answered

**1. Where exactly does the LLM run?**

Offline, in four places: document enrichment, query-expansion dictionaries, generating training
pairs for the reranker, and judging relevance on a sample. At serve time there is no LLM at all —
BM25, an ANN index, and a small distilled cross-encoder. If someone insists on a generative
feature in the results page, it goes **after** first paint, streamed asynchronously, so it cannot
hold up the ten blue links.

**2. Why not embed everything and use vector search?**

Because it is a worse search engine for a large fraction of real queries. An embedding has never
meaningfully seen `E4471`, a part number, or an unusual surname, so it returns a flat score
across the corpus — no signal at all, not merely a weaker one. BM25 handles those natively via
term frequency and rare-term weighting. Conversely BM25 has nothing to say about a paraphrase
with zero term overlap. You need both, and the argument is about the *floor*, not the average.

**3. What is your first-stage retrieval, and why hybrid?**

BM25 over an inverted index, plus ANN over embeddings, fused with reciprocal rank fusion. RRF
because it needs no weight to tune, and the right weight would differ per query type anyway. The
non-obvious detail: **gate each retriever on whether it produced any signal before fusing.**
Fusing a real ranking with an arbitrary one measurably degrades it — in the simulation, naive
fusion scores 0.00 on a query where BM25 alone scores 1.00.

**4. How do you rank, once you have 100 candidates?**

A cross-encoder — small, distilled, ~28ms for 100 pairs. Unlike the bi-encoder used for
retrieval, it encodes query and document jointly and can attend across them, which is where the
quality comes from. Then apply business rules — freshness, popularity, sponsored — as **separate
ranking features on top**, never folded into the model, so they stay tunable and auditable. Over
time, replace the hand-tuned combination with learning-to-rank on click signal.

**5. You have no click data yet. How do you bootstrap?**

Three sources, in order. Use the LLM offline to generate query/document training pairs from the
corpus — imperfect, and enough to train a first reranker. Use a pretrained cross-encoder
zero-shot, which is usually better than BM25 alone out of the box. And build a small
human-judged set for evaluation, a few hundred queries, so you can tell whether you are
improving. Then instrument clicks from day one and switch to them as they accumulate, being
careful about position bias — logged clicks reflect the ranking that produced them, so you need
randomisation or a debiasing model before treating them as ground truth.

**6. A new document is published. When is it findable, and when is it ranked well?**

Two different times, and being explicit about the gap is the point. **Findable** within seconds:
index it into BM25 and embed it with the standard model — no LLM in that path. **Ranked well**
after enrichment, which is minutes to hours behind: summaries, synthetic questions, keywords.
Design so the document is searchable in its unenriched state rather than invisible until the
batch runs, and track enrichment lag as a metric, because "new content ranks badly for six hours"
is a real product problem that nobody notices in aggregate relevance numbers.

**7. How do you know a ranking change is an improvement?**

Offline first, on a held-out judged set — nDCG, and per query-type rather than only in aggregate,
because most changes help one segment and hurt another. Then an interleaved online experiment,
which is far more sensitive than an A/B test for ranking because it compares two rankings within
the same user's session and removes most of the between-user variance. Watch guardrails
alongside the primary metric: queries with no click, query reformulation rate, and results-page
abandonment. A change that raises click-through while raising reformulation has made search
worse.

**8. Head queries are 40% of traffic. What do you do with that?**

Cache them, and then spend the savings. A cached head query costs almost nothing to serve, which
frees latency budget for the tail where the work is. More usefully, the head is where you can
afford to be **expensive offline**: precompute the ideal ranking, have a human curate the top
handful for the highest-volume queries, and run a heavier reranker than the budget would allow
inline. The tail is where hybrid retrieval and the cross-encoder earn their keep, because there
is no click data to lean on.

**9. Business wants sponsored results promoted.**

As an explicit, separate ranking feature applied after relevance ranking — never trained into the
model or baked into embeddings. Three reasons: it stays tunable without retraining; it stays
auditable, so you can answer "why was this shown?"; and it can be capped, so a slot budget limits
how much relevance you are willing to trade. Then measure the cost — the relevance loss per
promoted slot — and put that number in front of whoever asked, because the honest framing is that
sponsorship spends relevance and someone should decide how much.

---

## One-line summary

200ms rules out generation in the request path entirely, so the serving stack is hybrid BM25 plus
ANN — gated on whether each retriever has any signal, because fusing a ranking with noise is
worse than one arm alone — followed by a small cross-encoder over the top 100, with business
rules as separate features and the LLM doing its work offline on enrichment, query expansion and
training pairs.

---

## The trap answer to avoid

"I'd embed everything and use vector search." It is a worse search engine than BM25 for exact
terms, error codes, SKUs and names, which is most of what people type into a site search — and
the failure is total rather than partial, because an embedding returns a *flat* score for a token
it has never seen. The second trap is trying to fit generation into 200ms with a smaller model or
a shorter prompt; the budget is off by 4.5x and the right move is to take the LLM out of the
request path entirely.
