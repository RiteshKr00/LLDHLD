# Meeting notes — diagrams

## 1. Transcript is the artefact, summaries are derived

```mermaid
flowchart TB
    A["audio, per-participant streams where available"] --> D["Diarise + transcribe<br/>speaker labels, timestamps,<br/>per-segment confidence"]
    D --> T[("TRANSCRIPT - the durable artefact<br/>£180/day, irreversible")]
    T --> EX["Single-pass extraction<br/>12k tokens, 9% of the window"]
    EX --> SC["schema: summary, decisions,<br/>action items, open questions<br/>every list MAY BE EMPTY"]
    SC --> ER{"Entity resolution<br/>attendees first, then topic"}
    ER -->|resolved| OWN["owner assigned"]
    ER -->|ambiguous| FLAG["owner = null<br/>flagged for the organiser"]
    OWN --> V{"quote + timestamp present?"}
    FLAG --> V
    V -->|yes| PUB["publish, linked to the recording"]
    V -->|no| DROP["render as an open question,<br/>not a decision"]
    T -.->|prompt improves next month| EX
    EX --- N["re-running history costs 5% of capture,<br/>because the transcript was kept"]
```

---

## 2. It fits — so do not chunk

```mermaid
flowchart LR
    M["60 min x 150 wpm"] --> W["9,000 words ≈ 12k tokens"]
    W --> F["9% of a 128k window"]
    F --> S["single pass"]
    S --> G["sees the WHOLE meeting:<br/>a decision revisited at minute 50,<br/>a commitment withdrawn later"]
    C["map-reduce over 8 chunks"] --> L["~19% of cross-chunk<br/>relationships lost"]
    L --- X["reach for it at 3+ hours,<br/>and carry a running decisions list<br/>into each chunk"]
```

---

## 3. Diarisation is load-bearing

```mermaid
flowchart TB
    O["overlapping speech,<br/>one room mic"] --> E{"speaker error rate"}
    E -->|2%| R1["783 correct, 17 misattributed"]
    E -->|10%| R2["735 correct, 65 misattributed"]
    E -->|25%| R3["606 correct, 194 misattributed"]
    R3 --> B["a task assigned to someone who<br/>never agreed to it, discovered<br/>in a summary email"]
    B --- W2["worse than a missing item.<br/>the text is right, the attribution is wrong,<br/>and nothing downstream signals it"]
    FIX["per-participant streams"] --> G2["near-perfect separation"]
    FIX2["low confidence -> render UNASSIGNED"] --> G3["a human resolves it in two seconds"]
```

---

## 4. A required list field is an instruction to invent

```mermaid
flowchart LR
    ST["'status update, nothing decided'"] --> S1{"schema"}
    S1 -->|action_items REQUIRED, non-empty| I["invents 2 items"]
    S1 -->|action_items may be empty| Z["returns 0"]
    I --> BAD["fabricated tasks, sent to real people"]
    Z --> OK["'no action items' as a<br/>first-class, expected output"]
    QT["also require a quote + timestamp per item"] --> H["an invented item<br/>has nothing to quote"]
```

---

## 5. Which Dave?

```mermaid
flowchart TB
    Q["'Dave will send the numbers'"] --> A1{"restrict to attendees"}
    A1 -->|one match| R4["Dave Okafor - resolved"]
    A1 -->|several| A2{"disambiguate on topic<br/>vs the directory"}
    A2 -->|one match| R5["resolved by topic"]
    A2 -->|still ambiguous| U["owner = null,<br/>flagged for the organiser"]
    U --- N2["never guess. a task on the wrong Dave's list<br/>is worse than a task on nobody's - the right<br/>Dave does not know it exists"]
```

---

## 6. Where the money is, and why it decides the design

```mermaid
flowchart LR
    TR["transcription £180/day<br/>expensive, irreversible"] --> K["KEEP the output"]
    SU["summarisation £10/day<br/>18x cheaper, repeatable"] --> DI["treat as disposable"]
    K --> RE["prompt improves -> re-run history<br/>for 5% of the original cost"]
    DI --> RE
    ONLY["keep only summaries"] --> LOST["you cannot improve the past.<br/>the capture cost is already spent"]
```
