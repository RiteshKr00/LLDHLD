# Agent production — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    REQ["Request<br/>tenant, conversation id, user turn"] --> RT["Agent runtime<br/>graph exec, thread id is the boundary"]
    RT --> BUD{"Budget gate<br/>steps, cost, per-step and per-run timeouts"}
    BUD -->|"over budget"| ESC["Checkpoint + escalate to a human<br/>stop visibly, never truncate silently"]
    BUD -->|"within budget"| CA["Context assembler<br/>hard token budget, criticals at the edges"]
    MEM[("Memory service, three tiers<br/>recent verbatim, rolling summary,<br/>structured facts that can be deleted")] --> CA
    RAG[("Retrieval<br/>ranked by recency x relevance")] --> CA
    CA --> GW["LLM gateway<br/>one call shape, fallback, cost attribution"]
    GW --> DEC{"answer, or tool call?"}
    DEC -->|"tool call"| TOOL["Tool registry<br/>schemas + scoped credentials"]
    TOOL --> IDEM["Idempotency key<br/>run:step:tool - resume is a no-op"]
    IDEM --> CP[("Checkpointer<br/>state written after EVERY step")]
    CP --> RT
    DEC -->|"answer"| OUT["Response to caller<br/>terminal state recorded"]
    ESC --> OUT
    OUT --> MEM
    RT -.-> TRACE[("Trace store<br/>prompt, chunks, tool calls, observations<br/>sampled and redacted")]
    CP -.-> TRACE
```

Four systems a demo does not have, on one path: an explicit context budget at
the assembler, tiered memory so cost does not grow quadratically, a checkpoint
after every step with an idempotency key on every side-effecting call, and a
trace store that makes step 3 replayable instead of guessable. The loop
`CP --> RT` is the run; everything hanging off it is what makes the run
survivable. Every section below zooms into one box of this picture.

## 2. Tiered memory — why naive resend goes quadratic

#### Naive — resend the whole history

```mermaid
flowchart TB
    N1["turn 1: 200 tok"] --> N2["turn 2: 400"] --> N3["turn 3: 600"] --> NN["turn 200: 40,000"]
    NN --> NC["total = sum(1..n)<br/>QUADRATIC<br/>measured: 4,020,000 tokens"]
```

#### Tiered — bounded per-turn context

```mermaid
flowchart TB
    T1[("recent ~10 turns<br/>VERBATIM")] --> TP["per-turn context<br/>stops growing"]
    T2[("rolling summary<br/>written on a TOKEN<br/>trigger, not per turn")] --> TP
    T3[("structured facts<br/>queryable + DELETABLE")] --> TP
    TP --> TC["LINEAR once the window fills<br/>measured: 430,890 tokens<br/>9.3x cheaper at 200 turns"]
```

Same 200 turns, same conversation: 4,020,000 tokens against 430,890. The whole
difference is whether per-turn context is allowed to keep growing. The third
tier earns its place twice — structured facts are queryable *and* deletable, so
right-to-erasure stays possible; a fact baked into a summary paragraph is
neither.

## 3. The context budget and its drop order

```mermaid
flowchart TB
    W["window = hard cap"] --> A["system + guardrails<br/>NEVER droppable"]
    W --> B["current input<br/>NEVER droppable"]
    W --> C{"remaining budget"}
    C --> D["recent turns - priority 1"]
    C --> E["retrieved chunks - priority 2"]
    C --> F["summary - priority 3, drops FIRST"]
    A --- P["placed at the EDGES:<br/>models attend to start + end<br/>('lost in the middle')"]
    B --- P
    F --> G{"budget exhausted?"}
    G -->|yes| H["DROP it - and LOG it.<br/>silent truncation is how<br/>grounding vanishes with no error"]
```

## 4. The partial-side-effect problem

```mermaid
sequenceDiagram
    participant R as Runtime
    participant CP as Checkpointer
    participant T as Tool (charges money)
    R->>CP: checkpoint step 1
    R->>T: charge(100)
    T-->>R: receipt-1
    Note over R: CRASH before checkpointing step 2
    R->>CP: resume - last good checkpoint is step 1
    alt no idempotency key
        R->>T: charge(100) AGAIN
        T-->>R: receipt-2
        Note over T: DOUBLE-CHARGED<br/>'resume' is now more<br/>dangerous than 'restart'
    else idempotency key "run-7:step2:charge"
        R->>T: charge(100, key)
        T-->>R: receipt-1 (no-op, first result)
        Note over T: safe to resume
    end
```

## 5. Trajectory vs final-answer evaluation

#### Final-answer scoring — 67 percent, looks acceptable

```mermaid
flowchart TB
    A1["run a: correct"] --> OK1["pass"]
    A2["run b: correct"] --> OK2["pass"]
    A3["run c: wrong"] --> F1["fail"]
```

#### Trajectory scoring — 33 percent, the real picture

```mermaid
flowchart TB
    B1["run a: get_user + get_policy<br/>3 steps"] --> P1["pass"]
    B2["run b: LIST_ALL_USERS + get_policy<br/>9 steps - the SAME RUN<br/>final-answer scoring passed"] --> P2["FAIL - right answer,<br/>wrong path, 3x the steps"]
    B3["run c: get_user only"] --> P3["fail"]
    P2 --> L["a right answer via a wrong path<br/>is a LATENT BUG - it will fail<br/>on the next input"]
```

Run b is the single disagreement between the two blocks, and it is the whole
argument: final-answer scoring called it a pass, trajectory scoring called it a
failure. Measure the p95 of the step-count distribution, not the mean, or run b
averages away.

## 6. What to alert on

#### Lagging — users already suffered

```mermaid
flowchart LR
    L1["error rate"] --> TOO["by now it is an incident"]
    L2["latency"] --> TOO
```

#### Leading — move first

```mermaid
flowchart LR
    E1["avg step count creeping up"] --> ACT["page on these"]
    E2["escalation rate rising"] --> ACT
    E3["repeat-state detections"] --> ACT
    E4["a conditional edge that<br/>suddenly always goes one way"] --> ACT
    E5["cost per SUCCESSFUL outcome<br/>catches 'works, costs 3x'"] --> ACT
```

Error rate and latency are the two an agent degrades *without* moving. The five
leading signals all come off the trace store in section 1 — which is why the
trace store is not optional instrumentation, it is the alerting substrate.
