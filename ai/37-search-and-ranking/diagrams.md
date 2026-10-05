# Search and ranking — diagrams

## 1. Two paths: offline is where the LLM lives

```mermaid
flowchart TB
    PUB["document published"] --> IDX["index immediately<br/>BM25 + standard embedding<br/>FINDABLE in seconds"]
    PUB --> ENR["LLM enrichment, offline<br/>summary, keywords, synthetic questions"]
    ENR --> IDX2["re-index enriched<br/>WELL-RANKED, minutes to hours later"]
    LOGS[("query logs")] --> QE["LLM mines a query-expansion<br/>dictionary, offline"]
    LOGS --> TP["LLM generates training pairs<br/>for the reranker"]
    Q["user query, 200 ms budget"] --> QU["query understanding, 3 ms"]
    QE -.->|lookup, 0 ms| QU
    QU --> BM["BM25 over 10M, 18 ms"]
    QU --> AN["ANN vector search, 22 ms"]
    BM --> G{"signal gate:<br/>did this arm rank anything?"}
    AN --> G
    G --> F["RRF fusion + dedup, 4 ms"]
    F --> CE["cross-encoder rerank top 100, 28 ms<br/>sees query and doc TOGETHER"]
    TP -.->|trains| CE
    CE --> BR["business rules as separate features<br/>freshness, popularity, sponsored"]
    BR --> R["render, 12 ms"]
    R --> CK[("click + dwell logging<br/>with position")]
    CK -.->|learning to rank| CE
```

No LLM appears anywhere in the request path. Everything it does happens hours earlier, and the
system is faster and better for it.

---

## 2. The budget, and what it rules out

```mermaid
flowchart LR
    B["200 ms budget"] --> S["serving stack totals 112 ms<br/>88 ms of headroom"]
    B --> L["one LLM generation call<br/>900 ms"]
    L --> X["4.5x the ENTIRE budget"]
    X --> Y["not 'should not' - CANNOT.<br/>a smaller model or a shorter prompt<br/>does not close a 4.5x gap"]
```

---

## 3. Each retriever is blind where the other sees

```mermaid
flowchart TB
    Q1["'E4471'<br/>rare exact token"] --> BM2["BM25: spread 3.96<br/>ranks the right doc first"]
    Q1 --> V1["vector: spread 0.00<br/>never meaningfully saw the token,<br/>every document scores the same"]
    Q2["'locked out'<br/>paraphrase, zero term overlap"] --> BM3["BM25: spread 0.00<br/>no document contains either word"]
    Q2 --> V2["vector: spread 0.55<br/>separates them cleanly"]
    V1 --- N["'embed everything and use vector search'<br/>loses error codes, SKUs, part numbers<br/>and names - most of a site search"]
```

---

## 4. Naive fusion is worse than one arm alone

```mermaid
flowchart LR
    E["query 'E4471'"] --> A["BM25 ranking: correct"]
    E --> B2["vector ranking: arbitrary"]
    A --> RRF{"plain RRF<br/>averages both"}
    B2 --> RRF
    RRF --> BAD["nDCG 0.00<br/>noise displaced the signal"]
    A --> GATE{"gated RRF<br/>fuse only arms with signal"}
    B2 -.->|no signal, excluded| GATE
    GATE --> GOOD["nDCG 1.00"]
```

Worst-query nDCG: BM25 alone 0.25, vector alone 0.00, plain RRF **0.00**, gated RRF **0.82**.
Read the worst row, not the mean — hybrid buys a floor.

---

## 5. Similarity is not usefulness

```mermaid
flowchart LR
    Q3["'how do i get my money back'"] --> SIM["by semantic similarity<br/>'Billing and invoices' ranks high"]
    Q3 --> CLK["by clicks<br/>'Refund policy' 62, 'Billing' 7"]
    SIM --> P["topically adjacent<br/>and nobody wants it"]
    CLK --> U["measures the thing itself"]
    U --- W["similarity proxies relevance,<br/>relevance proxies usefulness.<br/>clicks skip both proxies"]
```

---

## 6. Freshness has two clocks

```mermaid
flowchart LR
    P2["publish"] --> C1["findable: seconds<br/>BM25 + standard embedding"]
    P2 --> C2["well-ranked: minutes to hours<br/>after LLM enrichment"]
    C1 --> V3["searchable in its unenriched state,<br/>not invisible until the batch runs"]
    C2 --> M2["track enrichment lag as a metric"]
    M2 --- Z["'new content ranks badly for six hours'<br/>is invisible in aggregate relevance<br/>and obvious to whoever published it"]
```
