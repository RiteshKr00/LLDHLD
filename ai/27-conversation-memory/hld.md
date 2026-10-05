# Conversation memory at 100k users — the scaled view

## 1. Numbers first
| | |
|---|---|
| Users × turns | 100k × 50/month = **5M turns/month** ≈ 1.9/s average, **~12/s peak** |
| History generated | 1B tokens/month; ~4 GB of transcript resident at 30-day retention |
| Facts, at ~1 per 10 turns | 500k/month → **~60 per user per year**, ~18 GB of vectors |
| Read path budget | **50 ms** to assemble memory, inside a sub-second voice turn |
| Write path | 1 summarise+extract call per 8 turns, ~1.5s each |

Little's Law on both halves: the read path holds `12 × 0.05` = **0.6 concurrent assemblies**,
the write path `1.5 × 1.5` = **~2.3 concurrent provider calls**. Neither is a capacity problem,
and saying so out loud is the point — **nothing here is throughput-bound.** What *is* unbounded
is the naive token rate: 12 turns/s with 500-turn threads resent whole is **1.2M prompt tokens
per second**. So **tokens per turn is the only scaling lever that matters**, and every other
decision is about correctness and deletability.

## 2. Topology
```
                      ┌── last 8 turns ──── turn log (partitioned by user_id) ──┐
turn ─► scope resolve ─┼── summary row ───── one row per (user, thread) ────────┼─► prompt ─► LLM ─► stream
        (fails closed) └── top-6 facts ──── fact slots + vectors, per-user ─────┘                     │
                                                                                                      │
        turn log append (SYNC, fails the turn)  ◄──── async write queue, low priority ◄────────────────┘
        window > 1,600 tok? ─► summarise + extract ─► slot upsert (supersede) ─► embed
```

## 3. The read path, and where the 50 ms goes
Three lookups: a range scan for the last 8 turns (~2 ms), one summary row by key (~1 ms), and
fact retrieval. The scan itself is nothing — it is the **query embedding at 15–20 ms that eats
most of the budget**. Two ways out: **reuse the embedding you already computed** (a RAG-backed
assistant embeds the turn anyway for document retrieval, as on the Mongo Atlas vector path in
the HR platform — doing it twice is pure waste), and **gate fact retrieval**, because many turns
("make it shorter") cannot be improved by a fact at all.

## 4. The write path is where the quota goes
Summarisation and extraction are provider calls competing with live turns for the same quota.
Three rules: **lower priority than live traffic** (a memory write 30s late costs nothing);
**one call, not two**, summarising and extracting off the same window in the same request; and
**staleness-tolerant, so batch it** — a cheap model or a batch endpoint is legitimate here in a
way it never is on the read path.

## 5. Storage: why there is no ANN index
Every query touches **~60 vectors** — one user's namespace. An HNSW index over 6M vectors to
answer a 60-row question is engineering for the wrong number: a filtered scan is faster, exact,
and has no recall drift to monitor. Revisit only if memory goes org-shared, at which point the
namespace becomes a permission-scoped set and retrieval is a different problem — Casbin-shaped,
with the policy applied *before* ranking, never after.

## 6. Fairness
The namespace is already per user, so the contended resource is the **write-path quota**. A
power user having a 2,000-turn day generates 250 summariser calls. Per-user token bucket on the
write path, one shared bucket underneath it, and a bounded queue so their backlog delays their
own memory and nobody else's turns.

## What breaks, in order
1. **Prompt tokens per turn**, if anyone reintroduces resend. Day one, quadratic, invisible in
   short tests because tiered memory *loses* below turn 12.
2. **Contradiction.** Weeks in, once users change their minds. No dashboard shows it.
3. **Summarisation drift.** Folding a summary forward N times loses specifics silently — you
   want periodic regeneration from source turns, not perpetual folding.
4. **Extractor noise.** Precision@k collapses at ~10× the intended fact rate, long before
   storage notices.
5. **The first erasure request.** Fine if provenance exists, unrecoverable if it does not.
6. **Write-path quota** contending with live turns during a spike.
7. **An embedding-model change**, which invalidates every fact vector — a dual-index backfill,
   not a deploy.

## Degradation
It differs per component, and the split is the interesting part:

| Down | Behaviour |
|---|---|
| Fact store | verbatim window + summary only. Assistant is **forgetful, not broken** |
| Summariser | keep the previous summary, widen the verbatim window one tier, queue the backfill |
| Embedding service | slot-key and lexical match over the user's ~60 facts — exact anyway at that size |
| Turn-log append | **fail the turn.** A response you cannot reconstruct or delete is worse than an error |
| Scope resolver | serve with **zero** memory, never default memory |

Everything fails open except the two whose failure is unrecoverable: deletability and isolation.
Being able to say *why those two and not the others* is the answer, not the table.

## Observability
Per user cohort, not aggregate. **Leading indicators**, in the order they move:

- **memory tokens per turn regressed against turn index** — alert on the *slope*, never the level
- **summariser calls per turn** — target 0.125; drift means the trigger is misfiring
- **facts written per user per week** — rising means the extractor has started hoarding
- **supersession rate** — a spike means a regression is churning slots
- **stale share** — retrieved facts older than one half-life
- **orphaned summaries** — summaries citing a deleted turn, not yet regenerated. Must be zero;
  non-zero for an hour means your deletion path is broken and nobody knows
- **write-queue lag p95** — memory falling behind the conversation it describes

Lagging, and therefore useless as an alarm: "it forgot me" complaints, thumbs-down rate, and the
support ticket that says the assistant contradicted itself.
