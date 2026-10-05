"""
Scenario 14 - 10M records overnight: dedup, cascade, resumability, deadline cutover.

    python3 solution.py

Four mechanics, each with the FAILURE shown happening first so the fix is measured
rather than asserted:

  1. hashing the raw body finds no duplicates; hashing a normalised body finds 32%
  2. a crash at 62% replays 6.2M records without checkpoints, one shard with them
  3. a poison record makes an unbounded-retry shard never complete; a DLQ bounds it
  4. batch-only misses an 8h window behind a 24h SLA; a cutover clock at T+5h does not

What to notice: the cheap lever is free (dedup), the next one trades ACCURACY (cascade)
and the last one trades the DEADLINE (Batch API) - which is why it needs insurance.
"""
import hashlib
import random

random.seed(14)

# --- the run, and the design assumptions the whole ladder rests on ---------- #
N_SIM, N_REAL = 20_000, 10_000_000     # simulated tickets vs the real corpus
WINDOW_H = 8                           # 22:00 -> 06:00
DUP_RATE = 0.32                        # support corpora are macro-driven and repeat
ESCALATE = 0.12                        # cheap model unsure -> frontier
BATCH_RETURN = 0.85                    # fraction the Batch API returns before the cutover
CUTOVER_H = 5                          # cancel + drain sync from here
TOK_IN, TOK_OUT = 800, 150

CHEAP = (TOK_IN * 0.15 + TOK_OUT * 0.60) / 1e6      # $0.00021 per record
FRONT = (TOK_IN * 2.50 + TOK_OUT * 10.00) / 1e6     # $0.00350 per record
BLEND = CHEAP + ESCALATE * FRONT                    # $0.00063 - cascade, per distinct record

TEMPLATES = [
    "cannot log in to account {n}, the password reset link never arrives",
    "order {n} has not been delivered and the tracking has not moved",
    "refund for order {n} is still not showing on my card",
    "the mobile app crashes on the payments screen, account {n}",
    "how do I add a second user to account {n}",
]


def make_corpus(n):
    """Each ticket carries a unique id line and a signature - the dedup trap."""
    seen, out, uid = [], [], 0
    for i in range(n):
        if seen and random.random() < DUP_RATE:
            body = random.choice(seen)
        else:
            uid += 1
            body = random.choice(TEMPLATES).replace("{n}", f"{uid:07d}")
            seen.append(body)
        out.append({"id": f"T{i:06d}",
                    "raw": f"Ticket {i} at 2026-09-08T0{i % 6}:11:{i % 60:02d}\n"
                           f"{body}\n--\nSent from my phone"})
    return out


def normalise(raw):
    keep = [l.strip().lower() for l in raw.split("\n")]
    return " ".join(l for l in keep
                    if l and not l.startswith(("ticket ", "sent from")) and l != "--")


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def process(records, sink, counter):
    """One LLM call, then an IDEMPOTENT upsert - a replay overwrites, never duplicates."""
    for t in records:
        counter[0] += 1
        sink[sha(t["id"] + "|prompt_v3|cheap-1")] = normalise(t["raw"])[:40]


def shard_unbounded(records, poison, budget):
    """THE BUG: retry until it works. One poison record and the shard never completes."""
    calls, i = 0, 0
    while i < len(records):
        calls += 1
        if records[i]["id"] not in poison:
            i += 1
        elif calls >= budget:
            return calls, False, []
    return calls, True, []


def shard_dlq(records, poison, max_attempts=3):
    """Bounded attempts, then the DLQ - and the shard COMPLETES without the record."""
    calls, dlq = 0, []
    for t in records:
        for _ in range(max_attempts):
            calls += 1
            if t["id"] not in poison:
                break
        else:
            dlq.append(t["id"])
    return calls, True, dlq


if __name__ == "__main__":
    corpus = make_corpus(N_SIM)

    print("1. DEDUP - hash the raw body and you find nothing")
    raw_d = len({sha(t["raw"]) for t in corpus})
    nrm_d = len({sha(normalise(t["raw"])) for t in corpus})
    dup = 1 - nrm_d / N_SIM
    esc = sum(1 for _ in range(nrm_d) if random.random() < ESCALATE) / nrm_d
    print(f"   sha256(raw body)        distinct {raw_d:>6}/{N_SIM}   saved  0.0%")
    print(f"   sha256(normalised)      distinct {nrm_d:>6}/{N_SIM}   saved {dup:5.1%}")
    print(f"   measured escalation rate on the distinct set:      {esc:5.1%}  (design {ESCALATE:.0%})")
    assert raw_d == N_SIM, "the id line and timestamp must defeat a raw hash"
    assert abs(dup - DUP_RATE) < 0.03 and abs(esc - ESCALATE) < 0.03
    print("   -> the id line, timestamp and signature make every RAW body unique.")
    print("      Strip them first, then hash. The whole 32% lever hides behind that.\n")

    print("2. THE COST LADDER at 10M records - each row is the row above plus one lever")
    dist = N_REAL * (1 - DUP_RATE)
    ladder = [("A", "frontier model, sync, one key", N_REAL * FRONT, "nothing - it never finishes"),
              ("B", "+ normalised-hash dedup (32%)", dist * FRONT, "nothing - free and lossless"),
              ("C", "+ cheap-first cascade (12% esc)", dist * BLEND, "ACCURACY"),
              ("D", "+ Batch API on the 85% in time", dist * BLEND * (1 - BATCH_RETURN * 0.5),
               "the DEADLINE")]
    print(f"   {'#':<3}{'design':<34}{'cost':>10}   the lever risks")
    for tag, name, cost, risk in ladder:
        print(f"   {tag:<3}{name:<34}{'$' + format(round(cost), ','):>10}   {risk}")
    costs = [c for _, _, c, _ in ladder]
    assert costs == sorted(costs, reverse=True), "every lever must reduce cost"
    assert round(costs[0]) == 35000 and round(costs[-1]) == 2463
    assert costs[-1] < costs[0] / 10
    print("   -> 93% off. Take the FREE lever first, then the accuracy one, then the")
    print("      deadline one - only the last can make you miss the window.\n")

    print("3. RESUMABILITY - the run dies at 62%")
    crash, shard = int(N_SIM * 0.62), 500
    c1, sink1 = [0], {}
    process(corpus[:crash], sink1, c1)                    # progress lived in a variable
    process(corpus, sink1, c1)                            # ... so we restart from record 0
    c2, sink2 = [0], {}
    in_flight = crash % shard                             # done inside the LEASED shard
    process(corpus[:crash], sink2, c2)                    # pre-crash
    process(corpus[crash - in_flight:], sink2, c2)        # lease expires -> replay that shard on
    print(f"   no checkpoint    {c1[0]:>6} calls for {N_SIM} records   wasted {crash:>5} ({crash / N_SIM:.0%})")
    print(f"   shard leases     {c2[0]:>6} calls for {N_SIM} records   wasted {in_flight:>5} "
          f"({in_flight / N_SIM:.0%})")
    print(f"   rows in the sink after all that replay: {len(sink1)} / {len(sink2)}  (idempotent upsert)")
    assert c1[0] == N_SIM + crash and c2[0] == N_SIM + in_flight
    assert in_flight * 20 < crash, "a shard replay must be orders of magnitude cheaper"
    assert len(sink1) == len(sink2) == N_SIM, "replay must not duplicate rows"
    print("   -> at 10M with 5,000-record shards and 40 workers in flight, a crash costs")
    print("      200k records (2%), not 6.2M (62%). Size the shard in SECONDS of work.\n")

    print("4. POISON RECORDS - one malformed ticket, one shard of 500")
    sh0 = corpus[:shard]
    poison = {sh0[j]["id"] for j in (11, 57, 120, 199, 260, 388, 470)}
    n_calls, ok, _ = shard_unbounded(sh0, poison, budget=400)
    d_calls, d_ok, dlq = shard_dlq(sh0, poison)
    print(f"   retry until it works   {n_calls:>4} calls   shard complete: {ok}   <- stuck at record 11")
    print(f"   3 attempts then DLQ    {d_calls:>4} calls   shard complete: {d_ok}   dlq: {len(dlq)}")
    assert not ok and d_ok
    assert len(dlq) == len(poison) and d_calls == (shard - len(poison)) + len(poison) * 3
    print("   -> 7 bad records out of 10M is a run-report line. 7 bad records in ONE")
    print("      shard trips the per-shard failure budget - that is a schema change.\n")

    print("5. THE DEADLINE - a 24h SLA inside an 8h window")
    dedup_free, batched = N_REAL - dist, dist * BATCH_RETURN
    tail = dist - batched
    print(f"   {'hour':<5}{'required':>10}{'batch-only':>12}{'with cutover':>14}")
    for hr in range(1, WINDOW_H + 1):
        req = N_REAL * hr / WINDOW_H
        done = dedup_free + batched * min(max(hr - 1, 0), CUTOVER_H - 1) / (CUTOVER_H - 1)
        cut = done + (tail * (hr - CUTOVER_H) / (WINDOW_H - CUTOVER_H) if hr > CUTOVER_H else 0)
        mark = "  <- cutover fires" if hr == CUTOVER_H else ""
        print(f"   T+{hr}h {req / 1e6:>9.2f}M{done / 1e6:>11.2f}M{cut / 1e6:>13.2f}M{mark}")
    assert done < N_REAL - 1e6, "batch-only must be short at the end of the window"
    assert abs(cut - N_REAL) < 5_000, "the cutover run must land inside the window"
    only_cost, cut_cost = dist * BLEND * 0.5, batched * BLEND * 0.5 + tail * BLEND
    print(f"   batch-only  ${only_cost:,.0f}  finishes T+24h (the SLA)   <- misses by 16 hours")
    print(f"   cutover     ${cut_cost:,.0f}  finishes T+7.9h")
    assert abs(cut_cost - costs[-1]) < 1, "the cutover cost IS ladder row D"
    print(f"   -> the deadline insurance costs ${cut_cost - only_cost:,.0f} on a "
          f"${cut_cost:,.0f} run ({(cut_cost - only_cost) / cut_cost:.0%}).")
    print("      And note batch-only sits ABOVE the required line until the final")
    print("      hour: the bar says 'ahead' long after the tail has quietly stalled.")

    print("""
what to notice
  1  raw-hash dedup saves 0.0% and normalised-hash saves 32% on the SAME corpus. The
     lever is the normaliser, not the hash.
  2  $35,000 -> $2,463. Dedup is free, the cascade buys 82% for an accuracy risk, and
     the Batch API buys the last 43% for a deadline risk.
  3  32,400 calls vs 20,400 for the same 20,000 records, and the sink holds exactly
     20,000 rows either way - the upsert absorbs the replay, the checkpoint bounds it.
  4  the unbounded shard burns its budget and STILL is not complete; the DLQ shard
     costs 21 extra calls and finishes.
  5  batch-only is ahead of the required line for seven of the eight hours and still
     misses - completed-so-far says nothing about work you do not own the clock on.""")
    print("\nOK - scenario 14")
