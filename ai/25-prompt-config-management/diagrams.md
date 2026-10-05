# Prompt and config management — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    AUTH["authoring surfaces<br/>dashboard, PR, API"] --> CR["change request<br/>never a direct write"]
    CR --> GATE{"promotion gate<br/>eval + token budget + contract"}
    GATE -->|blocked| AUTH
    GATE -->|passes| STORE[("version store, write-once<br/>id = sha256 of the whole bundle")]
    STORE --> BIND[("binding table<br/>feature, env, scope to bundle id")]
    BIND --> SNAP["snapshot builder<br/>the whole corpus, about 5 MB"]
    SNAP --> PUSH["pub/sub push to every pod<br/>10s poll as the fallback"]
    PUSH --> RES["in-process resolver<br/>total precedence order, microseconds"]
    RES --> CAN{"canary arm<br/>hashed on conversation id"}
    CAN --> CALL["LLM call<br/>prompt + model + decode params"]
    CALL --> TR[("trace and logs<br/>carry the resolved bundle id")]
    TR --> GRD["guardrail metrics, per arm"]
    GRD -->|breach| ROLL["auto-revert<br/>binding flips back in 30s"]
    ROLL --> BIND
    GATE --> AUD[("audit log, append-only<br/>who, when, diff, verdict")]
    ROLL --> AUD
```

Read it as one change and one request sharing a spine. The control plane runs
left of the resolver — nothing there is in the request path. The data plane
resolves from an in-memory snapshot, so a config-store outage cannot fail an LLM
call. Two edges close the loop: guardrails to auto-revert, and everything to the
audit log.

---

## 2. Precedence — the thing that actually breaks

```mermaid
flowchart TB
    REQ["request: tenant t017, env prod, feature chat"] --> P4{"request pin?"}
    P4 -->|yes| WIN["resolved bundle id<br/>PLUS the rule that won"]
    P4 -->|no| P3{"tenant + env binding?"}
    P3 -->|yes| WIN
    P3 -->|no| P2{"tenant binding?"}
    P2 -->|yes| WIN
    P2 -->|no| P1{"env binding?"}
    P1 -->|yes| WIN
    P1 -->|no| P0["global default"]
    P0 --> WIN
    WIN --> LOG[("logged on EVERY request<br/>bundle id + winning rule")]
    TIE["two rules, same rank<br/>REJECTED at publish time"] -.-> P2
```

Highest rank wins outright — never a merge, because a merged prompt is one nobody
wrote and nobody evaluated. The dotted edge is the part people skip: equal-rank
ambiguity is refused when the binding set is published, not resolved arbitrarily
at read time. And the resolver returns *which* rule won, so "why did this tenant
get that prompt" is a log line rather than an argument.

---

## 3. Rollback: rows versus versions

#### Mutable rows — rollback is a rewrite

```mermaid
flowchart LR
    E1["edit 1"] --> ROW[("prompts row<br/>text, updated_at")]
    E2["edit 2"] --> ROW
    E3["edit 3"] --> ROW
    ROW --> BAD["rollback = retype from memory<br/>then revert PR, CI, deploy<br/>720s, and a THIRD prompt"]
```

#### Immutable versions + a binding — rollback is a pointer flip

```mermaid
flowchart LR
    P1["publish v1"] --> VS[("version store, write-once<br/>id = sha256 of the bundle")]
    P2["publish v2"] --> VS
    P3["publish v3"] --> VS
    VS --> BND[("binding: chat, prod, global<br/>currently v3")]
    BND --> FLIP["rollback = point at v1<br/>push snapshot, 30s, byte-exact"]
```

24× faster is the headline; byte-exactness is the point. The mutable row has
nothing to roll back *to*, so recovery depends on someone remembering a prompt
correctly during an incident.

---

## 4. The gate: available versus unavoidable

#### Available — a gate with a door beside it

```mermaid
flowchart LR
    PM["PM, dashboard"] --> DIR["direct write to live config"]
    ENG["engineer, PR"] --> CI["CI eval gate"]
    CI --> LIVE[("live binding")]
    DIR --> LIVE
    DIR -.- NOTE["about 35% of 400 changes a year<br/>never meet a gate"]
```

#### Unavoidable — one writer

```mermaid
flowchart TB
    PM2["PM, dashboard"] --> CRQ["change request"]
    ENG2["engineer, PR"] --> CRQ
    CRQ --> G1["eval gate<br/>hard metrics vs the golden set"]
    G1 --> G2["token budget<br/>+500 tokens = $400/day"]
    G2 --> G3["contract check<br/>tool schema, output shape"]
    G3 --> PS["promotion service<br/>the ONLY writer"]
    PS --> LIVE2[("live binding")]
    BG["break-glass: skips the eval gate<br/>pages, logs a reason, expires in 4h"] --> PS
```

The difference is not the checks — both diagrams run the same ones. It is whether
a second write path exists. Break-glass is drawn deliberately: a gate with no
emergency path becomes the outage the first time its provider is down.

---

## 5. The promotion lifecycle, with auto-revert

```mermaid
flowchart TB
    CAND["candidate bundle"] --> G{"gate passes?"}
    G -->|no| BACK["back to the author<br/>with the failing metrics"]
    G -->|yes| C1["canary 1%<br/>bucketed on conversation id"]
    C1 --> GM{"guardrails per feature<br/>parse fail, refusal, time-to-audio"}
    GM -->|breach| RB["auto-revert<br/>binding flips back, 30s"]
    GM -->|green| C2["widen to 10, then 50"]
    C2 --> GM
    GM -->|green at 50| FULL["100%, the new default"]
    RB --> AUD[("audit row: from, to, gate scores,<br/>canary result, reason")]
    FULL --> AUD
```

Bucketing on conversation id rather than request id is the detail that makes the
canary measurable: a thread that straddles both arms measures the seam, not the
change. Guardrails differ per feature — extraction watches parse failures, voice
watches time-to-first-audio — and a single shared error rate catches neither.
