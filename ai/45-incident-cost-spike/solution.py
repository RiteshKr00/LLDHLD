"""
Scenario 31 - incident: LLM cost spiked 5x overnight, nothing deployed.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. the one division that splits the problem in two
  2. the five causes that need no deploy, and how each one looks
  3. a cache-hit collapse, which is invisible as a cost line
  4. an agent without a step budget
  5. alerting on rate of change instead of absolute spend

Seeded, so reruns match exactly.

What to notice: every cause below happens with no code change, which is why
"nothing was deployed" narrows nothing. And the whole cost of the incident is
detection latency: an hourly problem discovered on a monthly invoice.
"""
import random

random.seed(31)

BASE_CALLS = 240_000            # per day
BASE_COST_PER_CALL = 0.0021
BASE_SPEND = BASE_CALLS * BASE_COST_PER_CALL


# --------------------------------------------------------------------------- #
# 1 and 2. the causes
# --------------------------------------------------------------------------- #
CAUSES = {
    "cache hit-rate collapse":   {"calls": 4.30, "cpc": 1.00},
    "agent with no step budget": {"calls": 5.20, "cpc": 0.98},
    "retry storm":               {"calls": 4.80, "cpc": 1.02},
    "fallback to a pricier model": {"calls": 1.02, "cpc": 4.90},
    "prompt got longer":         {"calls": 1.00, "cpc": 5.05},
    "provider raised prices":    {"calls": 1.00, "cpc": 5.00},
}


def observe(cause):
    m = CAUSES[cause]
    calls = int(BASE_CALLS * m["calls"])
    cpc = BASE_COST_PER_CALL * m["cpc"]
    return calls, cpc, calls * cpc


def bisect(calls, cpc):
    """The one division. Everything else follows from which side moved."""
    vol_ratio = calls / BASE_CALLS
    cpc_ratio = cpc / BASE_COST_PER_CALL
    if vol_ratio > 1.5 and cpc_ratio < 1.5:
        return "VOLUME", ["cache collapse", "agent loop", "retry storm", "a scraper"]
    if cpc_ratio > 1.5 and vol_ratio < 1.5:
        return "COST/CALL", ["longer prompt", "longer output",
                             "router shifted to an expensive model", "price change"]
    return "BOTH", ["two things happened, or a routing change that also retries"]


# --------------------------------------------------------------------------- #
# 3. the cache
# --------------------------------------------------------------------------- #
def with_cache(hit_rate, requests=1_000_000):
    misses = int(requests * (1 - hit_rate))
    return misses, misses * BASE_COST_PER_CALL


# --------------------------------------------------------------------------- #
# 4. the agent
# --------------------------------------------------------------------------- #
def agent_run(step_budget, loop_rate=0.002, hard_cap=400):
    """Most runs finish in a few steps; a small fraction never self-terminate.

    Modelling this as a per-step continue probability is wrong: it makes almost
    every run stop at step one and produces no tail at all. The real shape is a
    rare run that genuinely does not converge - a tool that keeps returning
    something the planner treats as progress.
    """
    looping = random.random() < loop_rate
    natural = random.randint(2, 6)
    limit = step_budget or hard_cap
    if looping:
        return limit, ("budget" if step_budget else "hard cap")
    return min(natural, limit), "finished"


# --------------------------------------------------------------------------- #
# 5. alerting
# --------------------------------------------------------------------------- #
def hourly_spend(hour, spiked_from=2):
    base = BASE_SPEND / 24
    return base * (5.0 if hour >= spiked_from else 1.0)


def absolute_alert(spend_so_far, monthly_budget=BASE_SPEND * 30):
    return spend_so_far > monthly_budget * 0.8


def rate_alert(this_hour, trailing_mean, factor=2.0):
    return this_hour > trailing_mean * factor


def main():
    print("\nINCIDENT: COST SPIKED 5x OVERNIGHT, NOTHING DEPLOYED")
    print("=" * 76)
    print(f"normal: {BASE_CALLS:,} calls/day at £{BASE_COST_PER_CALL:.4f} "
          f"= £{BASE_SPEND:,.0f}/day\n")

    # ---------------------------------------------------------------- 1
    print("1. THE FIRST DIVISION - spend / calls")
    print(f"   {'cause':<30}{'calls':>10}{'£/call':>10}{'spend':>10}   splits to")
    for cause in CAUSES:
        calls, cpc, spend = observe(cause)
        side, _ = bisect(calls, cpc)
        print(f"   {cause:<30}{calls / BASE_CALLS:>9.1f}x{cpc / BASE_COST_PER_CALL:>9.1f}x"
              f"{spend / BASE_SPEND:>9.1f}x   {side}")
    assert bisect(*observe("retry storm")[:2])[0] == "VOLUME"
    assert bisect(*observe("prompt got longer")[:2])[0] == "COST/CALL"
    print("   -> one division, thirty seconds, and half the hypotheses are gone. Do")
    print("      this before opening a single dashboard: every cause above produces the")
    print("      same 5x on the bill and they are not the same problem.\n")

    # ---------------------------------------------------------------- 2
    print("2. NONE OF THESE NEEDED A DEPLOY")
    reasons = [
        ("cache hit-rate collapse", "a re-index changed the key, or a TTL expired en masse"),
        ("agent with no step budget", "one user asked something that loops"),
        ("retry storm", "the provider got slower, so everything retried"),
        ("fallback to a pricier model", "the cheap provider circuit-broke"),
        ("prompt got longer", "a prompt edit, or retrieval returning more chunks"),
        ("provider raised prices", "an email nobody read"),
    ]
    for cause, why in reasons:
        print(f"   {cause:<30}{why}")
    print('   -> "nothing was deployed" is true and narrows nothing. The most common')
    print("      causes of a cost spike are all config, data or somebody else's")
    print("      infrastructure.\n")

    # ---------------------------------------------------------------- 3
    print("3. THE CACHE COLLAPSE - invisible as a cost line")
    print(f"   {'hit rate':>10}{'calls reaching the provider':>30}{'daily £':>12}")
    for hr in (0.78, 0.60, 0.30, 0.05):
        misses, cost = with_cache(hr)
        print(f"   {hr:>10.0%}{misses:>30,}{cost:>12,.0f}")
    m78, c78 = with_cache(0.78)
    m05, c05 = with_cache(0.05)
    assert c05 / c78 > 4
    print(f"   -> 78% to 5% is {c05 / c78:.1f}x the bill with IDENTICAL user traffic.")
    print("      On a provider dashboard it looks exactly like a volume increase, which")
    print("      is why cache hit rate has to be a first-class alert of its own: it is")
    print("      the one cause that disguises itself as a different cause.\n")

    # ---------------------------------------------------------------- 4
    print("4. THE AGENT WITHOUT A STEP BUDGET")
    print(f"   {'step budget':>12}{'mean steps':>13}{'worst run':>12}{'£/1k runs':>12}"
          f"{'p99.9 steps':>13}")
    for budget in (0, 8, 20):
        runs = [agent_run(budget) for _ in range(20_000)]
        mean = sum(s for s, _ in runs) / len(runs)
        worst = max(s for s, _ in runs)
        tail = sorted(s for s, _ in runs)[int(len(runs) * 0.999)]
        print(f"   {(budget or 'none'):>12}{mean:>13.1f}{worst:>12}"
              f"{mean * 1000 * BASE_COST_PER_CALL:>12,.2f}{tail:>13}")
    unbounded = [agent_run(0) for _ in range(20_000)]
    bounded = [agent_run(8) for _ in range(20_000)]
    assert max(s for s, _ in unbounded) > max(s for s, _ in bounded) * 3
    print("   -> the mean barely moves, so an average-based dashboard shows nothing.")
    print("      The damage is in the tail: a handful of runs that never terminate. A")
    print("      per-run step budget with a breaker caps the worst case, and the worst")
    print("      case is the entire problem.\n")

    # ---------------------------------------------------------------- 5
    print("5. ALERTING - absolute spend vs rate of change")
    trailing = BASE_SPEND / 24
    fired_abs = fired_rate = None
    cum = 0.0
    for hour in range(24):
        h = hourly_spend(hour)
        cum += h
        if fired_rate is None and rate_alert(h, trailing):
            fired_rate = hour
        if fired_abs is None and absolute_alert(cum + BASE_SPEND * 20):
            fired_abs = hour
    print(f"   spike begins at hour 2")
    print(f"   rate-of-change alert fires at hour {fired_rate}")
    print(f"   absolute-budget alert fires at hour "
          f"{fired_abs if fired_abs is not None else 'never today'}")
    assert fired_rate is not None and fired_rate <= 2
    print("   -> an 80%-of-monthly-budget alert is a smoke detector that waits until")
    print("      the house is 80% burnt. Alert on the DERIVATIVE: this hour against a")
    print("      trailing mean, per tenant and per feature. Same data, hours instead")
    print("      of weeks.\n")

    print("WHAT TO NOTICE")
    print("   * divide spend by calls before anything else - it halves the problem")
    print("   * every common cause needs no deploy, so 'nothing shipped' is not a clue")
    print("   * the cache is the cause that disguises itself as a different cause")
    print("   * agent loops hide in the tail, where means cannot see them")
    print("   * the entire cost of this incident is detection latency: an hourly")
    print("     problem found on a monthly invoice")
    print("\nOK - scenario 31")


if __name__ == "__main__":
    main()
