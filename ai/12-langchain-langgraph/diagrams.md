# LangChain & LangGraph — diagrams

## 1. The whole system, end to end

```mermaid
flowchart TB
    CL["client<br/>chat UI or API caller"] --> API["service endpoint<br/>thread_id + new message"]
    API --> GR["LangGraph runtime<br/>compiled StateGraph"]
    GR -- "node returns a partial update" --> ST[("typed State<br/>reducers decide append vs replace")]
    ST -- "merged state, pick next edge" --> RT{"conditional edge<br/>model-influenced branch"}
    RT -->|needs context| RET["node: retrieve<br/>Retriever .invoke(query)"]
    RT -->|needs an answer| MOD["node: call model<br/>init_chat_model, one call shape"]
    RT -->|needs an action| TL["node: run tools<br/>@tool, docstring IS the spec"]
    RT -->|low confidence| HL["interrupt: human review<br/>graph pauses, nothing held open"]
    RT -->|done| OUT["stream tokens + final state<br/>back to the caller"]
    RET --> VS[("vector store<br/>+ source documents")]
    MOD --> LLM["provider API<br/>openai / anthropic / local"]
    VS --> GR
    LLM --> GR
    TL --> GR
    GR -.->|"after every step"| CP[("checkpointer<br/>one row per thread_id, per step")]
    CP -.-> HL
    HL -- "resume from last checkpoint" --> GR
    OUT --> CL
```

What to notice in that path:

- LangChain owns exactly two edges — `MOD -> LLM` and `RET -> VS`. Swapping a
  provider or a store touches nothing else in the picture.
- LangGraph owns everything between `API` and `OUT`: the state, the branch, the
  checkpoint. That is control flow, not calls.
- The loop `GR -> ST -> RT -> node -> GR` is the whole runtime. A node never
  calls the next node; it returns an update and the router decides.
- `CP` is what makes `HL` cheap. The process exits at the interrupt; a human
  answers hours later and the graph resumes from the stored state.
- Tracing/usage wraps every node in this loop — per node, per model call — which
  is why cost regressions are attributable to a node rather than to "the app".

## 2. What each library is for

#### LangChain — the adapter layer

```mermaid
flowchart TB
    LC["LangChain = ADAPTERS"]
    LC --> L1["init_chat_model<br/>one call shape, many providers"]
    LC --> L2["Messages<br/>typed, not dicts"]
    LC --> L3["@tool<br/>docstring IS the spec"]
    LC --> L4["Retrievers<br/>uniform .invoke(query)"]
    LC -.->|"used inside nodes"| LG["LangGraph<br/>see the next block"]
```

#### LangGraph — the state machine runtime

```mermaid
flowchart TB
    LG["LangGraph = STATE MACHINE RUNTIME"]
    LG --> G1["typed State + REDUCERS"]
    LG --> G2["nodes: state -> partial update"]
    LG --> G3["conditional edges = branching + loops"]
    LG --> G4["checkpointer = resume, human-in-loop"]
    LG --> G5["Send = dynamic fan-out"]
    G2 -.-> IN["the four LangChain adapters<br/>are called in here, in node bodies"]
```

#### Which one do you actually need

```mermaid
flowchart TB
    Q{"does the MODEL decide<br/>what happens next?"}
    Q -->|no| P["plain functions.<br/>a graph adds indirection<br/>and buys nothing"]
    Q -->|yes| YG["LangGraph.<br/>the branch and the checkpoint<br/>are the whole reason"]
```

## 3. Reducers — the concept that matters most

```mermaid
flowchart TB
    S0[("state: findings=['a'], verdict='x'")] --> N1[node A returns<br/>findings=['b']]
    S0 --> N2[node B returns<br/>verdict='y']
    N1 --> R1{"'findings' has a reducer<br/>Annotated[list, add]"}
    R1 --> O1["APPENDED -> ['a','b']"]
    N2 --> R2{"'verdict' has NO reducer"}
    R2 --> O2["REPLACED -> 'y'"]
    O1 --> PAR["under PARALLEL nodes:<br/>two branches writing a<br/>reducer-less key = one<br/>SILENTLY wins"]
    O2 --> PAR
```

## 4. The PII filter as a graph (why a graph, not five calls)

```mermaid
stateDiagram-v2
    [*] --> classify
    classify --> detect_rules: deterministic first (cheap, exact)
    detect_rules --> detect_llm: only ambiguous chunks
    detect_llm --> verify
    verify --> apply: confident
    verify --> human: LOW CONFIDENCE
    human --> apply
    apply --> [*]
    note right of verify
        THIS is why it's a graph:
        a model-influenced BRANCH,
        plus a place to checkpoint
        before a human wait.
        Five function calls cannot
        express either.
    end note
    note left of detect_llm
        budget enforced in CODE:
        MAX_STEPS checked in the
        router, not asked for in
        the prompt
    end note
```

## 5. `Send` — dynamic fan-out

```mermaid
flowchart TB
    P["planner node<br/>N known only at RUNTIME"] --> S["return [Send('worker', {section: s})<br/>for s in sections]"]
    S --> W1[worker: synopsis]
    S --> W2[worker: efficacy]
    S --> W3[worker: safety]
    S --> WN[worker: ...16 total]
    W1 --> M[("results channel<br/>MUST have a merge reducer")]
    W2 --> M
    W3 --> M
    WN --> M
    M --> A[assemble]
    M --- WARN["no reducer here = parallel writes<br/>clobber each other"]
```

## 6. The fake-model seam — how you test a graph offline

```mermaid
flowchart LR
    C["node code - UNCHANGED<br/>await llm.ainvoke(prompt)"]
    C --> I{"which implementation?"}
    I -->|test| F["FakeLLM<br/>BaseChatModel subclass<br/>_generate / _stream + usage<br/>no key, no network, deterministic"]
    I -->|prod| R["init_chat_model('openai:...')"]
    F --> V["the graph you TEST"]
    R --> V2["the graph you SHIP"]
    V --- EQ["byte-identical call site<br/>-> same graph both sides"]
    V2 --- EQ
    I -.->|"the WEAK alternative"| MP["mock.patch the provider<br/>-> tests that you called a mock,<br/>not that routing works"]
```
