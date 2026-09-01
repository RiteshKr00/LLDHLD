# HLD-12 — Ad Serving / Real-Time Bidding

## META
- difficulty: hard
- time: 45 min
- tags: latency-budget, deadline-fanout, auction, second-price, budget-pacing, fail-open, click-fraud
- why-it-matters: the only problem with a **hard real-time deadline** — 100 ms, enforced by someone
  else — and that one constraint decides every other choice.

## PROMPT
> "A user loads a page with an ad slot on it. Design the system that decides which ad to show, runs an
> auction among advertisers, and returns it."

## CLARIFY
- **What is the latency budget?**
  → **~100 ms end-to-end**, or the page renders without you. **Ask first — everything derives from it.**
- **Are we the exchange, or a bidder answering one?**
  → **The exchange:** take the request, fan out to bidders, run the auction, return one ad.
- **How many bidders, and do we control them?**
  → 20–50 **external companies over the public internet.** None of their latency is ours.
- **Is returning "no ad" acceptable?**
  → **Never if we can help it.** An empty slot earns nobody anything and looks broken.
- **Must a daily budget be enforced exactly?**
  → **No — a small overspend is fine.** This concession unlocks the design; get it explicitly.
- **CPM or CPC, and when is billing settled?**
  → Both, **settled from logs afterwards.** Assume a **pCTR model** exists, ~1 ms.

## STEP 1 — Requirements
**Functional:** one ad per slot · auction across bidders · targeting, daily budgets with **pacing**,
**frequency caps** · track impressions and clicks · bill.
**Non-functional:** **p99 ≤ 100 ms wall clock, hard** · **never a blank slot** · budget may be **slightly
overspent** · caps **approximate** · billing **exact eventually**, reconciled from the event log.
**Out of scope:** training pCTR · creative hosting (CDN, HLD-04) · advertiser UI · brand safety.
**Posture, up front: this fails open** — a worse ad, an over-budget ad, or a house ad beat nothing.

### CHECKPOINTS
- States 100 ms as a **hard deadline with a business consequence**, not a p99 to tune later
- Declares **fail-open in the requirements** — never a blank slot, overspend is fine
- Separates **approximate-now (pacing, caps) from exact-later (billing)**

### TRAPS
- Treating 100 ms as a target for the end; it is the constraint every choice is made *under*
- Promising exact budget enforcement — that forces a consistent read per impression, which won't fit

### FOLLOWUPS
- *"Overspend an advertiser by 2%, or show a blank slot?"*

## STEP 2 — Capacity
```
traffic   100M DAU × 20 views/day × 2 slots = 4B requests/day
          4B ÷ 86,400 ≈ 46,000 req/sec  ->  peak 2× ≈ 100,000 req/sec
** fan-out amplification — the number that matters **
          100,000 req/sec × 20 bidders = 2,000,000 outbound RPC/sec
Little's  2M/sec × 60 ms deadline = 120,000 requests IN FLIGHT
Law       (W = the DEADLINE, not the mean -> a ceiling; size for it)
          ~600 concurrent/node -> 120,000 ÷ 600 = ~200 nodes (500 req/sec each)
          over ~20 pre-warmed HTTP/2 pools: a TCP+TLS handshake costs more
          than the whole auction slice
targeting 1M line items × 2 KB ≈ 2 GB  -> FITS IN RAM ON EVERY NODE
profiles  500M × 500 B ≈ 250 GB        -> sharded Redis, same region, ONE read
tracking  4B/day × 200 B ≈ 800 GB/day  -> a STREAM, not OLTP rows
clicks    0.1% CTR -> 4M/day ≈ 46/sec  -> trivial by comparison
```
**The bottleneck is connection concurrency and tail latency — not CPU, not the DB.**

### CHECKPOINTS
- Computes **fan-out amplification**: 100k req/sec × 20 bidders = 2M outbound RPC/sec
- Uses **Little's Law** for in-flight concurrency — connections are the real constraint
- Notices the index is **GB, not TB**, so it sits in RAM per node — why 5 ms is possible

### TRAPS
- Sizing the inbound 100k/sec and stopping; the 2M/sec outbound sets the machine count
- An OLTP database for 4B impression writes/day — those are append-only events

### FOLLOWUPS
- *"Two million outbound calls a second. How many TCP connections, and who owns them?"*

## STEP 3 — API
```
POST /api/v1/ad-request  {slot_id, floor_cpm, tmax_ms, user:{id, geo, device}}
     -> 200 ALWAYS {creative_url, impression_id, token, tracking:{imp, click}}
        "no winner" is a HOUSE AD, never a 204 and never an error

POST https://bidder-N/rtb/bid  {request_id, slot, segments[], floor_cpm, tmax_ms: 60}
     -> 200 {bid_cpm, creative_id}   |   late = DISCARDED, not retried

GET  /px/i?t=<signed token>  -> 204  append to stream, return immediately
GET  /px/c?t=<signed token>  -> 302  log first, then redirect
```
`token` is **server-signed**: `{impression_id, campaign_id, cleared_price, exp}`. The client never sends
us a price; it hands back something we signed.

### CHECKPOINTS
- The response is **always 200 with a creative**; no-winner is a house ad, not a 204
- Price and impression id ride in a **server-signed token**, and `tmax_ms` goes to the bidder

### TRAPS
- A `?price=` or `?campaign=` parameter on the tracking URL — a client-writable billing input
- A synchronous `POST /impressions` the render waits on

### FOLLOWUPS
- *"Someone curls your click URL a thousand times. What stops a thousand billable clicks?"*

## STEP 4 — Data model + DB
```
campaigns(campaign_id, advertiser_id, daily_budget, pacing_mode, bid_model, status)
line_items(line_item_id, campaign_id, targeting_expr, creative_id, floor, start/end)
targeting_index  IN-PROCESS inverted index: "geo:IN" -> [li_7, li_91, …]
                 ~2 GB, built centrally, pushed to every node every few minutes
budget_state(campaign_id, spent_today, remaining, version)   central, SLOW path
budget_leases(campaign_id, node_id, slice_amount, issued_at, expires_at)
user_profile  Redis: user_id -> {segments[], freq:{campaign_id: count}}  ONE read
impressions   Kafka -> ClickHouse + S3   APPEND-ONLY, billing truth
```
**Targeting runs backwards:** in search the user types the query and you match stored documents; here the
**user is the document and advertisers' targeting rules are the stored standing queries** (HLD-11 owns
the indexing detail). All that matters here is that it is **in-process**. The **frequency map rides
inside the profile object**, so a cap costs zero extra round trips.

### CHECKPOINTS
- Serving touches **only an in-process index plus one same-region profile read**
- Impressions are an **append-only stream**; billing is *derived* from it, as in HLD-05

### TRAPS
- Targeting index in Postgres, queried per request — a hop plus a query planner inside 5 ms
- A `campaigns.spent` column `UPDATE`d per impression: 46,000 writes/sec onto one hot row

### FOLLOWUPS
- *"The index is 2 GB on 200 nodes. An advertiser edits targeting. When does that take effect?"*

## STEP 5 — Architecture
```
browser/SSP ─▶ Ad Server (stateless, in EVERY edge region)
                 │  ONE deadline clock, started at arrival
                 ├─▶ Redis: profile + frequency map   one same-region hop
                 ├─▶ in-process targeting index       ~2,000 candidates
                 ├─▶ local filters: slice, cap, safety   zero network
                 ├─▶ FAN-OUT ~20 bidders, SHARED absolute deadline
                 │      not answered in time -> DROPPED, no retry
                 ├─▶ auction: eCPM rank, second price, floor
                 └─▶ CDN creative URL + signed impression token

Budget Service ◀─ spend reports every ~5 s ─ every Ad Server
               ─▶ hands out budget SLICES (leases) ─▶

pixel/click ─▶ Tracker (204/302 at once) ─▶ Kafka ─┬─▶ counters (pacing, caps)
                                                   └─▶ fraud filter ─▶ billing
```
Three things sit deliberately **off** the critical path: budget (a pre-fetched slice), tracking
(fire-and-forget), billing (batch, from the log). **What cannot be made local must be made optional.**

### CHECKPOINTS
- Every serving step is **in-process or one same-region hop** — a cross-region RTT alone exceeds 100 ms
- **One absolute deadline clock** at arrival, shared by all bidders — timeouts don't stack
- **Budget and tracking are off the critical path** — slice pre-fetched, write fire-and-forget

### TRAPS
- Per-bidder timeouts applied one after another: 20 bidders × 50 ms is a one-second response
- Writing the impression to a DB before returning the creative — a durable write inside 100 ms

### FOLLOWUPS
- *"Your ad server is in Mumbai, the bidder is in Virginia. Is that bidder ever going to win?"*

## DEEP DIVE — the 100 ms deadline, and money you cannot count

### 1. Write the budget down, then let it decide everything
```
network in (browser/SSP -> our edge, incl. TLS)  10 ms  spent BEFORE t=0
--- t = 0 : request lands on the ad server, ONE clock starts ---
parse + user profile read                         5 ms  t=5
targeting retrieval (in-memory inverted index)    5 ms  t=10
local filters (slice, freq cap, safety)           2 ms  t=12  <- fan-out starts
BIDDER FAN-OUT <- one shared absolute deadline   60 ms  t=72  <- GUILLOTINE
auction + ranking (eCPM sort, second price)       3 ms  t=75
response assembly + network out                  15 ms  t=90  <- bytes gone
                                              -------
                                                100 ms  wall clock, 90 of it ours
```
`t` runs from *arrival*, so wall clock is `t + 10`. Every choice downstream is forced, not chosen:
targeting can't be a database → **in-process index**; the profile gets one hop → **same-region Redis**;
the budget check can't be a consistent read → **local slices**; the impression write can't be synchronous
→ **fire-and-forget stream**; and there is **no room for a retry anywhere.**

### 2. Fan-out with a deadline — timeouts *are* the algorithm
The deadline is **absolute, not per-bidder**: computed once from arrival, so a slow first hop shortens
everyone's window rather than extending the total. A bidder that misses it was simply not in this
auction — no retry, no error, no page. **That is the normal path, not error handling.**

> **Contrast with search (HLD-11).** Both scatter-gather with a timeout; the *cost* is opposite.
>
> | | Search | Ads |
> |---|---|---|
> | A missing participant | **a shard you own** → missing documents | **someone else's bidder** → one fewer bid |
> | So the response | flagged **`partial: true`**, never cached | says **nothing**; nobody to tell |
> | Fix for a slow one | the **fastest healthy replica** | **circuit-break it out** — you can't route around another company's DC |
> | Goal | **completeness, or an honest admission of its absence** | **an answer on time** |

Lengthen a valuable bidder's `tmax` **only by shortening something else**, and keep a **per-bidder
circuit breaker** — 600 doomed connections are real capacity.

### 3. The auction — second price, and the floor
Rank by **eCPM**, which normalises bid models: a CPC bid becomes `bid_cpc × pCTR × 1000`. **Second
price** means the winner pays the **runner-up's price plus a cent**, not their own bid, which makes
bidding your true valuation dominant — shade down and you only lose auctions you'd have profited from;
shade up and you win above your own valuation. The floor composes with it:
```
bids: 8.00, 5.00  floor 2.00 -> winner pays 5.01  (runner-up + a cent)
bids: 8.00, 1.00  floor 2.00 -> winner pays 2.00  (the FLOOR, not the runner-up)
bids: 1.50        floor 2.00 -> nobody clears -> HOUSE AD, never a blank
```
*(Header bidding pushed the industry to first-price around 2019 — layered second-price auctions stopped
being truthful across exchanges. The theory is still what's tested.)*

### 4. Budget: pacing, and the counter you cannot afford to read
**Two problems that get confused. Separate them out loud.**

**(a) Pacing — scheduling.** ₹100,000/day spent by 10:05 am respects the budget and is still bad: you
bought only cheap early traffic and the advertiser's chart flatlines for 14 hours.
```
target = a cumulative spend curve shaped by HISTORICAL TRAFFIC, not a straight line
every ~1 min:  p = clamp(target_spend_so_far / actual_spend_so_far)
enforcement:   admit the campaign with PROBABILITY p (or scale its bid by p)
```
**Probabilistic, not a hard gate:** a hard stop makes a campaign win the first N auctions of each minute
then vanish, buying whatever arrives first — a biased sample of the day.

**(b) Counting — distributed systems.** A consistent read-modify-write per impression is a round trip
inside a 2 ms slice **and** every node hammering one row per campaign — the same single-row contention as
the hot merchant account in HLD-05. **The answer is local budget slices (leases):** a node takes ₹500 of
campaign 42, spends it with zero coordination, reports every ~5 s, and asks for more when low. An
unreturned slice just **expires** (the self-healing claim from HLD-08/09).
```
slice size is the whole tradeoff:
  big    fewer round trips -> more stranded and more overspent budget
  small  tighter accuracy  -> more coordination, more load on the budget service
  rule:  ~30 s at this node's RECENT spend rate, shrinking to seconds in the last 5%

where the overspend comes from — name the sources, don't wave at "eventual consistency":
  1. slices already handed out when the budget hits zero  (the dominant one)
  2. impressions won but not yet reported   (≤ one reporting interval)
  3. a node crashing holding a slice        (bounded by the lease TTL)
  4. CPC: the billable click lands MINUTES after the impression
  5. cross-region reconciliation, the slowest loop -> split the daily budget
     across regions UP FRONT by expected traffic share
```
**A deliberate fail-open decision:** the invariant is *"an ad gets served"*, **not** *"the budget is never
exceeded by a rupee"*. Target ≤1% overspend, measure it, eat it. A synchronous consistent check instead
misses the deadline, which serves **zero** ads.

### 5. Tracking, fraud, and where fail-open stops
The Tracker does **no database write and no business validation** on the request path — its durability
boundary is the collector's disk buffer, so a Kafka outage costs **lag, not loss.** **Billing is derived,
not incremented:** counters drive pacing and caps, **the event log is the ledger**, and an hourly job
aggregates the filtered stream into the invoice. Unlike a payment retry, **there is an adversary** — a
competitor draining a rival's budget with scripted clicks.
```
signed token  the client can't mint a click for an impression that never happened
short exp     a "click" six hours after the impression is not a click
dedup on      imp_id -> at most ONE billable impression and ONE billable click
price is ours the cleared price comes from the token, never a query parameter
offline       per-IP / per-publisher anomaly scoring; a 40% CTR publisher is fraud
```
**Deriving billing from the log is a *security* decision:** you cannot run a fraud model inside 100 ms,
so computing the invoice hours later is what lets a fraudulent click be **un-billed before the advertiser
is charged.** And the posture is scoped, not a personality — where HLD-05 payments **fail closed** because
a wrong write is money you must claw back, an impression is perishable inventory expiring in 100 ms, so
ads **fail open on serving and fail CLOSED on billing.**

### CHECKPOINTS
- Writes the latency budget as **numbers summing to the deadline**, then derives choices from it
- **A late bidder is dropped, not retried** — and that is the normal path, not error handling
- **Contrasts it with search's scatter-gather (HLD-11)**: a lost shard means missing documents so search flags `partial`; a lost bidder is one fewer bid, so ads say nothing
- Explains **second price** and **why honest bidding is then dominant**, plus how the floor composes
- Gives **budget slices/leases**, sizes the slice against a tradeoff, and lists the overspend sources
- **Names the overspend as a deliberate fail-open choice**, justified by perishable inventory

### TRAPS
- "I'll use a timeout" without an absolute shared deadline — per-bidder timeouts stack
- Retrying a slow bidder; there is no second RTT in the budget, and the bid is optional anyway
- A strongly-consistent budget check per impression — correct, and it serves zero ads
- Confusing pacing (spread the spend) with counting (don't exceed it) — separate answers
- Incrementing billable spend at serve time — it removes the window where fraud gets filtered

### FOLLOWUPS
- *"Your best bidder is consistently 20 ms late. Do you extend the deadline for them?"*
- *"Two nodes each hold a ₹500 slice of a campaign with ₹600 left. What happens?"*

## STEP 7 — Scale
- **Geography is the constraint, not throughput.** The whole stack deploys in every edge region; one
  cross-region RTT exceeds the budget. Scaling means *replicate everything*, not *shard one thing*.
- **Index distribution:** built centrally, pushed to 200 nodes every few minutes, **swapped in
  atomically, never edited in place** — the HLD-06 trie's rebuild-and-swap, so reads never take a lock.
- **Connections:** pre-warmed HTTP/2 pools per bidder, a **bulkhead per bidder** so one slow endpoint
  can't drain a shared pool, and a **circuit breaker** dropping a chronically-late bidder.
- **Fan-out width is a cost lever, not just latency:** each extra bidder adds RPC cost and tail risk for a
  diminishing bump in clearing price. Budget service is sharded by `campaign_id`, per-region splits up front.

### CHECKPOINTS
- **The whole stack replicates per region** — geography, not shard keys, is the scaling axis
- Names **per-bidder pools with bulkheads and a circuit breaker** for a chronically-slow bidder

### TRAPS
- Sharding the ad index and scatter-gathering internally — a second fan-out inside the one you can't afford
- Treating a slow bidder as only latency; it also holds hundreds of connections doing nothing

### FOLLOWUPS
- *"50 bidders, 5 of them win 95% of auctions. What do you do with the other 45?"*

## STEP 8 — Failure
The ladder, in the order things break — **every rung still serves something**:
- **All bidders time out** → direct-sold and internal demand. Still nothing? **House ad from the CDN.**
- **Profile store down** → untargeted / contextual ads. Revenue drops; the page still works.
- **Budget service down** → spend held slices, extend leases, log loudly, accept more overspend.
- **Frequency store down** → serve without caps. An annoyed user beats an empty slot.
- **Tracking pipeline down** → collectors buffer to disk and replay: **lag, not loss.**
- **The one thing that fails CLOSED:** token signature verification. A token that doesn't verify is
  **dropped, never billed.** Serving is optimistic; money is not.

### CHECKPOINTS
- A **degradation ladder that always ends in a served ad** — house ad, never an empty slot

### TRAPS
- Retrying the whole auction after a total timeout; the page has already rendered
- Applying fail-open uniformly and letting unverified clicks through to billing

### FOLLOWUPS
- *"Kafka is down for an hour. Have you lost money?"*

## STEP 9 — Wrap
- **Bottleneck:** the bidder fan-out — outbound connection concurrency and the tail latency of the
  slowest participants. Not CPU, not the database.
- **Tradeoffs:** slice size (coordination vs overspend) · fan-out width (clearing price vs tail risk) ·
  deadline length (more bids vs the publisher's page budget) · approximate counters (fast, for control)
  vs exact batch billing (slow, for money).
- **Monitoring:** **p99 against the deadline** · timeout rate **per bidder** · **fill rate** and house-ad
  rate · overspend % per campaign · pacing error vs the target curve · per-publisher CTR anomalies · lag.
- **Next:** pCTR inference inside the budget (~5 ms) · first-price and header bidding · brand safety.

### CHECKPOINTS
- **p99 against the deadline and per-bidder timeout rate** as headline metrics, not CPU graphs

### TRAPS
- Reporting the *average* — it sits under 100 ms while a quarter of requests miss the deadline
- Fill rate without house-ad rate; "we always served something" hides a collapse in paid demand

### FOLLOWUPS
- *"p50 is 40 ms and p99 is 130 ms. What's happening, and what do you look at first?"*

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | one service, query a DB for matching ads, take the highest bid, `UPDATE campaigns SET spent = spent + x`, timeouts as error handling |
| **Senior** | the **latency budget written out and summing to 100 ms** · deadline fan-out where late bidders are dropped, not retried · in-process index and one profile read · second price with a floor · **budget slices reconciled async, small overspend accepted** · fire-and-forget impression stream · house ad on total failure |
| **Staff** | all that **+ fail-open named as a product decision, with the HLD-05 fail-closed contrast** · sizing the slice and enumerating where overspend comes from · probabilistic pacing and why random beats a hard gate · the **search-scatter-gather vs ad-fan-out** contrast · per-bidder bulkheads and circuit breakers · **fail-open on serving, fail-closed on billing**, seeing that lagged billing is what makes fraud filtering possible |

## REFERENCE
**One ad request, end to end.** `t = 0` is arrival at the ad server; wall clock is `t + 10`.
1. `POST /ad-request {slot, user, floor_cpm: 2.00}` hits the **nearest region's** ad server.
2. `t=5` One Redis read → `{segments:[fitness, 25-34, mobile], freq:{c42: 2}}` — profile **and** caps.
3. `t=10` In-process index intersects `geo:IN ∩ interest:fitness ∩ device:mobile` → ~2,000 line items.
4. `t=12` Local filters, zero network: c42 is at its cap, c88 has no slice left → ~300 survive.
5. `t=12` Fan out to 20 bidders with `tmax: 60`. **Absolute deadline: t = 72.**
6. `t=72` **Guillotine.** 14 answered; 6 did not and are simply not in this auction. Nobody is paged.
7. `t=75` Rank by `eCPM = bid × pCTR × 1000`. Winner 8.00, runner-up 5.00, floor 2.00 → **pays 5.01.**
8. `t=90` Respond `200` with the creative URL and a signed token `{imp_id, campaign, 5.01, exp: +30 min}`.
   **90 ms from arrival, 100 ms wall clock, no slack** — which is why the retry and the cross-region hop
   were designed out, not trimmed later.

**Impression:** `/px/i` → verify → Kafka → `204`; counters move pacing and caps, **nothing is billed yet.**
**Click:** `/px/c` → verify signature and `exp` → dedup on `imp_id` → log → `302`.
**Budget, all day:** the node spends its ₹500 slice locally, reports every 5 s, takes the next at 20%
remaining, shrinking near exhaustion. The day ends **~0.6% over — known, measured, accepted.**
**Billing, an hour later:** the stream runs through the fraud filter and aggregates per campaign — *that*
is the invoice; the counters were never the money.
**Total bidder failure:** nothing above the floor → internal demand → **house ad.** Fail open.

## ONE-LINER
> *"Everything falls out of a 100 ms deadline someone else enforces, so I'd write the budget as
> arithmetic first — 10 ms in, 5 for the profile read, 5 for targeting from an in-process index, 2 for
> local filters, 60 for the bidder fan-out, 3 for the auction, 15 out — and then the rule that follows:
> **one absolute clock starts when the request lands, so the fan-out goes at 12 ms and the guillotine
> falls at 72; a bidder that hasn't answered is dropped, not retried.** Timeouts aren't error handling
> here, they're the algorithm — the opposite of search, where a missing shard means missing documents.
> The hard part is budget: a consistent spend check per impression is a round trip I don't have, so each
> server takes a **local slice**, spends it with zero coordination, and reconciles asynchronously —
> accepting ~1% overspend deliberately, because an impression is perishable inventory and an empty slot
> is revenue nobody gets back. **Fail-open on serving, fail-closed only on billing.**"*
