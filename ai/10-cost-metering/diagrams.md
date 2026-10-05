# Cost attribution — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CALL["Voice call<br/>one call, five paid providers"] --> GW
    GW["Gateway<br/>tenant tag required, not optional"] --> RT["Call runtime<br/>LLM, TTS, STT, avatar"]
    GW --> VP["Voice platform<br/>hosts the call, bills afterwards"]
    RT -- units as they happen --> EM["Usage emitter<br/>async, never on the critical path"]
    VP -- webhook, late and retried --> WH["Webhook endpoint<br/>constant-time secret, 503 if unset"]
    VP -. no webhook after T .-> PULL["Client pull fallback<br/>then re-check: did the webhook land?"]
    EM -. loss beats a failed call .-> LED
    WH -- idempotent by call id --> LED
    PULL -- post-fetch re-check --> LED[("Usage ledger<br/>append-only rows, 7-30 day retention")]
    LED --> RC["getRateCard<br/>versioned, effective-dated"]
    RC --> ROLL["Rollups<br/>hourly to daily to monthly"]
    ROLL --> BILL[("Monthly rollup<br/>the billing record, kept indefinitely")]
    ROLL --> DASH["Dashboard<br/>prices from the same rate card"]
    RC --> DASH
    ROLL --> BUDG{"Budget breaker<br/>the layer not yet built"}
    BUDG -. degrade, do not cut off .-> GW
```

Three paths reach the ledger and only one of them is authoritative: live units from the
emitter, the provider webhook, and the pull fallback. The ledger is queryable before the
authoritative number lands. Attribution is enforced at the gateway, because an untagged call
is unbillable and invisible.

## 2. Five providers, five timelines

```mermaid
flowchart TB
    D["DURING THE CALL<br/>t=0-30s, known live"] --> D1["LLM tokens<br/>from the stream"]
    D --> D2["TTS characters<br/>at synthesis, t=5s+"]
    D --> D3["STT minutes<br/>at finalisation"]
    S["AT SESSION END<br/>t=30-33s"] --> S1["Avatar minutes"]
    A["AFTER, OUT OF BAND<br/>t=40-55s, by webhook"] --> A1["Voice platform cost<br/>the authoritative one"]
```

The engineering problem is the gap between lane one and lane three, not the multiplication.

## 3. Reconciliation with a race

```mermaid
sequenceDiagram
    participant C as Call
    participant L as Usage ledger
    participant P as Voice platform
    C->>L: token usage (streaming, during call)
    C->>L: TTS / STT / avatar units
    Note over L: queryable now, but NOT authoritative
    par webhook path
        P->>L: webhook: authoritative cost
        L->>L: verify secret (constant time, length-guarded)
        L->>L: idempotent upsert by call id
    and fallback path
        L->>P: no webhook after T -> client pull
        P-->>L: cost
        L->>L: POST-FETCH RE-CHECK<br/>did the webhook land meanwhile?
        L->>L: reconcile, never double-count
    end
    L->>L: price via getRateCard()
```

## 4. Fail closed — the same habit, three places

```mermaid
flowchart TB
    W["FAIL CLOSED 1<br/>webhook verification"] --> W1{secret configured?}
    W1 -->|no, in production| W2["503 REFUSE"]
    W1 -.->|the bug: skip verification| W3[open endpoint]
    T["FAIL CLOSED 2<br/>tenant scope"] --> T1{tenant resolved?}
    T1 -->|no| T2["sentinel: NO rows"]
    T1 -.->|the bug: no filter| T3["every tenant's data"]
    E["FAIL CLOSED 3<br/>eval gate"] --> E1{ground truth exists?}
    E1 -->|no| E2["BLOCK"]
    E1 -.->|the bug: n/a counts as pass| E3["green board, shipped regression"]
```

Solid arrows are what the code does; dashed arrows are the plausible shortcut and what it
costs. Same shape three times over: when the answer is unknown, deny. A habit, not a one-off.

## 5. One rate card

#### Two copies — always diverge

```mermaid
flowchart LR
    B1[(billing logic<br/>rate table A)] --> B2[charge customer]
    B3[(dashboard<br/>rate table B)] --> B4[display to customer]
    B2 -.->|price change updates one| MIS["displayed != billed"]
    B4 -.-> MIS
```

#### One source

```mermaid
flowchart LR
    G1[getRateCard] --> G2[ledger prices the call]
    G1 --> G3[dashboard renders the same rates]
    G2 --> SAME["displayed IS billed<br/>divergence impossible"]
    G3 --> SAME
```

One card makes that class of bug impossible, not unlikely.
