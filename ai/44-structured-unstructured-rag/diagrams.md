# Structured + unstructured RAG — diagrams

## 1. Two paths, one answer

```mermaid
flowchart TB
    Q["'is Acme past their refund window on order 4471?'"] --> PL{"Planner<br/>docs / db / both - and decompose"}
    PL -->|docs| D1
    PL -->|db| S1
    PL -->|both| D1["Document path<br/>vector RAG + relevance floor"]
    PL -->|both| S1["Structured path<br/>text-to-SQL, ALL of scenario 21's guards"]
    D1 --> DR["clause + document version + section"]
    S1 --> SR["rows + the SQL + row count + 'as of 14:05'"]
    S1 -.->|user's OWN credentials| DB[("live database - NEVER embedded")]
    DR --> SY{"Synthesis"}
    SR --> SY
    SY --> CF{"do the sources conflict?"}
    CF -->|yes| BOTH["surface BOTH, marked, and route<br/>to whoever owns the discrepancy"]
    CF -->|no| ANS["answer with PER-SOURCE attribution<br/>and the arithmetic shown"]
    FAIL["one path unavailable"] -.-> PART["explicitly partial answer,<br/>never a silent omission"]
```

---

## 2. Why you cannot embed the rows

```mermaid
flowchart LR
    Q2["'how much did acme spend?'"] --> V["vector search<br/>returns the k most SIMILAR rows"]
    V --> V2["top 10 sum: 5,017<br/>= 7% of the answer"]
    Q2 --> S2["SQL over all 169 matching rows"]
    S2 --> S3["76,471"]
    V2 --- X["a similarity search has no notion of ALL.<br/>no SUM, no GROUP BY, no JOIN -<br/>and that is most of what people<br/>ask a database"]
```

```mermaid
flowchart LR
    IX["index built 45 minutes ago"] --> W["6,300 writes since"]
    W --> INV["invisible to the vector index"]
    INV --> BAD["a number that looks current and is not<br/>- the worst failure in this system"]
```

---

## 3. Routing dominates

```mermaid
flowchart TB
    A["routing 100%, retrieval 0.80"] --> R1["end-to-end 0.80"]
    B["routing 80%, retrieval 0.92"] --> R2["end-to-end 0.79"]
    R1 --> W2["perfect routing with WEAK retrieval<br/>beats the reverse"]
    R2 --> W2
    W2 --> WHY["a misrouted question is not degraded,<br/>it is UNANSWERABLE:<br/>semantic search over a table returns nothing,<br/>SQL over prose is not expressible"]
    WHY --> SPEND["so spend on the router<br/>before either retriever"]
```

---

## 4. Attribution is what makes it checkable

```mermaid
flowchart TB
    BL["blended:<br/>'Acme is past their refund window.'"] --> U2["a reader cannot tell which half<br/>came from where, so they cannot<br/>check EITHER half"]
    AT["attributed:"] --> A1["order 4471 shipped 3 March<br/>[database, live]"]
    AT --> A2["window is 30 days from shipment<br/>[policy doc v4, section 2.1]"]
    AT --> A3["therefore closed 2 April<br/>[computed]"]
    A3 --> V3["each fact is separately verifiable,<br/>and the arithmetic is visible"]
```

---

## 5. Conflicts are detected, not resolved

```mermaid
flowchart LR
    P["policy doc: 30 days"] --> C{"synthesis"}
    D["system of record: 45 days"] --> C
    C -->|model adjudicates| SIL["ships '30 days'.<br/>a bug BURIED"]
    C -->|surface both| CON["CONFLICT: policy says 30,<br/>system of record says 45"]
    CON --> OWN["routed to whoever owns<br/>the discrepancy"]
    OWN --- N["the model does not know whether the policy<br/>is aspirational, the database misconfigured,<br/>or there is a negotiated exception"]
```

---

## 6. Partial failure is the normal case

```mermaid
flowchart TB
    ST{"which sources are up?"} -->|both| F["full answer, both attributions"]
    ST -->|database down| DB2["policy answer<br/>+ 'live order data unavailable'<br/>and NO guess at the figure"]
    ST -->|documents down| DC["the figures<br/>+ 'policy text unavailable,<br/>so the rule is not applied'"]
    ST -->|both down| RF2["refuse, and say which"]
    DB2 --- N6["the dangerous version is an answer built<br/>on half the evidence that reads<br/>as though it had all of it"]
```
