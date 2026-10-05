# RAG — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    U["Employee question<br/>web client or Slack"] --> API["FastAPI /ask<br/>auth, tenant id, request id"]
    API --> CA{"semantic cache<br/>per-tenant namespace"}
    CA -->|miss| QE["embed query<br/>gemini-embedding-001"]
    QE --> VS["$vectorSearch<br/>numCandidates = 10 x top_k"]
    ING["ingest job, offline<br/>parse, chunk, embed, upsert"] --> DB[("MongoDB Atlas<br/>chunks + vector index")]
    DB --> VS
    VS --> TK["top-k chunks<br/>+ vectorSearchScore"]
    TK --> FL{"score above<br/>relevance floor?"}
    FL -->|no| RF["refuse: not in the policy"]
    FL -->|yes| PB["prompt assembly<br/>context chunks, citations, question"]
    PB --> LLM["Gemini generate<br/>grounded in the injected context only"]
    LLM --> SSE["StreamingResponse SSE<br/>token by token to the client"]
    CA -->|hit| SSE
    SSE --> OBS[("observability<br/>tokens, cost, recall@k<br/>refusal rate, groundedness")]
    RF --> OBS
```

One store, two paths: the ingest job writes chunks and embeddings offline, the
query path reads them. Every section below zooms into one box of this picture.

## 2. Ingest vs query

#### Ingest — offline, per document

```mermaid
flowchart TB
    D["Policy PDF"] --> P["parse"]
    P --> C["chunk<br/>section-aware + overlap"]
    C --> E1["embed each chunk<br/>gemini-embedding-001"]
    E1 --> M[("MongoDB Atlas<br/>vector index on 'embedding'")]
```

#### Query — online, per question

```mermaid
flowchart TB
    U["Employee question"] --> E2["embed<br/>SAME model as ingest"]
    E2 --> S["$vectorSearch<br/>numCandidates = 10 x top_k"]
    M[("MongoDB Atlas<br/>vector index, written by ingest")] --> S
    S --> K["top-k chunks + vectorSearchScore"]
    K --> F{"score above<br/>relevance floor?"}
    F -->|no| R["refuse: 'not in policy'"]
    F -->|yes| PR["inject as context"]
    PR --> G["Gemini generate"]
    G --> SSE["StreamingResponse<br/>SSE, token by token"]
```

The two paths meet at one place only: the vector index. They must embed with the
same model — a mismatch does not error, it silently destroys recall.

## 3. The recall/latency dial

```mermaid
flowchart LR
    LOW["numCandidates low<br/>fast<br/>may miss true nearest neighbours"] -- more recall --> MID["numCandidates = 10x top_k<br/>balanced default<br/>true top-k very likely in the pool"]
    MID -- more latency --> HIGH["numCandidates high<br/>best recall<br/>approaches a brute-force scan"]
```

## 4. Where chunking goes wrong

#### Chunk too large

```mermaid
flowchart LR
    B1["chunk too large<br/>answer plus 3 unrelated paragraphs"] --> B2["embedding is a blur<br/>matches nothing precisely"]
```

#### Chunk too small

```mermaid
flowchart LR
    S1["chunk too small<br/>'Notice period is' / '90 days for...'"] --> S2["fact split across the boundary<br/>neither half retrieves"]
```

#### Section-aware + overlap — the right size

```mermaid
flowchart LR
    R1["one clause = one chunk<br/>overlap covers the boundaries"] --> R2["complete idea<br/>selective embedding"]
```

## 5. Scaling to 1M — what you add and why

```mermaid
flowchart TB
    U["30 QPS peak"] --> SC{"semantic cache<br/>per-tenant namespace"}
    SC -->|hit ~60%| RET["return cached"]
    SC -->|miss| RT{"difficulty<br/>router"}
    RT -->|easy| SM["small cheap model"]
    RT -->|hard| QU[["queue: load levelling"]]
    QU --> BIG["large model"]
    BIG --> FB{"provider healthy?"}
    FB -->|no| ALT["fallback provider"]
    FB -->|degraded| EX["extractive answer<br/>citations only"]
    SM --> OBS[("observability:<br/>tokens, cost, recall@k<br/>refusal rate, groundedness")]
    BIG --> OBS
```
