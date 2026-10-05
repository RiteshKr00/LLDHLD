"""
06 - the noise floor, and the tri-state gate that failed open.

    python3 solution.py

Two lessons, both from a real bug:
  1. establish run-to-run variance BEFORE attributing any delta
  2. a gate has three states, and 'no data' must never mean 'pass'
"""
import random, statistics

random.seed(7)

GOLD = {"STUDY-006": {"enrollment": 430, "sites": 12}}


# --------------------------------------------------------------------------- #
# 1. THE NOISE FLOOR
# --------------------------------------------------------------------------- #
def score_model(name: str) -> float:
    """Stand-in for a scoring run. Same config still varies slightly."""
    base = {"qwen-32b": 0.677, "gemma-27b": 0.682, "qwen-14b": 0.681,
            "medgemma-27b": 0.684}[name]
    return round(base + random.uniform(-0.001, 0.001), 4)


def noise_floor(name: str, runs: int = 3) -> float:
    """Re-run ONE config with nothing changed. The spread is the floor."""
    scores = [score_model(name) for _ in range(runs)]
    return max(scores) - min(scores), scores


# --------------------------------------------------------------------------- #
# 2. THE TRI-STATE GATE
# --------------------------------------------------------------------------- #
PASS, FAIL, NO_DATA = "pass", "fail", "no-data"


def headline_fact_accuracy(draft: dict, study_id: str):
    """Returns a tri-state, not a bool. This is the whole fix."""
    gold = GOLD.get(study_id)
    if gold is None:
        return NO_DATA, None            # <- the bug was coercing this to PASS
    hits = sum(draft.get(k) == v for k, v in gold.items())
    return (PASS if hits == len(gold) else FAIL), hits / len(gold)


def gate_boolean(draft, study_id):
    """The BUGGY gate: two states, so 'no data' has to become one of them."""
    verdict, _ = headline_fact_accuracy(draft, study_id)
    return verdict != FAIL              # NO_DATA silently becomes True


def gate_tristate(draft, study_id):
    """The FIXED gate: no-data BLOCKS."""
    verdict, _ = headline_fact_accuracy(draft, study_id)
    return {PASS: "release", FAIL: "block", NO_DATA: "block"}[verdict]


if __name__ == "__main__":
    print("1. NOISE FLOOR - re-run one config, change nothing")
    spread, scores = noise_floor("qwen-32b")
    print(f"   qwen-32b x3 -> {scores}")
    print(f"   spread = {spread:.4f}  <- the NOISE FLOOR\n")

    print("2. NOW compare four models against it")
    results = {m: score_model(m) for m in
               ("qwen-32b", "gemma-27b", "qwen-14b", "medgemma-27b")}
    best, worst = max(results.values()), min(results.values())
    print("   " + "  ".join(f"{m}={v}" for m, v in results.items()))
    print(f"   best - worst = {best - worst:.4f}")
    verdict = "REAL" if (best - worst) > spread else "NOISE - do not act on it"
    print(f"   vs floor {spread:.4f} -> {verdict}\n")

    print("3. THE GATE - a regressed draft, gold facts keyed to the WRONG study")
    regressed = {"enrollment": 411, "sites": 12}      # 411 != 430, a regression
    for study_id, label in (("STUDY-006", "correct key"),
                            ("STUDY-999", "WRONG key -> no data")):
        v, acc = headline_fact_accuracy(regressed, study_id)
        b = gate_boolean(regressed, study_id)
        t = gate_tristate(regressed, study_id)
        print(f"   {label:<24} metric={v:<8} boolean-gate={'PASS' if b else 'block':<5}"
              f"  tri-state-gate={t}")

    assert gate_boolean(regressed, "STUDY-999") is True, "the bug: no-data passes"
    assert gate_tristate(regressed, "STUDY-999") == "block", "the fix"
    assert gate_tristate(regressed, "STUDY-006") == "block", "a real regression blocks"

    print("""
  what to notice
  --------------
  * the four models land INSIDE the noise floor. Without measuring the
    floor first you would read that spread as a finding and reorganise a
    sprint around it. The real lever was retrieval, not the model.
  * the boolean gate PASSED a regressed draft, because gold facts keyed to
    the wrong study id returned no-data and no-data was coerced to True.
    A figure regressed from 430 to 411 shipped under 'all hard gates pass'.
  * the bug was COLLAPSING THREE STATES INTO TWO. Same shape as fail-closed
    in topic 03: when the answer is unknown, the safe default is restrictive.
""")
    print("OK - topic 06")
