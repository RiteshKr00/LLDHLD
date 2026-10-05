"""
Scenario 10 - LLM observability: what you sample, what you redact, what you cut by.

    python3 solution.py

Four mechanics. Each shows the failure happening first, then the fix, measured:
  1. uniform 2% sampling destroys the error corpus - and stratified sampling
     without RE-WEIGHTING then reports a 61% error rate
  2. a global average hides a broken model, while latency and error rate say nothing
  3. one scalar "error rate" cannot tell two different outages apart
  4. redact at write and FAIL CLOSED, and the storage bill falls ~14x

What to notice is printed at the end. No sleeps; runs in well under a second.
"""
import random, re
from collections import Counter

random.seed(10)

CALLS_PER_DAY = 600_000     # same 600k/day used in explained.md and hld.md
PAYLOAD_BYTES = 20_000      # prompt + 8 retrieved chunks + response
SKELETON_BYTES = 400        # ids, model, prompt_version, tokens, cost, latency, outcome
RETAIN_SKELETON_D = 400     # the cost ledger needs year-on-year
RETAIN_PAYLOAD_D = 30       # prose expires by policy, not by disk pressure
N = 20_000                  # the simulated slice of one day
P_SUCCESS = 0.02            # random sample rate for non-error traces

MODELS = ("small-a",) * 11 + ("large-b",)    # large-b carries ~8% of traffic


def make_traces(n, degraded=None):
    """3.0% errors across four classes; 90% groundedness unless a model is degraded."""
    out = []
    for i in range(n):
        model = random.choice(MODELS)
        r = random.random()
        err = ("rate_limited" if r < 0.015 else "timeout" if r < 0.022 else
               "parse_failure" if r < 0.027 else "validation_failure" if r < 0.030 else None)
        latency, grounded = random.gauss(1800, 400), random.random() < 0.90
        if model == degraded:
            grounded, latency = random.random() < 0.55, latency + 120
        out.append({"id": i, "model": model, "err": err,
                    "latency": latency, "grounded": grounded})
    return out


def pctile(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * p))]


day1 = make_traces(N)                        # Monday
day2 = make_traces(N, degraded="large-b")    # Tuesday: one model quietly breaks

# --------------------------------------------------------------------------- #
# 1 + 2. SAMPLING - uniform loses the errors; stratified needs re-weighting
# --------------------------------------------------------------------------- #
true_err = sum(1 for t in day1 if t["err"])
true_rate = true_err / N
true_lat = sum(t["latency"] for t in day1) / N

uniform = [t for t in day1 if random.random() < P_SUCCESS]
uni_err = sum(1 for t in uniform if t["err"])

strat, weight = [], []
for t in day1:
    if t["err"]:                                  # kept by rule
        strat.append(t); weight.append(1.0)
    elif random.random() < P_SUCCESS:             # kept by dice
        strat.append(t); weight.append(1 / P_SUCCESS)

strat_err = sum(1 for t in strat if t["err"])
naive_rate = strat_err / len(strat)
w_all = sum(weight)
w_rate = sum(w for t, w in zip(strat, weight) if t["err"]) / w_all
w_lat = sum(t["latency"] * w for t, w in zip(strat, weight)) / w_all

print("1. SAMPLING - 20,000 traces, 3.0% errors, storage budget says keep ~5%")
print(f"   {'plan':<34}{'kept':>7}{'errors kept':>13}{'est. error rate':>16}")
print(f"   {'ground truth':<34}{N:>7}{true_err:>13}{true_rate:>16.2%}")
print(f"   {'uniform 2%':<34}{len(uniform):>7}{uni_err:>13}{uni_err/len(uniform):>16.2%}"
      "   <- rate ok, corpus useless")
print(f"   {'stratified, naive average':<34}{len(strat):>7}{strat_err:>13}{naive_rate:>16.2%}"
      "   <- WRONG by 20x")
print(f"   {'stratified, RE-WEIGHTED':<34}{len(strat):>7}{strat_err:>13}{w_rate:>16.2%}"
      "   <- correct")
print(f"   mean latency: truth {true_lat:7.1f} ms   re-weighted estimate {w_lat:7.1f} ms")
print(f"   -> uniform kept {uni_err} errors across 4 classes. You cannot characterise")
print("      a failure mode from three examples, and the rate looked fine.\n")

assert uni_err < 40, "uniform sampling should keep only a handful of errors"
assert strat_err == true_err, "stratified sampling must keep EVERY error"
assert abs(naive_rate - true_rate) > 0.30, "unweighted stratified aggregation must be biased"
assert abs(w_rate - true_rate) < 0.010, "re-weighting must recover the true error rate"
assert abs(w_lat - true_lat) < 100, "re-weighting must recover the true mean latency"

# --------------------------------------------------------------------------- #
# 3. THE AVERAGE HIDES A BROKEN MODEL - and latency/errors see nothing
# --------------------------------------------------------------------------- #
def grounded(ts, model=None):
    sel = [t for t in ts if model is None or t["model"] == model]
    return sum(t["grounded"] for t in sel) / len(sel)


def errate(ts):
    return sum(1 for t in ts if t["err"]) / len(ts)


print("2. AGGREGATION - Tuesday: large-b (8% of traffic) drops to 55% groundedness")
print(f"   {'signal':<34}{'Mon':>9}{'Tue':>9}{'delta':>10}")
for label, a, b in (
        ("groundedness, GLOBAL average", grounded(day1), grounded(day2)),
        ("groundedness, cut by small-a", grounded(day1, "small-a"), grounded(day2, "small-a")),
        ("groundedness, cut by large-b", grounded(day1, "large-b"), grounded(day2, "large-b")),
        ("error rate", errate(day1), errate(day2)),
        ("p95 latency (ms/1000)", pctile([t["latency"] for t in day1], .95) / 1000,
         pctile([t["latency"] for t in day2], .95) / 1000)):
    print(f"   {label:<34}{a:>9.3f}{b:>9.3f}{b - a:>+10.3f}")

g_drop = grounded(day1) - grounded(day2)
m_drop = grounded(day1, "large-b") - grounded(day2, "large-b")
p95d = abs(pctile([t["latency"] for t in day2], .95) - pctile([t["latency"] for t in day1], .95))
print(f"   -> global moved {g_drop*100:.1f} points and never crossed a 5-point threshold;")
print(f"      cut by model it is a {m_drop*100:.0f}-point collapse. p95 moved {p95d:.0f} ms,")
print("      error rate did not move. Latency and errors are BLIND to this.\n")

assert g_drop < 0.05, "the global average must stay under the alert threshold"
assert m_drop > 0.25, "the per-model cut must show the collapse"
assert p95d < 120, "latency must be near-silent"
assert abs(errate(day2) - errate(day1)) < 0.01, "error rate must be near-silent"

# --------------------------------------------------------------------------- #
# 4. ERROR TAXONOMY - same scalar, two completely different outages
# --------------------------------------------------------------------------- #
TUE = Counter(rate_limited=430, timeout=110, parse_failure=35, validation_failure=25)
THU = Counter(rate_limited=40, timeout=30, parse_failure=340, validation_failure=190)
OWNER = {"rate_limited": "capacity: more keys, spill to provider 2",
         "timeout": "capacity: hedge, re-tune the timeout",
         "parse_failure": "the prompt: bisect the change annotations",
         "validation_failure": "the contract: repair, or pin the version"}

print("3. TAXONOMY - two days, identical error rate")
print(f"   scalar error rate: Tue {sum(TUE.values())/N:.2%}   Thu {sum(THU.values())/N:.2%}"
      "   <- indistinguishable")
print(f"   {'class':<21}{'Tue':>6}{'Thu':>6}   who owns it")
for k in ("rate_limited", "timeout", "parse_failure", "validation_failure"):
    print(f"   {k:<21}{TUE[k]:>6}{THU[k]:>6}   {OWNER[k]}")
print("   -> Tuesday pages the capacity owner, Thursday pages whoever changed the")
print("      prompt. One number sends both to the wrong person.\n")

assert sum(TUE.values()) == sum(THU.values()), "the scalar must be identical"
assert TUE.most_common(1)[0][0] != THU.most_common(1)[0][0], "the taxonomy must separate them"

# --------------------------------------------------------------------------- #
# 5. REDACT AT WRITE, FAIL CLOSED - and the storage arithmetic
# --------------------------------------------------------------------------- #
PII = [(re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "<CARD>"),
       (re.compile(r"\+?\d[\d -]{8,13}\d"), "<PHONE>"),
       (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<EMAIL>")]
RAW = ("summarise the visit note for ritesh@example.com, "
       "phone +91 98765 43210, card 4111 1111 1111 1111")


def store_payload(text, redactor_up, fail_open):
    """Returns exactly what lands on disk. None means the payload was dropped."""
    try:
        if not redactor_up:
            raise TimeoutError("redactor exceeded its budget")
        for rx, tok in PII:
            text = rx.sub(tok, text)
        return text
    except TimeoutError:
        return text if fail_open else None      # skeleton is kept either way


ok = store_payload(RAW, True, False)
leaked = store_payload(RAW, False, True)
dropped = store_payload(RAW, False, False)
print("4. REDACTION - what actually lands on disk")
print(f"   redactor up                  {ok}")
print(f"   redactor down, FAIL OPEN     {leaked}")
print("   redactor down, FAIL CLOSED   payload dropped, skeleton kept, redaction_failed +1")
assert "@" not in ok and "4111" not in ok and "98765" not in ok, "redaction must remove all PII"
assert "ritesh@example.com" in leaked, "fail-open really does write raw PII"
assert dropped is None, "fail-closed must drop the payload"

kept_frac = len(strat) / N
full_day = CALLS_PER_DAY * PAYLOAD_BYTES / 1e9
skel_day = CALLS_PER_DAY * SKELETON_BYTES / 1e9
pay_day = CALLS_PER_DAY * kept_frac * PAYLOAD_BYTES / 1e9
resident_full = full_day * RETAIN_SKELETON_D
resident_split = skel_day * RETAIN_SKELETON_D + pay_day * RETAIN_PAYLOAD_D
print(f"\n   at {CALLS_PER_DAY:,} calls/day, payload kept at {kept_frac:.1%}")
print(f"   {'plan':<26}{'GB/day':>9}{'GB resident':>14}")
print(f"   {'log everything, 400d':<26}{full_day:>9.2f}{resident_full:>14.0f}")
print(f"   {'skeleton 400d + payload 30d':<26}{skel_day + pay_day:>9.2f}{resident_split:>14.0f}")
print(f"   -> {full_day/(skel_day+pay_day):.1f}x less written, "
      f"{resident_full/resident_split:.0f}x less resident, and the saving lands")
print("      entirely on the half that holds the prose.\n")

assert full_day / (skel_day + pay_day) > 10, "splitting the record must cut writes >10x"
assert resident_full / resident_split > 25, "differential retention must cut footprint >25x"

print("WHAT TO NOTICE")
print("  * uniform 2% reported a believable error RATE and left you ~12 error traces.")
print("    The rate was never the problem; the corpus was.")
print("  * keeping 100% of errors is only half the fix. Aggregate the retained set")
print("    unweighted and you publish a ~61% error rate - your own sampling policy,")
print("    measured back at you. Weight 1 for kept-by-rule, 1/p for kept-by-dice.")
print("  * on Tuesday latency, error rate and the global groundedness average were")
print("    all within noise. Only the per-model cut saw it. That is the trap.")
print("  * fail-open redaction writes PII precisely during the incident when you are")
print("    least likely to be watching. Drop the payload; the skeleton still bills.")
print("\nOK - scenario 10")
