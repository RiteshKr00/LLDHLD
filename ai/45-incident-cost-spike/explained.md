# The 5x cost spike — explained

> Incident genre. Method under pressure, not architecture. What is being tested is whether you
> bisect or guess.

---

## 1. The first thing you do is a division

Before opening a dashboard: **spend ÷ calls**.

That one number splits the entire problem in two, and it takes thirty seconds. `solution.py §1`:

| Cause | Calls | £/call | Spend | Splits to |
|---|---|---|---|---|
| Cache hit-rate collapse | 4.3x | 1.0x | 4.3x | **volume** |
| Agent with no step budget | 5.2x | 1.0x | 5.1x | **volume** |
| Retry storm | 4.8x | 1.0x | 4.9x | **volume** |
| Fallback to a pricier model | 1.0x | 4.9x | 5.0x | **cost/call** |
| Prompt got longer | 1.0x | 5.0x | 5.0x | **cost/call** |
| Provider raised prices | 1.0x | 5.0x | 5.0x | **cost/call** |

Every one produces the same 5x on the bill and they are not the same problem. Volume up means
cache, loop, retries or a scraper. Cost per call up means a longer prompt, a longer output, a
routing shift, or a price change.

---

## 2. "Nothing was deployed" narrows nothing

That clause is true and irrelevant, and knowing why is most of the answer:

| Cause | How it happens with no deploy |
|---|---|
| Cache hit-rate collapse | A re-index changed the key, or a TTL expired en masse |
| Agent loop | One user asked something that does not converge |
| Retry storm | The provider got slower, so everything retried |
| Fallback to a pricier model | The cheap provider circuit-broke |
| Prompt got longer | A prompt edit, or retrieval returning more chunks |
| Provider price change | An email nobody read |

The common causes of a cost spike are all **config, data, or somebody else's infrastructure**.

---

## 3. The cache is the cause that disguises itself

`solution.py §3`:

| Hit rate | Calls reaching the provider | Daily £ |
|---|---|---|
| 78% | 220,000 | 462 |
| 60% | 400,000 | 840 |
| 30% | 700,000 | 1,470 |
| 5% | 950,000 | 1,995 |

78% to 5% is **4.3x the bill with identical user traffic**. On the provider's dashboard this looks
exactly like a volume increase — so you will spend an afternoon looking for traffic that never
arrived.

That is why **cache hit rate must be a first-class alert in its own right**, not something you
compute during an investigation.

---

## 4. Agent loops live in the tail

`solution.py §4`:

| Step budget | Mean steps | Worst run | p99.9 |
|---|---|---|---|
| none | **4.8** | **400** | 400 |
| 8 | 4.0 | 8 | 8 |
| 20 | 4.0 | 20 | 20 |

The mean moves 20%. The worst case moves **50x**. An average-based dashboard shows almost nothing
while a handful of non-terminating runs consume the budget.

So: a per-run **step budget** and a **per-run cost cap** with a breaker, and alert on the tail of
steps-per-run rather than the mean.

---

## 5. Alert on the derivative, not the level

`solution.py §5`. Spike begins at hour 2.

- **Rate-of-change alert** — this hour against a trailing mean — fires at **hour 2**.
- **Absolute-budget alert** at 80% of monthly spend fires at **hour 20**, and on a quieter month
  would not fire at all until the invoice.

An 80%-of-budget alert is a smoke detector that waits until the house is 80% burnt. Same data,
different derivative, hours instead of weeks.

---

## 6. What should have caught it

| Control | Prevents |
|---|---|
| **Alert on rate of change**, per tenant and feature | monthly-invoice detection |
| **Per-tenant, per-feature, per-model cost dashboards** | an unattributable spike |
| **Cost per call tracked separately from volume** | conflating the two causes |
| **Cache hit rate as a first-class alert** | the disguised cause |
| **Per-run step and cost caps on agents**, with a breaker | the tail |
| **A budget breaker that degrades** | a monthly surprise |

---

## The follow-ups, answered

**1. The very first number, and why that one?**

Spend divided by calls. It is one division, it takes thirty seconds, and it eliminates half the
hypothesis space before I have opened anything. Volume and cost-per-call have entirely disjoint
cause lists, and every cause produces the same headline 5x — so without the split I would be
investigating six hypotheses instead of three, in whatever order they occurred to me.

**2. Volume flat, cost per call doubled. Candidates?**

Four, in the order I would check them. The **prompt got longer** — either someone edited it, or
retrieval started returning more or larger chunks, which is the version people forget because it
needs no prompt change. **Output got longer** — a format instruction changed, or a max-tokens
default moved. **The router shifted** to a more expensive model, usually because a cheaper
provider circuit-broke and the fallback is doing its job. And a **provider price change**. I would
look at mean prompt tokens and mean completion tokens first, since those two numbers separate the
first two from the last two immediately.

**3. Nothing was deployed. How can cost change?**

Because most of what determines cost is not code. Prompts and model choices are config. Retrieval
behaviour depends on the corpus, which changes when someone re-indexes. Cache behaviour depends on
keys and TTLs. Routing depends on provider health, which is somebody else's system. Retry volume
depends on provider latency. And prices are set by the vendor. "Nothing was deployed" eliminates
exactly one cause out of a long list, and it is not usually the one.

**4. How would a cache invalidation show up?**

As a **volume spike at the provider** with flat user traffic — which is to say, disguised as a
different problem. Anyone comparing provider call volume against last week will conclude they have
a traffic surge and go looking for its source. The only thing that identifies it directly is a
cache-hit-rate chart, which is why that metric belongs on the wall rather than in a query someone
writes during an incident. Common triggers: a re-index that changed the key, a corpus-version bump,
a mass TTL expiry, or a deploy that changed how the key is built.

**5. An agent with no step budget. What does the bill look like?**

Almost normal on average, and catastrophic in the tail. The mean steps-per-run barely moves —
20% in the simulation — while the worst run goes from 8 steps to 400. A handful of
non-terminating runs consume the budget, and every average-based dashboard shows a mild
uptick. The fix is a per-run step budget **and** a per-run cost cap, because a run can be
expensive in few steps if the context keeps growing, plus a breaker that stops the run rather than
letting it hit a hard cap 400 calls later.

**6. Immediate mitigation, before you know the cause?**

Cap first, diagnose second. Apply a per-tenant and per-feature rate limit at the gateway at
something like 1.5x normal, so the bleeding stops without taking the product down. If the split
says cost-per-call, pin the router to the cheaper model. If it says volume and an agent is
implicated, drop the step budget hard. All three are gateway config, reversible in minutes, and
none requires knowing the cause. Then investigate with the meter no longer running.

**7. What should have caught this on the day?**

A rate-of-change alert on spend per hour, per tenant and per feature, against a trailing mean —
that fires at hour 2 rather than hour 20. Underneath it, cost-per-call as a tracked series
separate from volume, so the alert already tells you which half of the problem you are in. Cache
hit rate as its own alert. And per-run cost caps on agents, so the tail cannot run away
unattended.

**8. Why is alerting on absolute spend wrong?**

Because it is a level, and the thing that went wrong is a change. An 80%-of-monthly-budget alert
fires late by construction — hour 20 in the simulation, and on a quiet month not until the
invoice. It also cannot be set per tenant without maintaining hundreds of thresholds by hand, and
every one of them goes stale as traffic grows. A derivative alert needs no threshold maintenance:
"this hour is more than double the trailing mean for this tenant" is self-calibrating and scales
to any number of tenants.

**9. How do you stop this being a monthly-invoice discovery?**

Get the feedback loop down to the timescale the problem operates on. Costs change hourly, so cost
telemetry has to be hourly — computed from your own token counts at request time rather than
waiting for the provider's billing export, which is usually a day behind. Attribute every call to
a tenant, feature and model at the gateway. Alert on the derivative. And put a budget breaker in
place that **degrades** — cheaper model, smaller context, cache-only — so crossing a threshold is
a quality event on the day rather than a finance conversation three weeks later.

---

## One-line summary

Divide spend by calls before touching a dashboard, because that single division splits six causes
into two disjoint sets of three; note that every common cause needs no deploy, so "nothing
shipped" is not a clue; treat cache hit rate as a first-class alert because it disguises itself as
a volume spike; cap agent runs because loops live in the tail where means cannot see them; and
alert on rate of change rather than absolute spend, which is the difference between hour 2 and the
invoice.

---

## The trap answer to avoid

Listing everything that could raise cost, unordered. The bisection is the answer, and the first
division is nearly free. The second trap is treating "nothing was deployed" as a meaningful clue —
it eliminates one cause from a list on which most entries are config, data or someone else's
infrastructure. And the quiet one: designing the fix as an absolute-spend alert, which is the
control that failed here by construction.
