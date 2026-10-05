# Multi-tenant RAG at 500 tenants — the scaled view

## 1. Numbers
| | |
|---|---|
| Tenants | 500 |
| Median corpus | 10k docs → 200k chunks |
| Largest corpus | 200k docs → 4M chunks (**20×**) |
| Total | **~100M chunks**, ~400 GB of raw vectors |
| Query load | 50k DAU × 5 = 250k/day ≈ 3 QPS, 30 peak |
| Ingest | one onboarding = 200k embeddings = **minutes of the whole cluster** |

**The conclusion those numbers force:** query is cheap and namespaced; **ingest is the
contended resource**, and skew means one sharding rule cannot serve everyone.

## 2. Topology
```
                          ┌─ per-tenant ingest queue + rate limit ─┐
upload ──► dedup (content hash) ──► chunk ──► embed (batched) ──► upsert (uuid5)
                                                                        │
                    ┌───────────────────────────────────────────────────┤
                    ▼                    ▼                    ▼
             shard 1 (tail)       shard 2 (tail)      dedicated (whales)
                    ▲                    ▲                    ▲
query ─► scope resolver (fails closed) ─► tenant→shard map ─► namespace ─► top-k
```

## 3. Sharding rules
- **tenant → shard map**, never a hash — a hash fans every query across every shard
- **whales get dedicated shards**; the long tail shares
- **rebalancing is a real operation** — a tenant that grows 10× must be movable without
  downtime. Same dual-index/shadow-read pattern as an embedding migration

## 4. Fairness — the dominant operational problem at this count
Per-tenant **token buckets** on query · per-tenant **ingest queues** with weighted fair
draining · per-tenant **concurrency caps** on expensive paths · per-tenant **budgets**.

Without these, tenant 1's bulk job is tenant 2's outage — and tenant 2 is the one who calls.

## 5. What breaks, in order
1. **Embedding throughput during bulk onboarding** — the first real wall
2. **Vector-store write throughput** on upsert
3. **Index memory** as the shard grows (quantise before sharding again)
4. **ANN recall drift** after many inserts without a rebuild — silent, no error
5. **Query tail latency** on the biggest shard
6. **An embedding-model change** — 100M re-embeddings, a project not a deploy

## 6. Per-tenant lifecycle — build these before you need them
**Onboarding** (own queue, own rate limit, resumable) · **offboarding** (drop the namespace,
purge cache, logs, traces, backups — embeddings are derived personal data) ·
**export** · **rebalance** · **per-tenant progressive migration**, smallest first so problems
surface cheaply.

Namespaces make offboarding a *drop*. A shared index makes it a delete-by-query across 100M
vectors, which is the underrated second argument for namespacing.

## 7. Cost
Cost per query ≈ prompt tokens × rate, and prompt tokens = chunk count × chunk size — both
your choice. **So retrieval precision is a cost lever, not just a quality one.** Add per-tenant
budgets and a semantic cache (tenant + corpus-version namespaced) and the cache is usually the
single largest saving.

## 8. Observability
**Per tenant**, never aggregate: query p95, ingest lag, recall@k on a rolling labelled sample,
cost, queue depth, cache hit rate. An aggregate dashboard hides the one tenant currently
having an outage.

Plus the platform-level numbers: shard memory headroom, index rebuild age, and **percentage of
queries with complete tenant attribution** — anything under 100% is a blind spot.
