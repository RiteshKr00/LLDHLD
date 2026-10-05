"""
Scenario 20 - incident: the assistant started fabricating.

    python3 solution.py

Four mechanics, each with the failure shown happening FIRST, then the fix:
  1. triage as a bisection, priced against guessing
  2. the actual bug: prompt assembly that REPLACED context instead of adding it
  3. the second bug: a character cap that truncated facts out of the prompt
  4. detection - groundedness on sampled traffic, and refusal rate as a guardrail

Population: 5,000 production requests over 14 days, the fault introduced on
day 7. Seeded, so reruns match exactly.

What to notice: the technical fix in section 2 is one line. The whole cost of
this incident is TIME TO DETECTION, which is a monitoring problem, not an
engineering one.
"""
import random

random.seed(20)

DAYS = 14
FAULT_DAY = 7
PER_DAY = 5_000 // DAYS

# the triage ladder: (hypothesis, prior probability, minutes to check)
LADDER = [
    ("retrieval returns nothing",        0.34,  3),
    ("context not reaching the prompt",  0.22,  8),
    ("context truncated",                0.14,  8),
    ("corpus changed",                   0.10, 25),
    ("model version changed",            0.08, 15),
    ("prompt template changed",          0.09,  5),
    ("one tenant only - scoping bug",    0.03, 12),
]


def expected_minutes(order):
    """Sum over hypotheses of P(cause) x minutes spent reaching it."""
    total, elapsed = 0.0, 0.0
    for name, p, mins in order:
        elapsed += mins
        total += p * elapsed
    return total


# --------------------------------------------------------------------------- #
# 2. prompt assembly - the either/or bug
# --------------------------------------------------------------------------- #
def assemble_buggy(persona, style, chunks):
    """The bug: a saved writing style REPLACED the retrieved facts."""
    body = style if style else "\n".join(chunks)
    return f"{persona}\n\n{body}"


def assemble_fixed(persona, style, chunks):
    """Style is a modifier. Facts are not optional."""
    parts = [persona]
    if style:
        parts.append("Write in this style: " + style)
    parts.append("Use ONLY these facts:\n" + "\n".join(chunks))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# 3. truncation
# --------------------------------------------------------------------------- #
CAP = 300


def pack(chunks, cap=CAP):
    return [c[:cap] for c in chunks]


def facts_surviving(chunks, packed):
    """A chunk carries its fact at a known offset; count how many survive."""
    kept = 0
    for original, cut in zip(chunks, packed):
        if "FACT:" in cut:
            kept += 1
    return kept


# --------------------------------------------------------------------------- #
# 4. detection
# --------------------------------------------------------------------------- #
def day_stats(day):
    """Groundedness and refusal rate, before and after the fault."""
    broken = day >= FAULT_DAY
    g, r = [], []
    for _ in range(PER_DAY):
        if broken:
            grounded = random.random() < 0.61          # facts often missing
            refused = random.random() < 0.02           # and it stops admitting it
        else:
            grounded = random.random() < 0.94
            refused = random.random() < 0.09
        g.append(grounded)
        r.append(refused)
    return sum(g) / len(g), sum(r) / len(r)


def main():
    print("\nINCIDENT: THE ASSISTANT STARTED FABRICATING")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. TRIAGE - a bisection, not a list")
    best = sorted(LADDER, key=lambda h: h[2] / h[1])       # cheapest per unit of prior
    worst = sorted(LADDER, key=lambda h: -h[2])            # start with the deepest dive
    print(f"   {'checked in this order':<36}{'exp. minutes to cause':>22}")
    for label, order in (("by prior / cost  (the ladder)", best),
                         ("by intuition     (deepest first)", worst)):
        print(f"   {label:<36}{expected_minutes(order):>19.0f} min")
    print()
    print(f"   {'#':<3}{'hypothesis':<34}{'prior':>7}{'min':>6}")
    for i, (name, p, mins) in enumerate(best, 1):
        print(f"   {i:<3}{name:<34}{p:>6.0%}{mins:>6}")
    assert expected_minutes(best) < expected_minutes(worst) / 2
    print("   -> order by prior divided by cost, and say WHY as you go. The top two")
    print("      hypotheses are 56% of the probability and 11 minutes of work.\n")

    # ---------------------------------------------------------------- 2
    print("2. THE BUG - prompt assembly, one line")
    persona = "You are the assistant."
    style = "Warm, concise, British spelling."
    chunks = ["FACT: the refund window is 30 days.",
              "FACT: refunds go to the original payment method."]
    bad = assemble_buggy(persona, style, chunks)
    good = assemble_fixed(persona, style, chunks)
    print(f"   with a saved style set, facts in the prompt: buggy "
          f"{sum(1 for c in chunks if c in bad)} of {len(chunks)}   "
          f"fixed {sum(1 for c in chunks if c in good)} of {len(chunks)}")
    none_set = assemble_buggy(persona, "", chunks)
    print(f"   with NO style set, facts present: {sum(1 for c in chunks if c in none_set)}"
          f" of {len(chunks)}  <- why it passed every test")
    assert all(c not in bad for c in chunks)
    assert all(c in good for c in chunks)
    assert all(c in none_set for c in chunks)
    print("   -> the either/or is invisible until a tenant saves a style. The fix is to")
    print("      make assembly a PURE FUNCTION and test it with each input present and")
    print("      absent - four cases, and the bug cannot survive any of them.\n")

    # ---------------------------------------------------------------- 3
    print("3. THE SECOND BUG - a cap that cuts facts out")
    long_chunks = ["x" * 320 + " FACT: the refund window is 30 days.",
                   "y" * 280 + " FACT: refunds go to the original method.",
                   "FACT: support hours are 9 to 5." + " z" * 200]
    packed = pack(long_chunks)
    kept = facts_surviving(long_chunks, packed)
    print(f"   {CAP}-char cap over chunks of "
          f"{', '.join(str(len(c)) for c in long_chunks)} chars")
    print(f"   facts surviving: {kept} of {len(long_chunks)}")
    assert kept < len(long_chunks)
    print("   -> truncation is silent by construction: the prompt is well-formed, the")
    print("      model is confident, and the facts are simply absent. Count dropped")
    print("      characters as a metric, and cap by TOKENS at a chunk boundary.\n")

    # ---------------------------------------------------------------- 4
    print("4. DETECTION - what should have caught it on day 7")
    print(f"   {'day':>4}{'groundedness':>15}{'refusal rate':>15}   alert")
    first_g = first_r = None
    for d in range(1, DAYS + 1):
        g, r = day_stats(d)
        flag = ""
        # both independently - an elif here would hide that they fire the same day
        if g < 0.85 and first_g is None:
            first_g, flag = d, "GROUNDEDNESS"
        if r < 0.05 and first_r is None:
            first_r = d
            flag = (flag + " + refusals") if flag else "refusal-rate drop"
        if d in (5, 6, 7, 8, 9, 14):
            print(f"   {d:>4}{g:>14.1%}{r:>14.1%}   {flag}")
    print(f"\n   groundedness alert fires on day {first_g}")
    print(f"   refusal-rate drop visible from day {first_r}")
    assert first_g == FAULT_DAY
    print(f"   users reported it on day 11, so detection was 4 days late.")
    print("   -> a FALL in refusals looks like an improvement on every dashboard you")
    print("      have. It is the same incident wearing a disguise, which is exactly why")
    print("      it belongs on the alert list as a guardrail rather than a KPI.\n")

    print("WHAT TO NOTICE")
    print("   * the technical fix is one line; the entire cost was time to detection")
    print("   * both bugs are SILENT - a well-formed prompt with the facts missing")
    print("   * the mitigation before you know the cause is to raise the relevance floor")
    print("     and refuse more: a refusal is recoverable, a fabrication is not")
    print("   * log the resolved prompt version and retrieved chunk ids per request, or")
    print("     the next incident is unbisectable")
    print("\nOK - scenario 20")


if __name__ == "__main__":
    main()
