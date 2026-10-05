# Cost governance at 500 tenants — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CALL["Any LLM call<br/>chat, voice, extraction, agent step"] --> ADM
    ADM["Admission gate: tenant + feature tag REQUIRED<br/>untagged is refused, never logged as unknown<br/>worst-case cost estimated BEFORE the call"] --> RES
    RES[("Live reservation counter in Redis<br/>per tenant, per hour, TTL 1h")] --> GATE
    GATE{"Under the soft ceiling,<br/>3x the tenant's own baseline?"} -->|yes| GW
    GATE -->|no| DEG["Degrade: mid model, fewer chunks<br/>1/22 the cost, refuses nobody"]
    DEG --> HARD{"Under the hard monthly cap?"}
    HARD -->|yes| GW
    HARD -->|no| REF["Refuse: 429 carrying the budget reason"]
    GW["Gateway to the provider<br/>one internal call shape"] --> COM
    COM["Commit actual, release the difference<br/>overshoot = calls in flight x $0.063"] --> LED
    COM --> CALL
    LED[("Usage ledger, append-only, async write<br/>3M rows/day, never on the critical path")] --> ROLL
    ROLL["Rollups 5-min to hourly to monthly<br/>priced by ONE versioned rate card"] --> BURN
    ROLL --> DASH["Showback per tenant AND per feature<br/>same rate card, so displayed IS billed"]
    BURN{"Burn rate over 3x own baseline<br/>AND over $10/hour projected excess?"} -->|yes| PAGE["Page the owner, about 10 minutes in"]
    BURN -->|no| DASH
    RES -.- ROLL
```

Read it as one call. The tag is enforced at the top because an untagged call is unbillable
*and* invisible; the cost is estimated before the provider is touched because you cannot cap a
number you only learn afterwards; and the gate reads the **live** reservation counter, not the
rollup, because the rollup is minutes stale and a runaway spends $3.60 in every stale minute.
The dotted line is reconciliation — the rollup corrects the counter, it does not replace it.
Nothing on the enforcement path waits for the ledger write.

---

## 2. Detection latency is the whole design

```mermaid
flowchart TB
    E["Runaway starts: 10 calls/s from one tenant<br/>$216/hour against a $100/hour platform"] --> D1
    E --> D2
    E --> D3
    E --> D4
    D1["burn rate, 5-min buckets vs own baseline<br/>fires at plus 10 min"] --> C1["excess $35"]
    D2["monthly budget, 80% threshold<br/>fires at plus 13.8 h"] --> C2["excess $2,919"]
    D3["daily rollup vs a $200/day cap<br/>fires at plus 15.0 h"] --> C3["excess $3,180"]
    D4["the provider invoice<br/>arrives after the month closes"] --> C4["excess $140,556"]
```

Every detector is correct and every one of them names the right tenant. The only variable is
**when**, and it is worth $140,521. Notice also that the two "proper" budget controls land 72
minutes apart and cost about the same: a monthly window cannot see an hourly burn, however
carefully you set its threshold.

---

## 3. Reserve worst case, commit actual, release the difference

```mermaid
sequenceDiagram
    participant R as Request
    participant G as Budget gate
    participant B as Reservation counter
    participant P as Provider
    participant L as Ledger
    R->>G: prompt 1000 tok, max_tokens 4000
    G->>G: estimate the WORST case, $0.063
    G->>B: reserve $0.063
    alt the reservation fits under the ceiling
        B-->>G: admitted
        G->>P: call
        P-->>G: 200 output tokens, actual cost $0.006
        G->>B: commit $0.006 and release $0.057
        G->>L: append row: tenant, feature, model, units
    else ceiling reached
        B-->>G: no room
        G->>R: degrade to the mid model, or 429 at the hard cap
    end
```

The estimate is deliberately pessimistic because it is the only bound available pre-flight.
Reserving the prompt-only cost instead — the version that lets the ledger reconcile later —
over-admits by 11×, since the gate is counting $0.003 while the calls average $0.033. The
release step is what stops the pessimism becoming a self-inflicted outage.

---

## 4. Three tiers, three time constants

```mermaid
stateDiagram-v2
    [*] --> Normal
    Normal --> Soft: hour-to-date over 3x own baseline
    Soft --> Normal: hour rolls over at the baseline rate
    Soft --> Paged: 3x sustained over two 5-min windows
    Paged --> Normal: cause fixed and the loop stopped
    Soft --> Hard: month-to-date reaches 100 pct of cap
    Paged --> Hard: month-to-date reaches 100 pct of cap
    Hard --> Normal: budget raised or the month rolls over
```

**Soft** is automatic and costs nothing to be wrong about — it degrades and self-clears on the
hour. **Paged** is the only tier that needs a human, which is why the $10/hour floor on the
alert matters. **Hard** is contractual and refuses. A design with only the hard tier is an
outage generator; a design with only the soft tier degrades a broken retry loop forever.

---

## 5. Where a runaway hides

#### Untagged — the storm has no owner

```mermaid
flowchart LR
    J["nightly summariser<br/>Celery retry storm"] --> U[("UNATTRIBUTED bucket<br/>no key, no budget, no baseline")]
    T1["t-042 counter"] --> OK1["green"]
    T2["the other 499 counters"] --> OK2["green"]
    U --> GAP["invoice $316, dashboard $97<br/>31 pct attributed and the gap IS the storm"]
```

#### Tag required at admission

```mermaid
flowchart LR
    J2["nightly summariser<br/>tenant=internal-ops feature=nightly-summary"] --> K[("its own counter<br/>own baseline, own budget")]
    K --> AL["burn rate 3x over two windows<br/>paged at plus 10 min, with the owner named"]
    K --> DB["invoice $316, dashboard $316<br/>100 pct attributed"]
```

Both dashboards are honest about what they can see. The first one just cannot see 69% of the
bill, and every per-tenant budget in it is intact while the spend triples. Background jobs,
retries and internal tooling are the usual occupants of that bucket — and they are exactly the
things that loop.
