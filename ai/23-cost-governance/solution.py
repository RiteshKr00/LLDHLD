"""
Scenario 9 - cost governance across 500 tenants. Detection latency is the bug.

    python3 solution.py

Four mechanics, failure first then fix, so the gap is measured not asserted:
  1. ATTRIBUTION - 3% of calls carry no tenant tag, and that is where a runaway
     hides: all 500 per-tenant detectors stay green while the bill triples
  2. DETECTION LATENCY - one runaway, four detectors. The provider invoice costs
     $140,556 more than a burn-rate alert on a 5-minute window
  3. ENFORCEMENT - capping a cost you only learn AFTER the call. The prompt-only
     estimate over-admits 11x; reserve worst case, commit actual, release the rest
  4. DEGRADE, DON'T CUT OFF - one hour under three policies, priced, alongside
     the number of requests actually served

What to notice: no detector in part 2 is wrong, and all four name the right
tenant. The only variable separating $35 from $140,556 is WHEN.
"""
import random

random.seed(9)

# ONE rate card, USD per 1k tokens. Versioned and effective-dated in reality, so
# a rollup computed in March does not move when the card is edited in April.
RATE_CARD = {"frontier": {"in": 0.0030, "out": 0.0150},
             "mid":      {"in": 0.00015, "out": 0.00060}}
PROMPT_TOK, OUT_TOK, MAX_TOK = 1000, 200, 4000


def price(model, prompt_tok, out_tok):
    r = RATE_CARD[model]
    return prompt_tok / 1000 * r["in"] + out_tok / 1000 * r["out"]


CALL_FRONTIER = price("frontier", PROMPT_TOK, OUT_TOK)   # $0.00600
CALL_MID      = price("mid", PROMPT_TOK, OUT_TOK)        # $0.00027, 22x cheaper
WORST_CASE    = price("frontier", PROMPT_TOK, MAX_TOK)   # $0.06300 pre-flight

# the platform (hld.md): 600k calls/day x $0.004 mean = $2,400/day = $100/hour
PLATFORM_HOURLY, TENANT_HOURLY, UNTAGGED_HOURLY = 100.00, 4.00, 3.00
LOOP_CPS      = 10                                    # the runaway, calls/second
LOOP_HOURLY   = LOOP_CPS * 3600 * CALL_FRONTIER       # $216.00/hour, one tenant
EXCESS_HOURLY = LOOP_HOURLY - TENANT_HOURLY           # $212.00/hour
MIN_PER_DAY, DAYS = 1440, 30
START, MONTH_END = 2 * MIN_PER_DAY + 9 * 60, DAYS * MIN_PER_DAY   # day 3, 09:00


def tenant_spend_at(m):
    """USD spent by tenant t-042 during minute m of the month."""
    return (LOOP_HOURLY if m >= START else TENANT_HOURLY) / 60.0


def excess(at):
    return (at - START) / 60.0 * EXCESS_HOURLY


# --- 1. ATTRIBUTION: an untagged call reaches no counter, budget or owner -----
def one_hour(tag_required):
    attributed = {"t-042": (TENANT_HOURLY, TENANT_HOURLY),
                  "the other 499 tenants": (93.00, 93.00)}
    untagged = 0.0
    if tag_required:
        attributed["internal-ops / nightly-summary"] = (
            UNTAGGED_HOURLY, UNTAGGED_HOURLY + LOOP_HOURLY)
    else:
        untagged = UNTAGGED_HOURLY + LOOP_HOURLY
    fired = [k for k, (base, act) in attributed.items() if act > 3.0 * base]
    seen = sum(a for _, a in attributed.values())
    return seen, seen + untagged, fired


# --- 2. DETECTION LATENCY: four detectors, one incident -----------------------
def detect_invoice():
    return MONTH_END                    # nothing looks until the month closes


def detect_daily(cap=200.00):
    for d in range(DAYS):               # batch job over yesterday, at midnight
        if sum(tenant_spend_at(m)
               for m in range(d * MIN_PER_DAY, (d + 1) * MIN_PER_DAY)) > cap:
            return (d + 1) * MIN_PER_DAY


def detect_budget_pct(budget=4000.00, pct=0.80):
    total = 0.0                         # cumulative, absolute, monthly window
    for m in range(MONTH_END):
        total += tenant_spend_at(m)
        if total > budget * pct:
            return m + 1


def detect_burn(bucket=5, mult=3.0, runs=2, hist_n=12, floor=10.0):
    """Rate of CHANGE against the tenant's own baseline, plus a dollar floor.
    The floor is what stops 500 tenants becoming 2,000 pagers."""
    hits, hist = 0, []
    for b0 in range(0, MONTH_END, bucket):
        spend = sum(tenant_spend_at(m) for m in range(b0, b0 + bucket))
        if len(hist) >= hist_n:
            base = sorted(hist[-hist_n:])[hist_n // 2]
            proj = (spend - base) * (60.0 / bucket)         # projected $/hour
            hits = hits + 1 if (base > 0 and spend > mult * base
                                and proj > floor) else 0
            if hits >= runs:
                return b0 + bucket
        hist.append(spend)


# --- 3. ENFORCEMENT: cap a cost you only learn afterwards ---------------------
def run_cap(ceiling, est, commit):
    """commit=True books the actual cost and releases the unused reservation.
    commit=False is the let-the-ledger-reconcile-later bug: the gate counts an
    estimate it already knows to be wrong."""
    random.seed(9)
    reserved = spent = 0.0
    admitted = 0
    while reserved + est <= ceiling:
        reserved += est
        actual = price("frontier", PROMPT_TOK, random.randint(50, MAX_TOK))
        spent += actual
        if commit:
            reserved += actual - est
        admitted += 1
    return admitted, spent


# --- 4. DEGRADE, DON'T CUT OFF ------------------------------------------------
def hour_under(policy, soft=12.00, calls=LOOP_CPS * 3600):
    spend = frontier = 0.0
    served = 0
    for _ in range(calls):
        if policy == "none":
            spend, served = spend + CALL_FRONTIER, served + 1
        elif frontier + CALL_FRONTIER <= soft + 1e-9:
            frontier += CALL_FRONTIER
            spend, served = spend + CALL_FRONTIER, served + 1
        elif policy == "degrade":
            spend, served = spend + CALL_MID, served + 1
    return spend, served


if __name__ == "__main__":
    print(f"rate card: frontier ${CALL_FRONTIER:.5f}/call, mid ${CALL_MID:.5f} "
          f"({CALL_FRONTIER / CALL_MID:.0f}x cheaper), worst case ${WORST_CASE:.3f}")
    print(f"platform ${PLATFORM_HOURLY:.0f}/hour | runaway: {LOOP_CPS} calls/s from "
          f"ONE tenant = ${LOOP_HOURLY:.0f}/hour\n")

    print("1. ATTRIBUTION - one hour, a nightly job retry-storms")
    for req in (False, True):
        seen, inv, fired = one_hour(req)
        print(f"   {'tag REQUIRED' if req else 'untagged allowed':<16} dashboard "
              f"${seen:6.2f} of ${inv:6.2f} invoice = {seen / inv * 100:5.1f}%"
              f"   fired: {fired or 'NONE, nothing to page'}")
    assert one_hour(False)[2] == []
    assert one_hour(True)[2] == ["internal-ops / nightly-summary"]
    assert one_hour(True)[0] == one_hour(True)[1]
    print("   -> the 69% gap IS the runaway. Attribution under 100% is not")
    print("      untidiness, it is the exact shape of the blind spot.\n")

    print("2. DETECTION LATENCY - t-042's loop, found four ways")
    rows = [("burn rate, 5-min vs own baseline", detect_burn()),
            ("monthly budget, 80% threshold", detect_budget_pct()),
            ("daily rollup vs a $200/day cap", detect_daily()),
            ("the provider invoice", detect_invoice())]
    print(f"   {'detector':<34}{'found after':>13}{'excess spend':>15}")
    for name, at in rows:
        mins = at - START
        when = f"{mins} min" if mins < 120 else f"{mins / 60:.1f} h"
        print(f"   {name:<34}{when:>13}{'$' + format(excess(at), ',.2f'):>15}")
    burn, pct_at, daily, inv = (r[1] for r in rows)
    assert burn - START == 10, "3x sustained over two 5-minute windows"
    assert excess(burn) < 40 < 2000 < excess(pct_at) < excess(daily) < excess(inv)
    assert excess(inv) > 140_000
    mb = 0.10 / 12                                # median tenant, 5-minute bucket
    print(f"   floor check: a median tenant tripling projects "
          f"${(3 * mb - mb) * 12:.2f}/hour of excess -> no page, its cap covers it")
    print("   -> absolute thresholds are late BY CONSTRUCTION: the budget window")
    print("      is monthly, the burn is hourly. Alert on rate of change.\n")

    print("3. ENFORCEMENT - a $12 hourly ceiling, output tokens unknown up front")
    a_n, a_sp = run_cap(12.00, price("frontier", PROMPT_TOK, 0), commit=False)
    b_n, b_sp = run_cap(12.00, WORST_CASE, commit=True)
    print(f"   prompt-only estimate, no commit  {a_n:>5} calls  ${a_sp:7.2f}"
          f"  <- {a_sp / 12.0:.0f}x over a $12 cap")
    print(f"   worst case reserved, then commit {b_n:>5} calls  ${b_sp:7.2f}"
          f"  <- within one call of it")
    assert a_sp > 10 * 12.00, "estimating on prompt tokens alone over-admits"
    assert 12.00 - 2 * WORST_CASE < b_sp <= 12.00 + 1e-6
    print("   -> reserve worst case, book actual, release the difference. Overshoot")
    print(f"      is then bounded by calls-in-flight x ${WORST_CASE:.3f}.\n")

    print("4. DEGRADE, DON'T CUT OFF - one hour of the runaway, three policies")
    print(f"   {'policy':<30}{'spend':>10}{'served':>10}{'refused':>10}")
    res = {}
    for pol, label in (("none", "no governance"),
                       ("cutoff", "hard cutoff at the ceiling"),
                       ("degrade", "degrade to the mid model")):
        sp, sv = res[pol] = hour_under(pol)
        print(f"   {label:<30}{'$' + format(sp, ',.2f'):>10}{sv:>10}"
              f"{LOOP_CPS * 3600 - sv:>10}")
    assert res["degrade"][0] < res["none"][0] / 8
    assert res["degrade"][1] == res["none"][1], "degrading refuses nobody"
    assert res["cutoff"][1] < res["none"][1] / 10

    print("""
  what to notice
  --------------
  * part 1: the invoice is $316 and the dashboard adds to $97. Every budget is
    intact and every detector green, because an untagged call never reaches a
    counter. Require the tag at admission and the same storm becomes one
    named, owned, alertable line.
  * part 2: all four detectors are correct and all four name t-042. Only the
    timing differs, and the spread is $140,521. Detection latency IS the design.
  * the 80% budget alert and the daily rollup land 72 minutes apart and both
    cost about $3,000 - two 'proper' controls, both useless, because a monthly
    window cannot see an hourly burn.
  * part 3: the broken gate is not sloppy, it is precise about the wrong
    number: $0.003 of prompt against $0.033 of real cost. Reserving the worst
    case turns the cap from a suggestion into an upper bound.
  * part 4: degrading costs 10x less than doing nothing AND serves every
    request the cutoff refused. But 36,000 cheap answers to a retry loop are
    still 36,000 useless answers - the degrade buys the ten minutes until the
    burn alert reaches a human. It is not a fix.
""")
    print("OK - scenario 9")
