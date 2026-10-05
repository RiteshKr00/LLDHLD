# Document ingestion at 10M — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    SRC["source systems<br/>S3, SharePoint, mail archive"] --> CRAWL
    CRAWL["change feed<br/>emits keys and etags, never bodies"] --> LEDG
    LEDG[("document ledger<br/>one row per doc: hash, stage, fp")] --> HASH
    HASH{"content hash<br/>already embedded?"} -- yes: mark done, zero cost --> LEDG
    HASH -- new --> Q1
    Q1[["parse queue<br/>CPU pool, scales on cores"]] --> PARSE
    PARSE["parse and OCR<br/>1.5s born-digital, 20s scanned"] --> CHUNK
    PARSE -. no extractable text .-> DLQ
    CHUNK["chunk<br/>versioned size and overlap"] --> Q2
    Q2[["embed queue, BOUNDED<br/>its depth is the backpressure"]] --> EMB
    Q2 -. lag high, throttle parse .-> PARSE
    EMB["embed in batches of ~96<br/>sized by TOKEN budget, not count"] --> UPS
    EMB -. 429 means quota, not capacity .-> Q2
    UPS["idempotent upsert<br/>uuid5 of doc hash and chunk index"] --> VDB
    UPS --> LEDG
    VDB[("vector index and chunk rows<br/>200M vectors, ~600 GB raw")] --> SRCH
    SRCH["search and RAG<br/>reads the index, never the pipeline"]
    LEDG --> MON["run monitor<br/>docs/s per stage, projected finish"]
    DLQ[("dead letter queue<br/>reason code per document")] --> MON
```

Read it as one document: discovered by the change feed, written to the ledger
*before* any work, dedup-checked, then pushed through four stages that are bound
by four different resources. Two edges carry the whole design — `UPS --> LEDG`
(the fingerprint is written after the work, so a restart knows) and the dotted
`Q2 -.-> PARSE` (a pipeline that cannot slow down can only fall over).

---

## 2. One document's state machine — this is what makes it resumable

```mermaid
stateDiagram-v2
    [*] --> discovered
    discovered --> hashed
    hashed --> duplicate : hash already embedded
    hashed --> parsed
    parsed --> chunked
    chunked --> embedded
    embedded --> indexed
    parsed --> failed : no extractable text
    embedded --> failed : upsert rejected
    failed --> hashed : replay after the class is fixed
    duplicate --> [*]
    indexed --> [*]
```

The unit of resumability is this diagram, not the run. A restart is a query —
"give me rows not in `indexed` or `duplicate`" — and `failed` is a state you can
replay from, which is why the DLQ carries a reason code rather than a stack trace.

---

## 3. Crash at 60%

#### One job, one loop — the restart is from zero

```mermaid
flowchart LR
    A1["for doc in 10M:<br/>parse, chunk, embed, upsert"] --> A2["dies at 6M<br/>33 hours in"]
    A2 --> A3["nothing durable was written<br/>per document"]
    A3 --> A4["restart from doc 0<br/>320M embeddings for a 200M corpus"]
```

#### Staged, with a ledger — the restart is a scan

```mermaid
flowchart LR
    B1["ledger row per doc<br/>stage + per-stage fingerprint"] --> B2["dies at 6M"]
    B2 --> B3["6M rows say indexed<br/>the fingerprints survived"]
    B3 --> B4["resume: 4M rows behind<br/>cost of the crash = one batch"]
```

The two runs do identical work per document. The only difference is that one of
them wrote down what it had done, at a granularity smaller than "the job".

---

## 4. The fingerprint chain — how far back a change replays

```mermaid
flowchart LR
    CH[("content hash<br/>of the raw object")] --> PFP
    PFP["parse fp = hash of<br/>content + parser version"] --> CFP
    CFP["chunk fp = hash of<br/>parse fp + size + overlap"] --> EFP
    EFP["embed fp = hash of<br/>chunk fp + model id"] --> UFP
    UFP["upsert fp, stored<br/>per document id"] --> DONE["match on all four<br/>= this doc is free"]
    NEWM["new embedding model"] -.-> EFP
    NEWC["smaller chunk window"] -.-> CFP
    NEWP["better OCR engine"] -.-> PFP
```

Each stage skips itself when the stored fingerprint matches. A model swap enters
at `EFP` and reuses every CPU-hour of OCR; a chunker change enters at `CFP` and
reuses the same. The test of the whole scheme is `DONE`: re-running a finished
pipeline must cost **zero**.

---

## 5. Backpressure between embed and upsert

#### Unbounded — the broker becomes the outage

```mermaid
flowchart LR
    C1["embed: 1,000/s steady"] --> C2[["unbounded queue"]]
    C2 --> C3["upsert throttled to 600/s<br/>HNSW index build running"]
    C2 -.- C4["400/s of backlog for 30 hours<br/>= broker disk full at 3am<br/>the WHOLE pipeline stops"]
```

#### Bounded — the slow stage sets the pace

```mermaid
flowchart LR
    D1["embed workers"] --> D2[["bounded queue<br/>depth is the signal"]]
    D2 --> D3["upsert throttled to 600/s"]
    D2 -. depth over threshold .-> D1
    D1 --> D4["embed slows to 600/s<br/>run takes longer, nothing dies"]
```

Unbounded queues do not absorb a mismatch, they postpone it and then convert a
slow stage into a total outage. Bounding the queue is how you choose which of
those two you get.

---

## 6. Duplicates are a retrieval bug, not a storage bug

```mermaid
flowchart TB
    R1["queue redelivers a document<br/>at-least-once, always"] --> R2{"how is the chunk keyed?"}
    R2 -->|append| R3["3 copies of chunk 7<br/>in the index"]
    R3 --> R4["top-k returns the SAME passage<br/>three times, context window<br/>filled by one document"]
    R2 -->|uuid5 of doc hash and index| R5["same key, overwritten<br/>row count unchanged"]
    R5 --> R6["and a re-chunk DELETES<br/>ids the doc no longer owns"]
```

The storage waste is the boring half. The half that reaches users is a top-k that
spends three of its five slots on one passage — and the orphan ids left behind by
a re-chunk keep matching queries long after the text they describe is gone.
