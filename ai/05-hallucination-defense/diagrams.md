# Hallucination defence — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    REQ["Generation request<br/>feature, tenant, stakes tier"] --> RET["GROUNDING — retrieve first<br/>supply facts, don't ask for recall"]
    SRC[("Source of truth<br/>rows, chunks, vector index")] --> RET
    RET --> PB["Prompt assembly<br/>source facts, citations, schema"]
    PB --> GEN["LLM generate<br/>provider-enforced structured output"]
    GEN --> L1{"LAYER 1 — deterministic validator<br/>schema, numeric grounding, ranges<br/>100 percent of traffic, cost zero"}
    L1 -->|fail| RJ["reject<br/>log the reason, bounded retries"]
    L1 -->|pass| TIER{"stakes router and sampler<br/>high stakes, borderline, or sampled?"}
    TIER -->|low stakes, sampled out| SHIP["ship to caller<br/>record which layers ran"]
    TIER -->|high stakes or flagged| L2{"LAYER 2 — maker-checker LLM<br/>fed the source rows, must justify<br/>catches misleading and off-tone"}
    SRC --> L2
    L2 -->|fail| RJ
    L2 -->|pass| SHIP
    L2 -.->|checker unavailable| HQ["human review queue<br/>block high stakes, never skip silently"]
    RJ -->|retry budget left| PB
    RJ -->|budget spent| HQ
    HQ --> SHIP
    RJ --> LOG[("metrics and rejection log<br/>catch rate, escaped-defect rate")]
    SHIP --> LOG
```

Three defences on one path: grounding before generation, free deterministic
checks on everything, and a model only on what survives and is worth the tokens.
The rejection log is not decoration — a rejection nobody reviews is just a bin,
and a *drop* in the validator's rejection rate usually means the validator broke.
Every section below zooms into one box of this picture.

## 2. Three layers, three jobs

```mermaid
flowchart TB
    S[(source data / retrieved chunks)] --> G["GROUNDING — preventative<br/>inject facts so the model<br/>needn't invent"]
    G --> M[LLM generates]
    M --> V{"VALIDATION — deterministic<br/>schema? numbers in source?<br/>ranges? forbidden strings?"}
    V -->|fail| RJ[reject / regenerate<br/>cost: zero]
    V -->|pass| C{"VERIFICATION — maker-checker LLM<br/>misleading? contradictory?<br/>wrong tone?"}
    C -->|fail| RJ2[reject / flag]
    C -->|pass| OUT[ship]
```

## 3. Why this order

#### Right — cheap infallible layer first

```mermaid
flowchart LR
    A1["100 outputs"] --> A2["validator: free, exact<br/>cannot hallucinate"]
    A2 -->|30 rejected| A3["cost 0"]
    A2 -->|70 pass| A4["LLM check: 70 calls"]
```

#### Wrong — expensive fallible layer first

```mermaid
flowchart LR
    B1["100 outputs"] --> B2["LLM check: 100 calls"]
    B2 --> B3["validator rejects 30<br/>you already paid for them"]
```

Same 30 rejections either way. The order decides whether you bought 70 model
calls or 100 — and it decides whether a regex gets to overrule a judgement you
already paid for. At 600k generations a day that gap is the whole cost argument.

## 4. What only a model can catch

```mermaid
flowchart TB
    O["Output: 'Sales grew strongly this quarter'<br/>source rows: +0.4%"] --> V{deterministic validator}
    V --> S1["schema: valid"]
    V --> S2["number 0.4 appears in source: yes"]
    V --> S3["range: sane"]
    S1 --> P[PASSES layer 1]
    S2 --> P
    S3 --> P
    P --> C{maker-checker}
    C --> F["FAILS: 'strongly' misrepresents 0.4%<br/>code has no opinion on 'strongly'"]
```

## 5. Numeric grounding — the false-positive trap

```mermaid
flowchart TB
    T["'...BNT162b2 dosing at 30 ug [REF12]'"] --> A[strip citation tags FIRST]
    A --> B[extract numbers bounded by<br/>non-alphanumerics]
    B --> C{"which digits are salient?"}
    C -->|162, 2 inside BNT162b2| D["NOT salient — part of an identifier"]
    C -->|12 inside REF12| E["NOT salient — chunk id"]
    C -->|30| F["salient — check against cited chunks"]
    F --> G{"supported by ANY cited chunk?"}
    G -->|no| H[drop the sentence before assembly]
    G -->|yes| I[keep]
```
