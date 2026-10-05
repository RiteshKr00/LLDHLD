# Residency at scale — the deployment shape

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Regions | 3 | each a complete stack, not a replica |
| Infrastructure multiplier | ~3x | and utilisation drops, so cost/request rises more |
| Eval surface | 3x | separate model versions, separate gates |
| Cross-region pooling | none | headroom cannot be shared |
| Failover for regulated tenants | none | degradation is in-region only |
| Stateful stores per region | 4 | vector index, cache, telemetry, eval corpus |

The honest business framing: this is a **market-access cost**, not an infrastructure cost.

## 2. Topology

**Edge (global).** One thing only: resolve the tenant, read its residency attribute, route.
This layer must hold no payload and must be the *only* place the decision is made. If a second
component can also route, you have two policies and one of them is wrong.

**Regional (complete stack, x3).** API, LLM provider endpoint pinned to that region, vector
store, semantic cache, telemetry collector and backend, eval corpus and harness. Nothing here
reaches out of region — enforced by egress policy, not by convention.

**Global (aggregate only).** Metric counts, latencies, error rates, billing totals. Numbers
about payloads, never payloads. A useful test when someone proposes a new global service: could
this field ever contain a customer sentence? If yes, it is regional.

## 3. The controls, in order of durability

1. **Network egress policy.** The EU stack has no route to a non-EU endpoint. This survives
   bad code, and it is what an auditor actually wants.
2. **The CI residency test.** Reads config, fails the build. Survives staff turnover.
3. **Per-tenant residency attribute** at the edge, with failover disabled for regulated ones.
4. **Pinned model versions**, per region, gated against a per-region baseline.
5. **Redaction at the telemetry collector**, so traces carry IDs and shapes rather than text.
6. **Break-glass access** — time-boxed, approved, logged — for the cases that need real text.

Note the ordering. Code review and documentation are not on the list.

## 4. Per-tenant, not per-deployment

Residency is an attribute of the tenant, resolved at the edge, not a mode the whole system runs
in. Two reasons: most customers are not regulated and should keep normal failover; and a tenant
can relocate, which must be a data migration rather than a redeploy.

Store it next to the tenant record, resolve it **fail-closed** — an unknown tenant is treated
as regulated, never as unrestricted — and make it immutable outside the migration workflow.

## 5. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Failover during a regional outage | Disable it for regulated tenants; build the in-region ladder before you need it |
| 2 | Telemetry crossing | Regional collectors, redaction at source, region-locked consoles |
| 3 | Model version drift | Pin versions; gate per region; treat a version bump as a deploy |
| 4 | Cost and utilisation | Accept it and name it as market access; right-size per region |
| 5 | Golden set replication | Synthetic or in-region-only eval corpora |

## 6. Degradation ladder, in-region only

1. Serve from the in-region semantic cache
2. Second in-region provider
3. Smaller in-region self-hosted model
4. Queue, with an honest wait
5. Refuse, with a clear reason

Rungs 1–3 need to exist *before* the incident. A ladder designed during an outage is a
cross-region failover with extra steps.

## 7. Observability

Per-region dashboards as the default view, with a global roll-up of **counts and latencies
only**. Alert on: cross-border request count, which must be a hard zero for regulated tenants
and paged on any non-zero; per-region eval score against that region's gate; per-region
provider version, alerting on change; residency-test status per deploy; and the age of the
oldest in-region trace against the retention policy, because retention is where a migrated
tenant's data quietly persists.

The one metric worth putting on a wall: **cross-border requests, by tenant, per day.** It
should be zero, and a chart that is always zero is the point — you will notice the day it is
not.
