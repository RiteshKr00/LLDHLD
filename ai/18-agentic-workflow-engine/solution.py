"""
Scenario 4 - an agentic engine that cannot loop forever or overspend.

    python3 solution.py

The same stuck agent is run five times with progressively more of the guard ladder
enabled, and the bill is measured each time. Notice three things: agent cost is
QUADRATIC in step count (the transcript is resent every step), so the step cap is a
very expensive place to catch a loop; a naive state digest never repeats and so
never fires; and the guard that actually saves the money is repeat-state detection,
not the cap everyone reaches for.
"""
import hashlib, json, random
from collections import Counter

random.seed(4)

PROMPT_BASE, PER_STEP, OUT = 1_500, 600, 400        # tokens
IN_RATE, OUT_RATE = 2 / 1e6, 8 / 1e6                # $/token
CONTEXT = 128_000                                   # the accidental step cap


def prompt_tokens(step):
    """The transcript is resent every step, so the prompt grows linearly..."""
    return PROMPT_BASE + PER_STEP * step


def step_cost(step):
    return prompt_tokens(step) * IN_RATE + OUT * OUT_RATE


def run_cost(n):
    """...which makes the CUMULATIVE cost of an n-step run quadratic."""
    return sum(step_cost(k) for k in range(1, n + 1))


# --------------------------------------------------------------------------- #
# the agent under test: two planning steps, then an A/B loop it never escapes
# --------------------------------------------------------------------------- #
def state_at(step, stuck=True):
    if not stuck:
        return {"node": "work", "payload": f"finding-{step}", "_nonce": random.random()}
    if step <= 2:
        return {"node": "plan", "payload": f"plan-{step}", "_nonce": random.random()}
    node = "search" if step % 2 else "read"
    return {"node": node, "payload": "invoice 4471", "_nonce": random.random()}


def digest(state, mode="normalised"):
    """Normalised drops volatile keys. A nonce or a timestamp defeats a naive hash."""
    keys = [k for k in state if mode == "naive" or not k.startswith("_")]
    blob = json.dumps({k: state[k] for k in sorted(keys)}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:8]


def execute(guards, mode="normalised", stuck=True, useful_steps=8, start=0, spent=0.0):
    """One tick per step. EVERY guard is checked BEFORE the call, never after."""
    seen, facts, last_progress = Counter(), set(), start
    step, tokens = start, 0
    while True:
        nxt = step + 1
        if "max_steps" in guards and nxt > guards["max_steps"]:
            return step, tokens, spent, "max_steps"
        # pre-flight: project the NEXT step's cost. Checking spend-so-far always
        # overshoots by one step, and in a quadratic run that is the dearest one.
        if "cost_cap" in guards and spent + step_cost(nxt) > guards["cost_cap"]:
            return step, tokens, spent, "cost_cap"
        if prompt_tokens(nxt) > CONTEXT:
            return step, tokens, spent, "context_overflow"

        step = nxt                                    # the model call happens here
        tokens += prompt_tokens(step) + OUT
        spent += step_cost(step)
        if not stuck and step >= useful_steps:
            return step, tokens, spent, "done"

        st = state_at(step, stuck)
        d = digest(st, mode)
        seen[d] += 1
        if st["payload"] not in facts:                # the progress ledger grew
            facts.add(st["payload"])
            last_progress = step
        if "repeat" in guards and seen[d] >= guards["repeat"]:
            return step, tokens, spent, "repeat_state"
        if "no_progress" in guards and step - last_progress >= guards["no_progress"]:
            return step, tokens, spent, "no_progress"


CAPS = {"max_steps": 60, "cost_cap": 2.00, "no_progress": 7, "repeat": 3}
LADDER = [
    ("prompt only: 'do not loop'", {}),
    ("+ max steps (60)",           {"max_steps": 60}),
    ("+ cost cap ($2.00)",         {"max_steps": 60, "cost_cap": 2.00}),
    ("+ no-progress (7)",          {k: CAPS[k] for k in ("max_steps", "cost_cap", "no_progress")}),
    ("+ repeat-state (3)",         CAPS),
]

if __name__ == "__main__":
    print("1. WHY STEP COUNT IS THE COST DRIVER (the transcript is resent each step)")
    for n in (8, 50, 210):
        print(f"   {n:>4} steps -> {run_cost(n) / run_cost(8):>5.1f}x the median run"
              f"   ${run_cost(n):>6.2f}   prompt {prompt_tokens(n) / 1000:>5.1f}k on the last call")
    assert run_cost(50) / run_cost(8) > 15, "cost must grow faster than step count"
    print("   -> 6x the steps is 20x the bill. Linear intuition is wrong here.\n")

    print("2. THE GUARD LADDER - same stuck agent, five times")
    print(f"   {'guards enabled':<28}{'steps':>6}{'tokens':>10}{'cost':>9}   how it ended")
    results = {}
    for label, g in LADDER:
        s, tok, cost, why = execute(g)
        results[label] = (s, cost, why)
        print(f"   {label:<28}{s:>6}{tok / 1000:>9.0f}k{'$' + format(cost, '.2f'):>9}   {why}")

    bare = results["prompt only: 'do not loop'"]
    full = results["+ repeat-state (3)"]
    assert bare[2] == "context_overflow" and bare[1] > 27
    assert results["+ cost cap ($2.00)"][1] <= 2.00, "pre-flight must never exceed the cap"
    assert full[2] == "repeat_state" and full[0] == 7
    assert bare[1] / full[1] > 300
    print(f"   -> repeat-state caught it at step {full[0]} for ${full[1]:.2f}; the context window")
    print(f"      caught it at step 211 for ${bare[1]:.2f}. Same bug, {bare[1] / full[1]:.0f}x the money.")
    print("      The caps are backstops. If a cap is what usually fires, the")
    print("      detectors are not working.\n")

    print("3. NO FALSE POSITIVES - a healthy 8-step run, all guards on")
    s, _, cost, why = execute(CAPS, stuck=False)
    print(f"   healthy run: {s} steps, ${cost:.2f}, ended '{why}'")
    assert (s, why) == (8, "done"), "guards must not fire on a well-behaved run"
    print("   -> a guard that stops good runs gets switched off, and then you have none.\n")

    print("4. DIGEST NORMALISATION - a nonce defeats a naive detector")
    for mode in ("naive", "normalised"):
        s, _, cost, why = execute({"max_steps": 60, "cost_cap": 2.00, "repeat": 3}, mode=mode)
        print(f"   digest={mode:<11} halted at step {s:>3} for ${cost:>5.2f} on '{why}'")
    assert execute({"max_steps": 60, "cost_cap": 2.00, "repeat": 3}, mode="naive")[3] == "cost_cap"
    print("   -> the loop carried a changing nonce, so every naive hash was unique")
    print("      and the detector never fired. Normalise, then hash.\n")

    print("5. IDEMPOTENCY - the worker dies after the tool call, before the checkpoint")
    CRM, SEEN = [], {}

    def crm_create(args, key=None):
        if key is not None and key in SEEN:
            return SEEN[key]                          # broker replays the recorded outcome
        rid = f"rec-{len(CRM) + 1}"
        CRM.append((rid, args))
        if key is not None:
            SEEN[key] = rid                           # production records BEFORE dispatch
        return rid

    args = {"account": 4471, "note": "refund raised"}
    crm_create(args); crm_create(args)                # crash, then replay
    print(f"   no idempotency key -> {len(CRM)} customer records: {[r[0] for r in CRM]}")
    assert len(CRM) == 2
    CRM, SEEN = [], {}
    k = hashlib.sha1(json.dumps(["run-9f2", 5, "crm_create", args], sort_keys=True).encode()).hexdigest()[:10]
    crm_create(args, k); crm_create(args, k)
    print(f"   key=sha1(run,step,tool,args) -> {len(CRM)} customer record: {[r[0] for r in CRM]}")
    assert len(CRM) == 1
    print("   -> this is Celery acks_late plus a visibility timeout, wearing an")
    print("      agent's clothes. Any retry policy makes it mandatory.\n")

    print("6. CHECKPOINTING - crash at step 5 of 8")
    cold = run_cost(5) + run_cost(8)
    warm = run_cost(5) + (run_cost(8) - run_cost(5))
    print(f"   cold restart from zero: 13 calls, ${cold:.3f}")
    print(f"   resume from checkpoint:  8 calls, ${warm:.3f}   ({(1 - warm / cold) * 100:.0f}% cheaper)")
    assert warm < cold and abs((cold - warm) - run_cost(5)) < 1e-9   # the waste IS the replay
    print("   -> and the same checkpoint is what lets a budget halt be a PAUSE with")
    print("      a resume link rather than a loss of seven paid steps.")

    print("""
WHAT TO NOTICE
  * $27.89 vs $0.08 for the identical bug. The difference is entirely which layer
    noticed. Cost is quadratic in steps, so every step you fail to prevent costs
    more than the one before it.
  * The cost cap halts at 52 steps having spent $1.98, never $2.05 - because
    admission is checked against the PROJECTED next step, not the spend so far.
  * The naive digest run is indistinguishable from having no detector at all.
    Loop detection is a normalisation problem before it is a counting problem.
  * Two identical tool calls, one customer record - only once the broker stamps
    an idempotency key. Retries and side effects are the same conversation.""")
    print("\nOK - scenario 4")
