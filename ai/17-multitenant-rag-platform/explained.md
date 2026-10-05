# Multi-tenant RAG platform — explained

**Related:** topic 03 (the isolation primitive), topic 02 (the RAG pipeline), topic 07 (ANN).
This scenario is where those three collide.

---

## 1. The numbers force the design

500 tenants × 10k docs × ~20 chunks = **100M chunks**. That is past "one index" on every axis —
memory, build time, and blast radius.

And the **skew** matters more than the total: the largest tenant is typically 20–50× the
median. A design that works for the average tenant fails for the biggest one.

---

## 2. Isolation: namespace, not filter

This is the decision the whole scenario turns on.

| Approach | How isolation works | Failure mode |
|---|---|---|
| One index + `WHERE tenant_id` post-filter | you retrieve across everyone, then discard | **one bug leaks document content** |
| **Namespace / index per tenant** | the other tenant's chunks were never in the searched set | a bug returns *nothing*, not someone else's data |

**Say this explicitly:** a vector search is a *similarity query*, not a `WHERE` clause. With a
shared index you are ranking against every tenant's content and then hoping the filter is
right. With namespaces, isolation is **structural** — there is nothing to filter because
nothing else was ever a candidate.

The metadata side still needs the fail-closed scope resolver from topic 03, and out-of-scope
reads still return **404, not 403**.

---

## 3. Ingest is what breaks first, not query

The instinct is to design the query path. But:

- a query is one embedding + one ANN search — cheap, and the corpus is namespaced so it
  doesn't grow with tenant count
- **onboarding one tenant with 10k documents is 200k embeddings** — minutes of dedicated
  throughput, and if it shares a queue with everyone it blocks them all

So: **per-tenant ingest queues with per-tenant rate limits.** A tenant's own backlog degrades
*that tenant only*. That containment is the design goal.

---

## 4. Sharding, given the skew

Hash-sharding spreads each tenant across every shard, so a query fans out to all of them and
pays the slowest. **Shard by tenant** instead — one query touches one shard — with the
whales on **dedicated shards** and the long tail sharing.

Routing is a `tenant → shard` map, not a modulo. A map is boring and correct; a hash is elegant
and wrong here.

---

## 5. The cache is a leak waiting to happen

A semantic cache keyed only on the question is a **cross-tenant data leak**, not a performance
bug: tenant B asks a similar question and receives tenant A's answer.

Cache key must include **tenant + corpus version**. The corpus-version part matters
independently — re-index and an unversioned cache serves the old world indefinitely.

---

## 6. Deletion — design it on day one

A tenant offboards and you must remove: rows, **embeddings**, **cache entries**, **logs**,
**traces**, and backups. Embeddings are derived personal data and count.

If any of that is entangled — a shared index, prose summaries with facts baked in, an
unnamespaced cache — deletion is close to impossible. **Namespaces make deletion a drop
operation**, which is the underrated second reason to choose them.

---

## The follow-ups, answered

**"What breaks first?"**
Ingest. Specifically embedding throughput during bulk onboarding, then vector-store write
throughput. Query is fine because it's namespaced.

**"Onboard a 200k-document tenant without hurting anyone?"**
Its own queue, its own rate limit, content-hash dedup so repeats are free, batched embedding
calls, and progress telemetry so you know at hour two rather than hour eight. Backlog degrades
that tenant, nobody else.

**"Prove isolation to an auditor."**
A cross-tenant probe suite as a regression test, plus audit logs on any cross-tenant admin
access. Then be honest: it's **tested**, not *guaranteed*. For a guarantee you want row-level
security or physical separation, and I'd say which one the tenant's contract requires.

**"Embedding model deprecated."**
That's scenario 19 in full: dual-index, resumable backfill, shadow reads, compare recall@k per
tenant, progressive cutover. ~28 hours of embedding at 100M chunks plus double storage. It's a
project, not a deploy.

---

## One-line summary

> "Namespace per tenant so isolation is structural rather than filtered, shard by tenant with
> the whales on dedicated shards, give ingest its own per-tenant queues because that's what
> actually breaks, and version the cache key by tenant *and* corpus — a cross-tenant cache hit
> is a leak, not a perf bug."

## The trap answer to avoid

One shared index with a `tenant_id` filter. It looks equivalent, and it makes isolation one bug
away from leaking **document content** — and it makes offboarding a delete-by-query across a
100M-vector index instead of dropping a namespace.
