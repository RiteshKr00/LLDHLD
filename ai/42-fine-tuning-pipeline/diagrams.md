# Fine-tuning pipeline — diagrams

## 1. The pipeline, with the gate in the middle

```mermaid
flowchart TB
    J{"Justify: format, style, latency, cost?<br/>or KNOWLEDGE?"} -->|knowledge| RAG["stop. use retrieval.<br/>a fine-tune cannot be updated,<br/>cannot cite, fails silently"]
    J -->|format / style / latency / cost| SPLIT["fix the eval set and<br/>held-out split FIRST"]
    SPLIT --> BASE["score the strongest<br/>PROMPTED baseline"]
    BASE --> CUR["curate: source, label, dedup,<br/>near-duplicate detect,<br/>DECONTAMINATE by normalised hash"]
    CUR --> VER[("version the dataset<br/>content-hashed, immutable")]
    VER --> TR["train LoRA<br/>3.5 GPU-hours, about £7"]
    TR --> EV{"evaluate"}
    EV --> T1["task metric"]
    EV --> T2["general-capability regression suite"]
    T1 --> G{"GATE: beats the baseline on a NAMED axis<br/>AND no capability regression"}
    T2 --> G
    G -->|fail| BACK["do not ship.<br/>losing to a good prompt is a normal outcome"]
    G -->|pass| SRV["vLLM + adapter, behind the<br/>OpenAI-compatible gateway"]
    SRV --> CALL["call sites address a TASK NAME<br/>and never learn a fine-tune exists"]
    PROMPT[("prompted path kept LIVE<br/>- this is the rollback")] -.-> CALL
```

---

## 2. Where the effort goes, against where people plan for it

```mermaid
flowchart LR
    E["the real split"] --> D1["data: source, label 34%"]
    E --> D2["clean, dedup, decontaminate 26%"]
    E --> D3["eval set + baseline 20%"]
    E --> D4["TRAINING 6%"]
    E --> D5["serving and rollout 14%"]
    D4 --> C["about £7, 3.5 GPU-hours"]
    C --- X["the plan people arrive with<br/>allocates the time the other way round,<br/>and slips in the phase nobody budgeted"]
```

---

## 3. Contamination does not look like a bug

```mermaid
flowchart TB
    L["250 of 500 eval examples<br/>also in the training set"] --> M["model memorises them"]
    M --> R["reported score 85.2%"]
    R --> T["true skill 71.0%"]
    T --> W["+14 points of inflation"]
    W --> N["nothing looks wrong:<br/>the split WAS made,<br/>the numbers DID go up,<br/>the model IS better at what it memorised"]
    S["small leak: 25 of 500"] --> SM["+2.2 points"]
    SM --> NO["smaller than a single eval's<br/>~2 point standard error.<br/>you cannot see it in the numbers -<br/>you have to hash-check for it"]
```

---

## 4. The baseline is a gate you are allowed to fail

```mermaid
flowchart LR
    P1["prompted zero-shot  68%"] --> CMP{"compare"}
    P2["prompted 8-shot  79%"] --> CMP
    P3["prompted + stronger model  86%"] --> CMP
    FT["fine-tuned 7B  83%"] --> CMP
    CMP --> LOSE["the fine-tune LOSES on quality"]
    LOSE --> ASK{"which axis were you buying?"}
    ASK -->|quality| STOP2["do not ship"]
    ASK -->|cost per call, or p99 at volume| PROVE["ship - but argue it on THAT axis,<br/>and prove the trade"]
```

---

## 5. Catastrophic forgetting is invisible to the task metric

```mermaid
flowchart TB
    FT2["fine-tuned candidate"] --> TM["the tuned task<br/>66% -> 93%  +27"]
    FT2 --> G1["instruction following<br/>82% -> 61%  -21"]
    FT2 --> G2["multi-turn coherence<br/>79% -> 55%  -24"]
    FT2 --> G3["refusing out-of-scope<br/>88% -> 34%  -54"]
    TM --> DASH["every number you were<br/>watching went the right way"]
    G3 --> SAFE["a SAFETY regression,<br/>not a quality one"]
    SAFE --- Z["run the general-capability suite<br/>on every candidate, and treat refusal<br/>behaviour as a hard fail"]
```

---

## 6. LoRA: swappable, and rollback is a pointer flip

```mermaid
flowchart LR
    B[("one base model, 14 GB")] --> A1["adapter: classification  80 MB"]
    B --> A2["adapter: extraction  80 MB"]
    B --> A3["adapter: routing  80 MB"]
    A1 --> S2["3 tasks in 14.24 GB<br/>vs 42 GB for 3 full fine-tunes"]
    REG["production regression"] --> FLIP{"rollback"}
    FLIP --> P4["point the task at the previous adapter,<br/>or at the prompted path"]
    P4 --> SEC["seconds. no deploy. base untouched."]
    SEC --> DATA["and the failing production examples<br/>become eval cases for the next candidate"]
```
