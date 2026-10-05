# Evaluation — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    RUN["eval run trigger<br/>CI on merge, or a manual bake-off"] --> FIXT["frozen fixture<br/>corpus, retrieval, prompts, seed"]
    FIXT --> PIPE["generation pipeline<br/>retrieve, generate, cite, assemble"]
    PIPE --> DR[(generated draft<br/>plus its citation map)]
    DR --> SCORE["scorer harness<br/>runs all 5 metrics per run"]
    GOLD[(gold_facts.yaml<br/>keyed by study id)] --> SCORE
    REF[(536-page reference<br/>split per section)] --> SCORE
    SCORE --> RES[(run results store<br/>scores, seed, commit, study id)]
    RES --> NF["noise floor calibration<br/>3 null-change runs, take the spread"]
    RES --> GATE{"tri-state gate<br/>pass / fail / no-data"}
    NF --> GATE
    GATE -->|pass| SHIP["release candidate<br/>marked shippable"]
    GATE -->|fail| BLK["blocked<br/>diff against last green run"]
    GATE -->|no-data| BLK
    SHIP --> RPT["run report<br/>deltas shown against the noise floor"]
    BLK --> RPT
```

Read the two dangerous joins: `gold_facts.yaml -> scorer` (a key mismatch there
produces n/a, not an error) and `results -> gate` (n/a must reach the gate as a
third state, never as a boolean). Everything else is plumbing.

## 2. Why the gate failed open

```mermaid
flowchart TB
    G[gold_facts.yaml] -->|keyed to WRONG study id| L[lookup]
    L --> NA["result: n/a"]
    NA --> B{"gate modelled as BOOLEAN"}
    B -->|"n/a coerced to pass"| GR["gate GREEN"]
    GR --> SH["regressed enrollment figure SHIPPED<br/>under 'all hard gates pass'"]
    NA --> T{"gate modelled as TRI-STATE"}
    T -->|"no-data = BLOCK"| RD["gate BLOCKS<br/>the correct behaviour"]
```

## 3. Noise floor before comparison

#### Step 1 — null change, three runs

```mermaid
flowchart LR
    A["qwen2.5 run 1: F1 0.675"] --- B["run 2: 0.677"]
    B --- C["run 3: 0.677"]
    C --> S["spread = 0.002<br/>THE NOISE FLOOR"]
```

Nothing changed between the three runs. Whatever moved is the harness talking to
itself, not the system.

#### Step 2 — compare models against that floor

```mermaid
flowchart LR
    D[model A] --> R{"delta > 0.002?"}
    E[model B] --> R
    S["noise floor = 0.002<br/>carried in from step 1"] --> R
    R -->|yes| REAL[a real difference]
    R -->|no| NOISE["noise — do NOT act on it"]
```

Step 1 has to be run first. Without the floor, step 2's diamond has no threshold
and every wobble looks like a result.

## 4. Controlled bake-off — one variable

```mermaid
flowchart LR
    HELD["HELD CONSTANT<br/>identical in all 4 runs"] --> H1[retrieval]
    HELD --> H2[prompts]
    HELD --> H3[embeddings]
    HELD --> H4[corpus]
    IX[(already-indexed corpus<br/>NEVER re-indexed)] --> H4
    H1 --> GEN[generate]
    H2 --> GEN
    H3 --> GEN
    H4 --> GEN
    V1["THE ONLY VARIABLE<br/>generation model x4"] --> GEN
    GEN --> CITE[cite]
    CITE --> ASM[assemble]
    ASM --> SC[score vs 536-page reference]
    SC --> F["finding: all 4 within ~1 point<br/>-> the model was not the bottleneck<br/>-> retrieval was"]
```

Four inputs pinned, one swapped. Re-indexing the corpus between runs would have
made the whole comparison meaningless.

## 5. Five metrics, five failure modes

```mermaid
flowchart TB
    D[generated draft] --> M1["structural conformance<br/>catches: wrong shape"]
    D --> M2["reference resolution 185/185<br/>catches: invented citations"]
    D --> M3["numeric support 96.8% (gate 98)<br/>catches: unsupported numbers"]
    D --> M4["section coverage<br/>catches: missing sections"]
    D --> M5["per-section similarity<br/>catches: wrong content"]
    M5 --> FIX["was draft-vs-whole-536-page-PDF<br/>-> cosine 0.087 = noise<br/>-> fixed by scoring per section"]
```
