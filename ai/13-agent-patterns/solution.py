"""
13 - the four agent patterns, side by side, runnable with no model.

    python3 solution.py

All four run against the same fake model and the same task, so the printed
output lets you COMPARE them on the two axes that matter in an interview:
model calls made, and whether the shape can wander.

The point of the file is not the code - it is the measured comparison at the
bottom, and the fact that every budget is enforced in code rather than asked
for in a prompt.
"""
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# a fake model that counts how often it is called - the number that matters
# --------------------------------------------------------------------------- #
@dataclass
class FakeLLM:
    calls: int = 0
    tokens: int = 0

    def ask(self, prompt: str, reply: str) -> str:
        self.calls += 1
        self.tokens += len(prompt.split())      # stand-in for prompt cost
        return reply


TOOLS = {
    "get_user":   lambda **k: {"tier": "free"},
    "get_quota":  lambda **k: {"used": 9, "limit": 10},
    "get_policy": lambda **k: {"export": "paid-only"},
}


def call_tool(name, **kw):
    """The model REQUESTS; this function decides and executes.

    Validation lives here on purpose - never execute an unvalidated,
    model-chosen action.
    """
    if name not in TOOLS:
        raise ValueError(f"tool not allowed: {name}")
    return TOOLS[name](**kw)


MAX_STEPS = 6          # enforced in CODE, not in a prompt


# --------------------------------------------------------------------------- #
# 1. ReAct - think/act/observe, one model call PER STEP, history resent
# --------------------------------------------------------------------------- #
def react(llm):
    history, steps = [], 0
    script = ["get_user", "get_quota", "get_policy", "DONE"]
    while steps < MAX_STEPS:
        # the whole history is resent every turn -> cost grows quadratically
        prompt = "history:" + " ".join(history) + " what next?"
        nxt = llm.ask(prompt, script[min(steps, len(script) - 1)])
        if nxt == "DONE":
            break
        obs = call_tool(nxt, id=42)
        history.append(f"{nxt}->{obs}")
        steps += 1
    return {"steps": steps, "history": history}


# --------------------------------------------------------------------------- #
# 2. Plan-and-execute - ONE plan call, then steps (parallelisable)
# --------------------------------------------------------------------------- #
def plan_execute(llm):
    plan = llm.ask("task: can user 42 export?", "get_user,get_quota,get_policy")
    steps = plan.split(",")
    # the plan is an ARTIFACT: inspectable, loggable, approvable before spending
    if len(steps) > MAX_STEPS:
        raise RuntimeError("plan exceeds the step budget - reject before executing")
    results = {s: call_tool(s, id=42) for s in steps}   # could be parallel
    return {"plan": steps, "results": results}


# --------------------------------------------------------------------------- #
# 3. Reflection - only works when the critic has an EXTERNAL signal
# --------------------------------------------------------------------------- #
def deterministic_validator(draft: str) -> list:
    """The external signal. Cheap, exact, cannot hallucinate."""
    problems = []
    if "free tier" not in draft.lower():
        problems.append("must state the user's tier")
    if "%" in draft:
        problems.append("no invented percentages")
    return problems


def reflection(llm, with_signal=True):
    draft = llm.ask("write the answer", "You can export. Usage is 90%.")
    rounds = 0
    while rounds < 3:
        # the ONLY thing that makes this pattern work:
        problems = deterministic_validator(draft) if with_signal else []
        if not problems:
            break
        draft = llm.ask("fix: " + "; ".join(problems),
                        "Free tier cannot export; quota 9 of 10 used.")
        rounds += 1
    return {"draft": draft, "rounds": rounds,
            "signal": "deterministic validator" if with_signal else "none (self-critique)"}


# --------------------------------------------------------------------------- #
# 4. Multi-agent - and the failure mode nobody mentions
# --------------------------------------------------------------------------- #
def multi_agent(llm, pinned_facts=None):
    """Fan out to specialists over a shared corpus.

    Without a pinned-facts contract each worker retrieves *a* defensible
    answer and nothing enforces they answered about the SAME subject.
    """
    corpus = {"adult": "n=430", "adolescent": "n=112"}
    workers = ["narrative", "tables"]
    out = {}
    for w in workers:
        cohort = pinned_facts["cohort"] if pinned_facts else (
            "adult" if w == "narrative" else "adolescent")   # <- the bug
        out[w] = llm.ask(f"{w} section", f"{w}: cohort={cohort} {corpus[cohort]}")
    consistent = len({v.split("cohort=")[1].split()[0] for v in out.values()}) == 1
    return {"sections": out, "consistent": consistent}


if __name__ == "__main__":
    print("pattern            calls  tokens  note")
    print("-" * 74)
    for name, fn in [("ReAct", react), ("Plan-and-execute", plan_execute)]:
        llm = FakeLLM(); r = fn(llm)
        note = (f"{r['steps']} steps, history resent each turn"
                if name == "ReAct" else f"1 plan + {len(r['plan'])} steps, parallelisable")
        print(f"{name:<18} {llm.calls:>5}  {llm.tokens:>6}  {note}")

    llm = FakeLLM(); good = reflection(llm, with_signal=True)
    print(f"{'Reflection (signal)':<18} {llm.calls:>5}  {llm.tokens:>6}  "
          f"{good['rounds']} revision(s), fixed by an EXTERNAL check")
    llm = FakeLLM(); bad = reflection(llm, with_signal=False)
    print(f"{'Reflection (none)':<18} {llm.calls:>5}  {llm.tokens:>6}  "
          f"{bad['rounds']} revisions - nothing to critique against")

    llm = FakeLLM(); broken = multi_agent(llm)
    llm2 = FakeLLM(); fixed = multi_agent(llm2, pinned_facts={"cohort": "adult"})
    print(f"{'Multi-agent':<18} {llm.calls:>5}  {llm.tokens:>6}  "
          f"consistent={broken['consistent']}  <- NO pinned facts")
    print(f"{'Multi-agent +pinned':<18} {llm2.calls:>5}  {llm2.tokens:>6}  "
          f"consistent={fixed['consistent']}  <- pinned-facts contract")

    assert not broken["consistent"] and fixed["consistent"]
    assert "90%" not in good["draft"] and "90%" in bad["draft"]

    print("""
what to notice
--------------
* ReAct pays a model call PER STEP and resends history, so tokens grow
  faster than steps. Plan-and-execute pays 1 + N and the plan is an
  artifact you can inspect, log or get approved BEFORE spending.
* Reflection with a deterministic validator removed the invented "90%".
  With no external signal it made zero revisions - the same model agreed
  with itself. That is the whole argument about reflection.
* Multi-agent produced a self-contradicting document until a pinned-facts
  contract forced both workers onto the same cohort. Each section was
  individually correct and the document was wrong.
* MAX_STEPS is checked in code. plan_execute REJECTS an over-long plan
  before executing it. Neither is asked for in a prompt.
""")
    print("OK - topic 13")
