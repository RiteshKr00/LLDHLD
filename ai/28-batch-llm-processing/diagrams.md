# 10M records overnight — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    SRC[("Ticket store, 10M rows<br/>read by id range, never OFFSET")] --> PLAN
    PLAN["Shard planner<br/>2000 shards x 5000 records"] --> CKPT
    CKPT[("Checkpoint store<br/>pending, leased, done, dlq")] --> DED
    DED{"Normalised content hash seen?"}
    DED -->|"hit, 32%"| SINK
    DED -->|miss| RTR
    RTR["Difficulty router<br/>huge threads go straight to frontier"] --> SUB
    SUB["Wave submitter<br/>a batch job every hour, not one job"] --> BAPI
    BAPI["Provider Batch API<br/>half price, 24h SLA you do not own"] --> CUT
    CUT{"Cutover clock at T+5h"}
    CUT -->|"returned, 85%"| VAL
    CUT -->|"stalled, 15%"| DRAIN
    DRAIN["Sync drain pool, ~450 concurrent<br/>multi-key SHARED token bucket"] --> VAL
    VAL{"Schema valid and confident?"}
    VAL -->|"unsure, 12%"| ESC["Escalate to frontier<br/>same schema, second hop"]
    VAL -->|"invalid x3"| DLQ[("Dead letter queue<br/>shard completes without it")]
    VAL -->|ok| SINK
    ESC --> SINK
    SINK[("Idempotent sink<br/>upsert on id + prompt version")] --> BURN
    BURN["Burn-down telemetry<br/>projected finish vs the 06:00 line"] -.-> CKPT
```

One record's path: hash first (a third never reach a model), then a difficulty decision, then
the Batch API with a clock over it, then validation, then an upsert that is safe to repeat. The
only feedback edge is telemetry writing progress back to the checkpoint store — everything else
flows one way, which is what makes a replay cheap.

---

## 2. The cost ladder, and what each lever risks

```mermaid
flowchart LR
    A["A: frontier, sync, one key<br/>10M calls = $35,000<br/>107 hours on one key, 347 days as a loop"] --> B
    B["B: + normalised-hash dedup<br/>6.8M distinct = $23,800<br/>risks NOTHING, free and lossless"] --> C
    C["C: + cheap-first cascade<br/>12% escalate = $4,284<br/>risks ACCURACY"] --> D
    D["D: + Batch API on the 85%<br/>$2,463<br/>risks THE DEADLINE"]
```

Take them left to right, and notice the ordering is not by size. Dedup goes first because it is
free; the Batch API goes last because it is the only lever that can make you miss the window,
and it has to be insured against with the cutover clock in diagram 4.

---

## 3. Resumability

#### No checkpoint — progress lives in a variable

```mermaid
flowchart LR
    R1["one loop over 10M records"] --> R2["crash at 62%<br/>6.2M records done"]
    R2 --> R3["restart from record 0"]
    R3 --> R4["6.2M records paid for twice<br/>window gone, cost doubled"]
```

#### Shard leases and checkpoints

```mermaid
flowchart TB
    S1["2000 shards x 5000 records"] --> S2[("one checkpoint row per SHARD<br/>never per record")]
    S2 --> S3["worker takes a TTL lease"]
    S3 --> S4["done: result and checkpoint<br/>written in ONE transaction"]
    S3 --> S5["crash: lease expires,<br/>shard returns to pending"]
    S5 --> S6["replay ONE shard, 5000 records<br/>0.05% of the run, not 62%"]
    S6 --> S7["upsert on id + prompt version<br/>so the replay costs rows, not duplicates"]
```

Waste on a crash is bounded by *workers in flight × shard size*, not by how far into the night
you were. That is why the shard is sized in seconds of work — under a minute — rather than in a
round number of records.

---

## 4. A shard's life, including the cutover

```mermaid
stateDiagram-v2
    [*] --> Pending
    Pending --> Leased : worker takes a TTL lease
    Leased --> Pending : lease expires, worker died
    Leased --> Batched : submitted in wave n
    Batched --> Returned : provider drains it
    Batched --> Cancelled : cutover clock fires at T+5h
    Cancelled --> Drained : re-dispatched sync, full price
    Drained --> Returned
    Returned --> Escalated : confidence below the floor
    Returned --> Written : schema valid
    Returned --> Dead : invalid after 3 attempts
    Escalated --> Written
    Written --> [*]
    Dead --> [*]
```

Two exits, both deliberate. `Cancelled` is the deadline insurance — you stop waiting on someone
else's queue and pay full price for the remainder. `Dead` is the poison-record exit that lets
the shard reach `Written` for everything else instead of spinning on one malformed ticket.

---

## 5. One quota pool, two workloads

#### Batch at full throttle after 06:00

```mermaid
flowchart TB
    Q1[("provider quota: one TPM pool")] --> W1["overnight batch<br/>still draining at 09:00"]
    Q1 --> W2["interactive product<br/>morning traffic"]
    W1 --> X["batch consumes the pool<br/>product gets the 429s<br/>the ticket is filed against the PRODUCT"]
    W2 --> X
```

#### The batch as a low-priority tenant

```mermaid
flowchart TB
    Q2[("provider quota: one TPM pool")] --> B1["batch bucket<br/>100% 22:00-06:00<br/>20% until 08:00, then zero"]
    Q2 --> B2["product bucket<br/>reserved, never yielded"]
    B1 --> Y["batch degrades ITSELF<br/>an overrun is a slower batch,<br/>not a product outage"]
    B2 --> Y
```

The provider sees one tenant, so the fairness has to be yours. This is the dedicated-Celery-queue
bulkhead argument applied to quota instead of workers: the thing that overruns must be the thing
that suffers.
