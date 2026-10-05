# DESIGN-02 — multi-tenant RAG platform, 500 tenants

## META
- difficulty: hard
- time: 20 min
- tags: architecture, rag, multi-tenancy, sharding, ingest, fairness
- source: `AI-design-scenarios.md` #3, `03-multi-tenancy/`, `02-rag-pipeline/hld.md`

## PROMPT

> "Design a RAG platform serving 500 tenants, each with their own document corpus. No tenant
> may ever see another's documents. What breaks first?"

## CLARIFY

- **"Shared corpus or per-tenant?"**
  → *"Per-tenant, entirely separate."*
- **"Corpus size per tenant?"**
  → *"Average 10k documents, largest 200k."*
- **"Update frequency?"**
  → *"Continuous, plus bulk onboarding of new tenants."*
- **"How fast must a new document be searchable?"**
  → *"Minutes is fine."*
- **"Can tenants share a semantic cache?"**
  → *(trick — the answer is never)*

## STEP 1 — Clarify and scope

### CHECKPOINTS
- Establishes per-tenant corpora, so isolation is the primary constraint
- Notes the **skew**: largest tenant is 20x the average -> one shard strategy won't fit all
- Notes bulk onboarding exists -> ingest is a first-class workload, not an afterthought

## STEP 2 — Numbers

### CHECKPOINTS
- 500 x 10k docs x ~20 chunks = **~100M chunks** -> past "one index"
- Embedding cost for onboarding one 10k-doc tenant = 200k embeddings -> minutes of dedicated throughput
- Query side is modest; **ingest is the heavy path**

## STEP 3 — Architecture

### CHECKPOINTS
- **Per-tenant namespace or index** — isolation **structural**, not a post-filter
- Says why: a vector search is a similarity query, not a WHERE clause. Post-filtering leaks **content** if buggy
- **Shard by tenant**, with the largest tenants on dedicated shards (handles the skew)
- **Ingest pipeline with per-tenant queues** and its own rate limit
- **Per-tenant token buckets + weighted fair queueing** on query
- **Semantic cache namespaced per tenant** — a cross-tenant hit is a **leak, not a perf bug**
- **Per-tenant budgets**
- Single scope primitive on the metadata side, **failing closed**
- **404 not 403** for out-of-scope resources

## STEP 4 — What breaks first

### CHECKPOINTS
- **Ingest, not query** — and explains why: a tenant onboarding 10k docs saturates embedding throughput and blocks everyone
- Second: ANN latency as per-shard corpus grows
- Third: the noisy neighbour on query
- Fourth: embedding-model change = **re-embed 100M chunks**, which is a migration project not a config change

## STEP 5 — Degradation, cost, security

### CHECKPOINTS
- Ingest backlog degrades **that tenant only** — never globally
- Query degradation: retrieval-only extractive answer if generation is unavailable
- Cost: retrieval precision -> fewer prompt tokens -> lower cost per query
- Security: prompt injection can't cross tenants **because retrieval is namespaced**
- Cache key must include **corpus version**, or a re-index serves the old world forever

## STEP 6 — Observability and proof of isolation

### CHECKPOINTS
- Per-tenant: query latency, ingest lag, recall@k on a labelled sample, cost
- **Cross-tenant probe suite as a regression test** (the 17-probe pattern), and volunteers that it's a floor not a proof
- Would want **row-level security** (or equivalent) before claiming a hard guarantee to an auditor
- Uses the word **tested**, not *guaranteed*

## TRAP

One shared index with a post-filter by `tenant_id`. It looks equivalent and isn't: isolation
becomes one filter bug away from leaking **document content**. Namespaces mean the other
tenant's chunks were never in the searched set.
