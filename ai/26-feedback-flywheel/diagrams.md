# The feedback flywheel — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    PROD["production traffic<br/>600k calls/day, 4 features, 500 tenants"]
    CHK["deterministic checkers on 100%<br/>grounding, schema, citations - 93%"]
    CAP["capture hook, off the request path<br/>redact IN PROCESS, fail closed"]
    OUT[("outcome store: 200 B x 600k/day<br/>every call, no text, 13 months")]
    CAND[("candidate store: ~11.5k/day<br/>redacted text, only 39% defective")]
    PRI["priority = calibrated posterior<br/>x novelty x strata deficit"]
    QUOTA["stratified quota + admission bucket<br/>300/day and never more"]
    RQ[["review queue: 3-axis rubric<br/>+ failure tag + corrected output"]]
    LAB[("labelled store: 300/day<br/>10% double-labelled for kappa")]
    NOV["novelty + strata gate<br/>~2% of labels promote"]
    SFT[("the other 98%: SFT and few-shot pool<br/>wants volume, tolerates noise")]
    QUAR["quarantine, 2 weeks<br/>runs nightly, does NOT gate"]
    GS[("golden set, VERSIONED<br/>800 cases at v34, 4 tiers")]
    GATE["eval gate in CI, then deploy<br/>reported as score @ goldenset-v34"]

    PROD --> CHK
    PROD --> CAP
    CHK --> CAND
    CAP --> OUT
    CAP --> CAND
    CAND --> PRI
    OUT -.->|"quarterly: per-signal precision"| PRI
    PRI --> QUOTA
    QUOTA --> RQ
    RQ --> LAB
    LAB --> NOV
    NOV --> QUAR
    NOV -.-> SFT
    QUAR --> GS
    GS --> GATE
    GATE --> PROD
    GATE -.->|"do gate deltas predict the signal?"| OUT
```

Read it as one loop: traffic in at the top, a gated deploy back into traffic at the bottom. Two things
separate it from a logging pipeline. The **outcome store holds every call and no text**, which is what
lets you compute signal rates and calibration weights without keeping a corpus of PII. And there are
**two dotted feedback edges, not one** — calibration teaches the sampler what each signal is worth, and
the correlation check asks whether the gate predicts anything. Cut either and the loop still runs,
still looks busy, and stops being worth running.

---

## 2. What "the user edited it" actually means

```mermaid
flowchart TB
    E["user edited the output<br/>3,300 events/day"]
    Q{"what did the edit mean?"}
    S["style: shorter, our tone,<br/>house terminology"]
    W["wrong: unsupported claim,<br/>bad number, missing citation"]
    POI["train on this and you optimise<br/>for taste. Silent and permanent."]
    C{"did REGENERATE also fire?"}
    L["prior stays at 22%"]
    H["prior jumps past 90%<br/>nobody regenerates 'too long'"]

    E --> Q
    Q -->|"78%"| S
    Q -->|"22%"| W
    S --> POI
    E --> C
    C -->|no| L
    C -->|yes| H
```

The left branch is the trap: four in five edits are preference, and an eval set built from them gates
releases on tone. The right branch is the cheap escape — a second weak signal agreeing costs nothing
and moves the prior further than any single strong signal does.

---

## 3. The sampler: same 30 labels, two very different sets

#### Naive — log thumbs and edits, work the recent ones

```mermaid
flowchart LR
    N1[("~11.5k candidates/day")] --> N2["filter: thumbs_down OR edit<br/>then sort by recency"]
    N2 --> N3["30 labels"]
    N3 --- N4["yield ~22%: four in five are style<br/>t-loud takes 20% on 4% of traffic<br/>voice and extract: near zero cases"]
```

#### Priority — calibrated posterior, novelty, strata

```mermaid
flowchart LR
    P1[("~11.5k candidates/day")] --> P2["posterior from CALIBRATED<br/>per-signal precision"]
    P2 --> P3["x novelty: distance to the<br/>nearest case already held"]
    P3 --> P4["x strata deficit: floor per cell,<br/>cap per tenant at 2x share"]
    P4 --> P5["30 labels"]
    P5 --- P6["yield ~90%, t-loud under 7%<br/>all 4 surfaces, 8 failure modes"]
```

Same budget, same pool, four times as many labels worth having. The cap is not redundant with the
score: the posterior is calibrated globally, so it under-penalises the one tenant whose base click
rate is anomalous.

---

## 4. The review queue is the only queue that cannot autoscale

```mermaid
flowchart TB
    SC["priority score<br/>ranks ~11.5k candidates"] --> AD{"admission policy"}
    AD -->|"uncapped, 450/day"| U["queue grows 150/day<br/>4,500 deep by day 30"]
    U --> US["oldest waits 15 days:<br/>two release cycles<br/>the label describes a dead model"]
    AD -->|"token bucket at 300/day"| B["queue stays near zero"]
    B --> BS["wait under a day<br/>labels describe the LIVE model"]
    US --- LAW["L = lambda W. Capacity is 2 seats<br/>at 90s a case, so 300/day. The score<br/>picks WHICH, never HOW MANY."]
```

Everything else here runs at 0.13 events/second. The constraint is two people, and a queue fed faster
than they drain it does not degrade gracefully — it silently starts producing labels for a model that
no longer exists, and a stale label still counts.

---

## 5. Promotion, quarantine, retirement, versioning

```mermaid
flowchart TB
    L[("1,500 labels/week")] --> G{"novel AND under-represented?"}
    G -.->|"98%"| SFT[("SFT and few-shot pool<br/>volume over precision")]
    G -->|"2%, about 30/week"| Q["quarantine, 2 weeks<br/>nightly, does NOT gate"]
    Q --> R[("regression tier, 420<br/>runs on every gate")]
    MNB[("must-not-break, 260<br/>uniform random from ACCEPTED")]
    ADV[("adversarial, 120<br/>hand-written")]
    GATE["eval gate<br/>must-not-break is a HARD 97%"]
    ARC[("archive tier<br/>monthly only, never per gate")]
    V[("version bump to goldenset-v35<br/>hash into manifest.lock")]

    R --> GATE
    MNB --> GATE
    ADV --> GATE
    R -.->|"passed 3/3 for 8 weeks"| ARC
    GATE --> V
```

Three sources feed the gate and only one comes from the flywheel. **Must-not-break is sampled
uniformly from the accepted class** — the tier that stops a model that refuses everything scoring
brilliantly, and it must be a hard threshold because inside a composite the arithmetic still lets it
through. Retirement is not tidying: without it the pass rate climbs to 98% and the set quietly stops
discriminating.

---
