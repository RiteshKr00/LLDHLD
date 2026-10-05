# The migration at scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Chunks | 100M | the corpus |
| Embedding throughput | ~1,000/sec | batched, including API round trip |
| Pure embedding time | 28 hours | the floor, not the estimate |
| Storage during transition | 2x | for weeks, not hours |
| Realistic calendar time | 6–10 weeks | labels, shadow, progressive cutover |
| Indexes live simultaneously | 2 | not a phase — the design |

## 2. Topology

**Write path.** Every ingest writes to **both** indexes from the moment the migration starts.
If dual-write is not live before the backfill begins, the backfill is chasing a moving target
and never converges.

**Backfill.** A separate, sharded, checkpointed job reading the source of truth — not the old
index. Idempotent per chunk, resumable at a committed offset, rate-limited against the provider
quota.

**Read path.** One retrieval client. Index selection resolved centrally from the tenant's
cutover state. Never a config flag read independently in two places — that is how you get the
same query returning different answers depending on which code path served it.

**Cache.** Keyed with the embedding model version. Cutover then invalidates it automatically.

## 3. Phases

1. **Dual-write on.** Both indexes receive live writes. Nothing is served from the new one.
2. **Backfill.** 28 hours of throughput, several days of wall clock. Checkpointed.
3. **Shadow.** Real queries against both, old served, comparison logged. Run for a week.
4. **Gate.** Recall@k against independently labelled data, sliced by tenant and query type.
5. **Progressive cutover.** Tenant by tenant, starting with one you can phone.
6. **Soak.** A full business cycle.
7. **Delete**, 30 days after the last cutover, as an explicit decision.

Phase 1 before phase 2 is the ordering people get wrong.

## 4. Rollback

While both indexes exist, rollback is a **routing change** — per tenant, seconds, free. That is
the property the entire design exists to preserve, and it is why deleting the old index is a
decision rather than a cleanup task.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Backfill cost and duration | Checkpoint, shard, rate-limit; budget the API spend explicitly |
| 2 | Cache serving old-space answers | Model version in the key, before cutover not after |
| 3 | Partial-state bugs | One retrieval client; log index version on every read |
| 4 | Storage | Accept 2x; it is the cheapest line in the project |
| 5 | Forgotten consumers | Inventory everything reading vectors *before* phase 1 |

## 6. The consumers nobody lists

Search is the obvious one. Also reading those vectors: the semantic cache, deduplication jobs,
clustering and topic analytics, recommendation features, the eval harness, admin tooling, and a
notebook someone runs at month end. Each is a separate cutover with its own correctness
criterion. Inventory them in phase 0, because discovering one in phase 5 means a tenant is
half-migrated in a way nobody modelled.

## 7. Observability

Backfill progress against committed offset, per shard, with projected completion. Embedding API
spend against budget, daily. Shadow comparison recall@k, sliced by tenant and query type, never
only in aggregate. Cache hit rate **by model version** — a high hit rate on the old version
after cutover is the stale-space bug. Index version logged on every retrieval, with an alert if
one tenant hits both within a window. Storage against the 2x projection.

The one chart to watch during cutover: **recall@k per tenant, old versus new, on the same
queries.** Everything else is process; that is the outcome.
