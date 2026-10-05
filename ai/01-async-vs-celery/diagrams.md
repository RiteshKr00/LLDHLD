# async vs Celery — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    U["Client<br/>browser or service"] --> API["FastAPI / DRF<br/>one process, one event loop"]
    API -->|fast path, awaited inline| GEM[("Gemini via LiteLLM<br/>~4s per call, I/O bound")]
    API -->|slow path, apply_async| R[("Redis broker<br/>durable, survives a deploy")]
    API -. 202 queued in milliseconds .-> U
    R --> Q1[["ai_insights queue<br/>bulkhead for LLM work"]]
    R --> Q2[["default queue<br/>emails, cleanups"]]
    Q1 --> W1["LLM workers<br/>high concurrency, acks_late"]
    Q2 --> W2["default workers<br/>low concurrency"]
    W1 --> GEM
    GEM --> V{{"validate<br/>then maker-checker"}}
    V -->|rejected, retry| Q1
    V --> DB[("Postgres<br/>insight rows, audit trail")]
    V --> RB[("Result backend<br/>task state for polling")]
    RB --> API
    W1 -. ack only after success .-> R
```

Two exits from the API: the fast path keeps the caller on the line and pays for it
with a held connection; the slow path hands the work to Redis and answers in
milliseconds. Everything after the broker is durable, retried and observable.

## 2. Where the waiting happens

#### async def + await — one process

```mermaid
flowchart TB
    A1["Request 1"] --> AL["Event loop<br/>free while awaiting"]
    A2["Request 2"] --> AL
    A3["Request 3"] --> AL
    AL -->|await, loop free| AX[("Gemini 4s")]
```

Three requests overlap inside one process; all finish in roughly 4s.

#### async def + BLOCKING — the bug

```mermaid
flowchart TB
    B1["Request 1"] --> BL["Event loop FROZEN<br/>sync call inside async def"]
    B2["Request 2"] -. queued 4s .-> BL
    B3["Request 3"] -. queued 8s .-> BL
    BL --> BX[("Gemini 4s, sync")]
```

One sync call inside `async def` serialises the whole process. Request 3 waits 8s
for work it never asked to queue behind.

#### def — threadpool

```mermaid
flowchart TB
    C1["Request 1"] --> T1["thread 1"] --> CX[("Gemini 4s")]
    C2["Request 2"] --> T2["thread 2"] --> CX
    C3["Request 3"] --> T3["thread 3"] --> CX
```

A plain `def` handler is pushed to the threadpool, so blocking is absorbed —
correct, but bounded by the pool size rather than by memory.

## 3. Celery — the caller stops waiting

```mermaid
sequenceDiagram
    participant U as Client
    participant API as FastAPI / DRF
    participant R as Redis broker
    participant W as ai_insights worker
    participant G as Gemini via LiteLLM
    U->>API: POST /insight
    API->>R: apply_async(queue="ai_insights")
    API-->>U: 202 queued (milliseconds)
    W->>R: reserve task
    W->>G: generate (4s)
    G-->>W: narrative
    W->>W: validate -> maker-checker
    W->>R: ack (acks_late, after success)
    Note over W,R: worker dies before ack -> task redelivered<br/>safe only because the task is idempotent
```

## 4. The bulkhead — why a dedicated queue

#### One shared queue

```mermaid
flowchart LR
    L1["LLM x20"] --> Q1[["default<br/>one queue for everything"]]
    E1["emails"] --> Q1
    Q1 --> WP1["worker pool<br/>every slot held by a 4s LLM call"]
    E1 -. starved .-> WP1
```

Twenty LLM tasks occupy the pool and the emails sit behind them. Nothing is
broken, but the cheap work inherits the slow work's latency.

#### Bulkheaded

```mermaid
flowchart LR
    L2["LLM x20"] --> Q2[["ai_insights"]] --> WPA["LLM workers<br/>high concurrency, I/O bound"]
    E2["emails"] --> Q3[["default"]] --> WPB["default workers<br/>untouched by the LLM burst"]
```

Separate queues and separate worker pools: an LLM burst can only exhaust its own
capacity.

## 5. The decision tree

```mermaid
flowchart TB
    S{"Is the caller<br/>waiting for the result?"} -->|No| D{"Must it survive<br/>a deploy?"}
    D -->|Yes| CEL["Celery: durable, retried, observable"]
    D -->|No| BG["BackgroundTasks: same process, best effort"]
    S -->|Yes| AW{"Does every call<br/>inside have an await?"}
    AW -->|Yes| ASY["async def"]
    AW -->|No| DEF["def — threadpool absorbs blocking"]
    AW -->|Mixed| TT["async def + await asyncio.to_thread"]
```
