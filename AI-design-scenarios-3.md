# Design scenario bank III — twelve more

Continues [`AI-design-scenarios.md`](AI-design-scenarios.md) (1-10) and
[`AI-design-scenarios-2.md`](AI-design-scenarios-2.md) (11-20). Same shape.

Diagrams: [`AI-architecture-diagrams.md`](AI-architecture-diagrams.md).

---

## 21 - Text-to-SQL: "chat with your database"

*One of the most-asked LLM design questions. Know it cold.*

**The prompt:** *"Let business users ask questions of the data warehouse in English. It must
not return wrong numbers."*

**Clarify:** how many tables, and are they documented? read-only (must be)? are there
canonical metric definitions, or does every team compute revenue differently? is a wrong
answer worse than no answer (yes — this is a finance-adjacent product)?

**Numbers:** 300 tables x 40 columns = **12,000 columns**. That doesn't fit in a prompt, so
schema retrieval is mandatory — the design is a **RAG problem over schema**, not a prompting
problem.

**Layers:**
- **Schema retrieval** — embed table/column descriptions, retrieve only relevant tables — *prevents:* context overflow and the model inventing columns
- **A curated semantic layer / metric store** — *prevents:* the model inventing its own definition of "revenue". This is the single highest-value component and most candidates miss it
- **Few-shot exemplars of verified query patterns** — *prevents:* structurally wrong joins
- **SQL validation before execution**: parse it, assert read-only, assert tables/columns exist, reject `DELETE`/`UPDATE`/DDL — *prevents:* both hallucinated schema and catastrophic writes
- **Cost guard**: `EXPLAIN` first, reject or warn above a row/byte threshold, `LIMIT` injected — *prevents:* a £500 full-table scan from one question
- **Row-level security via the *user's* credentials**, not a service account — *prevents:* the LLM becoming a privilege-escalation path
- **Show the SQL and the row count** alongside the answer — *prevents:* unverifiable numbers
- **Result caching keyed on (question embedding, schema version)** — *prevents:* paying twice

**Breaks first:** **silently wrong joins.** The query runs, returns a plausible number, and
nobody can tell. That's worse than an error — and it's why the semantic layer and showing the
SQL matter more than model quality.
**Trap:** treating it as prompt engineering. It's schema retrieval + a semantic layer +
validation. And **never** let the model's SQL run under a privileged account.

---

## 22 - Document extraction with an accuracy SLA

**The prompt:** *"Extract 20 fields from 50k invoices a month, contractually 99% field-level
accuracy."*

**Clarify:** is 99% per field or per document (huge difference — 20 fields at 99% each is only
82% per document)? is human review budgeted? are the documents templated or arbitrary? what's
the cost of an error downstream?

**Numbers:** **20 fields x 99% = 0.99^20 = 82% document-perfect.** State this immediately — it
reframes the whole problem and it's the insight being tested. To hit 99% *per document* you'd
need 99.95% per field, which no model does unaided. **Therefore human-in-the-loop is not
optional, it's the architecture.**

**Layers:**
- **Confidence-routed human review** — auto-accept high confidence, queue the rest — *prevents:* paying for 100% review or shipping 18% bad documents
- **Per-field confidence, not per-document** — *prevents:* re-reviewing 19 correct fields because one was uncertain
- **Deterministic validators**: checksums, date sanity, totals reconciling to line items — *prevents:* spending model confidence on things arithmetic can prove
- **Template detection + cached layout** for recurring senders — *prevents:* paying full extraction cost for the 80% that are repeats
- **Cross-field consistency** (subtotal + tax = total) — *prevents:* individually-plausible, jointly-impossible extractions
- **Reviewer corrections flow back into the eval set** — *prevents:* a static benchmark
- **Per-field accuracy dashboard** — *prevents:* an aggregate hiding one broken field

**Breaks first:** the **SLA definition itself**, then reviewer throughput. Get the definition
pinned before designing anything.
**Trap:** promising 99% without noticing the per-field/per-document distinction. Also: quoting
a single "accuracy" number when different fields have wildly different difficulty.

---

## 23 - LLM-powered search and ranking

**The prompt:** *"Improve search on a 10M-document site using LLMs. Latency budget: 200ms."*

**Clarify:** head or tail queries dominating? is click data available (it's your best training
signal)? is a 200ms budget end-to-end or server-side?

**Numbers:** 200ms total rules out an LLM in the synchronous path — a generation call is
200ms-2s on its own. **So the LLM must move offline or to a reranking stage only.** Recognising
that immediately is the answer.

**Layers:**
- **Retrieval: hybrid BM25 + vector** — *prevents:* missing exact terms or missing paraphrases
- **Cross-encoder rerank over top ~50-100** (small, distilled, ~10-30ms) — *prevents:* first-stage ordering being the final ordering
- **LLM used OFFLINE**: query-expansion dictionaries, document enrichment (summaries, keywords, synthetic questions per doc), and generating training pairs — *prevents:* blowing the latency budget
- **Learning-to-rank on click signal** — *prevents:* relying on semantic similarity as a proxy for usefulness
- **Cached head queries** — *prevents:* recomputing the top 1% that is most of traffic
- **Freshness and business boosts as separate ranking features** — *prevents:* baking business rules into embeddings where you can't tune them

**Breaks first:** the **latency budget**, if you try to put generation inline. Then relevance
on tail queries, where click data is sparse.
**Trap:** "I'd embed everything and use vector search." That's a *worse* search engine than
BM25 for many query types. Search is **hybrid retrieval + learned ranking**; the LLM's best
role is offline enrichment.

---

## 24 - Repo-aware code assistant

**The prompt:** *"Build an assistant that answers questions and suggests changes across a
2-million-line monorepo."*

**Clarify:** answering questions, or writing code? is repo access per-user-permission scoped
(it must be)? can code leave the network?

**Numbers:** 2M lines is roughly 25M tokens. No context window holds it, so retrieval is
mandatory — and code retrieval behaves **differently from prose**.

**Layers:**
- **AST-aware chunking**, not fixed-size — chunk at function/class boundaries — *prevents:* splitting a function mid-body, which makes the chunk useless
- **A symbol/dependency graph** (definitions, references, imports) — *prevents:* retrieving a call site without its definition
- **Hybrid retrieval**: identifiers are exact tokens, so BM25 is essential alongside vectors
- **Include the file path and language in the chunk text** — *prevents:* the model losing where code lives
- **Incremental re-index on commit**, keyed by content hash — *prevents:* a full 25M-token re-index per push
- **Permission-scoped retrieval** — *prevents:* a user seeing code from a repo they can't read. This is the security answer
- **Tests as the verification loop** — for suggested changes, *run them* — *prevents:* plausible code that doesn't compile

**Breaks first:** **retrieval relevance**, because code has enormous near-duplication —
generated files, vendored deps, similar boilerplate all crowd the results. Then index
freshness on a busy monorepo.
**Trap:** treating code like prose. Fixed-size chunking on code is the classic mistake, and a
dependency graph is what makes retrieval work.

---

## 25 - Multimodal document pipeline

**The prompt:** *"Your documents contain scanned pages, tables and charts. Make them
answerable."*

**Clarify:** are numbers inside tables and charts required in answers (usually yes — that's
the hard part)? scanned or native PDFs? is layout meaningful?

**Numbers:** a chart's data isn't in the text layer at all. If 30% of the salient numbers live
in tables and figures, a text-only pipeline has a **hard 70% ceiling on numeric recall** no
matter how good the model is. Say that — it justifies the whole design.

**Layers:**
- **Layout analysis first** — segment into text / table / figure regions — *prevents:* tables being flattened into unreadable text soup
- **Table extraction as structured data**, not prose — *prevents:* losing the row/column relationship that makes a number meaningful
- **OCR fallback** for scanned pages, with a confidence threshold — *prevents:* silently indexing garbage
- **Figures: crop the region and store the image**; caption it with a vision model at ingest — *prevents:* paying vision costs per query
- **Keep provenance to page and region** — *prevents:* uncheckable citations. *(Your CSR pipeline does chunk provenance to page and table — cite it)*
- **Route by modality at query time** — a numeric question should search table chunks preferentially
- **Numeric grounding check** against the extracted tables — *prevents:* a fabricated figure

**Breaks first:** **table extraction quality.** It's the hardest part of the pipeline and
determines the ceiling on numeric answers. Then OCR on poor scans.
**Trap:** "I'd send the page image to a vision model." Works, doesn't scale (cost and latency
per query), and loses structure. Extract structure **once at ingest**, retrieve structure at
query time.

---

## 26 - Meeting notes: long audio to actions

**The prompt:** *"Turn 60-minute meetings into a summary, decisions and action items. 500
meetings a day."*

**Clarify:** real-time or post-hoc? speaker attribution required (it changes everything)? are
action items assigned to people (then you need entity resolution against a directory)?

**Numbers:** 60 min of speech = ~9,000 words = ~12k tokens. That fits a modern context window,
**so chunking is not forced** — a useful thing to notice out loud, because it means you can
choose whole-transcript summarisation and get better global coherence.

**Layers:**
- **Diarisation + speaker attribution** — *prevents:* "someone said they'd do it", which makes action items useless
- **Transcript as the durable artifact**, summaries as derived — *prevents:* being unable to re-summarise when the prompt improves
- **Map-reduce only if the transcript exceeds context**; otherwise single-pass for coherence
- **Structured output**: decisions, action items with owner and due date, open questions — *prevents:* an unactionable wall of prose
- **Entity resolution of names against the directory** — *prevents:* an action item assigned to "Dave" when there are four
- **Quote-and-timestamp every decision** — *prevents:* disputes, and gives a verification path
- **Async queue** — nobody waits; 500/day is trivially batchable

**Breaks first:** **diarisation quality** on overlapping speech and poor audio. Everything
downstream inherits it. Then hallucinated action items — the model's strong prior that meetings
*have* action items makes it invent them for meetings that don't.
**Trap:** focusing on summarisation quality. The value is in **attributed, verifiable action
items**, and the risk is inventing them.

---

## 27 - Support copilot with escalation

**The prompt:** *"Deflect support tickets with an AI agent. Don't make customers angrier."*

**Clarify:** what's the current deflection rate and CSAT baseline? can the agent take actions
(refunds, cancellations) or only answer? is there an SLA on human handoff?

**Numbers:** the trade is explicit and worth stating: if you deflect 40% but 10% of those are
*wrong*, you've created 4% badly-handled tickets that arrive at a human **already annoyed** —
which typically costs more than the 40% saved. **Deflection rate alone is the wrong metric.**

**Layers:**
- **Confidence-gated deflection** — answer only when grounded and confident; escalate otherwise — *prevents:* the 4% problem
- **Always-available "talk to a human"** — *prevents:* trapping people, the single biggest CSAT killer
- **Full context handoff** (transcript, what was tried, retrieved articles) — *prevents:* the customer repeating themselves, which is what actually makes them angry
- **Actions behind confirmation + idempotency** — *prevents:* a double refund
- **Tiered scope**: answer freely, act narrowly, never act irreversibly
- **Metrics that pair**: deflection rate **with** post-deflection reopen rate and CSAT — *prevents:* optimising deflection into a worse product
- **Feedback loop**: escalated tickets become eval cases

**Breaks first:** **CSAT, not accuracy.** A wrong-but-confident answer plus a hard-to-escape
loop is the failure mode, and it doesn't show up in accuracy metrics.
**Trap:** optimising deflection rate. Pair it with reopen rate and CSAT, or you'll ship
something that looks successful on the dashboard and is hated.

---

## 28 - Fine-tuning pipeline, end to end

**The prompt:** *"You've decided to fine-tune a small model for one high-volume task. Design
the pipeline."*

**Clarify:** why fine-tune rather than prompt (format? cost? latency?) — if they can't answer,
that's the finding. How much labelled data? is the base model licence commercially usable?

**Numbers:** LoRA on a 7B with ~5-10k examples is hours on one GPU, not weeks. The **data
curation** is the expensive part — usually 80% of the effort. Say that.

**Layers:**
- **Justify it first**: fine-tune for *format, style, latency, cost* — **never for knowledge** (that's RAG)
- **Data curation with dedup and decontamination** — *prevents:* eval-set leakage inflating your numbers, the most common self-deception in fine-tuning
- **Versioned dataset**, treated as code — *prevents:* an unreproducible model
- **Held-out split, fixed before any training** — *prevents:* tuning against your test set
- **LoRA over full fine-tuning** — cheaper, swappable adapters per task, no catastrophic forgetting of the base
- **Compare against a strong prompted baseline** — *prevents:* shipping a fine-tune that's worse than a good prompt. This comparison is the gate
- **Regression suite on general capability** — *prevents:* a model great at your task and broken at everything else
- **Serving: vLLM with the adapter**, same OpenAI-compatible interface — *prevents:* call-site changes
- **Rollback = pointer flip to the previous adapter**

**Breaks first:** **data quality**, then eval contamination. Not training.
**Trap:** fine-tuning to add knowledge. It doesn't work reliably, it can't be updated, and it
has no attribution. And never ship a fine-tune without beating a prompted baseline on the same
held-out set.

---

## 29 - Internal AI platform for many product teams

*Platform-engineering shaped. Common for senior roles.*

**The prompt:** *"Ten product teams all want to ship LLM features. Design the platform so they
don't each rebuild the same thing badly."*

**Clarify:** are teams allowed to call providers directly today (probably, and that's the
problem)? who owns cost? is there a central AI team or is this a guild?

**Numbers:** ten teams x (gateway + cache + eval + secrets + observability) = **ten
implementations, nine of them wrong**. The platform's value is the difference.

**Layers:**
- **A gateway every team must use** — *prevents:* ten key-management schemes and unattributable cost. Mandatory or it's pointless
- **Golden-path SDK** with sane defaults: timeouts, retries, streaming, tracing built in — *prevents:* every team relearning backoff and jitter
- **Central secrets and per-team keys** — *prevents:* a leaked key with no blast-radius bound
- **Per-team cost attribution and budgets** — *prevents:* nobody owning the invoice
- **Shared eval harness as a service** — *prevents:* nine teams with no gate
- **A model registry with approved models** — *prevents:* a team shipping on a deprecated or unvetted model
- **Shared PII/guardrail middleware** — *prevents:* each team reimplementing compliance differently
- **Paved road, not a wall**: an escape hatch with a review, or teams will route around you

**Breaks first:** **adoption.** A platform teams bypass is worse than none, because you now
have a false sense of central control. Make the paved road genuinely faster than DIY.
**Trap:** designing for technical purity over adoption. The correct first question is *"why
would a team choose this over calling the API directly?"* — and the answer must be "because
it's easier".

---

## 30 - RAG over structured *and* unstructured data

**The prompt:** *"Users ask questions needing both the policy documents and the database. One
answer."*

**Clarify:** are questions typically one or the other, or genuinely both? is freshness critical
on the structured side (yes — a database answer must be current)?

**Numbers:** the routing accuracy dominates end-to-end quality. If 20% of questions route to
the wrong source, no amount of retrieval quality saves you.

**Layers:**
- **Query router / planner** — classify: documents, database, or both — *prevents:* semantic search over a table (useless) or SQL over prose (impossible)
- **Two retrieval paths**: vector RAG for documents, **text-to-SQL for structured** (see #21, with all its guards)
- **A synthesis step** that composes both results with **separate attribution per source** — *prevents:* a blended answer nobody can verify
- **Never embed the database**: query it live — *prevents:* stale numbers, which is the worst failure here
- **Disagreement handling**: if the document says one thing and the data another, **surface both** — *prevents:* the model silently picking one
- **Per-source confidence** in the answer

**Breaks first:** **routing**, then answer synthesis when the two sources disagree.
**Trap:** embedding database rows so everything is "one RAG pipeline". Numbers go stale
instantly and aggregation is impossible — you cannot `SUM` a vector search.

---

## 31 - Incident: cost spiked 5x overnight

**The prompt:** *"Yesterday you spent five times normal on LLM calls. Nothing was deployed.
Find it and design what should have caught it."*

**Triage, as a bisection:**
1. **Is it volume or cost-per-call?** Divide spend by call count first — this splits the whole problem in two
2. **Volume up** -> which tenant/feature? a retry storm? an **agent loop**? a scraper?
3. **Cost-per-call up** -> prompt got longer (more chunks retrieved? a prompt edit?), output got longer, or the **router shifted to an expensive model** because a cheap provider was circuit-broken
4. **Cache hit rate** -> did it collapse? A re-index invalidating a cache, or a key-versioning change, silently multiplies cost
5. **Check a fallback shift** — a degraded primary means traffic on a pricier secondary. The bill rises with *no* code change
6. **Then the boring ones**: a provider price change, a config flip, a backfill someone kicked off

**Most likely causes, in order:** cache hit-rate collapse · an agent without a step budget ·
a retry storm · a fallback shift to an expensive provider · a prompt that got longer.

**What should have caught it:**
- **Alert on rate of change**, not absolute spend — *prevents:* monthly-invoice detection
- **Per-tenant, per-feature, per-model cost dashboards** — *prevents:* an unattributable spike
- **Cost per call as a tracked metric**, separate from volume — *prevents:* conflating the two causes
- **Cache hit rate as a first-class alert**
- **Per-run cost caps on agents** with a breaker
- **Budget breaker that degrades** rather than a monthly surprise

**Breaks first (as a process):** detection latency — hourly problem, monthly invoice.
**Trap:** assuming volume. Cost-per-call regressions are just as common and completely
invisible if you only track spend and requests separately.

---

## 32 - Incident: p99 latency blew up after a deploy

**The prompt:** *"p99 went from 3s to 25s after a release. p50 is unchanged. Debug it."*

**The key observation, say it first:** p50 unchanged means it is **not** a throughput or
capacity problem — adding instances will not help. Something affects a *subset* of requests.

**Triage:**
1. **Is it one provider, one model, one tenant, one endpoint?** Slice before theorising
2. **Timeouts** — is something now waiting longer before failing? A raised or removed timeout turns a fast failure into a 25s hang
3. **Retries** — did retry count or backoff change? 3 retries x 8s = your 25s
4. **A new synchronous call** in the request path (an added validation, a logging write, a metrics flush)
5. **Retrieval** — did chunk count or `numCandidates`/`ef_search` go up? More recall, more latency
6. **Prompt length** — longer prompts mean longer time-to-first-token, and it hits the tail hardest
7. **Cold starts / connection-pool exhaustion** — a pool sized for the old concurrency
8. **Event-loop blocking** — did someone put a blocking call inside an `async def`? *That freezes concurrent requests and shows up exactly as a tail problem*

**Most likely:** a retry/timeout config change, or a blocking call added to an async path.

**What should have caught it:**
- **p99 in the deploy gate**, not just p50 — *prevents:* shipping a tail regression
- **Per-provider, per-model latency**, so a slice is visible
- **Error taxonomy** — a timeout spike is a different signal from a 5xx spike
- **Canary with tail-latency guardrails**
- **A load test that measures the tail**, since averages hide it entirely

**Breaks first (as a process):** you were measuring the average. p50 dashboards make tail
regressions invisible, and the tail is what users experience.
**Trap:** scaling out. p50 unchanged means capacity isn't the issue; you'll spend money and
fix nothing.

---

## The incident-drill method (scenarios 20, 31, 32)

These test **method under pressure**, not architecture. The pattern that scores:

1. **Ask what changed and when** — deploys, configs, provider status, data
2. **Slice before theorising** — one tenant, one model, one endpoint, one surface?
3. **Bisect the pipeline** rather than listing guesses
4. **State a mitigation before a root cause** — reduce harm now, understand later
5. **Then design the detection** you were missing
6. **Name the process failure**, not just the technical one — usually "users were our monitoring"

**Never** open with "the model got worse". Model drift is rare; **your pipeline changed** is
overwhelmingly more likely.
