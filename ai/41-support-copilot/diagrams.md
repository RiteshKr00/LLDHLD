# Support copilot — diagrams

## 1. The request path

```mermaid
flowchart TB
    T["incoming ticket"] --> IC{"intent classification"}
    IC -->|cancellation, complaint, legal| ESC
    IC -->|handleable| R["retrieve from KB<br/>with a relevance floor"]
    R -->|nothing above the floor| ESC
    R --> GEN["grounded generation"]
    GEN --> CG{"confidence gate<br/>retrieval strength + groundedness + sentiment"}
    CG -->|below threshold| ESC["ESCALATE with full context"]
    CG -->|above| ANS["answer"]
    ANS --> ACT{"action requested?"}
    ACT -->|within tier| CONF["confirm + idempotency key + amount cap"]
    ACT -->|outside tier| ESC
    HUM["'talk to a person' - visible at EVERY step"] --> ESC
    ESC --> P[("handoff payload:<br/>transcript, actions tried, articles retrieved,<br/>confidence and reason, account state")]
    P --> H["human agent"]
    H --> EV[("escalations become eval cases")]
```

---

## 2. The optimum is interior

```mermaid
flowchart LR
    T0["threshold 0.00<br/>deflect 100%, 14% wrong<br/>saving 14%"] --> W["best dashboard,<br/>not the best outcome"]
    T7["threshold 0.70<br/>deflect 58%, 8% wrong<br/>saving 27%"] --> B["the optimum"]
    T95["threshold 0.95<br/>deflect 3%<br/>saving 2%"] --> N["barely worth shipping"]
    B --- K["neither extreme. the threshold is<br/>a real decision, not a direction to push in"]
```

```mermaid
flowchart LR
    H["handling cost only"] --> G["greedy deflection WINS<br/>- which is why teams build it"]
    C["+ expected churn per wrong deflection<br/>4% x £600 LTV = £24"] --> I["optimum moves INTERIOR"]
    I --- Z["leave the churn term out and the arithmetic<br/>sincerely recommends deflecting everything"]
```

---

## 3. Trapping people is worse than saying no

```mermaid
flowchart TB
    J1["resolved by AI, first answer"] --> C1["CSAT 4.6"]
    J2["not resolved, human offered immediately"] --> C2["CSAT 2.9"]
    J3["not resolved, had to repeat everything"] --> C3["CSAT 1.8"]
    J4["not resolved, could not reach a human"] --> C4["CSAT 1.0"]
    C4 --- X["the escape hatch costs you some deflection<br/>and buys the product's reputation"]
```

---

## 4. Escalation is not the failure — a bad one is

```mermaid
flowchart LR
    E["AI could not resolve it"] --> Q{"how does it hand off?"}
    Q -->|bare transfer| B2["customer starts over<br/>CSAT 1.8"]
    Q -->|full context| G2["human picks up mid-conversation<br/>CSAT 2.9"]
    G2 --- N2["more than a point of CSAT on a ticket<br/>the AI already FAILED.<br/>the fix is context, not accuracy"]
```

---

## 5. Actions: tiered, confirmed, idempotent

```mermaid
flowchart TB
    A["action requested"] --> T2{"which tier?"}
    T2 -->|answer, read state| F["freely"]
    T2 -->|resend receipt| NA["narrowly - idempotent anyway"]
    T2 -->|account credit| CF["explicit confirmation"]
    T2 -->|refund| RF["confirmation + idempotency key<br/>+ amount cap"]
    T2 -->|cancel contract| NV["NEVER - irreversible,<br/>and a retention conversation"]
    RF --> TO{"payment call times out"}
    TO -->|agent retries, with key| ONE["one refund applied"]
    TO -->|agent retries, no key| TWO["TWO refunds applied"]
    TWO --- Y["the retry is correct behaviour.<br/>the key is what makes it safe"]
```

---

## 6. Reopen clustering finds the wrong KB article

```mermaid
flowchart LR
    RO["reopened tickets"] --> CL{"group by the article<br/>that was retrieved"}
    CL --> A1["article 41: reopen rate 4%"]
    CL --> A2["article 88: reopen rate 31%"]
    A2 --> BAD["article 88 is WRONG"]
    BAD --> FIX2["correct it, then proactively<br/>re-answer affected customers"]
    BAD --- N3["it was quietly costing human agents<br/>time long before the AI existed"]
```
