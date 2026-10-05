# Cost governance at 500 tenants — explained

**Your version of this:** on the voice/video persona product you built **per-call metering
across five providers behind one `getRateCard()`**, with an idempotent ledger and fail-closed
tenant scoping. That is the attribution half, and it is the half that is genuinely hard to
retrofit. **You have not built enforcement.** Say so plainly and then design it — "I built the
prerequisite and here is the layer on top" is a stronger answer than pretending otherwise, and
the interviewer can tell the difference.

---

## 1. The numbers, and what they force

| | |
|---|---|
| Tenants | 500 |
| LLM calls/day | 600k → **7 QPS** average, ~70 peak |
| Mean cost per call | **$0.004** (blended: cache hits, mid-model routing, some frontier) |
| Platform spend | **$2,400/day · ~$72k/month · $100/hour** |
| Spend skew | top 10 tenants ≈ 40% of spend; largest ≈ **40× the median** |
| Largest tenant | ~$96/day = **$4/hour** |
| Median tenant | ~$2.40/day |

Now the incident that defines the whole design. A retry loop in one tenant's agent feature
issues **10 calls/second** on the frontier model. At 1,000 prompt + 200 completion tokens that
is $0.006 a call, so **$216/hour from one tenant**.

Notice what that is: **one tenant's bug generates more calls per second than the entire
platform's average.** Platform spend goes $100/hour → $316/hour. **A 3× multiplier from one
loop in one feature.**

Left until the invoice — 27 days and 15 hours of a 30-day month — that is **$140,556 of excess
on a $72k month**.

**What the numbers force:** the money is not lost to the average, it is lost to the *interval
between the runaway starting and someone noticing*. So the design target is not "accurate
billing", it is **detection latency**, and it has a formula:

```
detection_window  ≤  tolerated_excess / (runaway_rate − baseline_rate)
                  =  $50 / ($216 − $4 per hour)
                  =  14 minutes
```

Fourteen minutes. An hourly rollup does not fit. A daily job does not fit by two orders of
magnitude. That single line is why the alerting layer is built the way it is, and quoting it
out loud is worth more than any diagram.

---

## 2. The layers, each by the failure it prevents

### 1 · Attribution enforced at admission — not tagged, not admitted

**Prevents:** an unattributable invoice, and a runaway hiding in the gap.

Every call carries `(tenant, feature, model, request_id, actor)` — `actor` distinguishing a
human turn from an agent step, because agents are where loops live. The tag is **required at
the gateway**: an untagged call is **refused**, not logged with `tenant=unknown`.

The reason is sharper than tidiness. An untagged call reaches no counter, so it has no budget,
no baseline and no owner to page. In `solution.py` the storm lands in that bucket and **all 500
per-tenant detectors stay green while attribution completeness drops to 31%**. The gap *is* the
runaway. Anything under 100% is the exact shape of your blind spot — and that bucket is
disproportionately background jobs, Celery retries and internal tooling, which are exactly the
things that loop.

### 2 · One rate card, versioned and effective-dated

**Prevents:** displayed ≠ billed, and last month's invoice silently rewriting itself.

One `getRateCard()`: the ledger prices from it and the dashboard renders from it, so divergence
is impossible rather than unlikely. **Effective-dated** is the part people miss — prices change,
and a rollup computed in March must not move when you edit the card in April. Price each row
with the version in force at its timestamp and **store the resolved cost on the rollup**, not
just the units.

### 3 · Estimate before, actual after

**Prevents:** enforcement that arrives after the money is spent.

You cannot enforce on a number you only learn afterwards. The only cost you know pre-flight is
`prompt_tokens × in_rate`; the completion is unbounded up to `max_tokens`. So:

**reserve the worst case, commit the actual, release the difference.**

Reserve `prompt + max_tokens` priced at the frontier rate ($0.063 with `max_tokens=4000`).
When the call returns, book the real cost and hand the unused reservation back.

The naive version — reserve the prompt-only estimate and let the ledger reconcile later —
**over-admits by 11×**, measured in `solution.py`: a $12 ceiling lets roughly $133 through,
because the gate is counting $0.003 of prompt while the calls average $0.033.

### 4 · Two-tier spend state: lagging rollup + live reservation counter

**Prevents:** budgets enforced on stale numbers, which over-permit by construction.

The authoritative ledger is asynchronous and rolled up on a schedule — minutes stale at best.
At $216/hour a runaway spends **$3.60 inside every stale minute**. So the gate reads a **live
per-tenant reservation counter in Redis**, TTL'd to the hour, and the rollup **reconciles** it
rather than replacing it. Two clocks, one number, and you must say which one the gate reads.

### 5 · Per-tenant *and* per-feature budgets

**Prevents:** one runaway becoming everyone's problem, and a tenant budget that cannot name
the culprit.

Tenant budget contains blast radius; feature budget names which of chat, extraction, voice or
agent runs ate it. Underneath both, an **agent-run step budget** — the loop here is scenario 4's
failure arriving on scenario 9's invoice, and a per-run cap kills it at source before any of
this machinery is needed.

### 6 · A breaker with three tiers, three time constants

**Prevents:** both the bill and a self-inflicted outage.

| Tier | Trigger | Action | Human involved? |
|---|---|---|---|
| **Soft ceiling** | hour-to-date > 3× the tenant's own trailing baseline | **degrade** — cheaper model, fewer chunks | no |
| **Burn alert** | rate of change, see layer 7 | page the owner | yes, ~10 min |
| **Hard cap** | 100% of the contracted monthly budget | refuse, with the reason in the 429 | already involved |

Measured in `solution.py`, one hour of the runaway: no policy $216 / 36,000 served · hard
cutoff at the soft ceiling $12 / **2,000 served, 34,000 refused** · degrade **$21.18 /
36,000 served**. Ten times cheaper than doing nothing and it refuses nobody.

Be honest about the limit: 36,000 answers from a cheap model on a retry loop are still 36,000
useless answers. **The degrade buys the ten minutes until a human arrives. It is not a fix.**
That is why the hard cap exists behind it.

### 7 · Anomaly detection on rate of change, with a dollar floor

**Prevents:** slow detection — and, at 500 tenants, prevents the alerts being ignored.

Absolute thresholds are **late by construction**: the budget window is monthly and the burn is
hourly, so "you have used 80% of your budget" fires 13.8 hours into this incident. The rule is
5-minute buckets against **the tenant's own trailing baseline** (same-hour-last-week, not
yesterday — weekly seasonality is real), firing on 3× sustained over two windows. Ten minutes.
$35 instead of $140,556.

And the second condition, which is what makes it survive 500 tenants: **also require the
projected excess to exceed ~$10/hour.** A median tenant at $0.10/hour tripling is a perfect 3×
ratio and $0.20/hour of excess — 250 hours to reach the $50 you said you'd tolerate. Do not page
anyone. **Alert in dollars per hour, not in ratios.** The long tail is protected by its monthly
cap, not by a pager.

### 8 · Showback, then chargeback, in unit economics

**Prevents:** nobody owning the number.

Per tenant *and* per feature, in **$/conversation, $/document, $/resolved ticket** — not total
spend. A total falls in a quiet week and hides a prompt that got 40% dearer; the unit cost does
not. Showback informs; **chargeback changes behaviour**, because a team optimises what it is
billed for.

### 9 · Cost as a release gate

**Prevents:** a prompt change quietly adding 2,000 tokens to every call.

Same shape as the eval gate you own on the clinical-report generator: run the golden set,
measure **tokens and cost per task**, fail the build on a regression beyond the noise floor.
Cost is a quality metric with a currency symbol, and it is the one nobody gates.

---

## 3. What breaks first, in order

1. **Detection latency** — the invoice is monthly, the runaway is hourly. Everything below
   costs you accuracy; this one costs $212 an hour while you are asleep, and it is the only
   entry measured in six figures.
2. **Attribution completeness** — you cannot detect per-tenant what you never tagged.
3. **Rollup lag versus enforcement** — budgets reading minutes-old aggregates over-permit.
4. **Estimate accuracy** — too optimistic and the cap leaks 11×; too pessimistic and you refuse
   legitimate traffic.
5. **Rate-card drift** — hand-maintained against providers who change prices.
6. **Alert fatigue** — 2,000 thresholds get muted, and the real one is missed inside the noise.
7. **Cost of the cost system** — 3M rows/day, 1.1B/year, watching a $72k month.

`hld.md` has the reasoning for each position.

---

## The follow-ups, answered

**1 · "A tenant hits 100% mid-generation. What happens to that request?"**
Nothing. It completes. **The budget is checked at admission, never mid-stream** — killing a
half-generated response costs you the tokens *and* delivers nothing, which is strictly worse
than either alternative. A request admitted is a request completed; the cap applies to the
*next* one. On a live voice call that is the difference between a downgrade and a dropped
customer.

**2 · "You can't know output tokens beforehand. So how do you cap?"**
Reserve the worst case you actually permit — `prompt + max_tokens` — commit the actual, release
the difference. Overshoot is then bounded by `calls in flight × worst-case cost`, which is a
number you can quote: 140 in flight × $0.063 = **$8.82** platform-wide, and per tenant far less
if you cap tenant concurrency. Which means **a concurrency cap is a cost-precision lever**, not
just a fairness one — not the usual reason people give for having one.

**3 · "Budget store is down. Fail open or closed?"**
**Fail open on the soft ceiling, closed on the contractual hard cap.** A missed soft ceiling
costs recoverable money; refusing all 500 tenants because Redis blinked is an outage you built
yourself. But a prepaid tenant contracted to a hard cap must be refused — letting them through
is a commercial promise you cannot unmake. Same reasoning as failing open on rate limiting and
**closed** on tenant scope: the test is which error is irreversible, not a house style.

**4 · "Spend triples overnight. First ten minutes."**
The burn-rate alert has already fired at minute 10 naming tenant *and* feature, so I am not
discovering it, I am triaging it. Check the soft ceiling actually engaged — spend should have
flattened at ~$21/hour, not $216. Then classify in this order: **retry storm** (retry rate up,
unique prompts flat), **agent loop** (steps-per-run distribution has a tail), or **legitimate
growth** (unique users up, tokens-per-call flat). Only the third gets a budget increase. The
first two get the tenant's concurrency cap dropped while the owning team fixes it.

**5 · "2,000 thresholds. How do you not drown?"**
Three things. Alert on **rate of change against each tenant's own baseline**, so you never
hand-set a threshold. Add the **dollar floor** — no page unless the projected excess clears
~$10/hour, which silences the entire long tail. And **route by owner, not by severity**: a
tenant-scoped alert goes to that tenant's account team, a feature-scoped one to the owning
engineers. Platform on-call only sees platform-total anomalies. Roughly 30 tenants clear the
floor; that is a manageable pager.

**6 · "Dashboard says $71k, invoice says $78k."**
Assume the invoice is right about the total and your ledger is right about the attribution, then
find the gap in this order: **untagged calls** (check attribution completeness — a 9% gap on a
$78k bill is $7k and is the single likeliest cause), **rate-card drift** (a price changed and
nobody edited the card), **calls that never reached the ledger** because the async write was
dropped under load, and **cost categories you do not meter at all** — embeddings, moderation
endpoints, fine-tuning storage, egress. Reconcile monthly and alert when the delta exceeds 2%;
an unexplained 9% is a bug, not rounding.

**7 · "A prompt change added 2,000 tokens to every call for a week."**
Total spend barely moved because it was a quiet week — which is the entire lesson. **Gate on
tokens-per-task in CI** against the golden set, and monitor **$/unit-of-work**, not $/day.
Prompts and retriever configs are versioned artefacts and belong in the release gate with the
model, because "how many chunks do we send" is a cost decision wearing a quality costume.

**8 · "Where does a cache hit get attributed? A pricier fallback?"**
A cache hit is a **ledger row with zero provider cost and a `served_from=cache` flag** — omit
it and your $/conversation is wrong and your hit rate unverifiable. The *saving* belongs to the
tenant that hit, not the one that populated; cross-tenant sharing is a leak anyway (topic 03).
A pricier fallback is billed to the tenant at the pricier rate **and tagged as a fallback**,
because a spike caused by a provider outage must be visibly *not* the tenant's fault when their
account manager opens the dashboard.

**9 · "Product wants a free tier."**
It makes the hard cap the primary path rather than the exception, so everything above gets
exercised daily instead of once a quarter — which is good for you. Free tier gets a **low
monthly cap, mid-model-only routing, a small concurrency cap, no burst allowance**, and it
refuses rather than degrades because there is no revenue to protect. Watch the **abuse
economics**: at $0.006 a call one scripted account can spend $216/hour, so free tier needs the
concurrency cap and per-IP limits *before* it needs a budget.

---

## One-line summary

> "The invoice is monthly and the runaway is hourly, so I design for detection latency: every
> call tagged at admission or refused, worst-case cost reserved before the call and reconciled
> after, a live per-tenant counter the gate reads rather than a lagging rollup, and alerts on
> rate of change against each tenant's own baseline with a dollar floor so 500 tenants don't
> become 2,000 pagers. At the ceiling it degrades to a cheaper model rather than cutting off —
> ten times cheaper for the same requests served."

## The trap answer to avoid

Two versions, both common. **Using monthly provider invoices as your cost system**: aggregate
and late, so you cannot attribute, cannot cap, and cannot find the cause. And the subtler one
that loses just as reliably — **building a beautiful per-tenant dashboard and calling it
governance.** Visibility is not control. Governance lives in the request path, in a gate that
can say no before the money is spent, and the question the interviewer is really asking is
*how many minutes of runaway does your design pay for*.
