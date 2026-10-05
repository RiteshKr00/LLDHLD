"""
14 - the four production mechanics, demonstrated and measured.

    python3 solution.py

1. tiered memory      -> shows cost going QUADRATIC vs staying linear
2. context budgeting  -> what gets dropped, and what never does
3. idempotent resume  -> the partial-side-effect problem, both ways
4. trajectory eval    -> why final-answer scoring misses the real bug
"""
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# 1. MEMORY - naive resend vs tiered
# --------------------------------------------------------------------------- #
TURN_TOKENS = 200
SUMMARY_TOKENS = 120
FACT_TOKENS = 15


def naive_cost(turns: int) -> int:
    """Resend the whole history every turn -> sum(1..n) -> quadratic."""
    return sum(t * TURN_TOKENS for t in range(1, turns + 1))


def tiered_cost(turns: int, keep_verbatim=10, facts=6) -> int:
    """Recent verbatim + one rolling summary + a few structured facts.

    Per-turn context stops growing once the window is full, so total cost is
    LINEAR in turns instead of quadratic.
    """
    per_turn = keep_verbatim * TURN_TOKENS + SUMMARY_TOKENS + facts * FACT_TOKENS
    total = 0
    for t in range(1, turns + 1):
        total += min(t * TURN_TOKENS, per_turn)
    return total


# --------------------------------------------------------------------------- #
# 2. CONTEXT BUDGET - explicit allocation, and a defined drop order
# --------------------------------------------------------------------------- #
WINDOW = 8000


def build_context(system, chunks, recent, summary, user_input):
    """Assemble within a hard budget. Drop order is a DESIGN decision."""
    budget = WINDOW
    out, dropped = {}, []

    # never droppable, and placed at the EDGES (lost-in-the-middle)
    for name, text in (("system", system), ("input", user_input)):
        out[name] = text
        budget -= len(text.split())
    if budget < 0:
        raise RuntimeError("system + input alone exceed the window")

    # droppable, in PRIORITY order - whatever is checked last is dropped first
    for name, text in (("recent", recent), ("chunks", chunks), ("summary", summary)):
        cost = len(text.split())
        if cost <= budget:
            out[name] = text
            budget -= cost
        else:
            dropped.append(name)
    return out, dropped, budget


# --------------------------------------------------------------------------- #
# 3. IDEMPOTENT RESUME - the partial-side-effect problem
# --------------------------------------------------------------------------- #
@dataclass
class Ledger:
    """Stands in for the real world: a table you wrote a row to."""
    rows: list = field(default_factory=list)
    seen: dict = field(default_factory=dict)

    def charge(self, amount, key=None):
        if key is not None and key in self.seen:
            return self.seen[key]                 # no-op, returns the FIRST result
        receipt = f"receipt-{len(self.rows) + 1}"
        self.rows.append((amount, receipt))
        if key is not None:
            self.seen[key] = receipt
        return receipt


def run_with_crash(ledger, use_key: bool, run_id="run-7"):
    """Step 2 succeeds, the process dies before the checkpoint is written.
    Then we resume from the last GOOD checkpoint - which is step 1.
    """
    key = f"{run_id}:step2:charge" if use_key else None
    checkpoint = {"step": 1}

    # --- attempt 1: charge succeeds, crash before checkpointing step 2 ---
    ledger.charge(100, key=key)
    # (crash here - checkpoint still says step 1)

    # --- resume from the checkpoint: step 2 runs AGAIN ---
    if checkpoint["step"] < 2:
        ledger.charge(100, key=key)
        checkpoint["step"] = 2
    return checkpoint


# --------------------------------------------------------------------------- #
# 4. TRAJECTORY EVAL - a right answer via a wrong path
# --------------------------------------------------------------------------- #
RUNS = [
    {"id": "a", "answer": "correct", "tools": ["get_user", "get_policy"], "steps": 3},
    {"id": "b", "answer": "correct", "tools": ["list_all_users", "get_policy"], "steps": 9},
    {"id": "c", "answer": "wrong",   "tools": ["get_user"], "steps": 2},
]
EXPECTED_TOOLS = {"get_user", "get_policy"}


def score(runs):
    final = sum(r["answer"] == "correct" for r in runs) / len(runs)
    traj = sum(set(r["tools"]) == EXPECTED_TOOLS for r in runs) / len(runs)
    p95_steps = sorted(r["steps"] for r in runs)[int(0.95 * (len(runs) - 1))]
    return final, traj, p95_steps


if __name__ == "__main__":
    print("1. MEMORY - cost over a long conversation")
    print("   turns   naive (resend all)   tiered      ratio")
    for t in (10, 50, 200):
        n, d = naive_cost(t), tiered_cost(t)
        print(f"   {t:>5}   {n:>18,}   {d:>9,}   {n / d:>5.1f}x")
    assert naive_cost(200) / tiered_cost(200) > 4
    print("   -> naive is QUADRATIC in turns; tiered is linear once the window fills\n")

    print("2. CONTEXT BUDGET - what gets dropped")
    ctx, dropped, left = build_context(
        system="be terse " * 20, chunks="chunk " * 7500,
        recent="turn " * 400, summary="summary " * 200,
        user_input="what is the notice period")
    print(f"   kept: {sorted(ctx)}")
    print(f"   dropped: {dropped}   tokens left: {left}")
    assert "input" in ctx and "system" in ctx, "these are never droppable"
    assert "summary" in dropped, "the lowest-priority slice should drop first"
    print("   -> system + input are never droppable; the summary is lowest")
    print("      priority so it goes first. Silent truncation is how")
    print("      grounding disappears with no error - so LOG the drop.\n")

    print("3. IDEMPOTENT RESUME - crash after a side effect")
    bad = Ledger(); run_with_crash(bad, use_key=False)
    good = Ledger(); run_with_crash(good, use_key=True)
    print(f"   without an idempotency key: {len(bad.rows)} charges  <- DOUBLE-CHARGED")
    print(f"   with an idempotency key:    {len(good.rows)} charge   <- no-op on resume")
    assert len(bad.rows) == 2 and len(good.rows) == 1
    print("   -> without keys, 'resume' is more dangerous than 'restart'\n")

    print("4. TRAJECTORY EVAL - final answer vs the path taken")
    f, tr, p95 = score(RUNS)
    print(f"   final-answer accuracy : {f:.0%}   <- looks acceptable")
    print(f"   trajectory accuracy   : {tr:.0%}   <- the real picture")
    print(f"   p95 step count        : {p95}")
    print("   -> run 'b' got the RIGHT answer by calling list_all_users:")
    print("      correct output, wrong path, 3x the steps. Final-answer")
    print("      scoring calls that a pass. It is a latent bug.\n")
    assert tr < f

    print("OK - topic 14")
