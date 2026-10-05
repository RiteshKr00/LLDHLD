"""
Scenario 1 - a multi-model LLM platform that does not fail at scale.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. the component list that looks complete and leaves a failure uncovered
  2. daily rate limits, which break before per-minute limits and before capacity
  3. cascade routing, and the escalation rate at which it stops saving money
  4. a capability registry, because a fallback that cannot do the task is an
     outage wearing a 200
  5. per-feature degradation, because one fallback chain cannot serve a
     summariser and a legal answer

Seeded, so reruns match exactly.

What to notice: section 1 is the scenario's actual trap. Every candidate can
list a gateway, a router and a breaker. The design is the mapping from
component to prevented failure, and doing it as a table exposes the gap.
"""
import random

random.seed(1)

INSTANCES = 10
RPM_LIMIT = 6_000              # per-minute, per provider
DAILY_LIMIT = 2_000_000        # per-day, per provider - the one nobody quotes
PEAK_RPM = 4_200


# --------------------------------------------------------------------------- #
# 1. components against failures
# --------------------------------------------------------------------------- #
FAILURES = ["provider outage", "daily quota exhausted", "tail latency",
            "unattributable cost", "capability mismatch", "model deprecated",
            "retry amplification"]

# what a component list usually looks like, and what each item actually covers
NAIVE = {
    "gateway":            ["unattributable cost"],
    "router":             ["provider outage"],
    "cache":              ["tail latency"],
    "circuit breaker":    ["provider outage", "retry amplification"],
    "retries + backoff":  [],
}
FIXED = dict(NAIVE)
FIXED.update({
    "shared token bucket":  ["daily quota exhausted", "retry amplification"],
    "capability registry":  ["capability mismatch", "model deprecated"],
    "usage ledger":         ["unattributable cost"],
    "validate on receipt":  ["capability mismatch"],
    "per-model eval + pin": ["model deprecated"],
})


def uncovered(mapping):
    covered = set()
    for v in mapping.values():
        covered.update(v)
    return [f for f in FAILURES if f not in covered]


# --------------------------------------------------------------------------- #
# 2. rate limits
# --------------------------------------------------------------------------- #
def day_of_traffic(rpm_profile):
    """Returns (minute the cap blows or None, calls by then, calls the day wanted)."""
    used, hit = 0, None
    for minute, rpm in enumerate(rpm_profile):
        used += rpm
        if hit is None and used > DAILY_LIMIT:
            hit = minute
    return hit, DAILY_LIMIT, used


def profile():
    """A normal day: quiet night, business-hours peak."""
    out = []
    for m in range(1440):
        hour = m // 60
        if 9 <= hour < 18:
            out.append(int(PEAK_RPM * random.uniform(0.85, 1.0)))
        elif 6 <= hour < 9 or 18 <= hour < 22:
            out.append(int(PEAK_RPM * 0.45))
        else:
            out.append(int(PEAK_RPM * 0.08))
    return out


# --------------------------------------------------------------------------- #
# 3. the cascade
# --------------------------------------------------------------------------- #
CHEAP, MID, FRONTIER = 0.00020, 0.00120, 0.01000    # £ per call


def cascade_cost(n, escalate_to_mid, escalate_to_frontier):
    """Every call pays for the cheap attempt, escalations pay again."""
    mid = n * escalate_to_mid
    front = mid * escalate_to_frontier
    return n * CHEAP + mid * MID + front * FRONTIER


def frontier_only(n):
    return n * FRONTIER


# --------------------------------------------------------------------------- #
# 4. capabilities
# --------------------------------------------------------------------------- #
MODELS = {
    "fast-8b":    {"tools": False, "ctx": 8_000,   "json": True},
    "mid-70b":    {"tools": True,  "ctx": 128_000, "json": True},
    "frontier":   {"tools": True,  "ctx": 200_000, "json": True},
    "legacy-13b": {"tools": False, "ctx": 4_000,   "json": False},
}
NEEDS = {"tool-calling agent":  {"tools": True,  "ctx": 32_000,  "json": True},
         "long-doc summary":    {"tools": False, "ctx": 150_000, "json": False},
         "field extraction":    {"tools": False, "ctx": 8_000,   "json": True},
         # one the cheapest model genuinely can serve - a registry that rejects
         # everything is just a slower outage
         "short classification": {"tools": False, "ctx": 2_000,   "json": False}}


def can_serve(model, need):
    m = MODELS[model]
    return (m["tools"] or not need["tools"]) and m["ctx"] >= need["ctx"] \
        and (m["json"] or not need["json"])


def blind_fallback(chain, need):
    """Take the next healthy model. Capability never checked."""
    return chain[0]


def registry_fallback(chain, need):
    for m in chain:
        if can_serve(m, need):
            return m
    return None


# --------------------------------------------------------------------------- #
# 5. per-feature degradation
# --------------------------------------------------------------------------- #
FEATURES = [
    ("dashboard summariser", "cheaper model is fine", ["mid-70b", "fast-8b", "cached", "hide"]),
    ("legal answer",         "must not degrade quality", ["frontier", "REFUSE"]),
    ("support draft",        "human reviews it anyway",  ["mid-70b", "fast-8b", "template"]),
]


def main():
    print("\nMULTI-MODEL LLM PLATFORM")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. THE TRAP - a component list that looks complete")
    print(f"   {'component':<24}prevents")
    for c, f in NAIVE.items():
        print(f"   {c:<24}{', '.join(f) if f else '(nothing named)'}")
    gap = uncovered(NAIVE)
    print(f"\n   failures with NO component against them: {len(gap)}")
    for f in gap:
        print(f"      - {f}")
    assert len(gap) >= 3
    print("\n   after mapping each failure to something that stops it:")
    for c in ("shared token bucket", "capability registry", "usage ledger",
              "validate on receipt", "per-model eval + pin"):
        print(f"   + {c:<22}{', '.join(FIXED[c])}")
    assert uncovered(FIXED) == []
    print(f"   -> the first list has five plausible components and leaves "
          f"{len(gap)} failure modes")
    print("      uncovered. Writing the table is what finds them; a diagram never does.")
    print("      This is the whole trap: components are easy, the mapping is the design.\n")

    # ---------------------------------------------------------------- 2
    print("2. WHAT BREAKS FIRST - the daily limit, not capacity")
    prof = profile()
    peak = max(prof)
    hit, served, wanted = day_of_traffic(prof)
    print(f"   per-minute limit {RPM_LIMIT:,}  observed peak {peak:,}  "
          f"headroom {1 - peak / RPM_LIMIT:.0%}")
    print(f"   daily limit      {DAILY_LIMIT:,}  the day wanted {wanted:,}  "
          f"({wanted / DAILY_LIMIT:.1f}x)")
    if hit is not None:
        print(f"   -> the daily cap is exhausted at {hit // 60:02d}:{hit % 60:02d}, "
              f"with {1440 - hit} minutes of the day left")
    assert peak < RPM_LIMIT           # per-minute looks perfectly healthy
    assert hit is not None            # and the day still ends early
    assert wanted > DAILY_LIMIT
    print("      Every per-minute dashboard is green all day. The failure is a")
    print("      quota you are not watching, and it arrives at the same time every")
    print("      afternoon - which is why 'what are the limits' needs BOTH numbers.\n")

    # ---------------------------------------------------------------- 3
    print("3. THE CASCADE - and when it stops saving money")
    n = 1_000_000
    print(f"   {'escalation to mid':>19}{'then to frontier':>19}"
          f"{'cascade £':>12}{'frontier-only £':>17}{'saving':>9}")
    for e_mid, e_front in ((0.10, 0.10), (0.30, 0.20), (0.60, 0.40), (0.90, 0.80)):
        c = cascade_cost(n, e_mid, e_front)
        f = frontier_only(n)
        print(f"   {e_mid:>19.0%}{e_front:>19.0%}{c:>12,.0f}{f:>17,.0f}"
              f"{1 - c / f:>9.0%}")
    good = cascade_cost(n, 0.10, 0.10)
    bad = cascade_cost(n, 0.90, 0.80)
    assert good < frontier_only(n) * 0.1
    assert bad > frontier_only(n) * 0.7
    print("   -> a cascade is a bet on the escalation rate. At 10% it removes 97% of")
    print("      the bill; at 90% it removes almost nothing and you have added a whole")
    print("      extra call to every request. Measure the rate before designing around")
    print("      it, and alert on it - a rising escalation rate is a silent cost leak.\n")

    # ---------------------------------------------------------------- 4
    print("4. CAPABILITY REGISTRY - a fallback that cannot do the job")
    chain = ["legacy-13b", "mid-70b", "frontier"]     # ordered by cost
    print(f"   fallback chain: {' -> '.join(chain)}")
    print(f"   {'feature':<22}{'blind fallback':<16}{'can it?':<10}{'registry picks':<14}")
    broke = 0
    for feat, need in NEEDS.items():
        b = blind_fallback(chain, need)
        ok = can_serve(b, need)
        r = registry_fallback(chain, need)
        if not ok:
            broke += 1
        print(f"   {feat:<22}{b:<16}{('yes' if ok else 'NO'):<10}{str(r):<14}")
    assert 0 < broke < len(NEEDS)     # some break, not all - the registry has work to do
    print(f"   -> {broke} of {len(NEEDS)} features silently break on the blind fallback.")
    print("      The call returns 200. The agent gets no tool call, the long document")
    print("      is truncated, the JSON is prose. An outage wearing a success code is")
    print("      worse than an outage, because nothing pages.\n")

    # ---------------------------------------------------------------- 5
    print("5. PER-FEATURE DEGRADATION")
    print(f"   {'feature':<22}{'quality floor':<28}ladder")
    for feat, floor, ladder in FEATURES:
        print(f"   {feat:<22}{floor:<28}{' -> '.join(ladder)}")
    assert FEATURES[1][2][-1] == "REFUSE"
    print("   -> one global fallback chain cannot serve these three. The summariser")
    print("      should degrade all the way to hidden; the legal answer must REFUSE")
    print("      rather than answer from a weaker model, because a confident wrong")
    print("      answer there is the expensive outcome. Degradation is a product")
    print("      decision per feature, and the platform's job is to make it")
    print("      expressible rather than to choose it.\n")

    print("WHAT TO NOTICE")
    print("   * the trap is a component list - name the failure each one prevents,")
    print("     and write it as a table, because that is what exposes the gap")
    print("   * daily quotas break before per-minute limits and before capacity")
    print("   * a cascade is a bet on the escalation rate; alert on that rate")
    print("   * a fallback to a model that cannot do the task returns 200 and breaks")
    print("     the feature - nothing pages, which makes it worse than an outage")
    print("   * degradation is per feature, and 'refuse' is a legitimate rung")
    print("\nOK - scenario 1")


if __name__ == "__main__":
    main()
