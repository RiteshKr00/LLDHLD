# The fabrication incident — diagrams

## 1. The bisection

```mermaid
flowchart TB
    S["Reports: confident, wrong answers<br/>fine last week"] --> SC{"SCOPE FIRST<br/>all tenants? all surfaces? when exactly?"}
    SC -->|one tenant| T["scoping / namespace / saved config<br/>diff against a healthy tenant"]
    SC -->|all tenants| H1{"1. retrieval returning chunks?<br/>34%, 3 min"}
    H1 -->|no| F1["empty retrieval:<br/>model answers from general knowledge,<br/>equally confident"]
    H1 -->|yes| H2{"2. prompt template changed?<br/>9%, 5 min"}
    H2 -->|yes| F2["unreviewed config change"]
    H2 -->|no| H3{"3. context reaching the prompt?<br/>22%, 8 min"}
    H3 -->|no| F3["assembly bug - THIS ONE"]
    H3 -->|yes| H4{"4. context truncated?<br/>14%, 8 min"}
    H4 -->|yes| F4["character cap - ALSO THIS ONE"]
    H4 -->|no| H5{"5. model version changed?<br/>8%, 15 min"}
    H5 -->|no| H6{"6. corpus changed?<br/>10%, 25 min"}
```

Ordered by **prior divided by cost**, and the rule matters more than the list: it survives
being wrong. The top two hypotheses are over half the probability and eleven minutes of work.

---

## 2. Mitigate before you diagnose

```mermaid
flowchart LR
    U["cause unknown"] --> M1["roll back the most recent config change"]
    M1 --> M2["raise the relevance floor<br/>let it refuse more"]
    M2 --> A["availability down slightly"]
    M2 --> B["fabrications stop"]
    B --- W["a refusal is recoverable.<br/>a fabrication is not.<br/>the trade is deliberate"]
```

---

## 3. The either/or bug

#### Buggy: style replaced the facts

```mermaid
flowchart LR
    P["persona"] --> AS{"body = style OR chunks"}
    ST["saved style"] --> AS
    CH["retrieved facts"] --> AS
    AS -->|style is set| OUT1["prompt: persona + style<br/>zero facts"]
    OUT1 --- X["passed every test:<br/>no staging tenant had a style saved"]
```

#### Fixed: style is a modifier, facts are not optional

```mermaid
flowchart LR
    P2["persona"] --> AS2["persona + style-as-modifier + facts"]
    ST2["saved style"] --> AS2
    CH2["retrieved facts"] --> AS2
    AS2 --> OUT2["prompt: all three, always"]
    OUT2 --- Y["pure function, tested with each input<br/>present and absent - 8 cases"]
```

---

## 4. Why both bugs are invisible

```mermaid
flowchart TB
    B1["assembly drops the facts"] --> WF["prompt is WELL-FORMED"]
    B2["300-char cap cuts a fact in half"] --> WF
    WF --> N1["no error"]
    WF --> N2["no exception"]
    WF --> N3["latency normal"]
    WF --> N4["error rate normal"]
    N4 --> M["every dashboard is green<br/>while the model invents an answer"]
```

---

## 5. Detection: the counterfactual

```mermaid
flowchart LR
    D6["day 6<br/>grounded 93%, refusals 9%"] --> D7["day 7 - fault lands<br/>grounded 61%, refusals 2%"]
    D7 --> AL["groundedness alert fires SAME DAY"]
    D7 --> RF["refusal rate HALVED"]
    RF --> DIS["looks like an improvement<br/>on every dashboard you own"]
    D7 --> D11["day 11 - a user reports it"]
    D11 --> C["4 days of fabrication in production"]
    AL --- Z["the fix was one line.<br/>the cost was the detection lag"]
```

---

## 6. The control set that closes it

```mermaid
flowchart TB
    R["every request"] --> L[("log: prompt version, chunk ids,<br/>model version, truncated y/n")]
    R --> SMP["sample 1-2%"]
    SMP --> J["judge: is each claim supported<br/>by the chunks actually retrieved?"]
    J --> AL2{"drop vs rolling baseline?"}
    AL2 -->|yes| PAGE["page"]
    R --> CNT[("free counters:<br/>empty retrieval, truncation,<br/>chunk count, prompt length")]
    CNT --> AL2
    RR["refusal rate<br/>TWO-SIDED alert"] --> AL2
    CFG["prompt change"] --> GATE{"review + eval gate + canary"}
    GATE -->|pass| ROLL["ramp by percentage"]
    GATE -->|fail| BLOCK["blocked"]
```
