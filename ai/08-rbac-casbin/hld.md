# Authorisation at 500 tenants

## 1. Numbers first
500 tenants × ~8 roles × ~40 permissions = **~160k policy rows**. Every request performs at
least one `enforce()`, and a page render may perform dozens for field-level checks.

At 70 req/s peak with ~20 checks per request that is **1,400 enforce calls/second.** That
number is the whole design: authorisation is now on the hot path.

## 2. The enforcer must be cached, and that creates the real problem
Loading 160k rows per request is impossible, so the enforcer lives in memory. Which means:

> **A permission change on one node is invisible to the other nodes until they reload.**

That is the central problem of a distributed policy engine, and it's what interviewers probe.
Options:

| Approach | Staleness | Complexity |
|---|---|---|
| TTL reload (e.g. 30s) | up to 30s | trivial |
| **Pub/sub invalidation** (Redis channel on write) | ~milliseconds | moderate — the right default |
| Read policy per request | none | unusable at this rate |

**And the direction matters:** a stale *grant* is a security problem; a stale *deny* is only an
annoyance. So on a revoke, invalidate synchronously and confirm; on a grant, lazy is fine.
Saying that asymmetry out loud is the senior half of the answer.

## 3. Scoping policy per tenant
Don't load all 160k rows on every node. **Filter the policy by tenant** — Casbin supports
filtered policy loading — so a node holds only what its traffic needs. Memory drops from all
tenants to the working set.

## 4. Field-level checks are the volume, not page-level
Page-level is one check per request. **Field-level is one per field per row** — a 50-row table
with 20 columns is 1,000 checks. Naively that's the latency.

Fix: resolve the caller's field policy **once per request** into a visible-field set, then
filter rows against that set in memory. One enforce, not a thousand.

## 5. What breaks, in order
1. **Enforce on the hot path** without caching
2. **Stale grants** after a revoke — the security-relevant direction
3. **Field-level check explosion** on list endpoints
4. **Policy-store write contention** — bulk role edits across tenants
5. **Matcher complexity** — a regex or ABAC-style matcher is evaluated per check; keep it
   trivial or precompute

## 6. Auditability
At this scale the questions are "who could see this?" and "who changed that?" So: an
append-only **policy change log** (who, when, before, after), and periodic **effective-permission
snapshots** per user, because reconstructing them from a change log at audit time is painful.

## 7. Observability
enforce latency p95 · enforce rate per node · **policy cache age** and staleness after a revoke ·
denial rate per endpoint (a spike usually means a broken role edit, not an attack) ·
per-tenant policy row counts, which is where the skew shows up.
