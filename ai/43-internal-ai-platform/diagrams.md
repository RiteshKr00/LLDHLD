# Internal AI platform — diagrams

## 1. The platform

```mermaid
flowchart TB
    T1["team: support-bot"] --> SDK
    T2["team: search"] --> SDK
    T3["8 more teams"] --> SDK
    SDK["Golden-path SDK<br/>timeouts, retries + jitter,<br/>streaming, tracing - all default"] --> GW
    GW{"Gateway - the mandatory hop"} --> REG{"model registry<br/>approved models only"}
    REG -->|not approved| DENY["blocked at the gateway,<br/>not in a document"]
    REG -->|approved| MW["shared PII + guardrail middleware"]
    MW --> CA[("cost attribution<br/>per team, per feature, per model")]
    CA --> BUD{"budget breaker"}
    BUD -->|over| DEG["DEGRADE: cheaper model,<br/>smaller context, cache-only"]
    BUD -->|within| PROV["provider, via a PER-TEAM key"]
    SEC[("central secrets<br/>per-team credentials")] --> PROV
    EVAL[("eval harness as a service<br/>the component nobody builds alone")] -.->|gates releases| SDK
    ESC["escape hatch: documented,<br/>reviewed, TIME-BOXED"] -.->|bypasses gateway| PROV
    ESC --> RQ[("review queue = the roadmap")]
```

---

## 2. Ten implementations, nine of them wrong

```mermaid
flowchart LR
    D["10 teams x 5 components"] --> W["530 engineer-weeks duplicated"]
    O["built once, properly"] --> W2["106 engineer-weeks"]
    W2 --> S["424 weeks saved"]
    S --> R["but that is NOT the argument"]
    R --> E["9 of those 10 eval harnesses<br/>would never have been built at all"]
    E --- N["teams under delivery pressure skip<br/>the gate, not the feature.<br/>THAT is the platform's value"]
```

---

## 3. The adoption arithmetic

```mermaid
flowchart TB
    B["a team can DIY in 8 weeks"] --> C{"platform onboarding time"}
    C -->|12 weeks, no mandate| X1["0% adoption - all 10 bypass"]
    C -->|12 weeks, WITH mandate| X2["70% - 3 bypass, 7 comply resentfully<br/>+ a queue of exception requests"]
    C -->|2 weeks| X3["100% - and the mandate is redundant"]
    X2 --- Y["a mandate on a slower road buys<br/>partial compliance and shadow usage"]
    X3 --- Z["a faster road needs no mandate.<br/>the policy question stops being interesting"]
```

---

## 4. Attribution changes who the conversation is with

```mermaid
flowchart LR
    F["what finance sees: £49,640"] --> U["unexplainable.<br/>every team equally innocent"]
    U --> BLA["blanket cost-cutting mandate:<br/>annoys ten teams, targets none"]
    A["per-team attribution"] --> A1["support-bot £18,400 - 37%"]
    A --> A2["sales-copilot £11,900 - 24%"]
    A1 --> SP["two teams are 61% of the bill"]
    A2 --> SP
    SP --> CONV["a specific conversation<br/>with two people"]
```

---

## 5. Blast radius

```mermaid
flowchart LR
    K1["one shared provider key"] --> L1["leak -> rotate for everyone<br/>all 10 teams down"]
    K2["per-team keys via the gateway"] --> L2["leak -> revoke one<br/>9 teams unaffected"]
    L2 --- N2["the gateway is what makes per-team keys<br/>possible WITHOUT ten teams each<br/>managing their own secrets"]
```

---

## 6. The escape hatch, three ways

```mermaid
flowchart TB
    E1["no escape hatch"] --> R1["teams route around you silently.<br/>you lose the visibility you built<br/>the platform to obtain"]
    E2["escape hatch, no review"] --> R2["it is the main road within two quarters"]
    E3["escape hatch + review + expiry"] --> R3["legitimate cases proceed"]
    R3 --> R4["and every exception is a feature request<br/>with evidence attached"]
    R4 --> R5["requested three times? build it."]
```
