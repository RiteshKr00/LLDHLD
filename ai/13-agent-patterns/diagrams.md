# Agent patterns — diagrams

## 1. The whole system, end to end

One request through a production agent. The rest of this file zooms in on
individual boxes; this is where they sit relative to each other.

```mermaid
flowchart TB
    U["Client request<br/>task, tenant, budget ceiling"] --> GW["Agent gateway<br/>auth, quota, trace id"]
    GW --> RT{"Router<br/>are the steps known in advance?"}
    RT -->|yes| PL["Pipeline, NOT an agent<br/>fixed DAG, cheapest path"]
    RT -->|no| OR["Orchestrator<br/>runs ReAct or plan-and-execute"]
    OR --> ST[("Run state<br/>plan, scratchpad, pinned facts")]
    OR --> TR["Tool runtime<br/>allow-list, schema, tenant scope"]
    TR --> TL["Tools<br/>retrieval, SQL, HTTP, writes"]
    TL --> KB[("Corpus and system of record")]
    TL --> TR
    TR --> OR
    OR --> VC{"Validator<br/>tests, schema, source data"}
    VC -->|"defect found, under bound"| OR
    VC -->|pass| AS["Assembler<br/>consistency gate on pinned facts"]
    AS --> GW
    OR --> OB[("Trace log<br/>per-step tokens, cost, latency")]
```

The two edges that matter: the validator loops back into the orchestrator
(that is reflection, and it is only worth paying for when the validator is
external), and every tool call is brokered by your runtime, never executed by
the model.

## 2. The question that picks the pattern

```mermaid
flowchart TB
    Q{"are the steps known<br/>in advance?"}
    Q -->|YES| P["NOT AN AGENT<br/>write a pipeline.<br/>cheaper, faster, testable"]
    Q -->|no| A{"is there a verifiable<br/>success signal?"}
    A -->|yes| R["Reflection<br/>bounded rounds"]
    A -->|no| B{"can the steps be<br/>enumerated up front?"}
    B -->|yes| PE["Plan-and-execute<br/>inspectable plan, parallel steps"]
    B -->|no| RE["ReAct<br/>adaptive, most expensive"]
    Q -->|"wide, INDEPENDENT fan-out"| MA["Multi-agent<br/>+ consistency gate"]
```

## 3. ReAct vs plan-and-execute — the cost shape

#### ReAct — one model call per step

```mermaid
flowchart TB
    R0["ReAct loop<br/>1 model call PER STEP, history resent"] --> R1[think]
    R1 --> R2[act]
    R2 --> R3[observe]
    R3 --> R4[think]
    R4 --> R5[act]
    R5 --> R6[observe]
    R6 --> R7[answer]
    R7 --- RC["measured: 4 calls / 25 tokens<br/>tokens grow FASTER than steps"]
```

#### Plan-and-execute — one plan, then N steps

```mermaid
flowchart TB
    P0["Plan-and-execute<br/>1 plan call + N cheap steps"] --> P1[plan once]
    P1 --> PA{"inspect / log / approve<br/>BEFORE spending"}
    PA --> P2[step A]
    PA --> P3[step B]
    PA --> P4[step C]
    P2 --> P5[assemble]
    P3 --> P5
    P4 --> P5
    P5 --- PC["measured: 1 call / 5 tokens<br/>steps can run in PARALLEL"]
```

Same task, same tools. ReAct pays a model call per step and resends the whole
transcript each time, so tokens grow faster than steps. Plan-and-execute pays
once up front, and the plan is inspectable before you spend anything on it.

## 4. Reflection only works with an external signal

```mermaid
flowchart TB
    G[generate draft] --> S{"critic input"}
    S -->|"SAME model, no new info"| N["agrees with itself<br/>0 revisions<br/>you paid for a reword"]
    S -->|"deterministic validator<br/>tests / schema / source data"| Y["real defect found<br/>-> revise -> re-check"]
    Y --> L{"still failing?"}
    L -->|"yes, under bound"| Y
    L -->|no| OK["ship"]
    N --- T["measured: invented '90%'<br/>SURVIVED self-critique,<br/>was REMOVED by the validator"]
```

## 5. The multi-agent failure nobody mentions

```mermaid
flowchart TB
    C[("shared corpus<br/>adult n=430<br/>adolescent n=112")] --> W1["narrative agent<br/>fan-out worker"]
    C --> W2["table agent<br/>fan-out worker"]
    W1 --> A1["retrieves ADULT cohort<br/>individually CORRECT"]
    W2 --> A2["retrieves ADOLESCENT cohort<br/>individually CORRECT"]
    A1 --> D[assembled document]
    A2 --> D
    D --> X["SELF-CONTRADICTING<br/>every section right,<br/>the document wrong"]
    C --> PF[("PINNED-FACTS CONTRACT<br/>cohort = adult")]
    PF -.->|"forces both workers<br/>onto one subject"| W1
    PF -.-> W2
    PF --> OK["consistent=True"]
```

## 6. Tool use — the model requests, your code decides

```mermaid
sequenceDiagram
    participant M as Model
    participant R as Your runtime
    participant T as Tool
    M->>R: REQUEST call_tool("get_user", id=42)
    Note over M,R: the model never executes anything
    R->>R: is the tool allow-listed?
    R->>R: does the schema validate?
    R->>R: is it in the caller's tenant scope?
    R->>R: side effects? attach an idempotency key
    R->>T: execute (least-privilege credential)
    T-->>R: result
    R-->>M: observation
    Note over R: a destructive tool gets a<br/>dry-run mode and a confirmation
```
