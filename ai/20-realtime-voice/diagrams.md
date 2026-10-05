# Real-time voice at 50k — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    C["50k callers<br/>one turn every 8s"] --> TEL
    TEL["Telephony edge, per region<br/>terminates the call"] --> ADM
    ADM{"Admission control<br/>tenant floor + vendor headroom"} -->|reject at setup| TXT
    ADM -->|accept| STT
    STT["STT stream, finalise on pause<br/>partial transcript emitted early"] --> RET
    STT -. partial .-> PRE["Speculative retrieval<br/>overlaps the caller still talking"]
    RET["Retrieval, regional replica<br/>p99 310 ms - the tight stage"] --> LLM
    PRE -. warms .-> RET
    LLM["Custom-LLM webhook, your server<br/>streams tokens, does not buffer"] --> SEG
    SEG["Clause-boundary segmenter<br/>first clause goes now"] --> TTS
    TTS["TTS stream<br/>binding vendor quota: 20k"] --> C
    TXT["Degrade to text<br/>honest, still useful"] --> C
    LLM -. async .-> MET[("Per-call metering<br/>5 vendors, never blocks audio")]
    MET --> BRK["Per-tenant spend breaker<br/>and the concurrency cap"]
    BRK -. feeds .-> ADM
```

The whole diagram is one turn. Everything on the solid path is inside a 1,000 ms budget and
runs **serially**. Everything dotted is off the critical path and must stay there — a metering
write that blocks is a dropped call.

---

## 2. Why the autoscaler scales the wrong way

#### On CPU: the normal state looks like an idle fleet

```mermaid
flowchart LR
    S["50,000 sessions"] --> B["100 boxes<br/>CPU steady at 60%"]
    B --> M["Autoscaler reads CPU<br/>target met, or scale IN"]
    M --> D["capacity 40,000<br/>10,000 callers get nothing"]
    D --- W["the box was WAITING on sockets.<br/>CPU was never the saturating resource"]
```

#### On sessions: measure the thing that runs out

```mermaid
flowchart LR
    S2["50,000 sessions"] --> B2["157 boxes<br/>sessions at 80% of limit"]
    B2 --> M2{"Autoscaler reads open sessions<br/>headroom 25%"}
    M2 -->|under 80%| OK["hold"]
    M2 -->|over 80%| UP["scale out before saturation"]
```

Same fleet, same instant: 60% CPU and 125% of the session limit. Holding a non-binding metric
at target tells you nothing, and here it actively fires scale-in during an outage.

---

## 3. The serial budget, and what streaming buys

```mermaid
flowchart LR
    A["STT finalise<br/>120 ms"] --> B["retrieval<br/>90 ms"]
    B --> C2["LLM first token<br/>240 ms"]
    C2 --> D2["LLM full response<br/>700 ms"]
    D2 --> E["TTS first audio<br/>180 ms"]
    E --> F["network<br/>60 ms"]
    F --> G["1390 ms - over budget"]
```

```mermaid
flowchart LR
    A2["STT finalise<br/>120 ms"] --> B3["retrieval<br/>90 ms"]
    B3 --> C3["LLM first token<br/>240 ms"]
    C3 --> E2["TTS on first clause<br/>180 ms"]
    E2 --> F2["network<br/>60 ms"]
    F2 --> G2["690 ms - within budget"]
    D3["LLM keeps generating<br/>while audio already plays"] -. overlapped .-> E2
```

The only stage removed is the wait for the last token. 700 ms, for plumbing. Note what is
*not* removable: every remaining box is in the path, every turn, and they add rather than
overlap.

---

## 4. Why a queue rescues chat and destroys voice

```mermaid
flowchart TB
    SP["3-tick spike to 180% of capacity"] --> Q{"overflow"}
    Q -->|chat| QQ["queue it<br/>backlog peaks at 15,000"]
    QQ --> CS["100% served, some late<br/>the user waited and got an answer"]
    Q -->|voice| VD["nowhere to put the time"]
    VD --> VS["75% served<br/>15,000 turns are dead air, gone"]
    VS --- NB["a turn served 4s late is not served:<br/>the caller assumed a dropped line<br/>and started talking over it"]
```

Total capacity across the window exceeded total demand — the spike was survivable. Chat pays
in latency and recovers fully; voice has no latency to spend. This is the *favourable* case for
queueing: against a sustained shortfall, the queue serves no more than voice does and merely
hides the deficit in an unbounded backlog.

---

## 5. The real ceiling is somebody else's quota

```mermaid
flowchart TB
    N["need: 50,000 concurrent"] --> T{"vendor quota ÷ attach rate"}
    T --> V1["TTS: 20,000 at 100%<br/>supports 20,000"]
    T --> V2["avatar: 8,000 at 15%<br/>supports 53,333"]
    T --> V3["STT: 60,000 at 100%<br/>supports 60,000"]
    T --> V4["telephony: 75,000 at 100%<br/>supports 75,000"]
    V1 --> B4["TTS binds at 20,000<br/>a contract, not a deploy"]
    B4 --> R1["negotiate the quota"]
    B4 --> R2["second vendor behind an abstraction"]
    B4 --> R3["self-host TTS for low tiers"]
    B4 --> R4["cap admission until one lands"]
```

Divide by attach rate before ranking. The avatar's 8,000 looks like the tightest number on the
page and is not the constraint, because it rides on only 15% of calls.

---

## 6. Per-tenant caps as blast-radius control

```mermaid
flowchart LR
    D["demand: acme 34k, globex 9k, initech 7k<br/>available: 20,000"] --> M3{"allocation"}
    M3 -->|first-come| FC["acme 20,000<br/>globex 0, initech 0"]
    M3 -->|floor + burst| FB["acme 6,666<br/>globex 6,666, initech 6,666"]
    FC --- X2["one tenant's campaign<br/>is everyone else's outage"]
    FB --- Y["floors guaranteed, spare capacity<br/>lent out and reclaimed first"]
```

Enforced at **admission**. Rejecting a call at setup is a product decision the caller can act
on; dropping one at ninety seconds is an outage.
