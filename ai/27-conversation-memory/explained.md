# Conversation memory at scale — explained

**Related:** topic 03 (the scope resolver, reused as a per-user one), topic 17 (namespaces make
deletion a drop), topic 21 (the cache is a leak if the key is wrong).

## 1. The numbers force the design

100k users × 50 turns/month × ~200 tokens = **1B tokens of history per month**. Nothing puts
that in a context window, so memory is a **retrieval problem, not a storage problem** — and the
storage half is genuinely a rounding error:

| | |
|---|---|
| Turn volume | 5M turns/month ≈ **1.9 turns/s average, ~12 peak** |
| Raw transcript, 30-day retention | ~4 GB resident. Trivial |
| Facts, at ~1 durable fact per 10 turns | 500k/month → **~60 per user per year**, ~18 GB of vectors |
| Naive prompt at turn 500 | **100k tokens, every single turn** |

The binding constraint is not the monthly bill — it is **the per-turn prompt at the tail of the
distribution**. A 500-turn thread resent whole is past most models' usable window, several
seconds of prefill before the first token, and ~50× the cost of the same turn on day one: your
most engaged users get your worst and most expensive product. So the design target, in one
defensible sentence — **memory cost per turn must be O(1) in history length.**

## 2. The layers, each named by the failure it prevents

### Turn log, append-only, partitioned by user
**Prevents:** having nothing to regenerate from, and making erasure impossible.

The only source of truth. Everything else — summaries, facts, embeddings — is derived and
disposable. Get that invariant wrong once and nothing downstream can be repaired later.

### Verbatim window, last 8 turns
**Prevents:** summarisation destroying the thread of the current exchange.

Summaries lose pronoun antecedents, "the second one", and the correction made two turns ago.
Recent turns must survive **word for word**. Eight is a budget decision: 8 × 200 = 1,600 tokens.

### Rolling summary, on a token trigger
**Prevents:** context overflow, *and* paying an LLM call per message.

Summarise when the window crosses its threshold, not every turn. At a 1,600-token trigger that
is **1 turn in 8** — an 8× reduction in summariser calls for identical output. Cap the summary
at 300 tokens or it becomes the thing that grows.

### Fact extraction into slots, not prose
**Prevents:** memory you cannot query, verify, correct, or delete.

A fact is `(user_id, predicate, value, confidence, source_turn_ids, valid_from)`. Prose is none
of those things. You own the grounding layer on the clinical-report generator and the rule
transfers exactly: **a fact without a source turn is a hallucination with a database row.**

### Supersession on write, keyed by slot
**Prevents:** contradiction — both the old belief and the new one being retrieved.

`(user, diet)` is a slot, not an append-only stream. A new value supersedes; the old row keeps a
`superseded_at` rather than being deleted, so audit and "you used to say" still work. Without
it, top-k returns "is vegetarian" *and* "eats chicken again" and the model coin-flips.

### Retrieval scored by relevance × recency decay
**Prevents:** stuffing everything in, and a two-month-old preference beating today's correction.

`score = cosine × 2^(-age_days / half_life)`, with the half-life set **per fact class**:

| Class | Half-life | Why |
|---|---|---|
| Identity (name, employer, language) | none | it does not decay; it gets superseded |
| Preference (tone, length, format) | ~30 days | people change their minds quietly |
| State (mid-onboarding, trip next week) | ~14 days | mostly wrong within a fortnight |

**Supersession and decay fix different failures.** Supersession resolves conflict *within* a
slot; decay resolves staleness *across* slots. A real extractor emits near-duplicate slots
constantly, so you need both.

### Per-user namespace, resolved fail-closed
**Prevents:** the worst possible leak — someone else's memory in your prompt.

Same primitive as the fail-closed tenant scoping on the voice/persona product: no resolved id
means no memory, never "all memory". And note the counting — **60 vectors per user.** An HNSW
index over 6M vectors when every query touches 60 of them is engineering for the wrong number;
a filtered scan inside the namespace is faster and exact.

### Provenance links, and summaries that regenerate
**Prevents:** an erasure request you cannot honour.

Every summary carries `derived_from: [turn_ids]`. Deletion becomes: drop the turns → find
summaries citing them → regenerate from the survivors → drop facts whose provenance intersects
→ purge vectors, prompt cache and traces. Without provenance the fact is baked into a blob you
can neither edit surgically nor prove you edited.

### A token budget with fixed per-tier allocations
**Prevents:** memory silently crowding out retrieved documents.

Memory competes with RAG context for the same prompt, so arbitrate explicitly: 1,600 verbatim +
300 summary + 150 facts = **~2,050 tokens, flat, forever**. If that number drifts with turn
index, something has reintroduced resend.

### Writes after the stream closes
**Prevents:** extraction latency landing on the user's turn.

Extraction and summarisation are 1–2s LLM calls, and a Vapi custom-LLM turn has under a second
end to end. So the write path is a queued job running *after* the response has streamed — a
dedicated Celery queue in the Django-shaped version of this. Summarisation is
staleness-tolerant, which makes it a fair candidate for a batch endpoint or a smaller model.

---

## 3. What breaks first, in order

1. **Cost and latency per turn growing with history.** First because it is the *default
   behaviour* of every naive implementation and it starts on day one. Resend is O(N²) in turns,
   tiered memory is O(N): 2.3× at turn 50 — which is why nobody notices — 13× at turn 300, 43×
   at turn 1000.
2. **Contradiction.** Weeks in, once real users have changed their minds. A correctness bug,
   not a cost bug, so no dashboard shows it — only complaints do.
3. **Summarisation drift.** Summarising the summary compounds loss, specifics first and
   silently. Regenerate from source turns periodically rather than always folding forward.
4. **Extractor noise inflating the fact store.** Sixty facts per user is fine, six hundred is
   noise. Precision@k collapses long before storage does.
5. **Erasure.** Never breaks until someone asks, then breaks catastrophically and in writing.
6. **Write-path quota contending with user turns.** Summarisation hits the same provider quota
   as live traffic; during a spike they compete, and the memory writes must lose.

A cross-user leak is out of band — rare, and total. Test it as a regression suite, not a
dashboard.

---

## 4. The follow-ups, answered

**1 · "Vegetarian in January, chicken in March. What does April retrieve?"**
An append-only fact log returns both and the model coin-flips. Slots return only the live value
on `(user, diet)`, because March superseded January on write. The January row survives with
`superseded_at`, so "didn't you say you were vegetarian?" still works — a feature, not residue.

**2 · "Walk me through an erasure request."**
Turn rows; summaries **regenerated** from the survivors; facts whose provenance intersects the
deleted turns, plus their embeddings; cache entries keyed to that user; trace and log payloads;
backups within the stated window. Embeddings and summaries are derived personal data and count.
The proof is a counter — **orphaned summaries**, meaning summaries citing a deleted turn that
have not been regenerated. It should sit at zero.

**3 · "30× at turn 300, and the tests pass."**
Someone is resending. No test catches it because at turn 10 tiered memory is genuinely *worse*
— 2,050 tokens against 1,800 — and the per-turn crossover is around turn 12, the cumulative one
around turn 19. Every fixture you would naturally write sits below both. The guard is a metric,
not a test: **memory tokens per turn plotted against turn index, alerting on the slope.**

**4 · "What's worth remembering, and how do you know you're wrong?"**
Remember what would change a future answer: identity, stable preferences, commitments,
corrections. Never chit-chat, never your own answers. Two numbers say the decision is wrong —
**facts per user per week** rising (the extractor hoards) and **precision@k on a labelled
sample** falling. Establish that sample's noise floor first or you'll read variance as
regression.

**5 · "The summariser fails, or degrades silently."**
Failure is easy: keep the previous summary, widen the verbatim window for that turn, retry on
the queue. Silent degradation is the real risk, because a blander summary is not an error. Catch
it with a deterministic **entity-retention check** — a summary of eight turns naming none of the
entities in them is a defect you can fail on before a user sees it.

**6 · "How do you evaluate memory?"**
Retrieval: **precision@k** on labelled (query, should-retrieve) pairs — recall matters less,
since a missed fact degrades gracefully and a wrong one does not. End to end: held-out
multi-turn conversations with questions answerable only from memory, scored for correctness
*and* for contradicting a live fact. Plus **staleness** — the share of retrieved facts older
than one half-life.

**7 · "Transcripts expire at 30 days but facts persist. What broke?"**
The regenerable-summary invariant, and the grounding claim with it — a fact whose source turn is
purged is unverifiable. Make **retention provenance-aware**: a turn cited by a live fact is
pinned past the general window. At ~60 facts per user per year that pins almost nothing, and it
is the difference between "our memory is grounded" being true and being marketing.

**8 · "The user asks what you know about them."**
Read it out of the fact store, not the model. The slots are already structured: render them
grouped by class with source turn and date, and a delete control per row. If answering this
needs an LLM call, you built prose memory — the thing this design exists to avoid.

**9 · "Where does the write happen?"**
After the stream closes, on a queue, at lower priority than live traffic: a memory write landing
30 seconds late costs nothing, a turn landing 300 ms late is the product. The one exception is
the turn-log append, which is synchronous and **fails the turn if it fails** — a response you
cannot reconstruct or delete is worse than an error.

---

## One-line summary

> "Recent turns verbatim, a rolling summary triggered on tokens rather than every turn, and
> durable facts in supersedable slots retrieved by cosine times a recency decay — about 2,000
> tokens of memory per turn regardless of whether the thread is 10 turns or 1,000. The turn log
> is the only source of truth; summaries and facts carry provenance so erasure regenerates them
> instead of failing."

## The trap answer to avoid

"I'd put the conversation in the prompt." Fine at 10 turns, broken at 500, and the cost grows
quadratically because history is resent every turn.

The subtler trap sounds sophisticated: **"I'd embed every turn and vector-search the
transcript."** Turns are terrible retrieval units — pronoun-laden, meaningless standalone. It
retrieves the question rather than the answer, resolves no contradiction (January and March
embed almost identically, so both come back), and makes erasure a delete-by-query over a hundred
million vectors. Slots exist because a transcript index gets all four wrong.
