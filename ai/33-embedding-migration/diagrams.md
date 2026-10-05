# Embedding migration — diagrams

## 1. The whole migration

```mermaid
flowchart TB
    SRC[("Source of truth<br/>100M chunks")] --> DW{"Dual-write<br/>ON before the backfill starts"}
    DW --> OLD[("Old index<br/>embed-v1 space")]
    DW --> NEW[("New index<br/>embed-v2 space")]
    BF["Backfill job<br/>sharded, checkpointed, idempotent"] --> NEW
    SRC --> BF
    Q["Live query"] --> RC{"One retrieval client<br/>index chosen by tenant cutover state"}
    RC -->|all tenants, phase 3| OLD
    RC -. shadow, served to nobody .-> NEW
    OLD --> SERVE["served answer"]
    NEW -. logged .-> CMP["Comparison<br/>recall@k vs INDEPENDENT labels"]
    OLD -. logged .-> CMP
    CMP --> GATE{"parity gate<br/>sliced by tenant and query type"}
    GATE -->|pass| CUT["Progressive cutover<br/>tenant by tenant"]
    GATE -->|fail| HOLD["hold - the old index is still serving"]
    CACHE[("Semantic cache<br/>key includes embedding model version")] -.-> RC
```

Dual-write starts **before** the backfill, or the backfill chases a moving target and never
converges. That ordering is the step most often got wrong.

---

## 2. Why in-place does not exist

```mermaid
flowchart LR
    D["one document"] --> M1["embed-v1"]
    D --> M2["embed-v2"]
    M1 --> V1["vector in space A"]
    M2 --> V2["vector in space B"]
    V1 --- R["cosine between them: 60 of 60<br/>document pairs score under 0.35.<br/>unrelated, not merely different"]
    V2 --- R
```

```mermaid
flowchart LR
    H["half-migrated index<br/>50% space A, 50% space B"] --> S["nearest-neighbour search"]
    S --> N["real similarities and noise<br/>ranked against each other"]
    N --> RES["recall@5 falls 0.68 to 0.41"]
    RES --- W["it does not degrade gracefully.<br/>the two halves cannot be compared at all"]
```

Same dimensionality changes nothing: two 768-dimension spaces are exactly as incomparable as a
768 and a 1536.

---

## 3. The backfill, and the hour-20 failure

```mermaid
flowchart LR
    A["28 h of work"] --> B{"dies at hour 20"}
    B -->|no checkpoints| C["restart from zero<br/>48 h total, API paid twice"]
    B -->|checkpoint every 1M| D["resume at last offset<br/>28 h total"]
    D --- E["resumability is not an optimisation<br/>on a job this long - it is the<br/>difference between finishing this week"]
```

---

## 4. The labelled set, and the circular version of it

#### Circular — labels from the index under test

```mermaid
flowchart LR
    O["old index top-5"] --> L["used as ground truth"]
    L --> SC{"score both indexes"}
    SC -->|old| P["1.000 by construction"]
    SC -->|new| Q2["always lower"]
    Q2 --> X["gate rejects every upgrade, forever"]
```

#### Independent — labels from neither

```mermaid
flowchart LR
    H2["human judgements, click data,<br/>or a lexical relevance proxy"] --> L2["ground truth"]
    L2 --> SC2{"score both indexes"}
    SC2 -->|old| P2["0.312"]
    SC2 -->|new| Q3["0.297"]
    Q3 --> D2["delta -0.015 - a result you can act on"]
```

---

## 5. The cache, full of the previous universe

```mermaid
flowchart TB
    CU["cutover completes"] --> K{"cache key shape"}
    K -->|tenant + query| U["HIT<br/>answer grounded in OLD-space retrieval"]
    U --> BAD["served indefinitely.<br/>hit rate stays high, so nothing looks wrong"]
    K -->|tenant + query + model version| V["MISS<br/>recompute in the new space"]
    V --> GOOD["cutover invalidates the cache for free.<br/>budget one brief cost spike"]
```

The quietest failure in the migration: nothing errors, latency improves, and every answer is
from the world before the change.

---

## 6. Rollback is a routing change, while both indexes exist

```mermaid
flowchart LR
    T["tenant recall drops 8%"] --> R2{"old index still exists?"}
    R2 -->|yes| F["flip routing back<br/>seconds, free, no data movement"]
    R2 -->|no| G["another 28-hour backfill"]
    F --> I["investigate: corpus vocabulary,<br/>query shape, or chunk size"]
    I --> J["fix and retry, or leave<br/>that tenant on the old index"]
    J --- K2["a legitimate end state,<br/>available only because you kept it"]
```
