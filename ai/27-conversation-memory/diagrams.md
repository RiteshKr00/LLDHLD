# Conversation memory — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    TURN["user turn arrives<br/>voice or chat"] --> SCOPE
    SCOPE["resolve user_id + thread_id<br/>FAILS CLOSED: no id, no memory"] --> ASM
    ASM["memory assembler<br/>fixed 2,050 token budget"] --> LOG
    ASM --> SUMC
    ASM --> FACT
    LOG[("turn log, append-only, per-user<br/>THE source of truth")] --> PRM
    SUMC[("rolling summary, 300 tok cap<br/>derived, versioned, regenerable")] --> PRM
    FACT[("fact slots + vectors<br/>per-user namespace, ~60 rows")] --> RANK
    RANK["score = cosine x recency decay<br/>LIVE slots only, top 6"] --> PRM
    PRM["prompt: system + facts + summary<br/>+ last 8 turns verbatim"] --> LLM
    LLM["model, streams the answer"] --> OUT
    OUT["response to the user"] -. after the stream closes .-> WR
    WR["async write path, off the hot path<br/>lower priority than live turns"] --> LOG
    WR --> TRIG
    TRIG{"window over 1,600 tokens?<br/>true on 1 turn in 8"} -- yes --> SUMM
    SUMM["summarise + extract, ONE call<br/>cheap model or a batch endpoint"] --> SUMC
    SUMM --> FACT
```

Read it as one turn. The read half is three cheap lookups against a per-user
namespace, assembled to a fixed token budget and handed to the model. The write
half hangs off the *end* of the stream, and on seven turns in eight it does
nothing but append a row. The only synchronous write is the turn-log append,
because that is the source of truth everything else regenerates from.

## 2. Why the cost shape is the whole scenario

```mermaid
flowchart LR
    N0["one thread, turn 300"] --> N1["resend the transcript<br/>59,800 prompt tokens THIS turn"]
    N1 --> N2["cumulative 8.97M tokens<br/>grows as N squared"]
    N0 --> T1["tiered memory<br/>2,050 prompt tokens THIS turn"]
    T1 --> T2["cumulative 0.69M tokens<br/>grows as N"]
    N2 --- W["0.7x at turn 10, 2.3x at turn 50,<br/>13x at 300, 43x at 1000"]
    T2 --- W
    W --> W2["tiered LOSES below turn 12.<br/>Every natural fixture sits there,<br/>which is why this ships broken"]
```

Notice the left end of that ratio. Tiered memory is genuinely more expensive on
short threads, so a ten-turn test rewards the wrong design. The metric that
catches it is memory tokens per turn plotted **against turn index** — you alert
on the slope, never on the level.

## 3. Contradiction: a log cannot resolve it, a slot already has

#### Append-only fact log — the bug

```mermaid
flowchart TB
    A1["Jan: I am vegetarian"] --> AL[("append-only fact rows")]
    A2["Mar: I eat chicken again"] --> AL
    AL --> AR["top-2 retrieval returns BOTH<br/>0.88 vegetarian, 0.71 chicken"]
    AR --> AX["the model picks one,<br/>and is wrong about half the time"]
```

#### Slots — the fix

```mermaid
flowchart TB
    B1["Jan: I am vegetarian"] --> BS["upsert on the slot<br/>(user_id, diet)"]
    B2["Mar: I eat chicken again"] --> BS
    BS --> BL[("live value: eats chicken<br/>old row keeps superseded_at")]
    BL --> BR["retrieval scores LIVE slots only"]
    BL -.-> BH["the superseded row survives<br/>for audit and 'you used to say'"]
```

The conflict is resolved at **write** time, so retrieval has nothing to
disambiguate. A log pushes that decision into the model, which is the one place
in the system with no way to make it.

## 4. Ranking: relevance alone is not enough

```mermaid
flowchart TB
    Q["query: how long should this answer be?"] --> S{"scoring function"}
    S -->|cosine only| C1["0.90 wants exhaustive detail, 75d<br/>0.70 mid-way through onboarding, 40d"]
    C1 --> C2["yesterday's correction does not<br/>even make the top 2"]
    S -->|cosine x decay| D1["score = cosine x 2^(-age/half_life)<br/>0.61 three lines maximum, 1d<br/>0.55 name is Priya, 400d"]
    D1 --> D2["identity gets half_life = none,<br/>so the name survives 400 days"]
    D2 --> D3["preference 30d, state 14d<br/>the class sets the half-life"]
```

Supersession and decay are not the same mechanism. Supersession kills conflict
*within* a slot; decay kills staleness *across* slots, which is what you get
when the extractor emits `answer_style` and `answer_length` as separate rows —
and it will.

## 5. Erasure: the derived artefacts are the hard part

```mermaid
flowchart TB
    DEL["erasure request, user U"] --> T1["delete the turn rows"]
    T1 --> P{"is the summary derived,<br/>with turn ids recorded?"}
    P -->|prose blob| X1["no turn ids recorded<br/>the fact is compiled into the text"]
    X1 --> X2["unremovable surgically,<br/>and unprovable either way"]
    P -->|derived| Y1["derived_from names the turn ids<br/>regenerate from the survivors"]
    Y1 --> Y2["drop facts whose provenance<br/>intersects the deleted turns"]
    Y2 --> Y3["purge vectors, prompt cache,<br/>trace payloads, in-window backups"]
    Y3 --> Y4["orphaned-summary count back to 0<br/>that counter IS the evidence"]
```

Deleting the turn is the easy half. Everything derived from it — the summary,
the extracted facts, their embeddings, the cached prompt — is derived personal
data and has to go with it. That requirement is what forces summaries to be
regenerable rather than authoritative, and it is worth deciding on day one
because it cannot be retrofitted onto a prose store.
