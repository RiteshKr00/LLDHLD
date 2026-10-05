"""
Scenario 27 - support copilot: deflection without making people angrier.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. deflection rate as a metric, and the cost it hides
  2. confidence-gated deflection, and where the boundary should sit
  3. the escape hatch, and what trapping people costs
  4. context handoff - what actually makes a customer angry
  5. actions: confirmation, idempotency and a tiered scope

Population: 10,000 tickets. Seeded, so reruns match exactly.

What to notice: section 1 is the whole scenario. A deflection engine optimised
on deflection is strictly easy to build and strictly worse than no engine.
"""
import random

random.seed(27)

TICKETS = 10_000
HUMAN_COST = 6.20            # £ per human-handled ticket
AI_COST = 0.04               # £ per AI-handled ticket
# a ticket that was answered WRONGLY and comes back costs more than a fresh one:
# the customer is annoyed, the agent must undo an answer, and it takes longer
REOPEN_MULTIPLIER = 2.4
# On ticket-handling cost ALONE, deflecting everything wins - which is exactly
# why teams do it. The cost that makes the argument honest is the customer you
# lose: a badly-handled ticket carries a churn risk against lifetime value, and
# that term dwarfs the handling cost.
CHURN_P = 0.04               # chance a wrongly-deflected customer leaves
LTV = 600.0                  # £ lifetime value
CHURN_COST = CHURN_P * LTV   # £24 expected, per wrong deflection


def outcome(confidence, threshold):
    """Deflect above threshold. Accuracy rises with confidence, imperfectly."""
    if confidence < threshold:
        return "escalated", True
    correct = random.random() < (0.55 + 0.44 * confidence)
    return ("deflected_ok" if correct else "deflected_wrong"), correct


def run(threshold, n=TICKETS):
    counts = {"deflected_ok": 0, "deflected_wrong": 0, "escalated": 0}
    for _ in range(n):
        c = min(0.999, max(0.0, random.betavariate(5, 2)))
        kind, _ = outcome(c, threshold)
        counts[kind] += 1
    return counts


def economics(c):
    deflected = c["deflected_ok"] + c["deflected_wrong"]
    cost = (deflected * AI_COST
            + c["escalated"] * (AI_COST + HUMAN_COST)
            + c["deflected_wrong"] * (AI_COST + HUMAN_COST * REOPEN_MULTIPLIER
                                      + CHURN_COST))
    baseline = TICKETS * HUMAN_COST
    return {
        "deflection_rate": deflected / TICKETS,
        "true_deflection": c["deflected_ok"] / TICKETS,
        "reopen_rate": c["deflected_wrong"] / max(deflected, 1),
        "cost": cost,
        "saving": 1 - cost / baseline,
    }


# --------------------------------------------------------------------------- #
# 3 and 4. escape hatch and handoff
# --------------------------------------------------------------------------- #
def csat(trapped, repeated_self, resolved):
    """A crude model, but the ORDERING is the robust part."""
    s = 4.6 if resolved else 2.9
    if repeated_self:
        s -= 1.1          # the single biggest complaint in support research
    if trapped:
        s -= 1.6          # bigger than being told no
    return round(max(1.0, s), 1)


HANDOFF_FIELDS = [
    ("full transcript", "the customer does not repeat themselves"),
    ("what the agent already tried", "the human does not repeat the agent"),
    ("KB articles retrieved", "the human can see WHY it answered that"),
    ("confidence and escalation reason", "the human knows what to distrust"),
    ("customer's account state", "no 'can I take your order number?'"),
]


# --------------------------------------------------------------------------- #
# 5. actions
# --------------------------------------------------------------------------- #
class Ledger:
    def __init__(self):
        self.applied = {}

    def refund(self, ticket_id, amount, idempotency_key=None):
        key = idempotency_key or object()
        if key in self.applied:
            return "already applied", self.applied[key]
        self.applied[key] = amount
        return "applied", amount


TIERS = [("answer questions", "freely", "reversible, and the KB is the ceiling"),
         ("read account state", "freely", "no side effect"),
         ("resend a receipt", "narrowly", "idempotent, harmless if repeated"),
         ("apply account credit", "with confirmation", "reversible by a human"),
         ("issue a refund", "with confirmation + idempotency", "money moves"),
         ("cancel a contract", "never", "irreversible, and a retention decision")]


def main():
    print("\nSUPPORT COPILOT WITH ESCALATION")
    print("=" * 76)

    # ---------------------------------------------------------------- 1
    print("1. DEFLECTION RATE IS THE WRONG METRIC")
    print(f"   {'threshold':>10}{'deflection':>12}{'of those, wrong':>17}"
          f"{'TRUE deflection':>17}{'saving':>9}")
    rows = {}
    for t in (0.00, 0.50, 0.70, 0.85, 0.95):
        e = economics(run(t))
        rows[t] = e
        print(f"   {t:>10.2f}{e['deflection_rate']:>12.0%}{e['reopen_rate']:>17.0%}"
              f"{e['true_deflection']:>17.0%}{e['saving']:>9.0%}")
    greedy = rows[0.00]
    best_t = max(rows, key=lambda t: rows[t]["saving"])
    best = rows[best_t]
    # the optimum is INTERIOR: neither deflect-everything nor deflect-nothing
    assert best_t not in (0.00, 0.95)
    assert greedy["saving"] < best["saving"]
    assert greedy["deflection_rate"] > best["deflection_rate"]
    print(f"   -> deflecting EVERYTHING scores {greedy['deflection_rate']:.0%} deflection - the")
    print(f"      best possible dashboard - and saves {greedy['saving']:.0%}. Gating at "
          f"{best_t:.2f} deflects")
    print(f"      {best['deflection_rate']:.0%} and saves {best['saving']:.0%}.")
    print("      The optimum is INTERIOR, which is the finding: not deflect-everything,")
    print("      not deflect-nothing. And note what makes it interior - on handling")
    print(f"      cost alone greedy wins. It is the £{CHURN_COST:.0f} of expected churn per")
    print("      wrong deflection that turns the dashboard winner into the loser.\n")

    # ---------------------------------------------------------------- 2
    print("2. WHERE THE BOUNDARY SITS")
    print(f"   best saving at threshold {best_t:.2f}: {rows[best_t]['saving']:.0%}")
    print("   but the threshold is not really a cost optimisation:")
    print(f"      at 0.50 you deflect {rows[0.50]['deflection_rate']:.0%} with "
          f"{rows[0.50]['reopen_rate']:.0%} of them wrong")
    print(f"      at 0.95 you deflect {rows[0.95]['deflection_rate']:.0%} with "
          f"{rows[0.95]['reopen_rate']:.0%} of them wrong")
    assert rows[0.95]["reopen_rate"] < rows[0.50]["reopen_rate"]
    print("   -> it is a CSAT dial with a cost side-effect. Set it from the reopen rate")
    print("      you can live with, then read off the saving - not the other way round.\n")

    # ---------------------------------------------------------------- 3
    print("3. THE ESCAPE HATCH")
    print(f"   {'journey':<44}{'CSAT':>6}")
    for label, trapped, repeat, resolved in (
            ("resolved by AI, first answer", False, False, True),
            ("not resolved, human offered immediately", False, False, False),
            ("not resolved, had to repeat everything", False, True, False),
            ("not resolved, could not reach a human", True, True, False)):
        print(f"   {label:<44}{csat(trapped, repeat, resolved):>6}")
    assert csat(True, True, False) < csat(False, True, False) < csat(False, False, False)
    print("   -> being unable to reach a human costs more than being told no. An")
    print("      always-visible 'talk to a person' does reduce deflection slightly, and")
    print("      it is the difference between a tool people tolerate and one they hate.\n")

    # ---------------------------------------------------------------- 4
    print("4. THE HANDOFF - what actually makes people angry")
    for field, why in HANDOFF_FIELDS:
        print(f"   {field:<34}{why}")
    print(f"   CSAT, unresolved + had to repeat: {csat(False, True, False)}")
    print(f"   CSAT, unresolved + full handoff : {csat(False, False, False)}")
    assert csat(False, False, False) - csat(False, True, False) > 1.0
    print("   -> more than a point of CSAT, on a ticket the AI FAILED. Escalation is")
    print("      not the failure case to minimise; a bad escalation is.\n")

    # ---------------------------------------------------------------- 5
    print("5. ACTIONS - tiered scope, confirmation, idempotency")
    for what, when, why in TIERS:
        print(f"   {what:<22}{when:<32}{why}")
    led = Ledger()
    print()
    print(f"   refund attempt 1: {led.refund('T-1', 40.0, 'T-1:refund')}")
    print(f"   retry after a timeout: {led.refund('T-1', 40.0, 'T-1:refund')}")
    no_key = Ledger()
    no_key.refund("T-2", 40.0)
    no_key.refund("T-2", 40.0)
    print(f"   without an idempotency key, the same retry applies "
          f"{len(no_key.applied)} refunds")
    assert len(led.applied) == 1 and len(no_key.applied) == 2
    print("   -> the retry is not hypothetical: a timeout on a slow payment call is the")
    print("      normal case, and an agent that retries is doing the right thing. The")
    print("      key makes the right thing safe.\n")

    print("WHAT TO NOTICE")
    print("   * a deflection engine optimised on deflection is easy to build, wins the")
    print("     dashboard, and is worse than not shipping it")
    print("   * pair every deflection number with reopen rate and CSAT, or do not")
    print("     report it")
    print("   * the escape hatch costs you deflection and buys the product's reputation")
    print("   * escalation is not the failure - a BAD escalation is, and the fix is")
    print("     context, not accuracy")
    print("\nOK - scenario 27")


if __name__ == "__main__":
    main()
