# RAG end-to-end — explained

**Your code:** `AI-Studio-ResumeFlow/backend/routes/hr_chat_routes.py`

| Line | What's there |
|---|---|
| `:27` | `GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"` |
| `:304` | the embedding call |
| `:322` | MongoDB Atlas `$vectorSearch`, `path: "embedding"` |
| `:326` | **`numCandidates: top_k * 10`** |
| `:334` | `vectorSearchScore` via `$meta` |
| `:656` | `StreamingResponse` — SSE to the browser |

---

## The two paths

### Ingest (offline, once per document)

```
policy PDF → parse → chunk → embed each chunk → store {text, embedding, metadata}
                                                  in MongoDB with a vector index
```

### Query (online, per question)

```
question → embed (same model!) → ANN search → top-k chunks
        → inject as context into the prompt → generate → stream tokens over SSE
```

**The critical invariant: the same embedding model on both sides.** Embeddings from
different models live in different vector spaces — the numbers are meaningless across them.
Changing the embedding model means **reindexing the entire corpus**, which is why it's a
migration, not a config change.

---

## Why RAG at all, rather than fine-tuning

Three reasons, and you should give all three:

1. **Freshness** — a policy change is a re-index, not a retraining run.
2. **Attribution** — you can show *which* policy the answer came from. Fine-tuning bakes
   knowledge into weights with no provenance, which is unacceptable for an HR policy answer.
3. **Cost** — retrieval is cheap; fine-tuning is a training job plus a hosting problem.

Fine-tuning teaches *behaviour and format*. RAG supplies *facts*. Conflating them is a
common interview error — the honest line is *"I'd fine-tune for style, retrieve for facts."*

---

## `numCandidates = 10 × top_k` — the ANN question

Atlas vector search is **approximate**. It doesn't compare your query to every vector; it
walks a graph index. `numCandidates` is how many nodes it explores before narrowing to
`top_k`.

- **Low** → fast, but the true nearest neighbours may never be visited → **recall drops**.
- **High** → better recall, more latency, approaching a brute-force scan.

**10× is the standard starting ratio**: enough exploration that the true top-k is very
likely inside the candidate pool, without scanning the index.

The honest addendum, and say it: *"It's a sensible default, not a tuned value. I'd tune it
against measured recall@k on a labelled question set — that's the missing piece."*

This is the same dial as HNSW's `ef_search`. Knowing they're the same concept under
different names is the senior signal.

---

## Chunking — the thing that actually determines quality

Retrieval failures are usually **chunking** failures, not model failures.

- **Too large** → the chunk contains the answer plus three unrelated paragraphs; the
  embedding is a blur of all four, so it matches nothing precisely.
- **Too small** → a fact gets split across a boundary and neither half retrieves.
- **Overlap** exists so a fact spanning a boundary survives in at least one chunk.

For policy documents, **section-aware splitting beats fixed-size**, because the document
already has semantic boundaries — clauses and sections — and splitting on those means each
chunk is a complete idea.

> **Look up your actual chunk size and overlap before any interview.** "I don't remember"
> is a bad answer to a question you should own.

---

## Why SSE and not WebSockets

SSE is one-directional server→client, which is exactly the shape of streaming an answer. It's
plain HTTP, so it works through proxies and load balancers with no protocol upgrade, and it
auto-reconnects with `Last-Event-ID`.

WebSockets are right when the *client* also streams continuously — which is the voice path,
handled differently.

**Production gotcha worth volunteering:** nginx buffers responses by default, so streaming
works locally and appears broken in production until you set `X-Accel-Buffering: no`.

---

## The follow-ups, answered

**"An employee asks something not in the policies."**
It should say it doesn't know. That needs two things: a **relevance floor** on the retrieval
score (`vectorSearchScore` at `:334` is right there for it) and a prompt instruction to
refuse when context is insufficient. Without both, the model answers from general knowledge
and confidently invents company policy — the worst possible failure for this feature.

**"Why no reranking?"**
Concede it properly: first-stage ANN returns *plausible* chunks, not the *best ordering*. A
cross-encoder over the top ~20 would improve precision because it sees query and document
**together**, rather than comparing two independently-computed embeddings. For a policy corpus
with distinct topics, first-stage was good enough. On a larger or more homogeneous corpus I'd
add **hybrid BM25 + vector first** — policy questions contain exact terms ("Form 16", "notice
period") that embeddings blur — and reranking second.

**"How do you know retrieval is working?"**
Today: chunk preview and manual inspection. Properly: **recall@k on a labelled question set** —
for each question, is the chunk that actually contains the answer in the top k? That single
number tells you whether to fix retrieval or generation, and not having it is the real gap.

**"What breaks first at 1M users?"**
The LLM provider — rate limits, then cost. Not your servers. See `hld.md`.

---

## One-line summary

> "Chunk, embed, ANN-search, inject, stream. The interesting decisions are chunk boundaries
> and the recall/latency dial on the ANN index — the model is rarely the bottleneck."

## The trap answer to avoid

Describing RAG as "the model searches the documents." The model never searches anything —
**your code retrieves, then the model reads what you handed it.** Candidates who get this
backwards reveal they've only used a framework, not built one.
