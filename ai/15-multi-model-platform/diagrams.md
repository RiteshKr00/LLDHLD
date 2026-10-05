# Multi-model platform — diagrams

## 1. The path, with each component's job

```mermaid
flowchart TB
    C["call site<br/>sends a FEATURE name, not a model name"] --> GW["Gateway<br/>prevents: call sites coupling to provider SDKs"]
    GW --> REG{"Capability registry<br/>tools, context, structured output<br/>prevents: routing a task to a model that cannot do it"}
    REG --> RT{"Router: cascade cheapest CAPABLE first<br/>prevents: frontier prices for easy work"}
    RT --> TB{"Shared token bucket, Redis, atomic<br/>per-second AND per-day<br/>prevents: N instances each admitting the full rate"}
    TB -->|no room| DEG
    TB -->|admitted| CB{"Circuit breaker, per provider<br/>prevents: one sick provider eating every worker"}
    CB -->|open| DEG["Fallback chain, resolved PER FEATURE<br/>prevents: a summariser and a legal answer<br/>degrading identically"]
    CB -->|closed| P["provider call"]
    P --> V{"Validate on receipt<br/>prevents: trusting a model to have<br/>honoured its own contract"}
    V -->|schema fails| RT
    V -->|ok| OUT["response"]
    P -.-> LED[("Usage ledger<br/>prevents: unattributable cost")]
    EV[("Per-model eval + version pin<br/>prevents: a provider changing<br/>the model under you")] -.-> REG
```

Every box names the failure it prevents. That mapping *is* the design — a diagram of the same
boxes without it is the trap.

---

## 2. The trap, made visible

```mermaid
flowchart LR
    L["a plausible component list"] --> L1["gateway -> unattributable cost"]
    L --> L2["router -> provider outage"]
    L --> L3["cache -> tail latency"]
    L --> L4["circuit breaker -> outage, retry amplification"]
    L --> L5["retries + backoff -> nothing named"]
    L5 --> G["3 failure modes with NOTHING against them:<br/>daily quota exhausted,<br/>capability mismatch,<br/>model deprecated"]
    G --> W["writing the table is what finds them.<br/>a diagram never does"]
```

---

## 3. What breaks first is a quota, not capacity

```mermaid
flowchart TB
    D["a normal day"] --> M["per-minute limit 6,000<br/>peak 4,195 - 30% headroom"]
    D --> Y["daily limit 2,000,000<br/>the day wants 3,053,013 - 1.5x"]
    M --> G2["every per-minute dashboard<br/>is green all day"]
    Y --> B["cap blows at 15:36<br/>504 minutes of the day left"]
    B --> N["and it creeps EARLIER week by week<br/>as traffic grows, because the limit does not move"]
    N --> F["alert on PROJECTED exhaustion,<br/>not on the breach - a breach is not actionable"]
```

---

## 4. A cascade is a bet on the escalation rate

```mermaid
flowchart LR
    E1["escalate 10% / 10%<br/>£420 vs £10,000 - saves 96%"] --> OK["the cascade earns its place"]
    E2["escalate 30% / 20%<br/>saves 88%"] --> OK
    E3["escalate 60% / 40%<br/>saves 67%"] --> MEH["thinning out"]
    E4["escalate 90% / 80%<br/>saves 15%"] --> BAD["plus an extra call on EVERY request:<br/>worse latency for almost no saving"]
    BAD --> AL["so instrument the escalation rate per feature<br/>and alert on it - it drifts with prompts,<br/>corpus and traffic mix"]
```

---

## 5. A fallback that cannot do the job

```mermaid
flowchart TB
    F["provider down. fall back."] --> BL{"chain ordered by PRICE<br/>legacy-13b -> mid-70b -> frontier"}
    BL --> A1["tool-calling agent -> legacy-13b<br/>no function calling"]
    BL --> A2["long-doc summary -> legacy-13b<br/>4k context, document truncated"]
    BL --> A3["field extraction -> legacy-13b<br/>no structured output, JSON comes back as prose"]
    A1 --> R["all three return 200"]
    A2 --> R
    A3 --> R
    R --> P2["error rate flat. latency fine.<br/>NOTHING PAGES."]
    P2 --> X["an outage wearing a success code<br/>is worse than an outage"]
    CAP{"chain filtered by CAPABILITY"} --> C1["agent -> mid-70b"]
    CAP --> C2["long doc -> frontier"]
    CAP --> C3["extraction -> mid-70b"]
    CAP --> C4["short classification -> legacy-13b, genuinely fine"]
```

---

## 6. Degradation is per feature, and refuse is a rung

```mermaid
flowchart LR
    S["dashboard summariser<br/>a cheaper model is fine"] --> S1["mid-70b"]
    S1 --> S2["fast-8b"]
    S2 --> S3["last cached answer"]
    S3 --> S4["hide the panel - nobody is harmed"]
    L2b["legal answer<br/>must not degrade"] --> L2a["frontier"]
    L2a --> L2c["REFUSE"]
    L2c --- N2["a confident wrong answer here carries liability.<br/>refusing is the correct product behaviour,<br/>and one global chain cannot express it"]
```
