# Topic 3: multi-tenancy, retrofitted, fail-closed

## The prompt

> "You converted a single-tenant app to multi-tenant. Walk me through how you did it, and
> convince me one tenant can't see another's data. Then tell me why you didn't just give each
> tenant its own database."

---

## Clarifying questions worth asking back

1. "Is this a retrofit or greenfield?" — completely different answer.
2. "How many tenants, and are any of them regulated?" — decides how far to go.
3. "Do tenants share any data?" — most designs have *some* shared reference data.

---

## The follow-up bank

1. Why shared-schema rather than schema-per-tenant or DB-per-tenant?
2. A developer forgets the tenant filter on a new endpoint. What happens?
3. What exactly does "fails closed" mean here?
4. 17 probes — how did you choose them, and is that enough?
5. How does superadmin cross-tenant access not break the model?
6. Why 404 and not 403?
7. How would you prove isolation to an auditor?
8. Your RAG index — how is *that* isolated?

Answers in `explained.md`.
