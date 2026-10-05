"""
12 - LangGraph mechanics, runnable with NO model and NO network.

    python3 solution.py

Everything here is real LangGraph *structure* driven by a fake model, which is
the trick that makes graph logic testable: the node code below is byte-identical
whether the model is this stub or a real provider.

Covers, in order:
  1. state + reducers        (replace vs append, and why parallel needs it)
  2. nodes + edges           (a node is just state -> partial update)
  3. conditional routing     (the loop, and its budget)
  4. dynamic fan-out         (Send, when N is only known at runtime)
  5. the fake-model seam     (how to test all of the above)

If langgraph is not installed, the file still runs: it falls back to a ~40-line
interpreter that implements the same semantics, so the CONCEPTS stay executable.
"""
from typing import Annotated, TypedDict
import operator

# --------------------------------------------------------------------------- #
# 1. STATE + REDUCERS - the concept that matters most
# --------------------------------------------------------------------------- #
# A node returns a PARTIAL update. The reducer decides how it merges.
#   no reducer      -> REPLACE  (last writer wins - unsafe under parallelism)
#   operator.add    -> APPEND / concatenate
#   add_messages    -> append + dedupe by message id (LangChain's message reducer)


class State(TypedDict):
    text: str                                   # no reducer -> replaced
    findings: Annotated[list, operator.add]     # reducer    -> appended
    steps: Annotated[int, operator.add]         # reducer    -> summed
    verdict: str


# --------------------------------------------------------------------------- #
# 5. THE FAKE-MODEL SEAM (defined early because the nodes use it)
# --------------------------------------------------------------------------- #
class FakeLLM:
    """Stands in at the same interface a real ChatModel exposes.

    The point: `llm.invoke(prompt)` below never changes. Swap this for
    init_chat_model("openai:gpt-4o-mini") and the graph is untouched.
    """

    def __init__(self, script):
        self.script, self.calls = script, 0

    def invoke(self, prompt: str) -> str:
        out = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return out


llm = FakeLLM(["EMAIL", "PHONE", "low-confidence"])


# --------------------------------------------------------------------------- #
# 2. NODES - a node is a plain function. No framework needed to unit-test it.
# --------------------------------------------------------------------------- #
def classify(state: State) -> dict:
    # returns a PARTIAL update, not the whole state
    return {"verdict": "document", "steps": 1}


def detect_rules(state: State) -> dict:
    """The deterministic detector. Cheap, exact, runs first."""
    found = [w for w in ("aadhaar", "pan") if w in state["text"].lower()]
    return {"findings": found, "steps": 1}


def detect_llm(state: State) -> dict:
    """The model detector - catches what the rules missed."""
    guess = llm.invoke("find PII in: " + state["text"])
    return {"findings": [guess.lower()], "steps": 1}


def verify(state: State) -> dict:
    n = len(state["findings"])
    return {"verdict": "escalate" if n < 2 else "auto", "steps": 1}


def human(state: State) -> dict:
    return {"verdict": "reviewed-by-human", "steps": 1}


def apply_redaction(state: State) -> dict:
    return {"verdict": "redacted", "steps": 1}


# --------------------------------------------------------------------------- #
# 3. CONDITIONAL ROUTING - this is what makes it a graph and not a pipeline
# --------------------------------------------------------------------------- #
MAX_STEPS = 12          # the budget lives in CODE, never in a prompt


def route_after_verify(state: State) -> str:
    if state["steps"] >= MAX_STEPS:          # budget beats everything
        return "apply"
    return "human" if state["verdict"] == "escalate" else "apply"


def build_real_graph():
    """The same graph, expressed in actual LangGraph."""
    from langgraph.graph import StateGraph, START, END
    g = StateGraph(State)
    for name, fn in [("classify", classify), ("rules", detect_rules),
                     ("llm", detect_llm), ("verify", verify),
                     ("human", human), ("apply", apply_redaction)]:
        g.add_node(name, fn)
    g.add_edge(START, "classify")
    g.add_edge("classify", "rules")
    g.add_edge("rules", "llm")               # sequential here; parallel below
    g.add_edge("llm", "verify")
    g.add_conditional_edges("verify", route_after_verify,
                            {"human": "human", "apply": "apply"})
    g.add_edge("human", "apply")
    g.add_edge("apply", END)
    return g.compile()


# --------------------------------------------------------------------------- #
# The fallback interpreter - same semantics, ~40 lines, zero dependencies.
# It exists so the CONCEPT is runnable even without langgraph installed.
# --------------------------------------------------------------------------- #
def merge(state: dict, update: dict) -> dict:
    """Apply reducers exactly the way LangGraph does."""
    reducers = {"findings": operator.add, "steps": operator.add}
    out = dict(state)
    for k, v in update.items():
        if k in reducers and k in out:
            out[k] = reducers[k](out[k], v)   # APPEND / SUM
        else:
            out[k] = v                        # REPLACE
    return out


def run_fallback(state: dict) -> dict:
    edges = {"classify": "rules", "rules": "llm", "llm": "verify",
             "human": "apply", "apply": None}
    fns = {"classify": classify, "rules": detect_rules, "llm": detect_llm,
           "verify": verify, "human": human, "apply": apply_redaction}
    node, hops = "classify", 0
    while node and hops < 50:
        state = merge(state, fns[node](state))
        node = route_after_verify(state) if node == "verify" else edges[node]
        hops += 1
    return state


# --------------------------------------------------------------------------- #
# 4. DYNAMIC FAN-OUT - Send, when N is only known at runtime
# --------------------------------------------------------------------------- #
def fan_out_demo(sections):
    """One worker per section, results merged by a reducer.

    In LangGraph this is:
        return [Send("worker", {"section": s}) for s in sections]
    and the target channel needs a merge reducer, or parallel writes clobber
    each other. That is the CSR fan-out: 16 section workers, dict-merge on the
    shared results channel.
    """
    results = {}
    for s in sections:                      # sequential here; parallel in reality
        results = {**results, s: f"drafted:{s}"}   # dict-merge reducer
    return results


if __name__ == "__main__":
    start: State = {"text": "my aadhaar is 1234", "findings": [], "steps": 0,
                    "verdict": ""}

    try:
        out = build_real_graph().invoke(start)
        engine = "real langgraph"
    except Exception as e:                  # not installed - use the interpreter
        out = run_fallback(start)
        engine = f"fallback interpreter ({type(e).__name__})"

    print(f"engine: {engine}\n")
    print("  findings (APPENDED by reducer) :", out["findings"])
    print("  steps    (SUMMED by reducer)   :", out["steps"])
    print("  verdict  (REPLACED, no reducer):", out["verdict"])
    assert len(out["findings"]) >= 2, out
    assert out["verdict"] in ("redacted", "reviewed-by-human")

    print("\n  fan-out:", fan_out_demo(["synopsis", "efficacy", "safety"]))

    print("""
  what to notice
  --------------
  * 'findings' grew because it has a reducer; 'verdict' was overwritten
    because it has none. Under PARALLEL nodes that difference is the whole
    ballgame - two branches writing a reducer-less key means one silently wins.
  * the budget (MAX_STEPS) is checked in route_after_verify - in CODE.
    A prompt saying "don't loop" is advisory; this is enforcement.
  * every node above is a plain function: unit-testable with a dict, no
    framework, no model.
  * the model is a stub. `llm.invoke(...)` is identical against a real
    provider, so the graph you test is the graph you ship.
""")
    print("OK - topic 12")
