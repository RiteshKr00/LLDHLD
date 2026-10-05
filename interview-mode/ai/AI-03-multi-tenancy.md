# AI-03 — multi-tenancy, retrofitted

## META
- difficulty: hard
- time: 15 min
- tags: multi-tenancy, fail-closed, isolation, rbac, rag-namespace
- source: `03-multi-tenancy/`

## PROMPT

> "You converted a single-tenant app to multi-tenant. Convince me one tenant cannot see
> another's data. Then tell me why you didn't just give each tenant its own database."

## CLARIFY

- **"Retrofit or greenfield?"**
  → *"Retrofit — that's why I'm asking."*
- **"How many tenants, any regulated?"**
  → *"Low tens, none regulated yet."*
- **"Do tenants share any data?"**
  → *"Only reference data."*

## STEP 1 — Scope & stakes

### CHECKPOINTS
- Built for one organisation, needed many
- The stake: the product's whole promise is "this is *your* persona" — a cross-tenant read is the worst possible defect
- Retrofit constraint named up front (live app, no downtime for a data migration)

## STEP 2 — Mechanism

### CHECKPOINTS
- **One primitive**, not scattered filters: every tenant-owned query resolves scope through `resolveScopeTenant`
- Why one funnel: scattered `WHERE tenant_id = ?` relies on every developer remembering forever
- **Fail closed**: tenant-less non-superadmin → **sentinel matching no rows**
- Plain-English version: *"a request without a valid organisation returns nothing rather than everything"*
- **RAG isolation is structural** — per-persona namespace (`ragContextIdOf`), so the wrong tenant's chunks were never in the searched set
- **404 not 403** on out-of-scope, so existence isn't leaked
- Superadmin cross-tenant is one explicit, validated, **audited** act-as door

## STEP 3 — Trade-offs

### CHECKPOINTS
- Names all three patterns: shared-schema / schema-per-tenant / DB-per-tenant
- **Concedes** DB-per-tenant gives isolation by construction
- Names the constraint that ruled it out: live retrofit, no data migration, connection multiplication, per-tenant cost before tenant count justified it
- **States the trade accepted**: isolation is app-enforced, so a missed filter is a leak
- **What would change my mind**: a tenant requiring data residency, or one tenant needing independent scaling

## STEP 4 — Failure modes

### CHECKPOINTS
- "A developer forgets the filter on a new endpoint" → it leaks; doesn't pretend otherwise
- Three mitigations, increasing strength: one funnel → probe suite → **Postgres RLS / repository layer where the un-scoped query is unreachable**
- Distinguishes fail-open vs fail-closed consequence: an auth bug becomes a **full data dump** vs an empty result
- 17 probes = cross-product of surfaces (users, personas, conversations, RAG) × shapes (list, detail, export, reindex)
- **Volunteers that it's a regression floor, not a proof** — a new surface needs a new probe

## STEP 5 — Scale

### CHECKPOINTS
- Per-tenant **rate limits and quotas**, not just global
- Noisy-neighbour problem: one tenant's burst degrading others → per-tenant concurrency caps
- At scale the isolation story must harden: RLS, per-tenant encryption, audit retention
- Prompt-injection angle: tenant-scoped retrieval means injected text can't reach another tenant's corpus

## STEP 6 — Honesty

### CHECKPOINTS
- Volunteers: the guarantee is *"we routed everything through the funnel"*, **not** *"the database refuses"*
- Uses the right word: **tested**, not *guaranteed*
- Would want RLS before claiming a hard guarantee to an auditor
- 17 is a **verifiable** number — countable in `isolation.test.ts`

## TRAP

"We added a `tenant_id` column and filter on it." True but junior — it describes the schema,
not the guarantee. The content is the **fail-closed default**, the **single funnel**, and
**namespace-level** isolation for retrieval.
