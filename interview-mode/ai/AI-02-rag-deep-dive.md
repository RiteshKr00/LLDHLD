# AI-02 — RAG deep dive

## META
- difficulty: med-hard
- time: 15 min
- tags: rag, embeddings, ann, chunking, sse, refusal
- source: `02-rag-pipeline/`, `07-vector-search-ann/`

## PROMPT

> "You built a RAG chatbot over company policy documents. Take me from the employee typing a
> question to the first token on their screen. Then: retrieval quality is bad — debug it."

## CLARIFY

- **"Ingest path too, or just query time?"**
  → *"Both, briefly."*
- **"Optimising for latency, cost, or answer quality?"**
  → *"Quality first. Assume moderate traffic."*
- **"Static corpus or continuously updated?"**
  → *"Policies change a few times a year."*

## STEP 1 — Scope & stakes

### CHECKPOINTS
- Employees asking HR the same policy questions repeatedly
- The stake: a **wrong** policy answer is worse than no answer — it's the company speaking
- Therefore the refusal path is load-bearing, not an afterthought

## STEP 2 — Mechanism (both paths)

### CHECKPOINTS
- **Ingest**: parse → chunk → embed each chunk → store text + embedding + metadata with a vector index
- **Query**: embed question → ANN search → top-k → inject as context → generate → stream
- Names the invariant: **same embedding model both sides** (different models = different vector spaces)
- Streams over **SSE**; can say why SSE not WebSockets (one-directional, plain HTTP, proxy-friendly)
- Can point at the file: `hr_chat_routes.py:322` `$vectorSearch`, `:656` `StreamingResponse`

## STEP 3 — Trade-offs

### CHECKPOINTS
- **RAG vs fine-tuning**: freshness (re-index, not retrain), **attribution** (which policy), cost
- "Fine-tune for style, retrieve for facts"
- **`numCandidates = 10 × top_k`** — explains it as the recall/latency dial, and that it's the same concept as HNSW `ef_search`
- Concedes it's a **default, not a tuned value**
- Chunking: too large → blurred embedding; too small → fact split across a boundary; overlap covers boundaries
- Section-aware splitting beats fixed-size for structured policy docs

## STEP 4 — Failure modes & the debug checklist

### CHECKPOINTS
Debugs in the right **order** — chunking first, measurement last:
1. chunking (size / boundaries)
2. embedding mismatch (same model? right prefix for asymmetric models?)
3. no hybrid search — exact tokens ("Form 16") that embeddings blur → add BM25
4. no reranking — cross-encoder over top ~20, and **why** it's better (sees query+doc together)
5. query preprocessing / multi-turn reformulation
6. **then measure**: recall@k on a labelled set — everything above is a hypothesis until then
- Out-of-corpus question → **relevance floor on the score** + prompt instruction to refuse
- Names the worst failure: confidently inventing company policy

## STEP 5 — Scale to 1M

### CHECKPOINTS
- Estimates: 50k DAU × 5 q/day ≈ 3 QPS avg, design for 30 QPS peak, ~60 concurrent
- Names the **first** bottleneck correctly: the **LLM provider** (rate limits, then cost) — not servers
- **Semantic caching** as the top lever, with the trade: threshold, TTL, and **per-tenant namespacing** (a cross-tenant cache hit is a leak)
- Model routing / cascading — cheap model for easy queries
- The answer most miss: **quality degrades too** — corpus and query diversity explode, precision falls, reranking stops being optional, continuous eval required
- Connects retrieval precision to **cost** (fewer chunks = fewer prompt tokens)

## STEP 6 — Honesty

### CHECKPOINTS
- Volunteers: **no reranking, and no measured recall@k** — can't say how often the right chunk is retrieved
- `numCandidates` untuned
- Separates credit: Atlas does ANN; *you* chose the ratio and know what it trades
- No accuracy metric invented

## TRAP

Saying "the model searches the documents." The model never searches anything — **your code
retrieves, then the model reads what you handed it.** Getting this backwards reveals framework
use rather than system understanding.
