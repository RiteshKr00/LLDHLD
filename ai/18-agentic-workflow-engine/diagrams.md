# Agentic workflow engine — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    API["Run API<br/>caller submits and gets a run id<br/>202 accepted, never blocks"] --> REG
    REG[("Run registry<br/>state, budget spent, step cursor")] --> SCHED
    SCHED["Admission and slot pool<br/>capacity is SLOTS held, not QPS"] --> EXEC
    EXEC["Step executor<br/>one graph node per tick"] --> GUARD
    GUARD{"Pre-flight guards<br/>steps, projected cost, repeat, clock"}
    GUARD -- halt --> HALT["Terminal HALTED<br/>reason plus checkpoint id"]
    GUARD -- admit --> LLM["LLM gateway<br/>per-step timeout of 30s"]
    LLM --> BROKER["Tool broker<br/>schema check, tenant creds, idem key"]
    BROKER --> TOOLS[("Tools<br/>some write to customer records")]
    TOOLS --> CKPT[("Checkpoint store<br/>written after EVERY node")]
    CKPT --> VERIFY{"Critic node<br/>done or continue or escalate"}
    VERIFY -- continue --> EXEC
    VERIFY -- escalate --> HUMAN["Human review queue<br/>run suspended, SLOT RELEASED"]
    VERIFY -- done --> DONE["Terminal DONE<br/>result plus trajectory"]
    HALT --> LEDGER[("Run ledger<br/>cost, step distribution, terminal state")]
    DONE --> LEDGER
    HUMAN --> LEDGER
```

Read it as one run. The loop is `EXEC → GUARD → LLM → BROKER → CKPT → VERIFY → EXEC`, and the
guard sits **inside** that loop, before the spend, not around the outside of it. Three terminal
states, all of them ledgered: done, halted with a reason, and escalated to a person. A run that
is waiting on a human has released its slot — otherwise a reviewer's lunch break is a capacity
incident.

---

## 2. The ladder of stops, in the order they fire

```mermaid
flowchart TB
    S["a stuck run ticks forward"] --> G1{"same normalised state 3 times?"}
    G1 -- yes at step 7 --> H1["halt for $0.08<br/>the cheap catch"]
    G1 -- no --> G2{"progress ledger frozen 7 steps?"}
    G2 -- yes at step 10 --> H2["halt for $0.13"]
    G2 -- no --> G3{"projected spend over $2.00?"}
    G3 -- yes at step 52 --> H3["halt for $1.98"]
    G3 -- no --> G4{"step count over 60?"}
    G4 -- yes at step 60 --> H4["halt for $2.57"]
    G4 -- no --> G5{"prompt over 128k?"}
    G5 -- yes at step 211 --> H5["PROVIDER ERROR for $27.89<br/>a crash, not your decision"]
    G5 -- no --> S
```

Every branch is the same bug caught at a different price. The caps are backstops; the detectors
are the policy. If your step cap is the guard that usually fires, the detectors above it are not
working — and the bottom box is what you get with none of them.

---

## 3. Where the budget lives

#### The trap — enforcement inside the prompt

```mermaid
flowchart LR
    P["system prompt<br/>do not loop and stay in budget"] --> M["the model<br/>currently malfunctioning"]
    M --> D["it decides whether to stop<br/>you asked the fault to police itself"]
```

#### The answer — enforcement in the executor

```mermaid
flowchart LR
    C["executor tick<br/>budget state read from the registry"] --> A{"admit the NEXT step?"}
    A -- no --> H["halt with a reason<br/>plus a checkpoint id"]
    A -- yes --> M2["the model<br/>gets judgement, nothing else"]
    M2 --> C
```

Note *which* step is priced. Admission projects the cost of the step about to run, because a
transcript-resending agent makes the last step the dearest one — check spend-so-far instead and
you overshoot the cap you were defending, every time.

---

## 4. The tool broker — one chokepoint, four jobs

```mermaid
flowchart TB
    OUT["model output<br/>a PROPOSED tool call"] --> V{"validates against the schema?"}
    V -- no --> RJ["reject and repair<br/>nothing executed"]
    V -- yes --> SC["resolve credentials<br/>scoped to THIS run tenant"]
    SC --> CL{"tool classified destructive?"}
    CL -- yes --> CONF["human confirm or dry run"]
    CL -- no --> IK["stamp idempotency key<br/>digest of run step tool args"]
    CONF --> IK
    IK --> RC[("record the key BEFORE dispatch")]
    RC --> EX["execute"]
    EX --> RES["result returns as DATA<br/>never as instructions"]
```

Trace an injected *"delete account 4471"* through it: it has to survive schema validation,
tenant-scoped credentials, and a destructive-tool confirmation. Three of those hold even if the
model is fully compromised — which is the only test of a defence worth having. `record the key
BEFORE dispatch` is the box that decides whether a crashed worker creates one customer record or
two.

---

## 5. Run lifecycle — why halted is a pause

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: slot acquired
    running --> running: step ok, checkpoint written
    running --> suspended: escalated, SLOT RELEASED
    suspended --> running: reviewer answers, resume from checkpoint
    running --> halted: a guard fired, reason recorded
    halted --> running: budget extended by an owner
    running --> done
    done --> [*]
    halted --> [*]
    note right of halted
        HALTED IS NOT A FAILURE.
        40 steps of paid work survive
        in the checkpoint, the partial
        result goes back to the caller
        with a machine-readable reason,
        and an owner can extend the
        budget and resume.
    end note
```

The two edges that matter are the ones back into `running`. Without a checkpoint after every
node, `suspended` cannot exist (you cannot park a stack frame for a human) and `halted` is a loss
rather than a decision.
