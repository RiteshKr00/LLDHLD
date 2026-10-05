# Guardrails and content safety — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    U["Caller: voice turn or chat<br/>custom-LLM webhook, tenant resolved"] --> IN
    IN["Input guard, under 20 ms<br/>injection patterns, abuse, scope"] --> GR
    IN -. blocked .-> DEF
    GR["Grounding: approved corpus only<br/>persona brief, published statements"] --> GEN
    GEN["Model, streamed<br/>system prompt advisory, NOT the control"] --> SEG
    SEG["Segment buffer: hold to a clause<br/>nothing reaches TTS unchecked"] --> RUL
    RUL{"Deterministic rules, 0.4 ms<br/>banned entities, claim patterns"} -->|match| BLK
    RUL -->|clean| CLS
    CLS{"Classifier, banded by severity tier<br/>block / deflect / allow"} -->|allow| OUT
    CLS -->|band| DEF
    CLS -->|score over 0.95| BLK
    BLK["Hard block<br/>rule id or score recorded"] --> DEF
    DEF["Graceful deflection<br/>points at the official statement"] --> OUT
    OUT["Emit segment to TTS or client"] --> U
    OUT -. async .-> LOG[("Hash-chained decision log<br/>input, output, verdict, policy version")]
    LOG --> REV["Sampled review + rule promotion<br/>and the per-persona kill switch"]
```

Read it as one turn. Three refusal points, deliberately different: the input guard drops
instructions before they reach the model, the rules stop the enumerated classes at zero
latency, and the classifier's band becomes a *deflection* rather than an error. Everything
after `OUT` is off the critical path — the log write must never hold up audio.

---

## 2. Where enforcement lives — the trap and the fix

#### Prompt-level: advisory, and one line defeats it

```mermaid
flowchart LR
    S["system prompt<br/>never discuss competitors"] --> M["model"]
    U["user: ignore previous instructions"] --> M
    M --> O["output mentions the competitor"]
    O --- X["the rule was INPUT to the component<br/>you are trying to constrain.<br/>injection, drift, or plain helpfulness"]
```

#### Enforced: the model does not get a vote

```mermaid
flowchart LR
    S2["system prompt<br/>still there, still useful"] --> M2["model"]
    U2["user: ignore previous instructions"] --> M2
    M2 --> E{"output rules + classifier<br/>run OUTSIDE the model"}
    E -->|hit| D["deflection ships instead"]
    E -->|clean| P["output ships"]
```

The system prompt stays — it raises the base rate of good behaviour cheaply. It just stops
being the thing you rely on. Same argument as authz: policy is evaluated in the request path,
not requested politely from the caller.

---

## 3. The banded decision, and why tiering exists

```mermaid
flowchart TB
    O["model output segment"] --> R{"deterministic rule hit?"}
    R -->|yes| HB["HARD BLOCK<br/>rule id in the log, provable"]
    R -->|no| T{"which severity tier<br/>does this surface touch?"}
    T -->|"T1: legal, financial, defamation"| P["paranoid point<br/>deflect at the 98.75% recall mark"]
    T -->|"T2: competitor, internal info"| B["balanced point<br/>deflect from 0.60"]
    T -->|"T3: tone, register"| L["log only<br/>fix the persona brief instead"]
    P --> S{"classifier score"}
    B --> S
    S -->|"over 0.95"| HB
    S -->|"in the band"| DF["DEFLECT<br/>a dull answer, not an outage"]
    S -->|"below"| AL["ALLOW"]
    L --> AL
```

The band is the whole trick: containment is identical to a single threshold, but the mass of
false positives lands on *deflect* instead of *block*. Tiering is the second trick — one global
threshold forces a choice between 60 escapes a day and 57,000 blocked answers, and severity
tiers refuse that choice by applying the expensive point only to the narrow T1 surface.

---

## 4. Streaming to TTS — the bug and the gate

#### Checked at stream close: already spoken

```mermaid
flowchart LR
    C1["chunk 1"] --> TTS["TTS, audible immediately"]
    C2["chunk N: the damaging clause"] --> TTS
    TTS --> CK["check runs when the stream closes"]
    CK --- Z["verdict arrives after the audio.<br/>there is no retract on speech"]
```

#### Segment gate: buffer to a clause boundary

```mermaid
flowchart LR
    G1["chunks accumulate in a buffer"] --> SB{"clause boundary reached?"}
    SB -->|no| G1
    SB -->|yes| CH{"rules, then classifier<br/>only if the segment is on-surface"}
    CH -->|clean| EM["emit segment to TTS"]
    CH -->|hit| DFL["emit the deflection instead"]
    EM --> G1
```

Cost is one segment of buffering — 8 to 15 tokens, ~200 ms at 50 tok/s — and only on the first
segment, because every later one is checked while the previous is still playing. Chat gets a
cheaper deal: stream optimistically and replace the bubble.

---

## 5. The residual — detected and recoverable, not prevented

```mermaid
flowchart TB
    ESC["residual: ~130 escapes/day that matter<br/>the design target is NOT zero"] --> LOG[("hash-chained decision log")]
    UR["user report or comms escalation"] --> LOG
    LOG --> SMP["sampled review queue<br/>all T1 hits, a daily quota of band items"]
    SMP --> RP["rule promotion<br/>semantic case becomes a deterministic rule"]
    SMP --> GS[("golden set per tier<br/>gates every threshold change in CI")]
    RP --> RULES["rules layer: caught every time, zero FP"]
    GS --> SHADOW["shadow mode, then one-persona canary"]
    SHADOW --> RULES
```

This is the only loop in the design that makes the system better over time, and it is the
justification for the review queue's cost. A promoted rule moves a case from *caught 78% of the
time at a false-positive price* to *caught every time at zero* — which is why the first hour of
an incident is spent shipping a rule, not retraining anything.

---

## 6. Kill switch: a ladder, not a toggle

```mermaid
stateDiagram-v2
    [*] --> FullPersona
    FullPersona --> GroundedOnly: escape detected
    GroundedOnly --> FixedDeflections: a pattern not a one-off
    FixedDeflections --> Off: legal says stop
    GroundedOnly --> FullPersona: rule shipped and verified
    FixedDeflections --> GroundedOnly: rule shipped and verified
    Off --> [*]
```

Scoped per persona, read per turn, not per deploy. A hard `Off` on a live voice product is
often worse than a dull persona, so the ladder exists to give the incident commander a choice
that isn't "outage or risk".
