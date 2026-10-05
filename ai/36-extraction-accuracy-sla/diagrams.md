# Extraction against an SLA — diagrams

## 1. The pipeline

```mermaid
flowchart TB
    IN["50k invoices / month"] --> CL{"classify: known sender?"}
    CL -->|template cached| TP["Template path<br/>cheap, deterministic, most of the volume"]
    CL -->|new or arbitrary| GX["General extraction<br/>20 fields, per-field confidence"]
    TP --> VAL
    GX --> VAL{"Deterministic validators<br/>arithmetic, checksums, dates, enums"}
    VAL -->|fails| Q
    VAL -->|passes| XF{"Cross-field consistency<br/>subtotal + tax = total"}
    XF -->|fails| Q
    XF -->|passes| CONF{"per-FIELD confidence<br/>below threshold?"}
    CONF -->|yes| Q[("Review queue<br/>ordered by downstream error cost")]
    CONF -->|no| OUT["auto-accept"]
    Q --> REV["Reviewer sees ONE field<br/>source region highlighted"]
    REV --> OUT
    REV --> EV[("Eval set<br/>every correction is a free label")]
```

Validators run **before** confidence routing on purpose: each deterministic catch is a review
avoided, and review is the expensive resource in this system.

---

## 2. The arithmetic that reframes the problem

```mermaid
flowchart LR
    A["20 fields<br/>99% accuracy each"] --> B["0.99 to the 20th"]
    B --> C["82% of documents perfect"]
    C --> D["9,104 imperfect docs / month"]
    D --> E["for 99% PER DOCUMENT<br/>you need 99.95% per field"]
    E --> F["no model does that unaided"]
    F --- G["so human review is not a fallback.<br/>it is the architecture"]
```

---

## 3. Per-field routing versus per-document

```mermaid
flowchart LR
    U["one uncertain field<br/>in a 20-field document"] --> P1{"routing granularity"}
    P1 -->|per document| D1["reviewer re-reads all 20<br/>26,654 fields per 3,000 docs"]
    P1 -->|per field| D2["reviewer reads 1<br/>1,773 fields per 3,000 docs"]
    D1 --- X["15x the reviewer time<br/>for identical accuracy"]
    D2 --> N["the difference between a review queue<br/>and a department"]
```

---

## 4. What an aggregate hides

```mermaid
flowchart TB
    AG["aggregate field accuracy 97.74%"] --> R["reads as a broad 1.3-point shortfall<br/>to close with a better model"]
    R --> W["wrong diagnosis, wrong fix"]
    PF["per-field view"] --> F1["handwritten_note 78.2%<br/>10,899 errors - 48% of ALL errors"]
    PF --> F2["line_2_desc 96.1% - 9%"]
    PF --> F3["line_1_desc 96.4% - 8%"]
    PF --> F4["bank_account 99.95%"]
    F1 --> T["one field, more than the next three combined.<br/>it should never have been in the contract"]
    F4 --> V["99.95% because it is VALIDATED,<br/>not because it is easy"]
```

---

## 5. Routing economics

```mermaid
flowchart LR
    S1["review nothing<br/>£550/mo, 9,104 errors escape"] --> B2{"the SLA"}
    S2["review everything<br/>£21,550/mo, 0 escape"] --> B2
    S3["confidence-routed<br/>£10,154/mo, touches under half"] --> B2
    B2 --> N3["the residual is not a bug to fix.<br/>it is the number you negotiate around"]
```

---

## 6. Validators are free accuracy

```mermaid
flowchart TB
    D["extracted document"] --> V1{"subtotal + tax = total?"}
    V1 -->|no| Q2["queue - and show BOTH fields,<br/>the error is in the relationship"]
    V1 -->|yes| V2{"line items sum to subtotal?"}
    V2 -->|no| Q2
    V2 -->|yes| V3{"due date after invoice date?"}
    V3 -->|no| Q2
    V3 -->|yes| V4{"VAT and IBAN checksums?"}
    V4 -->|no| Q2
    V4 -->|yes| A2["no model confidence spent<br/>on anything arithmetic can prove"]
```
