# Multi-model architecture — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CL["client / call site<br/>one call shape, no provider SDKs"] --> GW["gateway<br/>auth, adapters, transport retries"]
    GW --> SC["semantic cache<br/>tenant-namespaced"]
    SC -->|hit| RESP["response to client<br/>validated, cost attributed"]
    SC -->|miss| RT["router<br/>cascade: small first, escalate"]
    REG[("capability registry<br/>models, status, prices")] --> RT
    BUD[("budget + spend state<br/>per tenant, per feature")] --> RT
    RT --> TB["token buckets in Redis<br/>per provider AND per tenant"]
    TB --> CB{"circuit breaker<br/>one per provider"}
    CB -->|closed| PA["primary provider"]
    CB -->|open| PB["secondary or self-hosted"]
    CB -->|all open| DEG["degraded path<br/>defined PER FEATURE"]
    PA --> VAL["validate on receipt<br/>schema, then repair or fail"]
    PB --> VAL
    DEG --> RESP
    VAL --> RESP
    VAL -. async write .-> LED[("usage ledger<br/>one rate card, never in hot path")]
    RESP -. populate .-> SC
```

Read it as one request: cache lookup, then a routing decision fed by the
registry and the budget, then admission control, then a provider chosen by
breaker state, then validation before anything reaches the caller. The ledger
write is the only branch that must never block the response.

## 2. The layers, each named by the failure it prevents

```mermaid
flowchart TB
    C[client] --> SC["semantic cache<br/>PREVENTS: paying twice for one question<br/>(tenant-namespaced)"]
    SC -->|miss| GW["gateway<br/>PREVENTS: every call site knowing every SDK"]
    GW --> REG[("capability registry<br/>PREVENTS: deprecation = 20-file migration")]
    GW --> RT["router<br/>PREVENTS: frontier prices for easy work"]
    REG --> RT
    BUD[("budget state")] --> RT
    RT --> TB["per-provider + per-tenant token bucket<br/>SHARED state in Redis<br/>PREVENTS: 429s and noisy neighbours"]
    TB --> CB{"circuit breaker per provider<br/>PREVENTS: their outage = your outage"}
    CB -->|closed| PA[provider A]
    CB -->|open| PB[provider B]
    CB -->|all open| DEG["degraded path<br/>defined PER FEATURE"]
    PA --> VAL["validate on receipt<br/>PREVENTS: contract drift across models"]
    PB --> VAL
    VAL --> LED[(usage ledger, one rate card<br/>async write, never in critical path)]
```

## 3. The router: cascade, don't jump to the big model

```mermaid
flowchart TB
    R[request] --> CAP{"needs vision / 200k ctx /<br/>function calling?"}
    CAP -->|yes| ONLY["only models with that capability<br/>from the REGISTRY"]
    CAP -->|no| D{difficulty classifier}
    D -->|easy 60-80%| SM["small cheap model"]
    SM --> CONF{"confident?"}
    CONF -->|yes| DONE[return]
    CONF -->|no| BIG[escalate to large model]
    D -->|hard| BIG
    ONLY --> B2{budget state}
    BIG --> B2
    B2 -->|near cap| DOWN["DOWNGRADE, don't cut off"]
    B2 -->|ok| GO[dispatch]
```

## 4. Fallback chain, and what "degraded" means per feature

```mermaid
flowchart TB
    T{task type} --> CH["ordered chain:<br/>primary -> secondary -> self-hosted -> degraded"]
    CH --> RAG["RAG chat degraded =<br/>retrieval-only extractive answer + citations<br/>(no generation, STILL USEFUL)"]
    CH --> SUM["summarisation degraded =<br/>queue it, return 'processing'"]
    CH --> VOI["voice degraded =<br/>fall back to TEXT<br/>(never degrade audio quality)"]
    CH --> EXT["extraction degraded =<br/>FAIL LOUDLY<br/>(a wrong extraction is worse than none)"]
```

## 5. Retry amplification — the trap

#### Retries in BOTH places

```mermaid
flowchart LR
    B1["client retry x3"] --> B2["gateway retry x3"]
    B2 --> B3["9 provider calls<br/>for ONE logical request<br/>-> self-inflicted DDoS"]
```

#### One place per concern

```mermaid
flowchart LR
    G3["worker: business retry<br/>whole task re-runs later"] --> G1["gateway: transport errors only<br/>429 / 5xx / timeout<br/>backoff + JITTER"]
    G1 --> G2[provider]
    G2 --> G4["bounded, observable"]
```

The multiplication is what kills you: retry counts at two layers multiply, they
do not add. Transport retries live in the gateway only; the worker re-runs the
whole task, and never the individual call.

## 6. Model deprecation — the lived one

```mermaid
flowchart TB
    N["provider: model retired in 30 days"] --> S["registry status -> deprecated"]
    S --> R["router stops selecting it<br/>for NEW traffic"]
    R --> E["eval gate: candidates vs golden set<br/>noise floor established FIRST"]
    E --> P{"passes hard gates?"}
    P -->|no| E
    P -->|yes| M["swap behind the GATEWAY<br/>-> call sites unchanged"]
    M --> G["guard: block a stale config value<br/>from reinstating the retired model"]
    G --> C["canary behind a flag<br/>+ guardrail metrics"]
```

## 7. Multi-tenant fairness

#### Global limits only

```mermaid
flowchart TB
    T1["tenant 1: 10k-doc batch"] --> Q1[[one shared queue]]
    T2["tenant 2: 5 chat requests"] --> Q1
    Q1 --> W1[workers]
    T2 -. starved for hours .-> W1
```

#### Per-tenant everything

```mermaid
flowchart TB
    T3[tenant 1] --> B3["per-tenant token bucket"]
    T4[tenant 2] --> B4["per-tenant token bucket"]
    B3 --> QA[[weighted fair queue]]
    B4 --> QA
    QA --> W2[workers]
    B3 --- BD["per-tenant budget + spend breaker"]
    B4 --- BD
    W2 --- NS["per-tenant cache namespace<br/>cross-tenant hit = LEAK, not a perf bug"]
```

A global limit is satisfied by one tenant consuming all of it. Fairness needs
per-tenant buckets, a weighted queue, a per-tenant spend breaker, and a
per-tenant cache namespace — all four, or the batch tenant still wins.
