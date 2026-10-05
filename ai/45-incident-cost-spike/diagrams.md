# The cost spike — diagrams

## 1. The bisection

```mermaid
flowchart TB
    S["spend is 5x normal.<br/>nothing was deployed."] --> D{"FIRST: spend / calls<br/>thirty seconds, before any dashboard"}
    D -->|volume up, £/call flat| V["VOLUME"]
    D -->|volume flat, £/call up| C["COST PER CALL"]
    D -->|both moved| B["two things, or a routing change<br/>that also retries"]
    V --> V1["cache hit-rate collapse"]
    V --> V2["agent with no step budget"]
    V --> V3["retry storm"]
    V --> V4["a scraper"]
    C --> C1["prompt got longer<br/>- often MORE CHUNKS, not an edit"]
    C --> C2["output got longer"]
    C --> C3["router shifted to a pricier model"]
    C --> C4["provider price change"]
    V1 --- N["every one of these produces the same 5x.<br/>they are not the same problem."]
```

---

## 2. None of them needed a deploy

```mermaid
flowchart LR
    ND["'nothing was deployed'"] --> E["eliminates exactly one cause"]
    E --> L["cache key changed by a RE-INDEX"]
    E --> L2["a TTL expired en masse"]
    E --> L3["provider got slower, so everything RETRIED"]
    E --> L4["cheap provider circuit-broke, fallback engaged"]
    E --> L5["retrieval returned more chunks"]
    E --> L6["the vendor raised prices"]
    L6 --- Z["config, data, or somebody else's infrastructure"]
```

---

## 3. The cache disguises itself

```mermaid
flowchart LR
    H["hit rate 78% -> 5%"] --> P["calls to the provider<br/>220k -> 950k"]
    P --> B2["4.3x the bill"]
    B2 --> D2["identical USER traffic"]
    D2 --> M["on the provider dashboard this is<br/>indistinguishable from a traffic surge"]
    M --> A["you spend an afternoon looking for<br/>traffic that never arrived"]
    A --- F["which is why cache hit rate belongs<br/>on the wall, not in a query someone<br/>writes during an incident"]
```

---

## 4. Agent loops hide in the tail

```mermaid
flowchart TB
    NB["no step budget"] --> M2["mean 4.8 steps"]
    NB --> W["worst run 400 steps"]
    NB --> T["p99.9 = 400"]
    M2 --> DASH["a 20% move.<br/>every average-based dashboard<br/>shows a mild uptick"]
    W --> DAM["a handful of non-terminating runs<br/>consume the budget"]
    SB["step budget 8"] --> M3["mean 4.0, worst 8, p99.9 = 8"]
    DAM --- FIX["cap per RUN: steps AND cost.<br/>alert on the tail, never the mean"]
```

---

## 5. Alert on the derivative

```mermaid
flowchart LR
    SP["spike begins, hour 2"] --> R["rate-of-change alert<br/>this hour vs trailing mean"]
    SP --> A2["absolute alert<br/>80% of monthly budget"]
    R --> H2["fires at HOUR 2"]
    A2 --> H20["fires at HOUR 20<br/>- or never, on a quiet month"]
    H20 --- X2["a smoke detector that waits until<br/>the house is 80% burnt"]
    H2 --- Y2["self-calibrating, needs no per-tenant<br/>threshold to maintain, scales to any<br/>number of tenants"]
```

---

## 6. Cap first, diagnose second

```mermaid
flowchart LR
    U["cause unknown, meter running"] --> M4["gateway rate limit to 1.5x normal"]
    M4 --> M5["if £/call: pin the router to the cheap model"]
    M5 --> M6["if volume + agent: drop the step budget"]
    M6 --> INV["now investigate, with the bleeding stopped"]
    INV --- N4["all three are gateway config,<br/>reversible in minutes, and none of them<br/>requires knowing the cause"]
```
