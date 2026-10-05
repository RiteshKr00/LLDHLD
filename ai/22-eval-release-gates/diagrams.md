# Eval and release gates — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    PR["PR: code, prompt text, model id,<br/>decode params, retrieval config"] --> MAN
    MAN["manifest.lock<br/>content hash of every one of those"] --> TIER
    TIER["tier and cache<br/>smoke on push, full on merge<br/>results keyed by manifest hash"] --> HARN
    GOLD[("golden set, versioned in the repo<br/>800 cases, provenance per case")] --> HARN
    HARN["harness: IMPORTS the production<br/>grounding and scoring modules"] --> SCORE
    SCORE["deterministic scorers first<br/>judge is a SOFT signal only"] --> CARD
    CARD[("scorecard artifact<br/>per case, plus coverage")] --> GATE
    BASE[("baseline scorecard<br/>pinned to main's manifest hash")] --> GATE
    GATE{"gate evaluator, declared as data<br/>hard or soft, pass or fail or NO-DATA"}
    GATE -->|"fail or no-data"| BLOCK["block the merge<br/>reasons on the PR, named per case"]
    GATE -->|"all hard gates pass"| CAN["canary at 5 percent behind a flag<br/>guardrails defined PER FEATURE"]
    CAN -->|"guardrail breach"| RB["auto-rollback, flag off<br/>breaching sessions become cases"]
    CAN -->|"clean for 24h"| PROM["promote to 100 percent<br/>pin the manifest hash in the deploy"]
    PROM --> SAMP["production sampler<br/>stratified weekly refresh PR"]
    SAMP --> GOLD
    RB --> GOLD
```

Read it as one change: a prompt edit enters at the top and is hashed *before* anything is
scored, because the hash is what the gate keys on — a text file with no code diff still
triggers a full run. Two loops close back onto the golden set: the weekly production sample,
and every canary rollback. Without those the set is a snapshot, and a snapshot rots.

---

## 2. The gate evaluator — three states, and no-data blocks

```mermaid
flowchart TB
    M["metric computed for one gate"] --> Q{"is there data<br/>for every case?"}
    Q -->|no| ND["NO-DATA"]
    Q -->|yes| V{"value clears<br/>the threshold?"}
    V -->|yes| P["PASS"]
    V -->|no| F["FAIL"]
    ND --> H{"hard or soft?"}
    F --> H
    H -->|hard| BLK["BLOCK the release"]
    H -->|soft| WARN["annotate the PR, do not block"]
    P --> OK["contributes to the verdict"]
```

The whole design is in the first diamond. Model this as a boolean and "no data" must collapse
into pass or fail — and the comfortable default makes every un-evaluable gate silently green.
That is the bug that once shipped a regressed enrolment figure under *"all hard gates pass"*.
Same instinct as fail-closed tenant scoping: when the answer is unknown, take the restrictive
default.

---

## 3. Why the aggregate is blind

```mermaid
flowchart LR
    A["composite score<br/>unchanged to 4 decimal places"] --> AG{"aggregate gate"}
    AG -->|"delta inside the floor"| SHIP["no measurable change<br/>SHIP IT"]
    B["paired per-case diff<br/>same cases, same repeats"] --> PC{"per-case gate"}
    PC -->|"6 cases fixed"| GOOD["report as a win"]
    PC -->|"7 cases newly failing"| BAD["BLOCK: a new failure is a<br/>regression whatever the mean did"]
```

`solution.py` runs exactly this. Six fixes cancelling seven breaks is invisible to a mean and
obvious to a paired diff. Notice also that the two gates need different noise floors — averaging
60 cases shrinks noise by root-60, so a threshold borrowed from the composite would flag half
the set as regressed.

---

## 4. Offline gate to online canary — guardrails differ per feature

```mermaid
flowchart TB
    G["all hard gates pass offline"] --> C["canary at 5 percent, flag-gated"]
    C --> R["RAG chat<br/>refusal rate, empty-retrieval rate,<br/>thumbs-down rate"]
    C --> X["extraction<br/>schema-parse failures, repair rate"]
    C --> V["voice turn<br/>p95 time-to-first-token,<br/>barge-in rate, call-abandon rate"]
    R --> D{"any guardrail past<br/>its own noise floor?"}
    X --> D
    V --> D
    D -->|yes| RB["flag off in seconds<br/>mine the sessions for new cases"]
    D -->|no| RAMP["ramp 5, then 25, then 100"]
```

Naming a *different* guardrail set per feature is what separates this from "add a canary".
Extraction fails as a parse error you can count; voice fails as latency and people talking over
the model; chat fails as a refusal or a shrug. One dashboard of "error rate" catches none of them.

---

## 5. Golden-set rot — the thing that breaks first

```mermaid
flowchart LR
    P1["production traffic, month 1"] --> GS["golden set<br/>sampled once, then frozen"]
    P2["production traffic, month 9<br/>new tenants, new doc types,<br/>new phrasings"] -.->|"never sampled again"| GS
    GS --> GATE["the gate stays green"]
    P2 --> USERS["users hit the new cases<br/>and the answers are wrong"]
    GATE -.->|"scoring a distribution<br/>that no longer exists"| USERS
    REF["weekly stratified sample,<br/>plus every incident as a case"] --> GS
```

This is first in the break-order because every other failure here is loud and this one is
silent, and it fails in the direction of a green board. The leading indicator is not a metric on
the gate at all: embed a rolling sample of production queries, embed the golden set, and watch
the distance between the two distributions widen.

---

## 6. Where the eval traffic goes

```mermaid
flowchart LR
    CI["CI eval runs<br/>bursty, up to 48 concurrent"] --> KEY["its own gateway key<br/>own token bucket, hard concurrency cap"]
    PRD["production traffic<br/>~140 concurrent in flight"] --> GW
    KEY --> GW["shared LLM gateway"]
    GW --> Q[("one provider quota")]
    Q -.->|"without the separate bucket"| INC["a merge storm becomes<br/>a production 429 incident"]
```

The gate is a load generator. It arrives in bursts, it competes for the same quota, and a
nightly full run overlapping a merge is the worst case. Give it its own bucket and run the
nightly off-peak, or the thing protecting your releases will page the on-call.
