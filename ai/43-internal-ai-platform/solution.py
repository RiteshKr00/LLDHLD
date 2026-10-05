"""
Scenario 29 - an internal AI platform for ten product teams.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. duplicated effort: ten teams building the same five components
  2. adoption arithmetic - a platform slower than DIY is not adopted
  3. cost attribution, and what an unattributable invoice costs you
  4. the blast radius of one shared key vs per-team keys
  5. the escape hatch, and the paved road staying ahead

Seeded, so reruns match exactly.

What to notice: sections 2 and 5 are the scenario. The components are
uncontroversial; whether teams USE them is the entire problem, and a mandate
without a speed advantage is a bypass with extra steps.
"""
import random

random.seed(29)

TEAMS = 10
COMPONENTS = [("gateway + key management", 12),
              ("caching", 6),
              ("eval harness", 15),
              ("observability + tracing", 9),
              ("PII / guardrail middleware", 11)]
DEV_WEEK = 4_200.0           # £ loaded cost of one engineer-week


def duplicated():
    per_team = sum(w for _, w in COMPONENTS)
    return per_team * TEAMS, per_team


# --------------------------------------------------------------------------- #
# 2. adoption
# --------------------------------------------------------------------------- #
def adopts(platform_weeks, diy_weeks, mandate, team_pragmatism):
    """A team adopts if the platform is faster, or if a mandate binds them.

    A mandate on a slower road does not produce adoption; it produces a
    conversation, an exception, and eventually a bypass.
    """
    if platform_weeks < diy_weeks:
        return True, "faster"
    if mandate and team_pragmatism < 0.5:
        return True, "complied"
    return False, "bypassed"


def adoption_rate(platform_weeks, diy_weeks, mandate):
    got = 0
    reasons = {}
    for i in range(TEAMS):
        ok, why = adopts(platform_weeks, diy_weeks, mandate, random.random())
        got += ok
        reasons[why] = reasons.get(why, 0) + 1
    return got / TEAMS, reasons


# --------------------------------------------------------------------------- #
# 3. cost attribution
# --------------------------------------------------------------------------- #
SPEND = {"search": 4_100, "support-bot": 18_400, "summariser": 2_200,
         "onboarding": 900, "analytics": 6_600, "recommender": 1_050,
         "moderation": 3_300, "docs-qa": 780, "sales-copilot": 11_900,
         "internal-tools": 410}


def unattributed_view(spend):
    return {"TOTAL": sum(spend.values())}


def main():
    print("\nINTERNAL AI PLATFORM FOR TEN PRODUCT TEAMS")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. TEN IMPLEMENTATIONS, NINE OF THEM WRONG")
    total, per_team = duplicated()
    print(f"   {'component':<32}{'weeks per team':>16}{'x10 teams':>12}")
    for name, w in COMPONENTS:
        print(f"   {name:<32}{w:>16}{w * TEAMS:>12}")
    print(f"   {'TOTAL':<32}{per_team:>16}{total:>12}")
    print(f"\n   duplicated build cost: £{total * DEV_WEEK:,.0f}")
    print(f"   built once, properly:  £{per_team * 2 * DEV_WEEK:,.0f}   "
          f"(2x, because a platform version is harder)")
    assert per_team * 2 < total
    print(f"   -> {total - per_team * 2} engineer-weeks saved, and - the real point - "
          f"nine of the ten")
    print("      eval harnesses would not have existed at all. The platform's value is")
    print("      not the saving, it is the nine teams that get a gate they would")
    print("      otherwise have skipped.\n")

    # ---------------------------------------------------------------- 2
    print("2. ADOPTION - the arithmetic that decides everything")
    diy = 8
    print(f"   a team can DIY a working integration in {diy} weeks")
    print(f"   {'platform onboarding':>22}{'mandate?':>11}{'adoption':>11}   outcome")
    for pw, mand in ((12, False), (12, True), (2, False), (2, True)):
        rate, why = adoption_rate(pw, diy, mand)
        desc = ", ".join(f"{v} {k}" for k, v in sorted(why.items()))
        print(f"   {str(pw) + ' weeks':>22}{str(mand):>11}{rate:>11.0%}   {desc}")
    slow_mand, _ = adoption_rate(12, diy, True)
    fast_none, _ = adoption_rate(2, diy, False)
    assert fast_none > slow_mand
    print("   -> a mandate on a SLOWER road buys partial, resentful compliance and a")
    print("      steady stream of exception requests. A faster road needs no mandate.")
    print("      Make the paved road genuinely quicker than DIY and the policy question")
    print("      stops being interesting.\n")

    # ---------------------------------------------------------------- 3
    print("3. COST ATTRIBUTION")
    print(f"   what finance sees today: {unattributed_view(SPEND)}")
    top = sorted(SPEND.items(), key=lambda kv: -kv[1])
    total_spend = sum(SPEND.values())
    print(f"   what per-team attribution shows:")
    for name, amt in top[:4]:
        print(f"      {name:<18}£{amt:>7,}{amt / total_spend:>8.0%}")
    print(f"      {'... 6 more':<18}"
          f"£{sum(v for _, v in top[4:]):>7,}{sum(v for _, v in top[4:]) / total_spend:>8.0%}")
    assert top[0][1] / total_spend > 0.3
    print(f"   -> two teams are {(top[0][1] + top[1][1]) / total_spend:.0%} of the bill. "
          f"Without attribution that is one")
    print("      unexplainable number and every team is equally innocent. With it, the")
    print("      conversation is with two people and it is a specific one.\n")

    # ---------------------------------------------------------------- 4
    print("4. BLAST RADIUS - one shared key vs per-team keys")
    scenarios = [("one shared provider key", TEAMS, "rotate for everyone, all teams down"),
                 ("per-team keys via the gateway", 1, "revoke one, nine teams unaffected")]
    print(f"   {'scheme':<32}{'teams affected':>16}   response")
    for name, blast, resp in scenarios:
        print(f"   {name:<32}{blast:>16}   {resp}")
    assert scenarios[1][1] < scenarios[0][1]
    print("   -> the gateway is what makes per-team keys possible without ten teams")
    print("      each managing secrets. Central secrets, per-team credentials, and a")
    print("      leak is bounded to the team that leaked it.\n")

    # ---------------------------------------------------------------- 5
    print("5. THE ESCAPE HATCH")
    options = [
        ("no escape hatch", "teams route around you silently; you lose visibility too"),
        ("escape hatch, no review", "it becomes the main road within two quarters"),
        ("escape hatch with a review and a time limit",
         "legitimate cases proceed; the review tells you what to build next"),
    ]
    for name, effect in options:
        print(f"   {name}\n      {effect}")
    print("   -> every exception request is a feature request with evidence attached.")
    print("      A platform with no escape hatch does not get compliance, it gets")
    print("      shadow usage - which is strictly worse, because you have lost the")
    print("      visibility you built the platform to obtain.\n")

    print("WHAT TO NOTICE")
    print("   * the components are uncontroversial; ADOPTION is the whole problem")
    print("   * a platform teams bypass is worse than none - you have a false sense of")
    print("     central control and no data")
    print("   * the value is not the engineer-weeks saved, it is the nine teams that get")
    print("     an eval gate they would otherwise have skipped")
    print("   * make the paved road faster than DIY and you will not need the mandate")
    print("\nOK - scenario 29")


if __name__ == "__main__":
    main()
