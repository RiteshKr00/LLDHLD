# Embeddings & ANN — explained

**Your anchors:** `hr_chat_routes.py:322-334` (Atlas `$vectorSearch`, `numCandidates`,
`vectorSearchScore`) · `CSR-Exp` uses Weaviate with hybrid BM25+dense and `bge-m3` ·
`digital-twin` uses Vectra, a local index.

Three different vector stores across three systems — that's a genuine strength. You can
compare them, which most candidates can't.

---

## What an embedding is, in one sentence

A fixed-length vector where **geometric closeness approximates semantic similarity** — so
"notice period" and "resignation timeline" land near each other even with no shared words.

## Cosine vs dot product

- **Cosine** = angle only, magnitude-independent.
- **Dot product** = angle **and** magnitude.

They're identical **when vectors are normalised to unit length** — which most embedding models
do. When they aren't, dot product lets a longer vector win on magnitude alone, which usually
means "longer document" rather than "more relevant". Default to cosine unless you know the
model's vectors are normalised.

---

## Why "approximate", and what HNSW is doing

Exact search compares your query to **every** vector — O(n), fine at 10k chunks, hopeless at
10M.

**HNSW** (Hierarchical Navigable Small World) builds a layered graph. Sparse upper layers have
long-range links for coarse navigation; dense lower layers have short-range links for fine
search. A query enters at the top, greedily hops toward closer neighbours, descends, repeats.
Log-ish time instead of linear.

**The cost of the shortcut:** greedy graph traversal can get stuck in a local minimum and miss
the true nearest neighbour. That's the "approximate" — and it's the trade you're tuning.

| Parameter | Turn it up | Turn it down |
|---|---|---|
| `ef_search` / `numCandidates` | better recall, more latency | faster, may miss true top-k |
| `M` (links per node) | better recall, bigger index | smaller index, worse recall |
| `ef_construction` | better index quality, slower build | fast build, worse recall |

**Atlas's `numCandidates` is the same dial as HNSW's `ef_search`.** Knowing they're one
concept under two names is the senior signal.

Your `numCandidates = 10 × top_k` is the standard starting ratio — enough exploration that the
true top-k is very likely in the candidate pool. **Say the honest part too:** it's a default,
not a tuned value, and tuning it requires measured recall@k.

---

## Changing the embedding model is a migration, not a config change

Vectors from different models occupy **different spaces**. Comparing them is meaningless — not
degraded, meaningless. So changing the model means:

1. re-embed the entire corpus
2. rebuild the index
3. cut over atomically, or dual-write and dual-read during transition

**And the subtle one:** the same model must embed the query, and asymmetric models (like
`bge-m3` variants) need the **right prefix** for query vs document. Getting the prefix wrong
silently degrades recall with no error — the worst kind of bug, because everything "works".

---

## Why a cross-encoder beats the search that produced the candidates

- **Bi-encoder** (what the index uses): embeds query and document **separately**, compares
  vectors. Fast, precomputable, but the document embedding was computed without ever seeing
  the query.
- **Cross-encoder** (the reranker): puts query and document **through the model together**, so
  attention can relate specific words in each. Far more accurate, far slower — you can't
  precompute it.

Hence the standard two-stage design: **bi-encoder for recall over millions, cross-encoder for
precision over the top ~20.** Being able to explain *why* the second stage is better rather
than just that it is — that's the answer.

---

## When hybrid BM25 + vector is necessary

When queries contain **exact tokens that embeddings blur**: identifiers, policy names, form
numbers, error codes, product SKUs. "Form 16" and "Form 26AS" are semantically nearly
identical and operationally completely different — vectors struggle, BM25 doesn't.

CSR-Exp does hybrid with a **per-section alpha** (the vector/keyword weighting), because
different sections favour different retrieval modes. That's a real, defensible tuning
decision — cite it.

---

## One-line summary
> "The index is a navigable graph, so search is approximate — and `numCandidates` is the
> recall/latency dial. Bi-encoder for recall, cross-encoder for precision, BM25 for the exact
> tokens embeddings blur."

## The trap answer to avoid
Saying "it finds the most similar chunks." It finds *approximately* the most similar, via a
graph traversal with a tunable exploration budget. The approximation **is** the topic.
