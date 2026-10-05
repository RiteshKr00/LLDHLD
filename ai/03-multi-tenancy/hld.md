# Multi-tenancy at 500 tenants

## 1. What changes with tenant count
| Tenants | The dominant problem |
|---|---|
| < 10 | correctness — does isolation hold? |
| 10–100 | **fairness** — noisy neighbours |
| 100–1000 | **skew** — the largest tenant is 50× the median |
| 1000+ | per-tenant operations: onboarding, deletion, migration at scale |

You're designing for the second and third rows, and most candidates only answer the first.

## 2. Noisy neighbour — the dominant operational issue
One tenant's bulk import saturates workers and every other tenant sees an outage. Four
mitigations, in order of effectiveness:
1. **per-tenant rate limits** (shared token buckets, not per-process)
2. **weighted fair queueing** — a per-tenant queue, round-robin drain
3. **per-tenant concurrency caps** on expensive paths
4. **per-tenant budgets** with degradation

## 3. Skew
At 500 tenants the largest is often 20–50× the median. So a single shard strategy fails:
put the big tenants on **dedicated shards**, the long tail on shared ones. Route on a tenant→
shard map, not on a hash — a hash spreads a whale across everything.

## 4. Per-tenant lifecycle operations
The things nobody designs until they hurt:
- **onboarding** — a 10k-document import must not block live queries (own queue, own rate limit)
- **deletion** — an erasure request must remove rows, embeddings, caches, logs and backups.
  Design it up front; retrofitting it is close to impossible
- **migration** — schema changes now run against 500 tenants. Per-tenant progressive rollout,
  not one big bang
- **export** — tenants will ask for their data; build it before they do

## 5. Hardening the isolation guarantee
Application-enforced isolation is a floor, not a proof. In order of strength:
one audited scope primitive → a probe suite → **row-level security** → schema-per-tenant →
DB-per-tenant. Name where you are and what would move you up.

## 6. Observability
**Per tenant**, not aggregate: request rate, error rate, p95 latency, cost, queue depth.
An aggregate dashboard hides the one tenant having an outage — and that tenant is the one who
calls.
