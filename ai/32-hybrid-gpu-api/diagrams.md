# Hybrid GPU + API — diagrams

## 1. The whole platform

```mermaid
flowchart TB
    A["Call site<br/>sends a TASK name, never a model name"] --> GW
    GW{"OpenAI-compatible gateway<br/>one surface over both paths"} -->|frontier quality| API
    GW -->|below crossover| API
    GW -->|above crossover| CAP{"free slot in the pool?"}
    CAP -->|yes| POOL["vLLM pool<br/>continuous batching on"]
    CAP -->|no, saturated or unhealthy| API["API provider<br/>overflow, failover, quality reference"]
    BATCH[("Batch queue<br/>preemptible, strictly lower priority")] --> POOL
    POOL --> OUT["response"]
    API --> OUT
    POOL -. per-task actual £/1k .-> DASH[("Cost dashboard<br/>both paths, side by side")]
    API -. per-task actual £/1k .-> DASH
    EVAL["Per-task parity eval<br/>self-hosted vs API baseline"] -. gates placement .-> GW
```

The gateway routes on **capacity**, not on a static map. A task has a preferred home; whether it
lands there depends on whether there is a free slot. That is what stops you paying for idle
cards, and it is why the API path stays live even for fully migrated tasks.

---

## 2. The arithmetic error at the centre of the trap

#### A ratio

```mermaid
flowchart LR
    R["GPU £0.00033 per 1k<br/>API £0.0009 per 1k"] --> C["GPU is 3x cheaper per token"]
    C --> D["therefore self-host"]
    D --- X["true premise, wrong unit"]
```

#### A product

```mermaid
flowchart LR
    T["task: 500M tokens per month"] --> A2["API: 500M x £0.0009<br/>= £450"]
    T --> G2["GPU: £1,460 card + £1,800 ops<br/>= £3,260, used at 11%"]
    A2 --> W["API wins by 7x"]
    G2 --> W
    W --- Y["you bought a whole card<br/>and filled a tenth of it"]
```

Per-token price is a ratio; the bill is a product. Only one of them arrives at the end of the
month.

---

## 3. Utilisation is the business case

```mermaid
flowchart LR
    U1["5%<br/>£0.01034 per 1k"] --> D1["DEARER than the API"]
    U2["20%<br/>£0.00258"] --> D1
    U3["40%<br/>£0.00129"] --> D1
    U4["70%<br/>£0.00074"] --> D2["cheaper"]
    U5["95%<br/>£0.00054"] --> D2
    D1 --- N["you need north of 50% sustained<br/>before the card beats the API at all"]
```

Interactive traffic is spiky, so you size for the peak and idle through the trough. A fleet
serving interactive only will struggle past 40%. The same fleet with a batch queue behind it
clears 80% — which is why batch work, not a better GPU, is the real unlock.

---

## 4. Continuous batching, and where the waste is

```mermaid
flowchart TB
    S["static batching<br/>wait for 8 slots or a timeout"] --> S1["1 concurrent request<br/>300 tokens/s"]
    S1 --> S2["7 of 8 slots idle<br/>while the card bills anyway"]
    C1["continuous batching<br/>slots refill as sequences finish"] --> C2["1 concurrent request<br/>1,035 tokens/s"]
    C2 --> C3["3.5x, and the gap closes<br/>as concurrency rises"]
    S2 --- Z["low concurrency is exactly the regime<br/>a first self-hosting attempt runs in"]
```

---

## 5. Placement is a table, not a verdict

```mermaid
flowchart TB
    Q{"per task"} -->|needs frontier quality| API2["API at any volume"]
    Q -->|below 3.6B tokens per month| API2
    Q -->|above crossover, latency-tolerant| SELF["self-hosted"]
    SELF --> EX1["classify tickets  14.0B"]
    SELF --> EX2["summarise calls    6.2B"]
    API2 --> EX3["extract from PDFs  3.1B  below crossover"]
    API2 --> EX4["draft replies      0.9B  frontier"]
    API2 --> EX5["rerank             0.3B  below crossover"]
    EX1 --> RES["all-API £22,374  ->  hybrid £13,294<br/>41% saving, ops included"]
```

Two of six tasks move. That ratio is normal, and an answer claiming otherwise has not done the
arithmetic.

---

## 6. Migrating a task, with a way back

```mermaid
flowchart LR
    M1["offline parity eval"] -->|fails| STOP["stop - do not migrate"]
    M1 -->|passes| M2["shadow: both paths,<br/>serve the API answer"]
    M2 --> M3["canary a percentage"]
    M3 --> M4["ramp, API overflow live"]
    M4 --> M5["reconcile ACTUAL £/1k<br/>against the projection"]
    M5 --- W2["step 5 is the one that gets skipped<br/>and the only one that says<br/>whether the project worked"]
```
