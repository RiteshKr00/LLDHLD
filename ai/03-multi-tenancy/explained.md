# Multi-tenancy — explained

**Your code:** `digital-twin/server/tenantScope.ts` and `personaScope.ts`

| Anchor | What it is |
|---|---|
| `tenantScope.ts:24` | `resolveScopeTenant(input)` — **the single primitive** |
| `tenantScope.ts:50` | `resolveScopedRagPersona(...)` — extends scoping to retrieval |
| `tenantScope.ts:66` | `ragContextIdOf(row)` — per-persona RAG namespace |
| `tenantScope.ts:77` | `canAccessConversation(...)` |
| `personaScope.ts:19` | `callerTenantScope(req)` — per-request entry point |
| `personaScope.ts:54` | `personaInScope(...)` |
| `personaScope.ts:67` | `scopedPersonaForReq(req, id)` |
| `isolation.test.ts:61/90/110/125` | 4 suites: users · personas · conversations · RAG |

---

## The three tenancy patterns

| Pattern | Isolation | Cost | Migration pain |
|---|---|---|---|
| **Shared DB, shared schema** (`tenant_id` column) | app-enforced | lowest | one migration |
| **Shared DB, schema per tenant** | DB-enforced-ish | medium | N schemas to migrate |
| **DB per tenant** | strongest | highest | N databases, N connection pools |

**You chose shared-schema.** The defensible reason is the *retrofit constraint*: the app was
live and single-tenant. Shared-schema needed no data migration and no change to connection
management. DB-per-tenant would have meant migrating live data, multiplying operational
surface, and paying per tenant from day one for isolation the tenant count didn't yet justify.

**The trade you accepted, and must state:** isolation is enforced in **application code**, so
a missed filter is a leak. That's the honest cost, and naming it is what makes the answer
senior rather than defensive.

---

## The actual design decision: one funnel, not scattered filters

The naive retrofit adds `WHERE tenant_id = ?` to every query. That fails because it relies on
every developer remembering, forever, on every new endpoint.

What you did instead: **every tenant-owned query resolves its scope through one primitive.**
`resolveScopeTenant` is the only thing that decides which tenant a request may see. New code
calls it; there's one place to audit and one place to test.

---

## "Fails closed" — the single most important sentence

> A tenant-less non-superadmin resolves to a **sentinel that matches no rows.**

Compare the two possible defaults when scope can't be determined:

| Default | Consequence of an auth bug |
|---|---|
| **Fail open** — no tenant → no filter | every tenant's data returned. Catastrophic. |
| **Fail closed** — no tenant → sentinel | the caller sees nothing. Visible, safe, debuggable. |

Fail-open is a *one-line* difference in code and a *company-ending* difference in outcome. The
plain-English version to say out loud: **"a request without a valid organisation returns
nothing rather than everything."**

---

## RAG isolation is structural, not filtered

`ragContextIdOf` (`:66`) gives each persona its **own retrieval namespace**. This matters more
than it sounds: a vector search is a similarity query, not a `WHERE` clause. If all personas
shared one index, isolation would depend on post-filtering results by tenant — and any bug
there leaks *content*, not just row ids.

Separate namespaces mean the wrong tenant's chunks are **not in the searched set at all**.
Isolation by construction beats isolation by filter. This is your strongest isolation point —
lead with it when asked about the RAG layer.

---

## 404, not 403

Out-of-scope reads return **404**. A 403 confirms the resource exists — so a tenant could
enumerate another tenant's persona ids by watching which requests return 403 versus 404. With
404 everywhere, existence itself isn't leaked.

Small detail, and interviewers notice it, because it means you thought about the *information*
an error code carries.

---

## Proving it: the 17 probes

`isolation.test.ts` is the cross-product of **surfaces** × **access shapes**:

- surfaces: users, personas, conversations, RAG
- shapes: list, detail, export, reindex

Each probe is tenant A attempting tenant B's resource and asserting nothing comes back.

**The honest limitation, volunteer it:** it's a *regression floor*, not a proof. It proves the
surfaces I knew about stay closed. A new endpoint needs a new probe — the suite can't discover
what it wasn't told about.

---

## The follow-ups, answered

**"A developer forgets the filter on a new endpoint."**
Then it leaks — that's the real cost of app-enforced isolation, and I won't pretend
otherwise. Three mitigations in increasing strength: (1) one funnel so there's a single
correct pattern to copy; (2) the probe suite, so known surfaces regress loudly; (3) the real
fix — **Postgres row-level security**, or a repository layer where the un-scoped query isn't
reachable. Then it's the *database* refusing, not developer discipline.

**"Superadmin cross-tenant access — doesn't that break the model?"**
It's an explicit, validated, **audited** "act as tenant" path, not an implicit bypass. So it
appears in audit logs and can't happen accidentally. The design rule: exactly one deliberate
door, logged — not a special case sprinkled through the handlers.

**"How would you prove isolation to an auditor?"**
The probe suite as evidence, audit logs for cross-tenant admin access, and honestly: I'd want
RLS before claiming a hard guarantee. *"Tested" and "guaranteed" are different words and I'd
use the right one.*

**"Is shared-schema ever wrong?"**
Yes — when a tenant contractually requires data residency or physical separation, or when one
tenant's volume needs independent scaling. That's the trigger to move, and it's a business
requirement surfacing, not a technical failure.

---

## One-line summary

> "Every tenant-owned query goes through one scope resolver that fails closed — no valid
> organisation resolves to a sentinel matching no rows — and RAG is namespaced per persona so
> isolation there is structural rather than filtered. 17 cross-tenant probes keep it honest."

## The trap answer to avoid

Saying "we added a `tenant_id` column and filter on it." True but junior — it describes the
schema, not the *guarantee*. The interesting content is the fail-closed default, the single
funnel, and namespace-level isolation for retrieval.
