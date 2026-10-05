# Reference architecture diagrams

One diagram per major design scenario. **Learn to draw these from blank**, not to recognise
them — a design round is a whiteboard, and being able to produce the boxes in order is what
buys you the time to talk about trade-offs.

Every box below exists because of a named failure. If you can't say the failure, don't draw
the box.

---

## A - The universal LLM platform skeleton
*Scenarios 1, 2, 9, 10 - `11-multi-model-architecture/`*

#### A1 - entry to admission: cache, gateway, router, buckets

```mermaid
flowchart TB
    CL[clients] --> API["API tier — stateless<br/>horizontal, not the bottleneck"]
    API --> SC{"semantic cache<br/>tenant + persona + corpus-version namespaced"}
    SC -->|hit| RET[return]
    SC -->|miss| GW["GATEWAY<br/>one call shape, per-provider adapters"]
    GW --> REG[("capability registry<br/>ctx window - modality - json mode<br/>cost - latency - quota - status")]
    GW --> RTR["ROUTER<br/>capability -> difficulty -> tier<br/>-> budget -> health"]
    REG --> RTR
    BUD[("budget state<br/>per tenant, per feature")] --> RTR
    RTR --> TB["token buckets — SHARED in Redis<br/>per provider AND per tenant"]
    TB --> NEXT["admitted call<br/>-> execution path, next diagram"]
```

#### A2 - execution to observability: breakers, providers, validate, ledger

```mermaid
flowchart TB
    TB["admitted call<br/>out of the token buckets"] --> CB{"circuit breaker<br/>PER PROVIDER, not global"}
    CB -->|closed| P1[provider A]
    CB -->|open| P2[provider B]
    CB -->|open| P3[self-hosted vLLM]
    CB -->|all open| DEG["degraded path<br/>DIFFERENT per feature"]
    P1 --> VAL["validate on receipt<br/>schema + numeric grounding"]
    P2 --> VAL
    P3 --> VAL
    VAL --> LED[("usage ledger — ONE rate card<br/>async write, never critical path")]
    LED --> OBS[("observability<br/>per MODEL and per TENANT")]
```

**Draw order to memorise:** clients -> API -> cache -> gateway -> registry+router -> buckets
-> breakers -> providers -> validate -> ledger -> observability.

---

## B - Async path and the bulkhead
*Scenarios 1, 14 - `01-async-vs-celery/`*

```mermaid
flowchart LR
    R[request] --> D{"is the caller<br/>waiting?"}
    D -->|yes| SY["sync path — thin<br/>timeouts, streaming"]
    D -->|no| Q{"must it survive<br/>a deploy?"}
    Q -->|no| BG["BackgroundTasks<br/>same process, best effort"]
    Q -->|yes| QQ[["queue PER TASK TYPE"]]
    QQ --> W1["chat workers"]
    QQ --> W2["summarise workers<br/>high concurrency, I/O bound"]
    QQ --> W3["extract workers"]
    W2 --- BH["BULKHEAD: separate pools<br/>-> summarisation cannot<br/>starve extraction"]
    SY --> GW[gateway]
    W1 --> GW
    W2 --> GW
    W3 --> GW
```

---

## C - Multi-tenant RAG at 500 tenants
*Scenario 3 - `DESIGN-02`*

#### C1 - ingest: the heavy path, breaks FIRST

```mermaid
flowchart TB
    UP[tenant uploads 10k docs] --> IQ[["per-tenant ingest queue<br/>+ per-tenant rate limit"]]
    IQ --> H{"content-hash dedup"}
    H -->|seen| SKIP[skip]
    H -->|new| CH[chunk] --> EM[embed, batched] --> UPS["idempotent upsert<br/>uuid5 of content"]
    UPS --> ST["-> sharded store, next block"]
    IQ -.->|"backlog degrades THAT tenant only"| UP
```

#### C2 - storage: sharded BY TENANT

```mermaid
flowchart TB
    UPS["idempotent upsert<br/>arriving from ingest"] --> S1[("shard 1<br/>tenants 1-200")]
    UPS --> S2[("shard 2<br/>tenants 201-400")]
    UPS --> S3[("dedicated shard<br/>the 200k-doc tenant")]
    S1 --- SH["shard by TENANT, never by doc<br/>-> the 200k-doc tenant gets its own<br/>-> nobody else feels it"]
```

#### C3 - query: scope first, then retrieve

```mermaid
flowchart TB
    QU[question] --> SCP["scope resolver — FAILS CLOSED"]
    SCP --> NS["per-tenant NAMESPACE<br/>not a post-filter"]
    NS --> S1[("shard 1<br/>tenants 1-200")]
    NS --> S2[("shard 2<br/>tenants 201-400")]
    NS --> S3[("dedicated shard<br/>the 200k-doc tenant")]
    S1 --> TK["top-k + score"] --> FL{"above relevance floor?"}
    FL -->|no| REF["refuse: not in corpus"]
    FL -->|yes| GEN[generate + stream]
```

---

## D - Real-time voice, serial budget
*Scenario 6 - `04-voice-custom-llm/hld.md`*

#### D1 - the call path

```mermaid
flowchart LR
    U[caller] --> VP["voice platform<br/>STT + TTS + call loop"]
    VP -->|"POST /voice/llm + voice-only JWT"| SRV["YOUR server<br/>= the model provider"]
    SRV --> DIS[discard their system message]
    DIS --> RB["rebuild: persona + guardrails<br/>+ tenant-scoped retrieval"]
    RB --> LLM[model]
    LLM -->|"stream chat.completion.chunk"| VP
    VP -->|"partial tokens -> TTS AS THEY ARRIVE"| U
    SRV --> PS[(persist turn server-side)]
    SRV --> MET[(per-call metering, 5 providers)]
```

#### D2 - the latency budget is SERIAL

```mermaid
flowchart LR
    B0["the budget is SERIAL<br/>every stage must stream<br/>or the caller hears silence"] --> B1[STT finalise]
    B1 --> B2[retrieval] --> B3[LLM first token] --> B4[TTS first audio] --> B5[network]
```

---

## E - Agentic engine with enforced budgets
*Scenario 4 - `DESIGN-03`*

```mermaid
stateDiagram-v2
    [*] --> Classify
    Classify --> Detect
    Detect --> Decide
    Decide --> Apply
    Apply --> Verify
    Verify --> [*]: confident
    Verify --> Human: low confidence
    Human --> [*]
    Decide --> Decide: loop, budget-capped
```

**Enforced in code at `Decide`, never in the prompt:** max-step budget; per-run token/cost cap
plus a breaker; repeat-state detection; per-step and per-run timeout; checkpoint after each
node.

**At `Apply`, because these tools have side effects:** least privilege, tenant-scoped creds;
an idempotency key per call; validate the tool call BEFORE executing it.

---

## F - Prompt / config management with an unavoidable gate
*Scenarios 8, 11 - `DESIGN-04`*

```mermaid
flowchart TB
    ED[engineer or PM edits a prompt] --> ART["written as an IMMUTABLE version<br/>v1, v2, v3 ... never edited in place"]
    ART --> RV[review + diff]
    RV --> GATE{"EVAL GATE — unavoidable<br/>golden set, noise floor first"}
    GATE -->|"fail"| BLK[blocked]
    GATE -->|"NO DATA"| BLK2["ALSO blocked<br/>tri-state: no-data never passes"]
    GATE -->|pass| CAN["canary: 5% traffic behind a flag"]
    CAN --> GM{"guardrail metrics<br/>refusal - escalation - parse failure<br/>sampled groundedness"}
    GM -->|regressed| RB["rollback = pointer flip"]
    GM -->|healthy| LIVE["promote 'live' pointer"]
    LIVE --> LOG[("audit: who, when, diff,<br/>gate result, resolved version id")]
    LOG --> REQ["every request logs the<br/>RESOLVED prompt version id"]
```

---

## G - Feedback flywheel
*Scenario 12*

```mermaid
flowchart LR
    P[600k calls/day] --> SIG["implicit signals<br/>edited - retried - abandoned<br/>copied - escalated"]
    SIG --> SAMP["STRATIFIED sample<br/>by feature, tenant, model,<br/>confidence band"]
    SAMP --> AL["active learning priority:<br/>uncertain + disagreed FIRST"]
    AL --> RED[PII redaction]
    RED --> HQ[["human review queue<br/>RUBRIC, not free text"]]
    HQ --> GS[("golden set — versioned")]
    GS --> GATE[eval gate in CI]
    GATE --> DEP[deploy]
    DEP --> P
    GS -.->|"refresh on a schedule<br/>or it ROTS"| SAMP
    GATE -.->|"do gate scores predict<br/>production signal?"| SIG
```

---

## H - Tiered conversation memory
*Scenario 13*

```mermaid
flowchart TB
    T[new turn] --> REC[("tier 1: recent turns VERBATIM<br/>last ~10")]
    REC --> TH{"token threshold hit?"}
    TH -->|yes| SUM["summarise session<br/>ON A TRIGGER, not every turn"]
    SUM --> ROLL[("tier 2: rolling session summary")]
    ROLL --> EXT["extract durable facts"]
    EXT --> FACTS[("tier 3: structured long-term facts<br/>per-user namespace<br/>QUERYABLE, not prose")]
    T --> RETR["retrieve relevant facts<br/>recency x relevance"]
    FACTS --> RETR
    RETR --> PR[prompt: recent + summary + facts]
    FACTS --- DEL["deletion path that ACTUALLY deletes<br/>-> never bake facts irreversibly<br/>into summaries"]
```

---

## I - Batch processing 10M records in 8 hours
*Scenario 14*

```mermaid
flowchart LR
    SRC[(10M records)] --> DD{"content-hash dedup<br/>support data is REPETITIVE"}
    DD -->|dup| CACHE[reuse prior result]
    DD -->|new| WU["work units + checkpointed progress"]
    WU --> CAS{"cheap model first"}
    CAS -->|confident| OUT
    CAS -->|"low confidence"| BIG[escalate to large model] --> OUT
    WU --> BA["provider Batch API<br/>~50% of sync rate"]
    BA --> OUT["idempotent write, keyed on record id"]
    WU --> MK["multi-key / multi-provider fan-out<br/>350/sec sustained needs it"]
    WU --> DLQ[["dead-letter queue<br/>one poison record must not stall the run"]]
    OUT --> ETA[("progress + ETA telemetry<br/>know at 02:00, not 07:00")]
```

---

## J - Guardrails and PII: two opposite trades
*Scenarios 15, 16*

#### J1 - PII gateway: optimise RECALL

```mermaid
flowchart TB
    I1[input] --> D1["deterministic first<br/>Presidio + checksums<br/>(latency budget under 50ms)"]
    D1 --> A1{ambiguous?}
    A1 -->|yes| L1["LLM extractor<br/>substring + type ONLY<br/>span re-found in CODE"]
    A1 -->|no| T1
    L1 --> T1["treatment table IN CODE<br/>model may only go STRICTER"]
    T1 --> R1["redact / tokenise (reversible)"]
    R1 --- W1["optimise RECALL<br/>false negative = UNRECOVERABLE LEAK<br/>-> over-redact on purpose<br/>-> FAIL CLOSED on detector error"]
```

#### J2 - output guardrails: optimise PRECISION

```mermaid
flowchart TB
    O1[model output] --> G1["grounding = primary defence"]
    G1 --> G2["deterministic rules<br/>banned topics, claim patterns"]
    G2 --> G3["safety classifier"]
    G3 --> G4{safe?}
    G4 -->|no| G5["graceful DEFLECTION<br/>not a hard block"]
    G4 -->|unsure| G6[human escalation]
    G4 -->|yes| G7[ship]
    G5 --- W2["optimise PRECISION<br/>false POSITIVE is the real risk<br/>-> over-blocking makes it useless"]
```

The two sides pull in opposite directions on purpose: input errs towards redacting too much,
output errs towards letting borderline text through. Tuning both to the same threshold is the
mistake.

---

## K - Multi-region with data residency
*Scenario 17*

```mermaid
flowchart TB
    E["edge — route on TENANT RESIDENCY"] --> EU1["eu-region app<br/>HARD boundary, nothing leaves"]
    E --> US1["us-region app"]
    E --> IN1["in-region app"]
    EU1 --> EU2[("eu vector store")]
    EU1 --> EU3[("eu cache")]
    EU1 --> EU4["eu region-pinned provider endpoint"]
    EU1 --> EU5[("eu logs + traces STAY here")]
    US1 --> US2[("us vector store")]
    IN1 --> IN2[("in vector store")]
    EU5 -.->|"aggregate METRICS only"| G[(global dashboards)]
    US2 -.-> G
    EU1 -.->|"NO cross-region failover<br/>for regulated tenants<br/>-> degrade IN-region"| EU1
    G --- N["embeddings and logs are DERIVED<br/>personal data — they count too"]
```

---

## L - Zero-downtime embedding migration
*Scenario 19*

```mermaid
flowchart TB
    OLD[("index OLD — model A<br/>100M chunks, SERVING")] --> SR
    BF["resumable checkpointed backfill<br/>~28h of embedding"] --> NEW[("index NEW — model B<br/>built alongside")]
    NEW --> SR{"SHADOW READS<br/>query both, compare, serve OLD"}
    SR --> CMP["compare recall@k<br/>on a labelled set"]
    CMP -->|"new is worse"| STOP["stop — do NOT cut over"]
    CMP -->|"new is equal or better"| PROG["per-tenant PROGRESSIVE cutover"]
    PROG --> DONE["all tenants on NEW"]
    DONE --> DROP["keep OLD until confident, then delete"]
    PROG --- CK["cache keys VERSIONED by model<br/>-> or the cache serves old-space answers"]
    OLD --- MIX["NEVER mix spaces in one index<br/>vectors from two models are<br/>not comparable, they are meaningless"]
```

---

## M - Incident triage: "it started fabricating"
*Scenario 20*

```mermaid
flowchart TB
    R["reports: confidently making things up"] --> S1{"is retrieval returning<br/>ANY chunks?"}
    S1 -->|no| F1["empty retrieval -> answers from<br/>general knowledge, sounds confident<br/>MOST COMMON CAUSE"]
    S1 -->|yes| S2{"does the context<br/>REACH the prompt?"}
    S2 -->|no| F2["style REPLACING facts<br/>instead of adding<br/>(the real bug)"]
    S2 -->|yes| S3{"is it TRUNCATED?"}
    S3 -->|yes| F3["300-char cap cutting facts<br/>from 1000-char chunks"]
    S3 -->|no| S4{"did the corpus change?"}
    S4 -->|no| S5{"did the model or<br/>prompt config change?"}
    S5 --> F5["unreviewed config is the<br/>most likely recent change"]
    S4 --> F4["failed ingest / re-index / deletion"]
    R --> SC{"one tenant or all?"}
    SC -->|one| F6["scoping / namespace bug"]
    SC -->|all| F7["shared path"]
    F1 --> MIT["MITIGATE NOW: raise the relevance floor,<br/>let it refuse more.<br/>A refusal is recoverable;<br/>a fabrication is not."]
```

---

## N - Text-to-SQL with guards
*Scenario 21*

```mermaid
flowchart TB
    Q["'revenue by region last quarter'"] --> SR["SCHEMA RETRIEVAL<br/>embed table/column docs<br/>12,000 columns won't fit a prompt"]
    SR --> SL[("SEMANTIC LAYER / metric store<br/>canonical definition of 'revenue'<br/>THE highest-value component")]
    SL --> FS["few-shot verified query patterns"]
    FS --> GEN[model generates SQL]
    GEN --> V{"VALIDATE before execute"}
    V -->|"parse fails"| RJ[reject + repair prompt]
    V -->|"not read-only"| RJ
    V -->|"unknown table/column"| RJ
    V -->|ok| EX{"EXPLAIN — cost guard"}
    EX -->|"too many rows/bytes"| WARN[reject or warn]
    EX -->|ok| RUN["run under the USER'S credentials<br/>NOT a service account<br/>-> row-level security holds"]
    RUN --> OUT["answer + THE SQL + row count<br/>-> verifiable"]
```

## O - Extraction with an accuracy SLA
*Scenario 22*

```mermaid
flowchart TB
    D[50k invoices/month] --> T{"template seen before?"}
    T -->|yes| CL["cached layout<br/>-> cheap path for the 80% repeats"]
    T -->|no| EXT[full extraction, 20 fields]
    CL --> DV
    EXT --> DV["DETERMINISTIC validators<br/>checksums - date sanity<br/>subtotal + tax = total"]
    DV --> CF{"PER-FIELD confidence<br/>not per-document"}
    CF -->|high| AUTO[auto-accept]
    CF -->|low| HQ[["human review queue<br/>ONLY the uncertain fields"]]
    HQ --> COR[corrections]
    COR --> AUTO
    COR --> ES[(eval set grows)]
    AUTO --> M[("per-FIELD accuracy dashboard<br/>an aggregate hides one broken field")]
    D --- MATH["20 fields x 99% = 0.99^20<br/>= 82% document-perfect<br/>-> human-in-the-loop is the ARCHITECTURE,<br/>not an add-on"]
```

## P - Search: LLM offline, not inline
*Scenario 23*

#### P1 - ONLINE: 200ms budget, NO generation

```mermaid
flowchart TB
    Q[query] --> H["hybrid retrieval<br/>BM25 + vector"]
    H --> R["cross-encoder rerank<br/>top 50-100, distilled, ~10-30ms"]
    R --> LTR["learning-to-rank<br/>+ freshness + business boosts<br/>as SEPARATE features"]
    LTR --> RES[results]
    Q --> CH{"head query?"} -->|yes| CACHE[cached]
    Q --- BUD["ONLINE budget: 200ms<br/>NO generation on this path"]
```

#### P2 - OFFLINE: where the LLM belongs

```mermaid
flowchart LR
    OFF["OFFLINE — the LLM runs HERE<br/>not in the request"] --> L1["query-expansion dictionaries"]
    OFF --> L2["document enrichment:<br/>summaries, keywords,<br/>synthetic questions per doc"]
    OFF --> L3["generate training pairs<br/>for the ranker"]
    L1 -.-> IDX["feeds the ONLINE index<br/>and the ranker"]
    L2 -.-> IDX
    L3 -.-> IDX
```

## Q - Repo-aware code assistant
*Scenario 24*

#### Q1 - index: incremental, on commit

```mermaid
flowchart TB
    C[2M lines / ~25M tokens] --> AST["AST-aware chunking<br/>function/class boundaries<br/>NOT fixed-size"]
    AST --> META["attach file path + language<br/>to the chunk text"]
    META --> SG[("symbol/dependency graph<br/>defs - refs - imports")]
    META --> VEC[(vector index)]
    META --> BM[(BM25 — identifiers are EXACT tokens)]
    C --> HASH{"content hash changed?"} -->|no| SKIP[skip]
    C --- INC["index is INCREMENTAL, on commit<br/>-> never a full rebuild"]
```

#### Q2 - query: scope, hybrid, expand, verify

```mermaid
flowchart TB
    U[question] --> PERM["PERMISSION-SCOPED retrieval<br/>user cannot see repos they can't read"]
    PERM --> HY[hybrid: BM25 + vector]
    VEC[(vector index<br/>from the index build)] --> HY
    BM[(BM25 index<br/>from the index build)] --> HY
    HY --> EXP["expand via dependency graph<br/>-> a call site brings its DEFINITION"]
    SG[("symbol/dependency graph<br/>from the index build")] --> EXP
    EXP --> GEN[generate]
    GEN --> TEST{"suggested a change?"}
    TEST -->|yes| RUN["RUN THE TESTS<br/>-> plausible code that<br/>doesn't compile is caught"]
```

## R - Multimodal document pipeline
*Scenario 25*

```mermaid
flowchart TB
    P[PDF page] --> LA["LAYOUT ANALYSIS first<br/>segment: text / table / figure"]
    LA --> TX[text region] --> CH[chunk + embed]
    LA --> TB[table region] --> ST["extract as STRUCTURED data<br/>not prose — keep row/col relations"]
    LA --> FG[figure region] --> CR["crop + store the image"]
    CR --> CAP["caption with a vision model<br/>AT INGEST, not per query"]
    LA --> SC{"scanned page?"}
    SC -->|yes| OCR["OCR + confidence threshold<br/>-> below threshold: flag,<br/>don't index garbage"]
    CH --> IX[(index with provenance<br/>page + region)]
    ST --> IX
    CAP --> IX
    OCR --> IX
    IX --> QR{"query modality router"}
    QR -->|numeric question| ST
    QR -->|conceptual| CH
    QR --> NG["numeric grounding check<br/>against extracted TABLES"]
    P --- CEIL["if 30% of salient numbers live in<br/>tables/figures, a text-only pipeline<br/>has a HARD 70% numeric-recall ceiling"]
```

## S - RAG over structured + unstructured
*Scenario 30*

```mermaid
flowchart TB
    Q[question] --> RT{"ROUTER / planner<br/>documents? database? BOTH?"}
    RT -->|documents| DOC["vector RAG<br/>policy corpus"]
    RT -->|database| SQL["text-to-SQL<br/>+ all guards from diagram N"]
    RT -->|both| DOC
    RT -->|both| SQL
    DOC --> SY["SYNTHESIS<br/>compose with SEPARATE<br/>attribution per source"]
    SQL --> SY
    SY --> DIS{"sources DISAGREE?"}
    DIS -->|yes| BOTH["SURFACE BOTH<br/>never let the model silently pick"]
    DIS -->|no| ANS["answer + per-source confidence"]
    SQL --- LIVE["NEVER embed database rows<br/>-> query LIVE<br/>-> you cannot SUM a vector search"]
    RT --- ACC["routing accuracy DOMINATES<br/>end-to-end quality"]
```

## T - Incident: cost spiked 5x
*Scenario 31*

```mermaid
flowchart TB
    S["spend x5, nothing deployed"] --> D["FIRST: divide spend by call count<br/>-> splits the problem in two"]
    D --> V{"volume up, or<br/>cost-per-call up?"}
    V -->|volume| V1["which tenant / feature?"]
    V1 --> V2["retry storm? agent LOOP?<br/>scraper? backfill?"]
    V -->|cost per call| C1["prompt got longer?<br/>more chunks retrieved?<br/>a prompt edit?"]
    C1 --> C2["router shifted to an expensive model<br/>because a cheap provider circuit-broke<br/>-> bill rises with NO code change"]
    S --> CA{"cache hit rate collapsed?"}
    CA -->|yes| CA2["a re-index or key-version change<br/>silently multiplies cost"]
    S --> PR["provider price change?<br/>config flip?"]
```

## U - Incident: p99 blew up, p50 flat
*Scenario 32*

```mermaid
flowchart TB
    O["p99: 3s -> 25s, p50 UNCHANGED"] --> K["KEY OBSERVATION, say it first:<br/>not capacity. Scaling out fixes NOTHING.<br/>something affects a SUBSET"]
    K --> SL["slice: one provider? model?<br/>tenant? endpoint?"]
    SL --> T1{"timeouts changed?"}
    T1 -->|"raised/removed"| A1["a fast failure became a 25s hang"]
    SL --> T2{"retries changed?"}
    T2 -->|yes| A2["3 retries x 8s = your 25s"]
    SL --> T3{"new SYNC call in<br/>the request path?"}
    T3 -->|yes| A3["added validation / logging write"]
    SL --> T4{"retrieval config?"}
    T4 -->|"chunk count or<br/>numCandidates up"| A4["more recall, more latency"]
    SL --> T5{"blocking call inside<br/>an async def?"}
    T5 -->|yes| A5["freezes the event loop<br/>-> shows up EXACTLY as a tail problem"]
    A5 --- MOST["most likely: a retry/timeout<br/>config change, or A5"]
```
