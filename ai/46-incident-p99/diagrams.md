# The p99 blowout — diagrams

## 1. The observation that shapes the investigation

```mermaid
flowchart TB
    O["p99: 3s -> 25s<br/>p50: unchanged"] --> Q{"did p50 move?"}
    Q -->|yes| CAP["CAPACITY: everything queues.<br/>add instances."]
    Q -->|no| SUB["a SUBSET is affected.<br/>adding instances does nothing."]
    SUB --> SL["slice before theorising:<br/>provider? model? tenant? endpoint?"]
    SL --> SH{"tail SHAPE"}
    SH -->|clustered at a round value| AR["arithmetic:<br/>attempts x timeout + backoff"]
    SH -->|smooth stretch| CO["contention or size:<br/>pool exhaustion, prompt length,<br/>retrieval parameters"]
    SH -->|bimodal| TW["two populations:<br/>cache hit/miss, primary/fallback"]
```

---

## 2. Capacity moves the median; a subset does not

```mermaid
flowchart LR
    B["baseline<br/>p50 1.42  p95 3.52  p99 4.98"] --> C["capacity problem<br/>p50 3.40  p95 8.45  p99 11.94"]
    B --> S["2% subset stalls<br/>p50 1.43  p95 3.95  p99 25.00"]
    C --> C2["median rose WITH the tail"]
    S --> S2["median untouched,<br/>tail blown"]
    S2 --- N["this is what we observed.<br/>do not add instances."]
```

---

## 3. Why 25 seconds is a suspiciously round number

```mermaid
flowchart LR
    A["before: 2 attempts x 3s<br/>+ 1s backoff"] --> B2["worst case 7.0s"]
    C3["after: 3 attempts x 8s<br/>+ 2 x 0.5s backoff"] --> D["worst case 25.0s"]
    D --> M["matches the observed p99 exactly"]
    M --- X["both numbers are CONFIG.<br/>multiply attempts by timeout, add backoff,<br/>and see if it lands on your p99 -<br/>two minutes, no profiler"]
```

---

## 4. A blocking call creates a queue, not latency

```mermaid
flowchart TB
    R["32 req/s, 0.9s awaited each"] --> P["pure async<br/>p50 0.90  p95 0.90  p99 0.90"]
    R --> BK["+ 30ms of CPU in the handler<br/>p50 1.19  p95 2.53  p99 2.83"]
    BK --> W["p50 +33%. p99 +215%."]
    W --> Y["awaited I/O OVERLAPS.<br/>CPU does not - it holds the single thread,<br/>so every concurrent request queues behind it"]
    Y --> U["loop utilisation 96%: capacity planning says fine.<br/>at 99% p99 becomes 5.34s.<br/>the cliff is not gradual"]
```

```mermaid
flowchart LR
    T["why it reached production"] --> T1["does not reproduce at low load"]
    T --> T2["does not reproduce with one request"]
    T --> T3["does not reproduce with a CONSTANT arrival rate -<br/>a queue below 100% utilisation<br/>needs bursty arrivals to build"]
    T3 --> LT["which is exactly what a default<br/>load generator does not have"]
```

---

## 5. What the dashboard showed

```mermaid
flowchart LR
    F["2% of requests stall at 25s"] --> M2["mean 2.08s  - moved 27%"]
    F --> P50["p50 1.43s  - unchanged"]
    F --> P95["p95 3.95s  - looks HEALTHY"]
    F --> P99["p99 25.00s - the only signal"]
    P95 --- N2["a 2% failure rate is invisible to every<br/>percentile below the 98th,<br/>which is most dashboards"]
```

---

## 6. The gate

```mermaid
flowchart TB
    D2["deploy"] --> G1{"p50 only"}
    G1 -->|passes| SHIP1["ships the regression"]
    D2 --> G2{"mean latency"}
    G2 -->|passes| SHIP1
    D2 --> G3{"p95"}
    G3 -->|passes| SHIP1
    D2 --> G4{"p99, PER provider and model"}
    G4 -->|FAILS| STOP1["blocked, and the slice is named"]
    D2 --> G5{"error taxonomy:<br/>timeouts counted separately from 5xx"}
    G5 -->|FAILS| STOP1
    D2 --> G6{"load test: tail, under BURSTY concurrency"}
    G6 -->|FAILS| STOP2["the only gate that catches<br/>the async-blocking class"]
```
