# LangChain & LangGraph — explained

**Your material:** `~/projects/csr-langgraph-learning` (a 12-chapter offline course you wrote,
pinned to langgraph 1.2.4 / langchain-core 1.4.1) and
`Scrap/Agents_Interview_Prep/LangChainGraph/practise*.py`.

---

## The one-line split

**LangChain is a library of adapters.** LangGraph is a **state machine runtime**. They solve
different problems and you can use either without the other.

| | LangChain | LangGraph |
|---|---|---|
| Gives you | provider adapters, message types, tool schemas, retrievers | typed state, nodes, edges, loops, checkpointing, streaming |
| Replaces | provider SDK boilerplate | your own `while` loop and state dict |
| Use it for | one call, or a fixed chain | control flow the model influences |

---

## Part 1 — LangChain, four primitives

### `init_chat_model` — one wrapper, many providers

```python
llm = init_chat_model("ollama:llama3.2:3b")   # or "openai:gpt-4o-mini", "anthropic:..."
```

**What it buys you:** one call shape across providers, so swapping is a string change instead
of a rewrite. **This is the same job as the gateway layer in topic 11** — say that connection,
it shows you see the pattern rather than the library.

**Backend analogy:** it's SQLAlchemy for models. You still write the query; you don't rewrite
it per database.

### Messages — typed conversation history

```python
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
msgs = [SystemMessage("You are terse."), HumanMessage("Capital of India?")]
```

**Why typed rather than dicts:** a dict typo (`"role": "hunan"`) fails at the provider with a
useless error. A typed object fails at construction, in your editor. Same argument as Pydantic
over raw dicts — validation at the boundary, not three layers in.

### Tools — Python functions the model may call

```python
@tool
def get_weather(city: str) -> dict:
    """Get current weather for a city."""      # <- the docstring IS the spec
    return {"temperature_c": 31, "conditions": "humid"}
```

The decorator introspects the signature and docstring to build the JSON schema the provider
needs. **The docstring is not a comment — it's the description the model uses to decide
whether to call this.** A vague docstring is a bug.

Critically: **the model never executes anything.** It emits a *request* to call
`get_weather("Delhi")`; your runtime validates and executes it. That separation is the whole
safety story for tool use.

### Retrievers — the RAG adapter

A uniform `.invoke(query) -> list[Document]` over Chroma, Weaviate, Mongo Atlas, whatever.
Same adapter idea again.

---

## Part 2 — LangGraph, the execution model

### State + reducers — the bit that actually matters

```python
class S(TypedDict):
    messages: Annotated[list, add_messages]   # reducer: APPEND
    count: int                                # no reducer: REPLACE
```

A node returns a **partial** update, not the whole state. How that update merges is decided by
the **reducer**:

- **no reducer** → the value is **replaced**
- **`add_messages`** → the value is **appended** (and it de-duplicates by message id)

**Why you can't just use a list:** with parallel nodes, two branches both return `messages`.
Replace semantics means one silently wins. A reducer makes the merge explicit and
order-independent. That is the single most important concept in LangGraph — and it's the answer
to "why not a plain dict?"

### Nodes and edges

```python
g = StateGraph(S)
g.add_node("detect", detect)
g.add_edge(START, "detect")
g.add_conditional_edges("decide", route, {"apply": "apply", "escalate": "human"})
app = g.compile()
```

- **node** = a plain function `state -> partial update`. Testable in isolation, no framework needed.
- **edge** = unconditional next step
- **conditional edge** = a router function returns the next node's name — this is how a loop or
  a branch is expressed

### Loops, and why they need budgets

A conditional edge pointing back at an earlier node *is* the loop. LangGraph enforces a
`recursion_limit` so a runaway graph raises instead of running forever — but that's a
backstop, not a design. **Your own step budget and cost cap still belong in code** (topic 13).

### Checkpointing

Pass a checkpointer and the state is persisted after every node, keyed by a thread id. Buys
you three things: **crash resume**, **human-in-the-loop** (stop, wait for input, continue), and
**time travel** for debugging. This is what makes a long agent run survivable.

### `Send` — dynamic fan-out

```python
return [Send("worker", {"section": s}) for s in sections]
```

Spawn N parallel instances of a node, one per item, when N is only known at runtime. The
results land in a channel with a merge reducer. **This is the machinery behind the CSR
migration you proposed** — 16 section workers in parallel with a dict-merge reducer on the
shared results channel.

### Streaming modes

`values` (whole state after each step) · `updates` (just the delta) · `messages` (token by
token). `updates` is what you want for an SSE progress feed; `messages` for token streaming to
a browser.

---

## Part 3 — When NOT to use LangGraph

Say this unprompted; it's the senior half of the answer.

| Situation | Use |
|---|---|
| One LLM call | the provider SDK. A framework is pure overhead |
| A fixed pipeline, A→B→C, no branching | plain functions. You don't need a graph to call three functions |
| Steps known in advance | a pipeline, not an agent |
| Control flow depends on model output, or you need loops with resume | **LangGraph earns it** |

**The test:** *does the model decide what happens next?* No → you're writing a pipeline, and a
graph adds indirection without buying anything. Yes → you need typed state, explicit routing
and checkpointing, and hand-rolling those is how you end up with an untestable `while` loop
around a mutable dict.

---

## Part 4 — Testing a graph with no model and no network

This is the part almost nobody does, and it's your differentiator — you built it.

**Implement the test doubles at the framework's own interfaces:** a real `BaseChatModel`
subclass with `_generate` / `_stream` and usage metadata, plus an `Embeddings` subclass and a
cosine store with metadata filtering.

Then node code calling `await llm.ainvoke(prompt)` is **byte-identical** against the fake and
against a real provider. So the graph structure you test is the graph structure that ships —
no API key, no Docker, no network, and the tests are deterministic.

Contrast the common approach — `mock.patch` on the provider call — which tests that you called
a mock, not that your graph routes correctly.

---

## The follow-ups, answered

**"`init_chat_model` vs the provider SDK?"**
One call shape across providers, so a swap is a config change. Same role as a gateway. The cost
is a dependency and a layer of indirection when you only ever use one provider.

**"What's a reducer, in one sentence?"**
The function that decides how a node's partial update merges into the shared state — replace by
default, append for messages, and it's what makes parallel branches safe.

**"When is a StateGraph overkill?"**
Whenever the steps are fixed. If there's no branch the model influences and no loop, it's a
pipeline — write functions.

**"How do you stop a graph looping forever?"**
`recursion_limit` is the framework backstop. The real answer is a step budget, a per-run cost
cap with a breaker, and repeat-state detection — **in your code**, because the prompt is
advisory and the framework limit is a crash, not a policy.

**"Why is your PII filter a graph and not five function calls?"**
Because the verify node routes: low confidence goes to human review, otherwise it completes.
That's a model-influenced branch, plus a place to checkpoint before a human wait. Five function
calls can't express either without hand-rolling both.

---

## One-line summary

> "LangChain is adapters — providers, messages, tools, retrievers. LangGraph is a state machine
> with typed state and reducers, so branching and loops are explicit and checkpointable. If the
> model doesn't decide what happens next, I'd skip the graph and write functions."

## The trap answer to avoid

Describing LangGraph as "a framework for building agents". That's marketing. It's a **state
machine runtime** — the useful specifics are typed state, reducers, conditional edges and
checkpointing. Candidates who can name the reducer semantics are immediately distinguishable
from candidates who followed a tutorial.
