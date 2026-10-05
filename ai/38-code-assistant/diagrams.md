# Repo-aware code assistant — diagrams

## 1. The index is three things, not one

```mermaid
flowchart TB
    REPO[("2M lines, 25M tokens<br/>125x a 200k window")] --> AST["AST-aware chunking<br/>function / method / class<br/>file path and language prepended"]
    AST --> EMB[("Vector index")]
    AST --> BM[("BM25 index<br/>identifiers are exact tokens")]
    AST --> GR[("Symbol graph<br/>definitions, references, imports,<br/>test-to-subject links")]
    Q["developer question"] --> H["hybrid first stage"]
    EMB --> H
    BM --> H
    H --> FAM["collapse near-duplicate families<br/>+ path priors: generated, vendor, migrations"]
    FAM --> EXP["graph expansion, 1-2 hops<br/>callees, types, tests"]
    GR --> EXP
    EXP --> PERM{"permission filter<br/>AT THE QUERY, fail closed"}
    PERM --> RR["rerank, assemble with paths visible"]
    RR --> A["answer"]
    PUSH["git push"] --> INC["content-hash diff<br/>re-embed only changed chunks"]
    INC --> EMB
    INC --> GR
```

The permission filter's position is the security answer. Filtering after generation means the
private code was already in the prompt.

---

## 2. Why fixed-size chunking breaks code

```mermaid
flowchart LR
    F["fixed 6-line chunks"] --> C1["chunk 1: def parse_config...<br/>whole definition"]
    F --> C2["chunk 2: if 'timeout' not in raw...<br/>STARTS MID-BODY"]
    C2 --> U["no signature. no name.<br/>no parameters. no imports."]
    U --> N["not a worse chunk - a useless one.<br/>it cannot be matched to a question<br/>and cannot be understood if retrieved"]
    A2["AST boundaries"] --> G2["every chunk is a complete definition"]
```

Prose degrades gracefully when split; code does not.

---

## 3. Similarity finds the call site, references find the answer

```mermaid
flowchart LR
    Q2["'what does parse_config do?'"] --> V["vector retrieval<br/>returns parse_config"]
    V --> P["it calls validate_config<br/>whose body the model cannot see"]
    P --> H1["hop 1: validate_config, read_file"]
    H1 --> H2["hop 2: MAX_TIMEOUT, ConfigError"]
    H2 --> ANS["MAX_TIMEOUT = 30 is the actual answer<br/>to 'why does my config keep failing?'<br/>and it is TWO HOPS from the question"]
```

---

## 4. An identifier is a token, not a concept

```mermaid
flowchart TB
    QQ["query: validate_config"] --> SUB["an embedding sees the pieces:<br/>validate, config"]
    SUB --> D1["app/config_schema.py<br/>vector 0.50 - contains the token NOWHERE"]
    SUB --> D2["app/config.py<br/>vector 0.40 - the only file that has it"]
    D1 --> W2["vector ranks the wrong file first"]
    QQ --> LEX["BM25 sees a whole token"]
    LEX --> D3["app/config.py  3.0"]
    LEX --> D4["everything else  0.0"]
```

---

## 5. Near-duplication owns the page

```mermaid
flowchart LR
    T["query: timeout"] --> RAW["raw top 5:<br/>pb2_user, pb2_order, pb2_invoice,<br/>pb2_payment, pb2_ledger"]
    RAW --> Y2["ALL FIVE generated, near-identical.<br/>generated code is long and repeats tokens,<br/>which is what term frequency rewards"]
    T --> FIX["collapse family + path priors"]
    FIX --> GOOD2["pb2_user (1 representative),<br/>retry.py, config.py, server.py"]
    Y2 --- Z2["the failure that arrives FIRST in a real<br/>deployment, and never in a demo repo"]
```

---

## 6. Suggesting a change is a different product

```mermaid
flowchart LR
    S["suggested patch"] --> SB["apply in a sandbox"]
    SB --> CP{"compiles?"}
    CP -->|no| RJ["reject, do not show"]
    CP -->|yes| TS["run tests touching the changed symbols<br/>- the graph already knows which"]
    TS --> RES{"pass?"}
    RES -->|yes| SHOW["show the patch WITH the test result"]
    RES -->|no| SHOW2["show the patch AND the failure"]
    SHOW --- N4["a suggestion that compiles and passes<br/>is a different product from one<br/>that looks plausible"]
```
