# LLM gateway — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CLIENT["calling services<br/>chat, summariser, extractor"] --> API
    API["gateway API: ONE internal call shape<br/>authn + tenant resolve"] --> RTR
    RTR["router policy<br/>model choice, per-tenant override"] --> LIM
    LIM[("shared token buckets in Redis<br/>per provider AND per tenant")] -- admitted --> AD
    LIM -. over quota .-> WAIT["queue or fail fast<br/>traffic SHAPED before a provider 429"]
    AD["provider adapter<br/>auth + shape + ERROR TAXONOMY"] --> RTY
    RTY["retry lives HERE, one layer only<br/>transport + 429, backoff + jitter"] --> PRV
    RTY -. provider hard-down .-> FB["fallback adapter<br/>same call shape, different provider"]
    FB --> PRV
    PRV["provider API<br/>streams chunks back"] --> STR
    STR["passthrough stream<br/>yield each chunk, NEVER buffer"] --> CLIENT
    STR --> TALLY["tally in flight<br/>n += 1 per chunk, no collection"]
    TALLY --> LEDGER[("usage ledger<br/>async write, one row per call")]
    LEDGER --> OBS["metrics + traces<br/>latency, error class, spend per tenant"]
```

Read it as one request: caller in at the top, chunks back out to the caller from
the passthrough stream, and everything else — quota, retry, fallback, accounting
— hanging off the same single path. The sections below zoom into four points on
it that are usually got wrong.

## 2. What the gateway owns, and what it prevents

#### Without a gateway — N call sites, 7 problems each

```mermaid
flowchart TB
    C1[chat service] --> P1[provider SDK]
    C2[summariser] --> P2[provider SDK]
    C3[extractor] --> P3[provider SDK]
    P1 -.- X["each call site: own keys, own retry,<br/>own 429 handling,<br/>unattributable cost.<br/>adding a provider = N-file migration"]
```

Every problem in that note is repeated once per call site, and nothing in the
system can answer "what did tenant X spend last week".

#### With a gateway

```mermaid
flowchart TB
    D1[chat] --> G
    D2[summariser] --> G
    D3[extractor] --> G
    G["GATEWAY<br/>one internal call shape"] --> AD["per-provider adapters<br/>auth + shape + ERROR TAXONOMY"]
    G --> TB[("shared token buckets in Redis<br/>per provider AND per tenant")]
    G --> RT["retry: transport errors ONLY<br/>backoff + jitter"]
    AD --> PR[providers]
    G --> LG[("usage ledger, async write")]
```

Adding a provider is now one adapter, not an N-file migration.

## 3. Streaming: the bug and the fix

#### Buffered — the common bug

```mermaid
flowchart TB
    B1[provider chunk 1] --> BUF["collect ALL chunks<br/>so we can count tokens"]
    B2[chunk 2] --> BUF
    B3[chunk N] --> BUF
    BUF --> BC[count + log] --> BR["return everything at once"]
    BR --- BX["time-to-first-chunk = FULL generation<br/>the entire latency budget, spent<br/>no non-streaming test catches it"]
```

#### Passthrough — the fix

```mermaid
flowchart TB
    P1[chunk 1] --> Y1[yield immediately] --> CL[caller]
    P1 --> T["tally n += 1"]
    P2[chunk N] --> Y2[yield] --> CL
    P2 --> T
    T --> END["stream closes:<br/>ONE usage record, async"]
```

Same accounting, same one usage record — the counter just rides alongside the
yield instead of gating it.

## 4. Why rate state must be shared

```mermaid
flowchart TB
    Q[("provider quota: 10 req/s")] --- N{where does the<br/>bucket live?}
    N -->|per process| L["instance 1: bucket(10)<br/>instance 2: bucket(10)<br/>... x10 instances"]
    L --> LO["100 admitted against a 10/s quota<br/>-> 429s anyway<br/>-> 'the limiter does not work'"]
    N -->|shared| S[("ONE bucket in Redis<br/>keyed per provider AND per tenant")]
    S --> SO["10 admitted, the rest queued<br/>traffic SHAPED before the<br/>provider ever rejects it"]
```

## 5. Retry amplification

#### Retries in two layers

```mermaid
flowchart LR
    A1[client x3] --> A2[gateway x3] --> A3["9 provider calls<br/>for ONE request"]
    A3 --> A4["aimed at a service<br/>that is ALREADY failing"]
```

#### One layer per concern

```mermaid
flowchart LR
    G3["worker: 'whole task failed,<br/>re-run later'"] --> G1
    G1["gateway: 429 / 5xx / timeout<br/>backoff + JITTER"] --> G2["3 calls, bounded"]
```

The worker retries the task, the gateway retries the call. Multiply the two and
you get the block above it.
