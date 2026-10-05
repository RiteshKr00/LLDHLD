# PII redaction gateway — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CALL["calling service<br/>chat, extraction, voice turn"]
    ASM["prompt assembly, one tested function<br/>question + chunks + history + tools"]
    DET["deterministic recognisers + checksums<br/>Verhoeff, Luhn, PAN structure, ~3 ms"]
    AMB{"ambiguous free text left?"}
    POL["treatment table in code<br/>entity x destination<br/>model may only push stricter"]
    TOK["tokenise: span re-found in code<br/>NEVER a model-reported offset"]
    VLT[("token vault<br/>HMAC per tenant, 24h TTL")]
    DEST{"destination"}
    EGR["egress proxy<br/>provider domains reachable ONLY here"]
    TP["third-party provider"]
    VPC["in-VPC or local model<br/>no redaction needed"]
    RH["rehydrator on the stream<br/>carry buffer for split placeholders"]
    LOG[("audit log: redacted text only<br/>counts by type, rule id, policy version")]
    SMP["async 2 percent sample to the extractor<br/>finds the types you never enumerated"]

    CALL --> ASM
    ASM --> DET
    DET --> AMB
    AMB -->|no| POL
    AMB -->|yes| DEST
    AMB -.-> SMP
    POL --> TOK
    TOK --> VLT
    TOK --> DEST
    DEST -->|clean| EGR
    DEST -->|sensitive or detector down| VPC
    EGR --> TP
    TP --> RH
    VPC --> RH
    VLT --> RH
    RH --> CALL
    RH --> LOG
    SMP -.-> DET
```

Read it as one request. The stage sits **after** prompt assembly, because the retrieved chunks
and tool outputs carry more PII than the user's question ever does. Ambiguity is a branch to a
different **destination**, not a wait on a model. The vault is touched twice — mint on the way
out, look up on the way back — and it is the only new store this design creates. The egress
proxy is the box that turns the whole thing from a convention into a guarantee: nothing else in
the estate can reach a provider domain at all.

---

## 2. Why a checksum is free precision

#### Bare regex

```mermaid
flowchart LR
    N["60 twelve-digit numbers<br/>from one day of prompts"] --> RX["12-digit regex<br/>no arithmetic"]
    RX --> T1["20 true"]
    RX --> F1["40 false<br/>order ids, invoices, refs"]
    F1 --> P1["precision 33 percent<br/>two false for every true"]
```

#### The same regex, plus the check digit

```mermaid
flowchart LR
    N2["the same 60 numbers"] --> RX2["12-digit regex<br/>plus the Verhoeff check digit"]
    RX2 --> T2["20 true<br/>recall unchanged at 100 percent"]
    RX2 --> F2["about 4 false<br/>a random number passes 1 in 10"]
    F2 --> P2["precision 83 percent<br/>zero added latency"]
```

The identifiers people worry about mostly carry arithmetic — Verhoeff on Aadhaar, Luhn on
cards, structure on PAN and GSTIN, a bank-code table for IFSC. Using it is the only precision
fix that costs no recall, which matters because everything else in this design is tuned to
over-detect.

---

## 3. Spans: the model's offsets index a string you no longer have

#### Trusting start and end

```mermaid
flowchart TB
    EX["extractor sees ONE 400-char chunk"] --> RET["returns text, type, start, end"]
    RET --> APP["offsets applied to the 6k-char<br/>assembled prompt"]
    APP --> B1["instruction line shredded"]
    APP --> B2["name and email UNTOUCHED<br/>the leak is still in the payload"]
    APP --> B3["no exception, no error metric<br/>nothing to alert on"]
```

#### Re-finding the substring in code

```mermaid
flowchart TB
    EX2["extractor returns text and type only"] --> FIND{"substring present in<br/>the prompt you will send?"}
    FIND -->|yes| REP["replace EVERY occurrence<br/>with a typed placeholder"]
    FIND -->|no| UNL["count as unlocatable"]
    UNL --> FC["third-party call BLOCKED<br/>reroute to the in-VPC model"]
    REP --> OK["outbound payload verified clean"]
```

The model was not lying about the offsets — it never saw the assembled prompt. Substrings are
invariant to where they sit, positions are not. And note the `unlocatable` branch: an entity the
model reported but you cannot locate is not a clean prompt, it is an unverified one.

---

## 4. Reversal, and the placeholder that arrives in two pieces

#### Naive per-chunk substitution

```mermaid
flowchart LR
    C1["chunk 1: I have emailed"] --> S1["substitute per chunk<br/>no match"]
    C2["chunk 2: EMA<br/>first half of the token"] --> S2["no match"]
    C3["chunk 3: IL_1 and copied"] --> S3["no match"]
    S1 --> U["user reads the placeholder<br/>instead of the address"]
    S2 --> U
    S3 --> U
```

#### With a carry buffer

```mermaid
flowchart LR
    D1["chunk 2 arrives split"] --> CB["carry buffer<br/>hold back from the last open token"]
    CB --> D2["chunk 3 completes it"]
    D2 --> SW["one substitution<br/>vault lookup by token"]
    SW --> OUT["user reads the real address<br/>carry capped so TTFT stays bounded"]
```

Same failure shape as buffering a stream to count tokens: invisible to every non-streaming
test, and the first thing a user reports. The cap on the carry is what keeps the fix from
becoming the bug it replaced.

---

## 5. Fail closed means change the destination, not skip the check

```mermaid
flowchart TB
    R["redaction stage"] --> Q{"detector healthy?"}
    Q -->|healthy and prompt clean| TP["third-party provider"]
    Q -->|healthy but sensitive| VPC["in-VPC or local model"]
    Q -->|timeout or error| FC{"is a local model available?"}
    FC -->|yes| VPC
    FC -->|no| REF["refuse the request<br/>never skip the check"]
    VPC --> DG["response marked degraded<br/>weaker model, same answer shape"]
    TP --> NORM["normal path"]
```

The whole ladder turns on one clarifying question. With a local or in-VPC model, a detector
outage is a quality event; without one, it is an availability event. Notice this is the
opposite call from rate limiting, where failing open is right — a missed rate limit costs
money, a missed redaction costs a disclosure.
