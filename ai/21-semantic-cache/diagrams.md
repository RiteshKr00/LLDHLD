# Semantic cache — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CL["client request<br/>question + auth token"] --> API
    API["API: authn, resolve permission set<br/>FAILS CLOSED - no scope, no lookup"] --> KEY
    KEY["build the namespace<br/>tenant + scope hash + corpus v<br/>+ model id + prompt v + locale"] --> L0
    L0[("L0 exact hash, 1ms, no embedding<br/>catches the ~10% byte-identical")] -->|hit| RESP["serve, ~25ms end to end"]
    L0 -->|miss| EMB["embed the query, ~15ms"]
    EMB --> ANN["ANN inside THIS namespace only<br/>nothing else was ever a candidate"]
    ANN --> TH{"best cosine at or above 0.93?"}
    TH -->|no| SF["single-flight on the key<br/>one miss does the work, rest wait"]
    TH -->|yes| GD{"numerals and negations<br/>identical on both sides?"}
    GD -->|no| SF
    GD -->|yes| RESP
    SF --> GEN["retrieve + generate, ~2s"]
    GEN --> ADM
    ADM{"admissible? complete, not degraded,<br/>not personalised, above the floor"} -->|no| RESP
    ADM -->|yes| ST
    ST[("cache store: ~400k entries, ~2.4 GB<br/>TTL 24h, refusals 15m")] --> RESP
    BUS["corpus re-index finished<br/>corpus version + 1"] --> KEY
```

Read it as one request. Authentication and scope resolution happen **before** the cache is
touched, because the resolved scope is an input to the key — a cache in front of auth serves
across tenants. Two gates decide a hit, not one: the threshold picks a candidate, the guard
decides whether it may be served. The re-index event feeds the key builder, not a delete job.

## 2. The false hit — why the threshold cannot do this alone

#### Threshold only

```mermaid
flowchart TB
    Q1["probe: notice period for band 5"] --> V1["cosine vs the cached band 3 entry = 0.961"]
    V1 --> T1{"0.961 at or above 0.93?"}
    T1 -->|yes| S1["SERVE the band 3 answer<br/>wrong answer, 25ms, zero cost"]
    S1 --> M1["hit rate went UP<br/>no error, no alert, no trace"]
```

#### Threshold plus the discriminative-token guard

```mermaid
flowchart TB
    Q2["probe: notice period for band 5"] --> V2["cosine 0.961, above the threshold"]
    V2 --> G2{"numerals: 5 versus 3"}
    G2 -->|differ| MS["MISS - go to the model<br/>hit rate went DOWN, correctness held"]
    Q3["probe: leave is NOT carried forward"] --> V3["cosine 0.975 vs the positive answer"]
    V3 --> G3{"negations: NOT versus none"}
    G3 -->|differ| MS
    Q4["probe: how long is the resignation<br/>warning for band 3"] --> V4["cosine 0.943 - the LOWEST of the three"]
    V4 --> G4{"numerals 3 and 3, no negation"}
    G4 -->|match| OK["serve - the only correct hit"]
```

The genuine paraphrase scores **lower** than both wrong answers. That is the whole point: there
is no threshold anywhere on the number line that admits 0.943 and rejects 0.961 and 0.975.
Recall comes from the vector, precision comes from the lexical comparison.

## 3. The key, dimension by dimension

```mermaid
flowchart LR
    K["cache key"] --> D1["tenant<br/>prevents: cross-tenant leak"]
    K --> D2["resolved permission set, hashed<br/>prevents: intra-tenant ACL leak"]
    K --> D3["corpus version<br/>prevents: the pre-re-index world"]
    K --> D4["model id + prompt version<br/>prevents: replaying an answer the<br/>current prompt would not produce"]
    K --> D5["locale<br/>prevents: answering in the wrong language"]
    D2 --- N1["hash the SCOPE SET, never the user id<br/>a namespace of one never hits"]
```

Each dimension buys a correctness property and costs hit rate. Corpus version is free in steady
state and costs 100% on the day it changes — which is the next diagram.

## 4. Invalidation, cold start, and the 09:00 problem

```mermaid
flowchart TB
    RE["nightly re-index completes at 03:00"] --> BUMP["corpus version 41 -> 42"]
    BUMP --> NS["every v41 entry is now UNREACHABLE<br/>no scan, no deletes, instantly consistent"]
    NS --> CS["but the cache is cold at 03:01<br/>and 09:00 is coming"]
    CS --> WARM["pre-warm BEFORE the flip:<br/>replay yesterday's top 5k queries<br/>through v42 offline"]
    CS --> SFL["single-flight per key<br/>200 identical misses -> ONE model call"]
    ALT["the alternative: delete-by-query<br/>scan 400k entries, eventually consistent,<br/>and you WILL miss some"] -.- NS
```

Version-in-key turns invalidation into a config change. What it does not solve is the cold
window it creates, so pre-warm before the flip and never bump in business hours — a cold cache
at peak presents as a provider rate-limit incident, not as a cache problem.

## 5. What you measure, and what it hides

```mermaid
flowchart TB
    H["served hits"] --> SAMP["shadow 1% through the real model"]
    SAMP --> AGR{"agreement at or above 98%?"}
    AGR -->|no| TIGHT["threshold too loose, or guard too narrow"]
    AGR -->|yes| OK["precision on hits - the actual metric"]
    DIST["distribution of served cosines"] --> CREEP["mass drifting down toward 0.93<br/>= false hits are already arriving"]
    JUMP["hit rate JUMPED after a deploy"] --> SUS["treat as an incident, not a win:<br/>normalisation changed, or a key<br/>dimension was dropped"]
```

Three signals, only one of which is the hit rate. The shadow sample is the ground truth; the
cosine distribution is the leading indicator; a sudden hit-rate improvement with no product
change is the alarm most teams have wired up as a celebration.
