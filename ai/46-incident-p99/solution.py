"""
Scenario 32 - incident: p99 3s -> 25s after a deploy, p50 unchanged.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. what an unchanged p50 rules out - and why adding instances cannot help
  2. retries x timeout arithmetic, and why 25s is a suspiciously round number
  3. a blocking call inside an async handler, which is a TAIL problem
  4. averages and even p95 hiding it; the shape of the distribution matters
  5. the deploy gate that would have caught it

Seeded, so reruns match exactly.

What to notice: three of these five are CONFIG, not code, and the one that is
code does not reproduce without concurrency - which is exactly why it reached
production.
"""
import random

random.seed(32)

N = 20_000


def pct(xs, p):
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def summarise(xs):
    return {"p50": pct(xs, 50), "p95": pct(xs, 95), "p99": pct(xs, 99),
            "mean": sum(xs) / len(xs)}


# --------------------------------------------------------------------------- #
# 1. capacity vs a subset
# --------------------------------------------------------------------------- #
def baseline(n=N):
    return [random.lognormvariate(0.35, 0.55) for _ in range(n)]


def capacity_problem(base, factor=2.4):
    """Everything queues. p50 moves with p99 - which is NOT what we observed."""
    return [x * factor for x in base]


def subset_problem(base, share=0.02, stall=25.0):
    """A fraction of requests hit something new. p50 untouched."""
    out = []
    for x in base:
        out.append(stall if random.random() < share else x)
    return out


# --------------------------------------------------------------------------- #
# 2. retries x timeout
# --------------------------------------------------------------------------- #
def worst_case(attempts, timeout_s, backoff_s):
    return attempts * timeout_s + sum(backoff_s[:attempts - 1])


CONFIGS = [("before: 2 attempts, 3s timeout", 2, 3.0, [1.0]),
           ("after:  3 attempts, 8s timeout", 3, 8.0, [0.5, 0.5])]


# --------------------------------------------------------------------------- #
# 3. the blocking call
# --------------------------------------------------------------------------- #
def event_loop(n_requests, rate_per_s, awaited_s, blocking_s):
    """One event-loop thread.

    Awaited I/O overlaps freely - a thousand requests can wait on the provider
    at once. CPU work does NOT: it occupies the single thread, so every other
    request queues behind it. A small blocking call therefore does not add its
    own duration to each request, it adds a QUEUE, and a queue is a tail.
    """
    loop_free = 0.0
    arrival = 0.0
    out = []
    for _ in range(n_requests):
        # Poisson arrivals. Perfectly regular arrivals never build a queue below
        # 100% utilisation, which is precisely why a constant-rate load test
        # misses this and real bursty traffic does not.
        arrival += random.expovariate(rate_per_s)
        start_cpu = max(arrival, loop_free)      # wait for the thread
        loop_free = start_cpu + blocking_s       # hold it, exclusively
        done = loop_free + awaited_s             # then await I/O, which overlaps
        out.append(done - arrival)
    return out


def main():
    print("\nINCIDENT: p99 3s -> 25s, p50 UNCHANGED")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. WHAT AN UNCHANGED p50 RULES OUT")
    base = baseline()
    cap = capacity_problem(base)
    sub = subset_problem(base)
    print(f"   {'scenario':<26}{'p50':>8}{'p95':>8}{'p99':>8}{'mean':>8}")
    for name, xs in (("baseline", base), ("capacity problem", cap),
                     ("a 2% subset stalls", sub)):
        s = summarise(xs)
        print(f"   {name:<26}{s['p50']:>8.2f}{s['p95']:>8.2f}{s['p99']:>8.2f}"
              f"{s['mean']:>8.2f}")
    b, c, u = summarise(base), summarise(cap), summarise(sub)
    assert c["p50"] > b["p50"] * 1.5          # capacity moves p50 too
    assert abs(u["p50"] - b["p50"]) < 0.05    # a subset does not
    assert u["p99"] > b["p99"] * 5
    print("   -> a capacity problem drags p50 with it. Ours did not move, so this is")
    print("      NOT throughput and adding instances will not help. Say that first: it")
    print("      is the observation that decides where to look.\n")

    # ---------------------------------------------------------------- 2
    print("2. RETRIES x TIMEOUT - why 25s is a suspiciously round number")
    print(f"   {'config':<36}{'worst case':>12}")
    for name, att, to, bo in CONFIGS:
        print(f"   {name:<36}{worst_case(att, to, bo):>11.1f}s")
    before = worst_case(*CONFIGS[0][1:])
    after = worst_case(*CONFIGS[1][1:])
    assert after > before * 3
    print(f"   -> {before:.0f}s to {after:.0f}s from a config change alone. A tail that")
    print("      CLUSTERS at a round number is arithmetic, not contention: multiply")
    print("      attempts by timeout and add the backoff, and see if it lands on your")
    print("      p99. Check the retry and timeout config before anything clever.\n")

    # ---------------------------------------------------------------- 3
    print("3. A BLOCKING CALL IN AN ASYNC HANDLER")
    RATE, AWAITED = 32.0, 0.9
    print(f"   {RATE:.0f} req/s, {AWAITED}s of awaited provider time each")
    print(f"   {'handler':<34}{'p50':>9}{'p95':>9}{'p99':>9}")
    runs = {}
    for name, blk in (("pure async", 0.0), ("+ 30ms of CPU in the handler", 0.030)):
        lat = event_loop(20_000, RATE, AWAITED, blk)
        runs[blk] = summarise(lat)
        st = runs[blk]
        print(f"   {name:<34}{st['p50']:>9.2f}{st['p95']:>9.2f}{st['p99']:>9.2f}")
    pure, blocked = runs[0.0], runs[0.030]
    assert blocked["p99"] > pure["p99"] * 2.5
    assert blocked["p50"] < blocked["p99"] / 2      # a TAIL, not a uniform shift
    print(f"   p50 moved {blocked['p50'] / pure['p50'] - 1:.0%}. p99 moved "
          f"{blocked['p99'] / pure['p99'] - 1:.0%}.")
    cliff = summarise(event_loop(20_000, 33.0, AWAITED, 0.030))
    print(f"   loop utilisation {RATE * 0.030:.0%} - under 100%, so capacity planning says")
    print(f"   it is fine. At 33 req/s ({33 * 0.03:.0%}) p99 becomes {cliff['p99']:.2f}s: the cliff")
    print(f"   is not gradual.")
    print("   -> 30 milliseconds. Not 30 milliseconds of latency - 30 milliseconds")
    print("      during which NOTHING else on that worker runs, so every concurrent")
    print("      request queues behind it. It never shows up in single-request testing,")
    print("      which is why it reaches production.\n")

    # ---------------------------------------------------------------- 4
    print("4. WHY THE DASHBOARD MISSED IT")
    s = summarise(sub)
    print(f"   with 2% of requests stalling at 25s:")
    print(f"      mean {s['mean']:.2f}s   p50 {s['p50']:.2f}s   "
          f"p95 {s['p95']:.2f}s   p99 {s['p99']:.2f}s")
    assert s["p95"] < 5 and s["p99"] > 20
    print(f"   -> the mean moved {s['mean'] / b['mean'] - 1:.0%}, p50 not at all, and even")
    print("      p95 looks healthy. Only p99 shows it. A 2% failure rate is invisible")
    print("      to every percentile below 98, which is most dashboards.\n")

    # ---------------------------------------------------------------- 5
    print("5. THE DEPLOY GATE THAT WOULD HAVE CAUGHT IT")
    gates = [("p50 only", False, "passes - p50 never moved"),
             ("mean latency", False, "passes - a 2% tail barely moves a mean"),
             ("p95", False, "passes - the stall is above the 95th percentile"),
             ("p99, per provider and model", True, "FAILS - and names the slice"),
             ("error taxonomy: timeouts separately", True,
              "FAILS - timeout count jumps, 5xx flat"),
             ("load test measuring the TAIL under concurrency", True,
              "FAILS - the only one that catches the blocking call")]
    for name, catches, note in gates:
        print(f"   {'CATCHES' if catches else 'misses ':<9}{name:<46}{note}")
    assert sum(1 for _, c, _ in gates if c) == 3
    print("   -> three of six catch it, and the load test is the only one that catches")
    print("      the async-blocking variant, because that failure needs concurrency to")
    print("      exist at all.\n")

    print("WHAT TO NOTICE")
    print("   * p50 unchanged rules out capacity - do not add instances")
    print("   * a tail clustered at a round number is retry x timeout arithmetic")
    print("   * three of the five likely causes are CONFIG, not code")
    print("   * a blocking call in an async path is invisible without concurrency,")
    print("     which is exactly why it ships")
    print("   * gate on p99 per slice, and taxonomise errors - a timeout spike and a")
    print("     5xx spike are different incidents")
    print("\nOK - scenario 32")


if __name__ == "__main__":
    main()
