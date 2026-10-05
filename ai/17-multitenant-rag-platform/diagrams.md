# Multi-tenant RAG platform — diagrams

## 1. The whole system, end to end

One tenant's request, from the token at the edge to the streamed answer. Ingest runs down
the left, query down the right; they meet only at the shards.

```mermaid
flowchart TB
    CL["Tenant app<br/>uploads and questions"]
    GW["API gateway<br/>authn, tenant id from the token"]
    IQ[["Per-tenant ingest queue<br/>own rate limit, weighted fair drain"]]
    PIPE["Dedup, chunk, embed batched<br/>content hash skips what we have"]
    UPS["Idempotent upsert<br/>uuid5 of content, safe to retry"]
    RT["Tenant to shard map<br/>a map, never a hash"]
    S1[("Shared shards<br/>the long tail, tenants 1-400")]
    S3[("Dedicated shard<br/>the 200k-doc whale tenant")]
    SCP["Scope resolver<br/>FAILS CLOSED: no tenant, no query"]
    CA[("Semantic cache<br/>keyed by tenant + corpus version")]
    NS["Namespaced top-k<br/>hard partition, not a post-filter"]
    FL{"Above relevance floor?"}
    GEN["Generate + stream<br/>only from the retrieved chunks"]
    REF["Refuse: not in corpus"]

    CL --> GW
    GW -->|upload| IQ
    GW -->|question| SCP
    IQ --> PIPE
    PIPE --> UPS
    UPS --> RT
    RT --> S1
    RT --> S3
    SCP --> CA
    CA -->|hit| CL
    CA -->|miss| NS
    NS --> S1
    NS --> S3
    S1 --> FL
    S3 --> FL
    FL -->|no| REF
    FL -->|yes| GEN
    GEN --> CL
    REF --> CL
```

What to notice: the tenant id is resolved **once**, at the edge, and every hop downstream
inherits it. The cache is namespaced by tenant *and* corpus version — a cache shared across
tenants is a cross-tenant leak with a nice hit rate. Query is cheap and namespaced; ingest is
the contended resource, which is why it gets a queue of its own.

---

## 2. Ingest — the heavy path, breaks FIRST

```mermaid
flowchart TB
    UP[tenant uploads 10k docs] --> IQ[["per-tenant ingest queue<br/>+ per-tenant rate limit"]]
    IQ --> H{"content-hash dedup"}
    H -->|seen| SKIP[skip]
    H -->|new| CH[chunk]
    CH --> EM[embed, batched]
    EM --> UPS["idempotent upsert<br/>uuid5 of content"]
    IQ -.->|"backlog degrades THAT tenant only"| UP
```

The dotted edge is the whole point of the per-tenant queue: a bulk onboarding backs up its
own queue and nobody else's. Without it, tenant 1's 200k-document import is tenant 2's
outage — and tenant 2 is the one who calls. Embedding throughput is the first real wall.

---

## 3. Storage — sharded by tenant

```mermaid
flowchart TB
    UPS["idempotent upsert<br/>uuid5 of content"] --> RT["tenant to shard map<br/>a map, never a hash"]
    RT --> S1[("shard 1<br/>tenants 1-200")]
    RT --> S2[("shard 2<br/>tenants 201-400")]
    RT --> S3[("dedicated shard<br/>the 200k-doc tenant")]
```

A map, not a hash: a hash fans every query across every shard. The long tail shares shards,
whales get their own, and a tenant that grows 10× must be movable between them without
downtime.

---

## 4. Query — fails closed

```mermaid
flowchart TB
    QU[question] --> SCP["scope resolver<br/>FAILS CLOSED"]
    SCP --> NS["per-tenant NAMESPACE<br/>not a post-filter"]
    NS --> S1[("shard 1<br/>tenants 1-200")]
    NS --> S2[("shard 2<br/>tenants 201-400")]
    NS --> S3[("dedicated shard<br/>the 200k-doc tenant")]
    S1 --> TK["top-k + score"]
    S2 --> TK
    S3 --> TK
    TK --> FL{"above relevance floor?"}
    FL -->|no| REF["refuse: not in corpus"]
    FL -->|yes| GEN[generate + stream]
```

Two refusals, both deliberate. The scope resolver fails closed — an unresolved tenant returns
nothing rather than everything. The relevance floor refuses on weak retrieval rather than
letting the model improvise. A namespace is a hard partition; a post-filter is a bug waiting
for the day someone forgets the `WHERE`.

---
