# Voice — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CALL["Caller<br/>PSTN or WebRTC"] --> VP["Voice platform<br/>STT, TTS, endpointing<br/>runs the call loop"]
    MINT["mintVoiceToken<br/>purpose=VOICE, TTL<br/>carries convId"] -.->|voice-only JWT<br/>at call setup| VP
    VP -->|per turn<br/>POST /voice/llm| EP["Your server<br/>OpenAI-shaped endpoint"]
    EP --> VER{"verifyVoiceToken<br/>purpose === VOICE?"}
    VER -.->|wrong purpose<br/>or expired| DENY["401<br/>useless on every other route"]
    VER -->|yes| GUARD["turn guard<br/>normalise, isRefiredTurn"]
    GUARD --> CTX["rebuild context<br/>discard their system msg"]
    CTX --> RET["tenant-scoped retrieval<br/>inside the turn budget"]
    RET --> VDB[("vector store<br/>tenant filter, ANN params")]
    VDB --> LLM["Gemini<br/>latency-tuned model"]
    LLM --> ENV["chunk envelope<br/>chat.completion.chunk"]
    ENV -->|first token<br/>not the full reply| VP
    VP -->|streamed<br/>TTS audio| CALL
    ENV -.-> CONV[("conversation store<br/>convId from the token")]
    VP -.-> MET[("per-call metering<br/>STT, TTS, avatar<br/>LLM, platform")]
    LLM -.-> MET
```

One extra hop in the real-time loop, and it is yours. Everything that makes the twin *the
twin* — persona, guardrails, tenant scope, versioning — lives in the boxes between
`verifyVoiceToken` and the chunk envelope. The vendor keeps STT, TTS and turn detection and
never holds the prompt. Two things to notice on the return path: chunks go back the moment
the model produces them, because that whole chain is serial inside one sub-second budget;
and the dotted edges are the parts the caller never sees — the persisted turn, and the
metering that makes per-tenant caps possible at scale.

## 2. The inversion

#### Default — the vendor owns the brain

```mermaid
flowchart TB
    U1[Caller] --> V1[Voice platform]
    V1 --> P1["prompt in THEIR dashboard"]
    P1 --> L1[their LLM]
    L1 --> V1
    V1 -.->|transcript only| A1[Your app]
    A1 -.- X1["no per-turn retrieval<br/>no tenant scope<br/>unversioned prompt"]
```

#### Inverted — you are the model provider

```mermaid
flowchart TB
    U2[Caller] --> V2["Voice platform<br/>STT + TTS + call loop"]
    V2 -->|POST /voice/llm<br/>+ voice-only JWT| S2[YOUR server]
    S2 --> D2[discard their system msg]
    D2 --> R2["rebuild: persona + guardrails<br/>+ tenant-scoped retrieval"]
    R2 --> G2[Gemini]
    G2 --> C2["stream chat.completion.chunk"]
    C2 --> V2
    S2 --> PS[("persist turn server-side<br/>convId from the token")]
```

Same caller, same platform. The only thing that moved is **where the prompt lives** — and
with it grounding, tenancy, versioning and cross-surface consistency. In the first diagram
your app is a spectator holding a transcript; in the second it is the brain.

## 3. The token boundary

```mermaid
flowchart LR
    M["mintVoiceToken<br/>purpose=VOICE, expiresIn=TTL"] --> T[["JWT held by the VENDOR"]]
    T --> E1["/voice/llm"] --> V{"purpose === VOICE?"}
    V -->|yes| OK[serve the turn]
    T -.->|leaked / replayed| E2["/api/users"] --> AM[normal auth middleware]
    AM -.->|rejects this purpose| DENY[401]
    T -.->|after TTL| EXP[expired -> 401]
```

The dotted edges are the point: not "how do we keep it secret" but "what is the blast radius
when it leaks". One endpoint, for minutes.

## 4. The serial latency budget

```mermaid
flowchart LR
    A[user stops speaking] --> B[STT finalise]
    B --> C[retrieval]
    C --> D[LLM first token]
    D --> E[TTS first audio]
    E --> F[network to caller]
    F --> G{"total under ~1s?"}
    G -->|yes| NAT[feels natural]
    G -->|no| LAG[feels laggy]
```

Nothing here is parallel, so every stage must stream. Waiting for any one of them to finish
blows the budget on its own.

## 5. Six turn-taking failure classes

```mermaid
stateDiagram-v2
    [*] --> Listening
    Listening --> Thinking: endpoint detected
    Thinking --> Speaking: first chunk
    Speaking --> Listening: turn complete
    Thinking --> Thinking: RE-FIRE, answered twice<br/>(isRefiredTurn suppresses)
    Listening --> Listening: STT upgrade broke finalise<br/>-> listens forever
    Speaking --> Listening: barge-in fired on OWN TTS echo<br/>-> cut off its own reply
    Listening --> Thinking: mid-sentence pause<br/>-> one question split in two
    Thinking --> [*]: malformed envelope<br/>-> HTTP 200, reply discarded
    [*] --> Listening: ~10s cold start<br/>-> first call after deploy dies
```

None are algorithmically hard. They are invisible until you are on a live call, and each one
needed its own regression test.
