# Design scenario 3: multi-tenant RAG platform, 500 tenants

## The prompt

> "Design a RAG platform serving 500 tenants, each with their own document corpus. No tenant
> may ever see another's documents. What breaks first?"

---

## Clarifying questions to ask FIRST

1. **Shared corpus or per-tenant?** *(Per-tenant makes isolation the primary constraint.)*
2. **Corpus size per tenant, and the spread?** *(Skew decides the sharding strategy.)*
3. **Update frequency — trickle, or bulk onboarding?** *(Bulk ingest is the workload that breaks things.)*
4. **How fast must a new document be searchable?** *(Minutes buys you an async pipeline.)*
5. **Can tenants share a semantic cache?** *(Trick question. Never.)*

---

## The follow-up bank

1. Namespace per tenant, or one index with a filter? Defend it.
2. What breaks first — query or ingest?
3. Your largest tenant is 20× the median. Now what?
4. How do you onboard a tenant with 200k documents without degrading everyone else?
5. A tenant asks you to delete all their data. Walk me through it.
6. How would you prove isolation to an auditor?
7. The embedding model is deprecated. What's the plan?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
