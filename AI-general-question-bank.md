# General AI-engineer question bank

**Project-independent.** Everything else in this track is anchored to your repos; this is what
any AI-engineer candidate gets asked regardless of what they built. Short, sharp answers —
the goal is that none of these can catch you cold.

Format: **Q** then the answer in 1-4 sentences, with the trap where there is one.

---

## 1 - LLM fundamentals

**Q: What is a token?**
A sub-word unit. Roughly 4 characters or 0.75 words in English; far worse for code and
non-Latin scripts. Cost and context limits are counted in tokens, not characters — which is
why "shorten the prompt" and "cut cost" are the same task.

**Q: What is the context window, and what happens when you exceed it?**
The maximum tokens of prompt + output the model can attend to. Exceed it and you get an error
or silent truncation depending on the API — **silent truncation is the dangerous one**, because
grounding disappears with no error.

**Q: temperature vs top-p vs top-k?**
All shape the sampling distribution. **Temperature** flattens or sharpens it; **top-k** keeps
the k most likely tokens; **top-p** (nucleus) keeps the smallest set whose cumulative
probability exceeds p. Use temperature 0 for extraction and classification; raise it only for
creative output. Don't tune temperature and top-p together — pick one.

**Q: Why isn't temperature 0 fully deterministic?**
Floating-point non-associativity in batched GPU kernels, plus MoE routing and provider-side
batching. Temperature 0 means *greedy*, not *reproducible*. This is exactly why an LLM-judged
eval can't be a release gate.

**Q: What's a system prompt vs a user prompt?**
Convention, not enforcement. Models are *trained* to weight system instructions more heavily,
but it's a prior, not a security boundary — which is why prompt injection works and why
guardrails must live outside the model.

**Q: What are logprobs useful for?**
A confidence proxy. Low token probability on a critical span is a signal to escalate to a
bigger model or a human. It's the cheapest confidence signal you get, and most people ignore it.

**Q: Encoder vs decoder vs encoder-decoder?**
Encoder-only (BERT) for understanding/embeddings; decoder-only (GPT-family) for generation;
encoder-decoder (T5) for seq2seq like translation. Embedding models are typically encoder-only,
which is why they aren't generative.

**Q: What is quantisation and what does it cost you?**
Storing weights at lower precision (fp16 -> int8/int4) to cut memory and increase throughput.
Cost is a small quality drop, usually acceptable at int8 and noticeable at int4 for reasoning
tasks. It's how a 70B model fits on one GPU.

**Q: What is a mixture-of-experts model?**
Only a subset of parameters activate per token, so you get large-model capacity at
smaller-model inference cost. Practical consequence: **latency is less predictable**, because
routing varies per token.

---

## 2 - Embeddings and vector search

**Q: What is an embedding?**
A fixed-length vector where geometric closeness approximates semantic similarity.

**Q: Cosine or dot product?**
Identical when vectors are unit-normalised (most models normalise). When they aren't, dot
product rewards magnitude, which usually means "longer document" rather than "more relevant".
Default to cosine.

**Q: Why is vector search "approximate"?**
Exact search is O(n) over every vector. ANN indexes (HNSW, IVF) trade a small recall loss for
sub-linear search by navigating a graph or searching only nearby clusters.

**Q: Explain HNSW.**
A layered proximity graph. Sparse upper layers give long-range hops for coarse navigation;
dense lower layers give fine search. A query enters the top, greedily moves toward closer
neighbours, descends, repeats. `ef_search` is the exploration budget — the recall/latency dial.

**Q: HNSW vs IVF vs flat?**
**Flat** = exact, no index, fine to ~100k. **HNSW** = best recall/latency, high memory, slow
build. **IVF** = cluster-then-search, lower memory, needs training and good `nprobe` tuning.
HNSW is the default unless memory is constrained.

**Q: You change the embedding model. What now?**
Re-embed the entire corpus and rebuild the index. Vectors from different models are not
comparable — not degraded, **meaningless**. It's a migration project with dual indexes and
shadow reads, not a config change.

**Q: What are asymmetric embedding models?**
Models that expect different prefixes for queries vs documents (e.g. "query: " / "passage: ").
Getting the prefix wrong silently degrades recall with **no error** — a classic invisible bug.

**Q: How do you evaluate retrieval?**
`recall@k` on a labelled set: for each question, is the chunk that actually contains the answer
in the top k? Also MRR and nDCG when ordering matters. Without this number you cannot tell a
retrieval problem from a generation problem.

---

## 3 - RAG

**Q: Why RAG instead of fine-tuning?**
Freshness (re-index, don't retrain), **attribution** (you can cite the source), and cost.
Fine-tune for *behaviour and format*; retrieve for *facts*.

**Q: When is fine-tuning actually the right answer?**
When you need a consistent output format or style, a domain vocabulary the base model
mangles, or lower latency/cost by making a small model competent at one narrow task.
Not for knowledge.

**Q: How do you choose chunk size?**
Small enough to be selective, large enough to contain a complete answer, with overlap so a
fact spanning a boundary survives. Prefer **structure-aware** splitting (sections, headings)
over fixed-size — the document already has semantic boundaries.

**Q: What is hybrid search and when do you need it?**
BM25 keyword + vector, fused (often reciprocal-rank fusion). Needed when queries contain exact
tokens embeddings blur — identifiers, product codes, form numbers, error codes.

**Q: What does a reranker do that retrieval doesn't?**
A cross-encoder puts query and document through the model **together**, so attention relates
their words. Retrieval uses a bi-encoder, which embeds them separately and never sees them
jointly. Hence: bi-encoder for recall over millions, cross-encoder for precision over the top ~20.

**Q: The model answers from general knowledge instead of the retrieved context. Fix it?**
A relevance floor on the retrieval score, an explicit instruction to answer only from context
and refuse otherwise, and a **groundedness check** on the output. If retrieval returns nothing
useful, refusing is the correct behaviour.

**Q: How do you handle multi-turn questions like "what about for contractors?"**
Query reformulation — rewrite the follow-up into a standalone question using conversation
history before embedding it. Embedding the raw follow-up retrieves nothing useful.

**Q: What's the biggest cause of bad RAG quality in practice?**
Chunking, then missing hybrid search, then no reranking. Almost never the model.

**Q: How do you cite sources reliably?**
Return chunk ids with the retrieved context, require the model to cite them, then **verify
post-hoc** that every cited id was actually retrieved. Unverified citations are just more
generated text.

---

## 4 - Agents and tool use

**Q: What makes a system "agentic"?**
The model chooses the control flow — which tool to call, whether to loop, when it's done —
rather than following a fixed pipeline. Planning, tool use, memory and iteration.

**Q: When should you NOT use an agent?**
When the steps are known in advance. A fixed pipeline is cheaper, faster, testable and
debuggable. Agents buy flexibility and cost you determinism — only pay that when the
flexibility is required.

**Q: How does function calling work?**
You pass tool schemas; the model emits a structured call; **your code** validates and executes
it and returns the result. The model chooses, your code acts — never execute an unvalidated
model-chosen action.

**Q: How do you stop an agent looping forever?**
Max-step budget, per-run cost cap with a breaker, repeat-state detection, per-step and per-run
timeouts, and a critic node with authority to terminate. **All in code — a prompt instruction
is advisory.**

**Q: ReAct vs plan-and-execute?**
ReAct interleaves reasoning and acting step by step — adaptive, more calls. Plan-and-execute
plans upfront then runs — cheaper, more predictable, worse at recovering when the plan is wrong.

**Q: How do you evaluate an agent?**
**Trajectory** evaluation, not just the final answer: did it call the right tools in a sensible
order, how many steps, what did it cost? A right answer via a wrong path is a latent bug.

**Q: Multi-agent systems — what's the failure mode nobody mentions?**
Independent agents over a shared corpus each retrieve *a* defensible answer, and nothing
enforces they answered about the same subject — so the combined output contradicts itself.
Fan-out needs a pinned-facts contract or a consistency gate.

---

## 5 - Prompt engineering

**Q: What actually works, in order?**
Clear instructions and output format; few-shot examples (the single biggest lever for format
adherence); chain-of-thought for reasoning tasks; and putting the most important instruction
**last** for many models, because of recency effects.

**Q: What is the "lost in the middle" problem?**
Models attend most reliably to the start and end of long contexts. Put critical instructions
and the most relevant retrieved chunks at the edges, not buried in the middle.

**Q: How do you get reliable JSON?**
Provider-side constrained decoding or JSON mode where available; a schema in the prompt as a
fallback; and **validate on receipt regardless**, with a repair-and-retry path. Never trust
the model to have honoured its own contract.

**Q: Zero-shot vs few-shot vs fine-tuning — how do you choose?**
Cheapest first. Zero-shot if it works; few-shot when format matters or accuracy is marginal;
fine-tune only when few-shot costs too many tokens or latency, or the task is narrow and
high-volume.

**Q: Does chain-of-thought always help?**
No. It helps multi-step reasoning and hurts simple extraction, where it adds latency, cost and
opportunities to talk itself out of the right answer. Reasoning models do it internally, so
prompting for it can be counterproductive.

---

## 6 - Evaluation

**Q: How do you evaluate an LLM feature?**
Offline against a versioned golden set with deterministic metrics where possible, gated in CI;
online via canary with guardrail metrics and sampled human review. **Establish the noise floor
before believing any comparison.**

**Q: Problems with LLM-as-judge?**
Non-deterministic (so you can't separate regression from variance), positionally biased,
biased toward verbosity and toward its own family's outputs, and it costs money per run. Fine
as a supplementary signal on sampled traffic; poor as a release gate.

**Q: What is a noise floor and why does it matter?**
Run-to-run variance with everything held constant. Any measured difference smaller than it is
not a result. Establish it by re-running one configuration N times **before** comparing
anything.

**Q: Precision or recall — how do you decide?**
By the cost asymmetry of the two error types. A privacy filter optimises **recall** (a false
negative is an unrecoverable leak). A content blocker optimises **precision** (over-blocking
makes the product useless). Say which failure is worse and the metric follows.

**Q: What's an ablation and why does it matter?**
Remove one component, remeasure, attribute the delta. It's the only honest way to claim a
component earned its place — otherwise you're shipping complexity on faith.

**Q: Your offline metrics improved but users complain. What happened?**
Golden-set rot — it no longer represents production traffic. Or you optimised a proxy that
doesn't correlate with user value. Refresh the set from sampled real queries and check whether
gate scores actually predict production signal.

---

## 7 - Production, latency and cost

**Q: How do you cut LLM cost, in order of impact?**
**Semantic caching** (removes the call), model cascading (cheap first, escalate), retrieval
precision (fewer prompt tokens), batch APIs for staleness-tolerant work, prompt compression,
then fine-tuning a small model for a narrow high-volume task.

**Q: What is a semantic cache and what's its risk?**
Cache keyed on embedding similarity rather than exact string, so paraphrases hit. Risks: a
loose threshold serves a *wrong* answer to a *different* question, and an un-namespaced cache
becomes a **cross-tenant data leak**. Version the key by corpus version too.

**Q: Where does latency actually go in a RAG call?**
Embedding (~20-50ms), ANN search (~10-100ms), then **time-to-first-token dominates**
(~200ms-2s). Which is why streaming matters more than micro-optimising retrieval.

**Q: How do you improve perceived latency?**
Stream. Time-to-first-token is what users feel, not total time. And for voice, stream partial
tokens **into TTS** rather than waiting for a complete response.

**Q: What are hedged requests?**
Fire the same request to a second provider after the p95 mark and take whichever returns
first. Costs extra tokens, buys tail latency. The right tool when p99 is the problem and p50
is fine.

**Q: A provider starts returning 429s. What's your response, in order?**
Client-side token bucket to shape traffic before they reject it; queue to absorb bursts; retry
with backoff **and jitter**; spill to a secondary provider; circuit-break if sustained; alert,
because persistent 429 is a quota conversation, not something to retry through.

**Q: Why does jitter matter in retries?**
Without it, all failed callers retry at the same instant and you build a self-inflicted DDoS
on a dependency that's already struggling.

**Q: Where should retries live?**
Gateway for transport errors (429/5xx/timeout); worker for business-level "re-run the whole
task". **Never both** — 3 x 3 = 9 provider calls for one logical request.

**Q: How do you rate-limit correctly across many instances?**
Shared state (Redis token bucket). Per-process buckets let N instances each admit the full
rate, so you get throttled anyway. This is the most common rate-limiting bug.

**Q: What's a circuit breaker and why per-provider?**
After N failures, stop calling and fail fast for a cooldown. Per-provider because a global
breaker means one bad provider disables your healthy ones.

---

## 8 - Safety and security

**Q: What is prompt injection and can you fully prevent it?**
Untrusted text in the context hijacking instructions. **You cannot fully prevent it** — say
that plainly. You mitigate: separate instructions from data, filter input and output,
least-privilege tools, tenant-scoped retrieval, and never rely on a system prompt as a
security boundary.

**Q: Direct vs indirect injection?**
Direct: the user types it. **Indirect**: it's planted in a document your RAG pipeline will
retrieve — far more dangerous, because the attacker never talks to your system and the payload
arrives with your own trusted retrieval.

**Q: How do you stop PII reaching a third-party model?**
A redaction gateway in front of every call: deterministic detection first for latency,
checksum validation to kill false positives, reversible tokenisation when the response must
reference the entity, recall-optimised on purpose, and **fail closed** if the detector errors.

**Q: Where do guardrails belong?**
**Outside the model.** In-prompt rules are advisory and injection-bypassable. Deterministic
rules plus a classifier on the output, with a graceful deflection rather than a hard block.

**Q: How do you isolate tenants in a RAG system?**
Per-tenant namespaces or indexes, so the other tenant's chunks were **never in the searched
set** — structural, not a post-filter. Post-filtering makes a leak one bug away, and the leak
is document *content*.

---

## 9 - ML fundamentals you're still asked

**Q: Overfitting — what and how do you detect it?**
The model memorises training data and fails to generalise. Detect via a gap between train and
held-out performance. Mitigate with more data, regularisation, early stopping, simpler models.

**Q: Why do you need a held-out split?**
Because performance on data you tuned against is not performance on new data. **The honest
caveat for small benchmarks: no held-out split means your numbers are directional only.**

**Q: What's the difference between LoRA and full fine-tuning?**
LoRA trains small low-rank adapter matrices and freezes the base weights — far cheaper, and
adapters are swappable per task. Full fine-tuning updates everything: more capable, far more
expensive, and risks catastrophic forgetting.

**Q: What is RLHF, briefly?**
Train a reward model on human preference comparisons, then optimise the policy against it.
DPO achieves similar alignment without a separate reward model. You'll rarely do this as an
AI engineer, but you should know what it is.

---

## 10 - The depth questions that separate candidates

**Q: You have 10 seconds. Should this endpoint be `def` or `async def` in FastAPI?**
`def` unless every call inside it awaits. `def` runs in a threadpool where blocking is safe;
one blocking call inside `async def` freezes the whole event loop.

**Q: Your RAG system is "good enough" in testing and bad in production. Why?**
Real query distribution differs from your test set — real users are terser, more ambiguous,
more multi-turn, and ask things the corpus doesn't cover. Your test set was written by someone
who knew the answers.

**Q: How would you know your LLM feature had degraded, before users told you?**
Leading indicators, not error rates: **fallback rate, escalation rate, parse-failure rate,
refusal rate** (a *drop* can mean it stopped admitting ignorance) and sampled groundedness. A
quality regression is invisible to latency and error monitoring.

**Q: Everyone says "just use a bigger model". When is that wrong?**
Usually. In a controlled bake-off across a 14B-32B range and general-vs-domain models, output
quality moved far less than the retrieval and grounding scaffold did. Model choice is often
the wrong axis to spend effort on — and the way to know is to measure with a noise floor first.

**Q: What's the most under-appreciated thing about shipping LLM systems?**
That **prompts and model IDs are config, so they escape code review** — the most frequently
changed, least reviewed part of the system, and the one most likely to regress quality
invisibly.

---

## How to use this bank

- **First pass:** cover the answers, read only the questions, and speak each answer out loud.
  Mark every hesitation.
- **Second pass:** just the marked ones.
- **The bar:** every answer in under 30 seconds, without notes, without "um, I think".
- Where an answer has a **trap**, the trap is the part being tested. Learn those first.
