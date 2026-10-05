# Text-to-SQL — diagrams

## 1. The whole request path

```mermaid
flowchart TB
    Q["English question"] --> SR["Schema retrieval<br/>embed table + column descriptions<br/>top ~6 tables, with foreign keys"]
    SR --> ML{"Metric resolution<br/>named metric, or ask which one"}
    ML -->|ambiguous| ASK["ask the user which definition"]
    ML -->|resolved| GEN["LLM generates SQL<br/>with verified exemplar joins"]
    GEN --> AST{"Parse to an AST<br/>NOT a regex"}
    AST -->|DML, DDL, stacked| REF["refuse, with the reason"]
    AST -->|unknown table or column| REF
    AST -->|clean| EXP{"EXPLAIN<br/>bytes scanned"}
    EXP -->|over threshold| REF2["refuse: 'that scans 4 TB,<br/>please add a date range'"]
    EXP -->|within budget| RUN["Execute under the USER's credentials<br/>read-only connection, LIMIT injected"]
    RUN --> OUT["Answer + SQL + row count<br/>+ metric definition + data freshness"]
    MS[("Metric store<br/>owns definitions AND joins")] --> ML
    CACHE[("Cache: question embedding + metric<br/>+ schema version + permission set")] -.-> RUN
```

The model appears once, in the middle, and is the least interesting box on the page. Everything
that makes the feature safe is retrieval, a definition, a parser or a cost check.

---

## 2. The failure that matters

```mermaid
flowchart LR
    S["SELECT SUM(o.amount)<br/>FROM orders o<br/>JOIN line_items li ON li.order_id = o.id"] --> R["runs cleanly"]
    R --> N["returns 1,075.00"]
    N --> T["true answer 825.00"]
    T --> W["inflated 30%: a 3-item order<br/>counted 3 times"]
    W --- X["no error. no warning. no anomaly.<br/>the number goes into a board deck"]
```

An error is recoverable because somebody sees it. This is worse than an error, and a better
model writes it less often rather than never.

---

## 3. Three revenues, all correct

```mermaid
flowchart TB
    QQ["'what was revenue last month?'"] --> D1["sales: gross order value<br/>825.00"]
    QQ --> D2["analytics: net of refunds<br/>775.00"]
    QQ --> D3["finance: net, shipped only<br/>700.00"]
    D1 --> P{"no metric store"}
    D2 --> P
    D3 --> P
    P --> BAD["the model picks one implicitly.<br/>same question, different number,<br/>different day"]
    D1 --> MS2{"metric store"}
    D2 --> MS2
    D3 --> MS2
    MS2 --> GOOD["named metrics with owners.<br/>the model selects one; it does not<br/>write the arithmetic"]
```

---

## 4. Defence in depth for writes

```mermaid
flowchart LR
    A["'delete the test rows'"] --> L4{"4. prompt says read-only"}
    L4 -->|bypassed by injection| L3{"3. AST validation<br/>rejects DML, DDL, stacked"}
    L3 -->|bug in my validator| L2{"2. role has no write grant"}
    L2 -->|misconfigured| L1{"1. read-only CONNECTION<br/>enforced by the database"}
    L1 --> STOP["refused"]
    L1 --- N2["listed in reverse order of trust.<br/>the layer I wrote and tested<br/>myself is only third"]
```

---

## 5. The cost guard

```mermaid
flowchart LR
    Q2["SELECT SUM(amount) FROM orders"] --> E{"EXPLAIN"}
    E --> B1["4,096 GB, about £20"]
    B1 --> R3["REFUSE: ask for a date range"]
    Q3["...WHERE created_at > '2026-01-01'"] --> E2{"EXPLAIN"}
    E2 --> B2["8 GB, four pence"]
    B2 --> R4["run it"]
    R3 --- Z["a curious user with a text box<br/>is a denial-of-wallet vector"]
```

---

## 6. Schema drift invalidates two things

```mermaid
flowchart TB
    MIG["schema migration"] --> A2["re-embed table and column descriptions"]
    MIG --> B3["bump the schema version in the cache key"]
    A2 --> C4["retrieval finds the new columns"]
    B3 --> D4["cached answers from the old schema expire"]
    C4 --> OK2["consistent"]
    D4 --> OK2
    MIG -.->|neither done| BAD2["retrieval misses new tables, so the model<br/>invents columns; the cache serves<br/>pre-migration numbers indefinitely"]
```
