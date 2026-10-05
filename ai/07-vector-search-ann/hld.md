# Vector search at 100M chunks

## 1. Numbers first
500 tenants × 10k docs × 20 chunks = **100M vectors**. At 1024 dimensions in float32 that is
**~400 GB of raw vectors**, before the index. HNSW adds roughly 30–60% for the graph edges.

**That single number forces the whole design**: it does not fit on one node, so sharding is
not an optimisation, it is the architecture.

## 2. Memory is the binding constraint, not CPU
HNSW wants the vectors and graph **resident in RAM** — spilling to disk destroys the latency
that made you choose ANN. So:

| Lever | Effect | Cost |
|---|---|---|
| **Quantisation** (float32 → int8) | 4× smaller | small recall loss, usually acceptable |
| **Lower dimensions** (1024 → 384) | ~2.7× smaller | measurable quality drop — test it |
| **Lower `M`** (graph edges/node) | smaller index | worse recall |
| **Shard** | linear | operational complexity |

Say quantisation first. It's the highest ratio of saving to quality loss, and most candidates
never mention it.

## 3. Sharding — by tenant, not by hash
A hash spreads every tenant across every shard, so a query fans out to all of them and you pay
the slowest. **Shard by tenant**: one query touches one shard, and the largest tenants get
dedicated shards (topic 03's skew problem).

Routing is a tenant→shard map, not a modulo.

## 4. Index build cost — the thing nobody budgets
Building HNSW is **far more expensive than querying it**. 100M vectors is hours of CPU, and it
is not incremental in the way people assume: inserts degrade graph quality over time, so you
periodically **rebuild**.

Plan for it: build offline into a new index, shadow-read, then swap. Never rebuild in place on
a serving node.

## 5. What breaks, in order
1. **Memory** — the index no longer fits; latency collapses when it spills
2. **Index build time** — a rebuild takes longer than the window you have
3. **Recall drift** — after many inserts without a rebuild, recall quietly falls. *Nothing
   errors.* Only a labelled recall@k check catches it
4. **Tail latency** on the biggest shard
5. **An embedding-model change** — see below

## 6. The embedding migration (the worst one)
Changing the model means re-embedding all 100M vectors: **~28 hours of pure embedding**, plus
index build, plus **double storage** during transition. Dual-index, shadow-read, compare
recall@k, then per-tenant progressive cutover. There is no in-place migration — the two vector
spaces are not comparable.

Cache keys must be versioned by embedding model, or the cache serves old-space answers forever.

## 7. Observability
p50/p95/p99 **per shard** (an aggregate hides one bad shard) · **recall@k on a rolling labelled
set** — the only thing that catches silent quality decay · index memory headroom · rebuild age ·
`numCandidates` actually in use versus configured.
