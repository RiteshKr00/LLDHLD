"""
Scenario 12 - the feedback flywheel: turning production signal into eval data.

    python3 solution.py            # deterministic, ~1s, stdlib only

Simulates one TENTH of the deck's day: 60,000 of the 600k calls, and 30 of the
300 labels/day a two-reviewer team can actually produce. Four mechanics, each
with the failure shown happening BEFORE the fix, so the contrast is measured:

  1. calibration    "the user edited it" is ~22% defective, not 100%
  2. the sampler    naive thumbs-and-edits vs posterior x novelty x strata
  3. class balance  a negatives-only golden set rewards refusing everything
  4. the queue      admitting faster than you label makes every label stale

A "what to notice" block at the end explains the printed numbers.
"""
import math
import random
from collections import Counter

random.seed(12)

N_REQUESTS = 60_000          # one tenth of a 600k/day production load
LABEL_BUDGET = 30            # one tenth of the 300 labels/day a 2-person team sustains
DEFECT_RATE = 0.015          # 9,000 genuinely bad answers per full day

FEATURES = [("chat", 0.67), ("voice", 0.20), ("extract", 0.08), ("report", 0.05)]
TENANTS = [("t-loud", 0.04), ("t-02", 0.24), ("t-03", 0.22),
           ("t-04", 0.20), ("t-05", 0.16), ("t-06", 0.14)]
MODES = [("ungrounded_claim", .28), ("wrong_number", .20), ("schema_break", .14),
         ("missing_citation", .12), ("truncated", .10), ("wrong_language", .07),
         ("over_refusal", .06), ("stale_fact", .03)]

# signal -> (P(fires | defective), P(fires | fine)). The SECOND number is the
# whole problem: every one of these fires on perfectly good answers too.
SIGNALS = {"checker_fail": (.1963, .000225), "downstream_fix": (.0432, .000154),
           "escalated": (.0510, .000273), "semantic_edit": (.1058, .000758),
           "regenerated": (.1493, .003140), "thumbs_down": (.0121, .000409),
           "edit_any": (.1140, .004694), "abandoned": (.0367, .001980)}
NOTE = {"checker_fail": "deterministic, no user involved", "downstream_fix": "delayed ground truth",
        "escalated": "strongest user signal, rarest", "semantic_edit": "a real content change",
        "regenerated": "often just 'make it shorter'", "thumbs_down": "self-selected, the angry few",
        "edit_any": "THE TRAP - mostly style", "abandoned": "the noisiest thing you can log"}
# a signal only exists where the surface exists: no edit box on a voice turn.
SURFACE = {"edit_any": {"chat", "report"}, "semantic_edit": {"chat", "report"}}
# the loud tenant clicks, edits and bails an order of magnitude more than
# anyone else - on the three LEAST precise signals. This wrecks a naive sampler.
LOUD = {"thumbs_down": 10.0, "edit_any": 8.0, "abandoned": 12.0}


def pick(weighted):
    r, acc = random.random(), 0.0
    for name, w in weighted:
        acc += w
        if r <= acc:
            return name
    return weighted[-1][0]


def fires_here(sig, feature):
    return feature in SURFACE.get(sig, {feature})


def precision(rows):
    return sum(r["defective"] for r in rows) / len(rows) if rows else 0.0


# a tenth of a day. Only requests emitting >=1 signal are kept - that IS the pool.
pool, defects = [], 0
for rid in range(N_REQUESTS):
    feature, tenant = pick(FEATURES), pick(TENANTS)
    bad = random.random() < DEFECT_RATE
    mode = pick(MODES) if bad else None
    defects += bad
    fired = {s for s, (pd, pk) in SIGNALS.items() if fires_here(s, feature) and random.random()
             < (pd if bad else pk * (LOUD.get(s, 1.0) if tenant == "t-loud" else 1.0))}
    if fired:
        # the cluster is OBSERVABLE (an embedding bucket of the redacted text);
        # the mode is not. Fine answers scatter over the same buckets, so the
        # cluster leaks nothing about the label.
        pool.append({"id": rid, "feature": feature, "tenant": tenant, "fired": fired,
                     "defective": bad, "mode": mode,
                     "cluster": [m for m, _ in MODES].index(mode) if bad else random.randrange(8)})

for r in pool:                                   # naive Bayes over available signals only
    lo = math.log(DEFECT_RATE / (1 - DEFECT_RATE))
    for s, (pd, pk) in SIGNALS.items():
        if fires_here(s, r["feature"]):
            lo += math.log(pd / pk) if s in r["fired"] else math.log((1 - pd) / (1 - pk))
    r["posterior"] = 1 / (1 + math.exp(-lo))

# --------------------------------------------------------------------------- #
# 1. CALIBRATION - measure what each signal is worth instead of trusting it
# --------------------------------------------------------------------------- #
print("1. CALIBRATION - what each signal is actually worth")
print(f"   {'signal':<16}{'fired':>6}{'precision':>11}   meaning")
prec = {}
for s in SIGNALS:
    rows = [r for r in pool if s in r["fired"]]
    prec[s] = precision(rows)
    print(f"   {s:<16}{len(rows):>6}{prec[s] * 100:>10.0f}%   {NOTE[s]}")
cofire = [r for r in pool if {"edit_any", "regenerated"} <= r["fired"]]
loud_e = [r for r in pool if "edit_any" in r["fired"] and r["tenant"] == "t-loud"]
rest_e = [r for r in pool if "edit_any" in r["fired"] and r["tenant"] != "t-loud"]
print(f"   {'edit+regen':<16}{len(cofire):>6}{precision(cofire) * 100:>10.0f}%   two weak signals AGREEING")
print(f"   {'edit, t-loud':<16}{len(loud_e):>6}{precision(loud_e) * 100:>10.0f}%   one tenant drags the blend")
print(f"   {'edit, everyone':<16}{len(rest_e):>6}{precision(rest_e) * 100:>10.0f}%   so calibrate PER SEGMENT too")

pool_prec, loud_share = precision(pool), sum(r["tenant"] == "t-loud" for r in pool) / len(pool)
print(f"\n   pool {len(pool)} of {N_REQUESTS} ({len(pool) / N_REQUESTS * 100:.1f}% of traffic) - "
      f"precision {pool_prec * 100:.0f}%, recall "
      f"{sum(r['defective'] for r in pool) / defects * 100:.0f}%")
print(f"   t-loud is 4% of traffic and {loud_share * 100:.0f}% of the pool\n")
assert prec["checker_fail"] > 3 * prec["edit_any"], "the free signal must beat the loud one"
assert precision(cofire) > prec["edit_any"] + .25, "co-firing must beat either signal alone"
assert pool_prec < 0.5, "a raw signal pool is majority noise - that is the point"
assert loud_share > 2.5 * 0.04, "the loud tenant must be over-represented in the pool"

# --------------------------------------------------------------------------- #
# 2. THE SAMPLER - 30 labels out of the pool. Which 30?
# --------------------------------------------------------------------------- #
FLOOR = 3
QUOTA = {f: FLOOR + int(round((LABEL_BUDGET - FLOOR * len(FEATURES)) * w)) for f, w in FEATURES}
QUOTA[FEATURES[0][0]] += LABEL_BUDGET - sum(QUOTA.values())
CAP = {t: max(2, int(round(2 * w * LABEL_BUDGET))) for t, w in TENANTS}


def sample_naive(n):
    """What teams actually ship: log thumbs-downs and edits, work the recent ones."""
    return sorted((r for r in pool if r["fired"] & {"thumbs_down", "edit_any"}),
                  key=lambda r: -r["id"])[:n]


def sample_priority(n):
    """posterior x novelty, under a per-feature quota and a per-tenant cap."""
    f_n, t_n, c_n, out, seen = Counter(), Counter(), Counter(), [], set()
    for _ in range(n):
        best, top = None, -1.0
        for r in pool:
            if r["id"] in seen or f_n[r["feature"]] >= QUOTA[r["feature"]] \
                    or t_n[r["tenant"]] >= CAP[r["tenant"]]:
                continue
            score = r["posterior"] / (1.0 + 0.5 * c_n[r["cluster"]])
            if score > top:
                best, top = r, score
        if best is None:
            break
        out.append(best)
        seen.add(best["id"])
        f_n[best["feature"]] += 1
        t_n[best["tenant"]] += 1
        c_n[best["cluster"]] += 1
    return out


def card(p):
    return (precision(p), sum(r["tenant"] == "t-loud" for r in p) / len(p),
            len({r["mode"] for r in p if r["defective"]}), len({r["feature"] for r in p}))


naive, smart = sample_naive(LABEL_BUDGET), sample_priority(LABEL_BUDGET)
ny, nl, nm, nf = card(naive)
sy, sl, sm, sf = card(smart)
print(f"2. THE SAMPLER - spending {LABEL_BUDGET} labels on {len(pool)} candidates")
print(f"   {'':<35}{'yield':>7}{'t-loud':>8}{'modes':>7}{'surfaces':>10}")
print(f"   {'naive: thumbs + edits, recent first':<35}{ny * 100:>6.0f}%{nl * 100:>7.0f}%{nm:>7}/8{nf:>9}/4")
print(f"   {'priority: posterior x novelty':<35}{sy * 100:>6.0f}%{sl * 100:>7.0f}%{sm:>7}/8{sf:>9}/4")
print(f"   quota {QUOTA}, t-loud capped at {CAP['t-loud']}")
print("   -> the naive set is one tenant's house style, on two surfaces\n")
assert sy > 2.0 * ny, "prioritised labels must be worth far more each"
assert sl <= 2 / LABEL_BUDGET + 1e-9, "the per-tenant cap must bind"
assert sf == len(FEATURES), "the per-cell floor must keep every surface present"
assert sm >= 6, "novelty must spread the budget across failure modes"

# --------------------------------------------------------------------------- #
# 3. CLASS BALANCE - a golden set of only failures cannot see a regression
# --------------------------------------------------------------------------- #
HARD_GATE = 0.97                              # must-not-break is a HARD gate, never a blend
CANDIDATES = {"genuinely better": (0.30, 0.98), "refuses everything": (0.75, 0.15)}
print("3. CLASS BALANCE - 420 regression cases, 260 must-not-break")
print(f"   {'candidate model':<22}{'negatives only':>16}{'must-not-break':>17}{'verdict':>10}")
verdict = {}
for name, (reg, mnb) in CANDIDATES.items():
    verdict[name] = (reg, mnb >= HARD_GATE)
    print(f"   {name:<22}{reg * 100:>15.0f}%{mnb * 100:>16.0f}%"
          f"{('SHIP' if mnb >= HARD_GATE else 'BLOCKED'):>10}")
print("   -> on the negatives alone the degenerate model wins by 45 points:")
print("      refusing never makes an ungrounded claim. Only the must-not-break")
print("      tier - sampled uniformly from the ACCEPTED class - catches it.\n")
assert verdict["refuses everything"][0] > verdict["genuinely better"][0]
assert verdict["refuses everything"][1] is False and verdict["genuinely better"][1] is True

# --------------------------------------------------------------------------- #
# 4. THE QUEUE - admission is a bucket set at review capacity, not a wish
# --------------------------------------------------------------------------- #
CAPACITY, STALE, DAYS = 300, 14, 30
print(f"4. THE QUEUE - {CAPACITY} labels/day of capacity, {DAYS} days, rot after {STALE}")
print(f"   {'admission policy':<30}{'admitted/day':>14}{'backlog':>10}{'oldest waits':>15}")
wait = {}
for label, admit in (("uncapped: score > threshold", 450), ("token bucket at capacity", 300)):
    backlog = max(0, (admit - CAPACITY)) * DAYS
    wait[label] = backlog / CAPACITY
    print(f"   {label:<30}{admit:>14}{backlog:>10}{wait[label]:>12.1f} d"
          f"{'  STALE' if wait[label] > STALE else '  fresh'}")
print("   -> the priority score decides WHICH cases get in, never HOW MANY.\n")
assert wait["uncapped: score > threshold"] > STALE > wait["token bucket at capacity"]

print("WHAT TO NOTICE")
print(f"  * the best signal has no user in it: checker_fail {prec['checker_fail'] * 100:.0f}% precise on"
      f" 100% of\n    traffic, against {prec['edit_any'] * 100:.0f}% for a raw edit.")
print(f"  * two cheap weak signals AGREEING ({precision(cofire) * 100:.0f}%) beat any single strong one.")
print(f"  * the blended edit number is a lie told by one tenant: {precision(loud_e) * 100:.0f}% for"
      f" t-loud,\n    {precision(rest_e) * 100:.0f}% for everyone else.")
print(f"  * the pool is only {pool_prec * 100:.0f}% precise - build a golden set straight from it"
      f"\n    and most of your eval set is stylistic preference.")
print(f"  * prioritising lifted yield {ny * 100:.0f}% -> {sy * 100:.0f}% on the SAME budget, cut the loud"
      f"\n    tenant {nl * 100:.0f}% -> {sl * 100:.0f}%, and covered 4 surfaces instead of {nf}.")
print("  * a negatives-only golden set rewards a model that refuses everything.")
print("  * admit 450/day against 300/day of capacity and by day 30 every label")
print("    describes a prompt version you retired. A stale label still counts.")
print("\nOK - scenario 12")
