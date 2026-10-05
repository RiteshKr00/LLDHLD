"""
Scenario 8 - the release gate for an LLM feature, and what a naive one ships.

    python3 solution.py          (stdlib only, deterministic, runs in ~1s)

One golden set of 60 cases - the smoke tier; the full tier in hld.md is 800 -
scored under a baseline system and a candidate whose prompt was rewritten. The
candidate's composite score is unchanged. It also breaks seven cases, silently
stops producing a hard-gate metric for a third of the set, and costs 27 percent
more per call. Watch the naive gate ship it; then watch the hardened gate block
it and say exactly why.
"""
import hashlib
import random
from dataclasses import dataclass

random.seed(8)

PASS_AT = 0.70                              # a case passes when its mean clears this
REPEATS = 3                                 # one run cannot see past its own variance
MARGIN = 2.5                                # noise-floor safety factor, see noise_floor()
FIXED = {3, 11, 19, 27, 35, 43}             # 6 cases the candidate improves
BROKEN = {5, 12, 21, 28, 37, 44, 53}        # 7 cases the candidate breaks
PRICE_IN, PRICE_OUT = 0.50e-6, 1.50e-6      # $ per token
CALLS = {"n": 0}
CACHE = {}


@dataclass(frozen=True)
class Case:
    cid: int
    feature: str
    base: float
    grounded: bool


@dataclass(frozen=True)
class System:
    """Everything that can move the output. All of it gets hashed."""
    name: str
    prompt_tokens: int
    tweaked: bool = False        # the candidate's prompt rewrite
    gold_key: str = "v1"         # the candidate renumbered the gold facts


def golden_set(n=60):
    """Stratified across three features. Provenance per case would live here too."""
    out = []
    for i in range(n):
        u = random.Random(f"case-{i}").random()
        if i in FIXED:
            base = 0.63 + 0.04 * u                      # just below the bar
        elif i in BROKEN:
            base = 0.74 + 0.04 * u                      # comfortably above it
        else:
            base = 0.62 + 0.30 * u
        out.append(Case(i, ("chat", "extract", "report")[i % 3], base, i % 25 != 0))
    return out


def manifest_hash(s: System) -> str:
    """The gate keys on this, not on the code diff. Prompts are config."""
    blob = f"{s.name}|{s.prompt_tokens}|{s.tweaked}|{s.gold_key}"
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def score_case(s: System, c: Case, run_id: str) -> float:
    key = (manifest_hash(s), c.cid, run_id)
    if key in CACHE:
        return CACHE[key]                               # content-addressed: no call
    CALLS["n"] += 1
    d = 0.0
    if s.tweaked:
        d = 0.14 if c.cid in FIXED else (-0.12 if c.cid in BROKEN else 0.0)
    noise = random.Random(str(key)).gauss(0, 0.008)     # temperature > 0
    CACHE[key] = max(0.0, min(1.0, c.base + d + noise))
    return CACHE[key]


def mean(d):
    return sum(d.values()) / len(d)


def run(s: System, cases, run_id: str):
    """Per-case mean score, the grounding metric, and the budget line."""
    scores = {c.cid: sum(score_case(s, c, f"{run_id}-{r}") for r in range(REPEATS))
              / REPEATS for c in cases}
    # The candidate renumbered the gold facts, so report cases are no longer
    # scoreable at all. The metric does not move. It stops existing.
    ground = {c.cid: c.grounded for c in cases
              if not (s.gold_key != "v1" and c.feature == "report")}
    return {"scores": scores, "ground": ground,
            "cost": s.prompt_tokens * PRICE_IN + 400 * PRICE_OUT,
            "p95": 900 + 0.35 * s.prompt_tokens}


def noise_floor(s, cases, trials=3):
    """Re-run the SAME system and diff it against itself. Nightly, not per PR.

    Set the threshold at the observed maximum and you flag one case in two, so
    multiply by a margin. And note the composite floor is sqrt(n) smaller than
    the per-case floor - it will not protect an individual case.
    """
    per_case = composite = 0.0
    for t in range(trials):
        a, b = run(s, cases, f"null{t}a"), run(s, cases, f"null{t}b")
        per_case = max(per_case, max(abs(a["scores"][c.cid] - b["scores"][c.cid])
                                     for c in cases))
        composite = max(composite, abs(mean(a["scores"]) - mean(b["scores"])))
    return per_case * MARGIN, composite * MARGIN


def naive_gate(b, k):
    """Aggregates only, booleans only, mean over whatever data happens to exist."""
    reasons = []
    if mean(k["scores"]) - mean(b["scores"]) < -0.005:
        reasons.append("composite dropped")
    if mean(k["ground"]) < 0.85:
        reasons.append("grounding below 0.85")
    return ("BLOCK" if reasons else "SHIP"), reasons


def hardened_gate(b, k, floors, cases):
    """Paired per case, tri-state, and the budgets are gates too."""
    pcf = floors[0]
    reasons, wins, regressed = [], [], []
    for c in cases:
        lo, hi = b["scores"][c.cid], k["scores"][c.cid]
        if lo - hi > pcf and lo >= PASS_AT > hi:
            regressed.append(c.cid)
        if hi - lo > pcf and hi >= PASS_AT > lo:
            wins.append(c.cid)
    if regressed:
        reasons.append(f"{len(regressed)} cases passed at baseline and now fail: "
                       f"{sorted(regressed)}")
    missing = len(b["ground"]) - len(k["ground"])
    if missing:
        reasons.append(f"grounding: NO-DATA for {missing} of {len(b['ground'])} cases "
                       f"- a hard gate with no data blocks, never passes")
    dc, dl = k["cost"] / b["cost"] - 1, k["p95"] / b["p95"] - 1
    if dc > 0.10:
        reasons.append(f"cost per call {dc:+.1%} against a +10% hard gate")
    if dl > 0.15:
        reasons.append(f"p95 latency {dl:+.1%} against a +15% hard gate")
    return ("BLOCK" if reasons else "SHIP"), reasons, wins, regressed


if __name__ == "__main__":
    cases = golden_set()
    BASE, CAND = System("baseline", 1800), System("candidate", 2600, True, "v2")

    print("0. NOISE FLOOR - re-run the identical config, change nothing")
    floors = noise_floor(BASE, cases)
    print(f"   per-case floor {floors[0]:.4f}    composite floor {floors[1]:.4f}"
          f"    (observed spread x{MARGIN})\n")

    b, k = run(BASE, cases, "main"), run(CAND, cases, "pr")
    delta = mean(k["scores"]) - mean(b["scores"])
    bp = sum(v >= PASS_AT for v in b["scores"].values())
    kp = sum(v >= PASS_AT for v in k["scores"].values())

    print("1. THE SCORECARD")
    print(f"   {'metric':<16}{'baseline':>11}{'candidate':>11}{'delta':>10}   note")
    for row in (
        ("composite", f"{mean(b['scores']):.4f}", f"{mean(k['scores']):.4f}",
         f"{delta:+.4f}", "inside the composite floor"),
        ("cases passing", f"{bp}/60", f"{kp}/60", f"{kp - bp:+d}", "net of 6 fixed, 7 broken"),
        ("grounding", f"{mean(b['ground']):.2f}", f"{mean(k['ground']):.2f}",
         f"{mean(k['ground']) - mean(b['ground']):+.2f}",
         f"coverage {len(k['ground'])}/{len(b['ground'])} <- the tell"),
        ("cost per call", f"${b['cost']:.4f}", f"${k['cost']:.4f}",
         f"{k['cost'] / b['cost'] - 1:+.1%}", "quality is not the only budget"),
        ("p95 latency", f"{b['p95']:.0f}ms", f"{k['p95']:.0f}ms",
         f"{k['p95'] / b['p95'] - 1:+.1%}", "nor is cost"),
    ):
        print(f"   {row[0]:<16}{row[1]:>11}{row[2]:>11}{row[3]:>10}   {row[4]}")

    nv, nr = naive_gate(b, k)
    hv, hr, wins, regressed = hardened_gate(b, k, floors, cases)
    print(f"\n2. NAIVE GATE - aggregates, booleans, mean-of-what-exists -> {nv}")
    for r in nr:
        print(f"     - {r}")
    print(f"     (it fixed {len(wins)} cases and broke {len(regressed)}; "
          f"the mean reports neither)")
    print(f"\n3. HARDENED GATE - paired, tri-state, budgeted -> {hv}")
    for r in hr:
        print(f"     - {r}")

    print("\n4. CONTENT ADDRESSING - what a re-run costs")
    CALLS["n"] = 0
    run(BASE, cases, "main")
    hit = CALLS["n"]
    CALLS["n"] = 0
    run(System("baseline", 1810), cases, "main")
    miss = CALLS["n"]
    print(f"   same manifest hash {manifest_hash(BASE)}     -> {hit:>3} provider calls")
    print(f"   one prompt token edited, new hash  -> {miss:>3} provider calls")

    assert nv == "SHIP", "the naive gate ships it - that is the whole point"
    assert hv == "BLOCK"
    assert set(regressed) == BROKEN, "the paired diff must find exactly those 7"
    assert set(wins) == FIXED, "and credit exactly those 6"
    assert abs(delta) < floors[1], "composite delta is inside the noise floor"
    assert mean(k["ground"]) == mean(b["ground"]), "the metric value did not move"
    assert len(k["ground"]) < len(b["ground"]), "its coverage collapsed"
    assert hit == 0 and miss == 180

    print("""
  what to notice
  --------------
  * the composite is unchanged and SEVEN cases regressed - six fixes cancelled
    seven breaks. An aggregate sees net movement, never churn, so the gate has
    to be a PAIRED PER-CASE diff where a new failure blocks whatever the mean did.
  * the per-case floor is far larger than the composite floor. Averaging 60
    cases shrinks noise by sqrt(60), so a threshold borrowed from the composite
    would flag half the set. Measure both, under a NULL change.
  * grounding still reads 0.95 - over a third fewer cases. The metric did not
    move, it stopped being computable. Report COVERAGE beside every metric and
    block on a hard gate with no data. Coercing no-data to a boolean is how a
    regressed figure once shipped under 'all hard gates pass'.
  * cost +26.7 percent and p95 +18.3 percent, from a prompt that genuinely
    improved six cases. Gate the budgets or you buy quality with latency.
  * an unchanged manifest hash costs 0 provider calls, one edited token costs
    180. That cache is what keeps a 6-minute full tier affordable - and a cheap
    gate is the one nobody bypasses.
""")
    print("OK - scenario 8")
