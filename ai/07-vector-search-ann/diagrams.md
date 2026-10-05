# Vector search — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    ING["INGEST PATH<br/>offline, once per document"] --> CH["parse and chunk<br/>size and overlap per section type"]
    CH --> EM["embed chunks<br/>model version pinned into the key"]
    EM --> BLD["index build, offline<br/>hours at 100M, shadow-read then swap"]
    CH --> BM["BM25 inverted index<br/>exact tokens and identifiers"]
    BLD --> SH["tenant shard: HNSW in RAM<br/>int8 quantised, never spilled to disk<br/>numCandidates = 10x top_k"]
    Q["query + tenant id<br/>online path starts here"] --> QE["embed query<br/>SAME model version as ingest"]
    QE --> RT["tenant to shard router<br/>a map, not a modulo"]
    RT --> SH
    Q --> BM
    SH --> F["fuse<br/>per-section alpha, dedupe by chunk id"]
    BM --> F
    F --> RR["cross-encoder rerank<br/>top 20 in, top 5 out"]
    RR --> GEN["generate<br/>top 5 chunks as grounded context"]
    SH -.-> OBS["recall@k on a labelled set<br/>p95 per shard, rebuild age"]
```

What to notice, left to right:

- The two paths meet only at the index. Ingest is slow and batched; serving is
  hot and memory-bound.
- One model version spans both sides. A mismatch throws no error, it just
  quietly returns the wrong neighbours.
- The router runs *before* the shard, so one query touches one shard and never
  fans out to pay the slowest.
- `numCandidates` is the only dial in the picture that trades latency for recall
  at query time (see 3). Everything else is a build-time decision.
- The dotted line is the only thing that catches silent recall decay.

## 2. HNSW: coarse to fine

```mermaid
flowchart TB
    Q[query vector] --> L2["LAYER 2<br/>sparse, long links, few nodes"]
    L2 --> A2((entry))
    A2 -- greedy hop --> C2((distant hub))
    C2 --> L1["LAYER 1<br/>medium density, shorter links"]
    L1 --> B1((neighbour))
    B1 -- greedy hop --> D1((closer))
    D1 --> L0["LAYER 0<br/>dense, holds every vector"]
    L0 --> D0((local cluster))
    D0 --- E0((target))
    E0 --> R["numCandidates explored<br/>-> narrow to top_k"]
```

Each layer restarts the greedy walk where the layer above stopped. The top
layers cover distance cheaply on a thin graph; layer 0 is the only complete one
and does the fine sorting. Approximate because the walk is greedy — it can
settle in a local minimum and never see the true nearest neighbour.

## 3. The recall/latency trade

```mermaid
flowchart LR
    Q[query] --> E{"numCandidates<br/>= exploration budget"}
    E -->|"low: 1x top_k"| F["fast<br/>may be stuck in a local minimum<br/>true top-k missed"]
    E -->|"10x top_k (yours)"| G["balanced default<br/>true top-k very likely in pool"]
    E -->|"very high"| H["best recall<br/>approaches exact O(n) scan"]
```

## 4. Two-stage retrieval

```mermaid
flowchart TB
    Q[query] --> BI["stage 1: BI-encoder / ANN<br/>query and doc embedded SEPARATELY<br/>fast, precomputable, millions of docs"]
    BI --> K["top 20 candidates<br/>plausible, imperfectly ordered"]
    K --> CE["stage 2: CROSS-encoder rerank<br/>query + doc through the model TOGETHER<br/>attention relates their words<br/>slow, cannot precompute"]
    CE --> T["top 5, well ordered"]
    T --> G[generate]
```

## 5. Why hybrid

```mermaid
flowchart TB
    Q["'What is the Form 16 deadline?'"] --> V[vector search]
    Q --> B[BM25 keyword]
    V --> VR["'Form 26AS filing dates'<br/>semantically near, WRONG doc"]
    B --> BR["exact token 'Form 16'<br/>-> right doc"]
    VR --> F[fuse with per-section alpha]
    BR --> F
    F --> OUT["vector catches paraphrase<br/>BM25 catches identifiers"]
```
