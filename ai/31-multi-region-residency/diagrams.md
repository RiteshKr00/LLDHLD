# Multi-region residency — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    C["Client request<br/>tenant resolved at the edge"] --> EDGE
    EDGE{"Edge router<br/>reads tenant residency, fail-closed"} -->|regulated EU| EU
    EDGE -->|unrestricted| ANY["nearest healthy region"]
    EU["eu-west stack"] --> EUV[("Vector store<br/>eu-west only")]
    EU --> EUC[("Semantic cache<br/>key: tenant + region + corpus ver")]
    EU --> EUL["LLM endpoint<br/>PINNED to eu-west, version pinned"]
    EU --> EUT[("Telemetry collector<br/>in-region, payload redacted")]
    EUT -->|counts and latencies only| GM["Global metrics<br/>numbers about payloads, never payloads"]
    EU --> EVAL["Per-region eval + gate<br/>own baseline, own model version"]
    EGRESS["Egress policy: eu-west has NO route<br/>to a non-EU endpoint"] -. enforces .-> EU
    CI["CI residency test<br/>reads config, fails the build"] -. gates .-> EU
```

The edge is the only place the routing decision is made. Everything inside a regional box is
local by construction — which is exactly why a leak there is invisible in code review.

---

## 2. Failover: the best practice that is the breach

#### Nearest healthy region — correct everywhere else

```mermaid
flowchart LR
    R["EU tenant request"] --> H{"eu-west healthy?"}
    H -->|no| F["fail over to us-east"]
    F --> S["served, fast, available"]
    S --- X["6,810 of 20,000 requests<br/>crossed a border.<br/>nothing malfunctioned"]
```

#### Residency-aware — degrade in place

```mermaid
flowchart LR
    R2["EU tenant request"] --> H2{"eu-west healthy?"}
    H2 -->|no| G{"tenant regulated?"}
    G -->|no| F2["fail over normally"]
    G -->|yes| L["in-region ladder"]
    L --> L1["1 cache"]
    L1 --> L2["2 second in-region provider"]
    L2 --> L3["3 smaller local model"]
    L3 --> L4["4 queue, honest wait"]
    L4 --> L5["5 refuse, clear reason"]
```

Availability and residency are in direct conflict. Residency wins, so the ladder has to exist
before the incident — one improvised during an outage is cross-region failover with extra steps.

---

## 3. What counts as personal data

```mermaid
flowchart TB
    T["customer text"] --> P["prompt<br/>protected"]
    T --> E["embedding<br/>derived, invertible"]
    P --> CO["completion<br/>protected"]
    CO --> CA["cache entry<br/>holds the completion"]
    P --> TR["trace span attributes<br/>carries both"]
    P --> GS["golden-set sample<br/>copied into a repo"]
    E --- N1["a naive 3-region build routes the PROMPT<br/>correctly and still leaks these four"]
    CA --- N1
    TR --- N1
    GS --- N1
```

Every leaking artefact is a sensible default that shipped before residency was a requirement.
The prompt is the one everybody protects and the least likely to escape.

---

## 4. One eval suite hides three models

```mermaid
flowchart LR
    G["one global suite<br/>average of 3 regions"] --> A["79.2 - PASS"]
    A --- W["ships a regression to eu-west"]
    S1["eu-west  v2024-03  77.8"] --> G
    S2["us-east  v2024-08  80.5"] --> G
    S3["ap-south v2024-06  79.3"] --> G
    S1 --> PR{"per-region gate 78.0"}
    S2 --> PR
    S3 --> PR
    PR -->|eu-west| FAIL["FAIL - blocked"]
    PR -->|us-east, ap-south| OK["PASS - ships"]
```

Same model ID, three rollout states. Providers version by region and rarely announce it, so
parity is an assumption you have to test rather than a property you inherit.

---

## 5. The leak a config test catches

```mermaid
flowchart TB
    CFG["eu-west deploy config"] --> C1["llm_endpoint -> eu-west  OK"]
    CFG --> C2["vector_store -> eu-west  OK"]
    CFG --> C3["semantic_cache -> eu-west  OK"]
    CFG --> C4["eval_bucket -> eu-west  OK"]
    CFG --> C5["otel_collector -> telemetry.global  VIOLATION"]
    C5 --> Y["owned by a different team.<br/>traces do not look like customer data<br/>until you read the span attributes"]
    Y --> FIX["pin in-region, redact at source,<br/>let counts and latencies cross"]
```

Four of five clients regionalised. The test reads **config, not intent**, and fails the build —
which is why it still works after everyone who read the policy has left.

---

## 6. Tenant relocation is a migration, not a flag

```mermaid
flowchart LR
    A1["provision in eu-west"] --> A2["copy corpus"]
    A2 --> A3["RE-EMBED in region<br/>model versions differ"]
    A3 --> A4["discard the old cache"]
    A4 --> A5["move conversation history"]
    A5 --> A6["flip the routing attribute"]
    A6 --> A7["verify us-east holds nothing:<br/>cache, traces in retention, golden samples"]
    A7 --> A8["delete, with evidence"]
    A8 --- Z["step 7 is the one everyone forgets.<br/>the tenant is EU now and their traces<br/>sit in us-east for another 30 days"]
```
