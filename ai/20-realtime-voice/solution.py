"""
Scenario 6 - real-time voice at 50k concurrent: why the chat playbook fails.

    python3 solution.py

Four mechanics, each with the failure shown happening FIRST, then the fix:
  1. autoscaling on CPU vs on concurrent sessions
  2. a queue, which rescues chat and destroys voice
  3. the serial turn budget, and streaming into TTS
  4. vendor concurrency quota as the real ceiling, and per-tenant caps

Population: 50,000 concurrent calls, 3-minute average, one turn every 8s.
Seeded, so reruns match exactly.

What to notice: nothing here is solved by adding servers. Three of the four
failures get WORSE with more capacity, because the binding constraint is
somebody else's quota, a budget you do not control, or physics.
"""
import random

random.seed(6)

CONCURRENT = 50_000          # calls up at once, the target
TURN_CADENCE_S = 8.0         # one speaking turn per caller per 8 seconds
BUDGET_MS = 1000             # sub-second round trip, the natural-speech threshold

# a voice server spends its life waiting on sockets, not burning CPU
SESSIONS_PER_BOX = 400
CPU_PER_SESSION = 0.0012     # 0.12% of a core - it is I/O, not compute


# --------------------------------------------------------------------------- #
# 1. the autoscaler
# --------------------------------------------------------------------------- #
def cpu_scaler(sessions, boxes, target_cpu=0.60):
    """Scale to hold CPU at 60%. Standard, correct for web, wrong for voice."""
    cpu = (sessions * CPU_PER_SESSION) / max(boxes, 1)
    return max(1, round(sessions * CPU_PER_SESSION / target_cpu))


def session_scaler(sessions, boxes, headroom=1.25):
    """Scale on the thing that actually saturates: open sessions."""
    return max(1, -(-int(sessions * headroom) // SESSIONS_PER_BOX))


def capacity(boxes):
    return boxes * SESSIONS_PER_BOX


# --------------------------------------------------------------------------- #
# 2. the queue
# --------------------------------------------------------------------------- #
def serve_chat(arrivals, capacity_per_tick):
    """Chat: overflow waits. A slow answer is still the right answer."""
    backlog, waited, served = 0, [], 0
    for a in arrivals:
        backlog += a
        take = min(backlog, capacity_per_tick)
        backlog -= take
        served += take
        waited.append(backlog)
    return served, max(waited)


def serve_voice(arrivals, capacity_per_tick):
    """Voice: overflow is a dead-air turn. Nobody waits 4 seconds mid-sentence."""
    served, dropped = 0, 0
    for a in arrivals:
        take = min(a, capacity_per_tick)
        served += take
        dropped += a - take          # the backlog does not carry - the moment passed
    return served, dropped


# --------------------------------------------------------------------------- #
# 3. the serial turn budget
# --------------------------------------------------------------------------- #
#            stage            p50   p99   can it overlap the next stage?
STAGES = [("STT finalise",     120,  260, False),
          ("retrieval",         90,  310, False),
          ("LLM first token",  240,  520, False),
          ("LLM full response", 700, 1400, True),    # only needed if you wait for it
          ("TTS first audio",   180,  340, False),
          ("network RTT",        60,  190, False)]


def turn_latency(stream_into_tts, pct):
    i = 1 if pct == 50 else 2
    total, parts = 0, []
    for name, p50, p99, overlappable in STAGES:
        if overlappable and stream_into_tts:
            continue                  # TTS starts on the first clause, not the last
        ms = (p50, p99)[i - 1]
        total += ms
        parts.append((name, ms))
    return total, parts


# --------------------------------------------------------------------------- #
# 4. vendor quota and per-tenant caps
# --------------------------------------------------------------------------- #
# quota is concurrent streams at the vendor; attach is the fraction of calls
# that use it. An avatar rides only on video calls, so its small quota buys
# more concurrency than the raw number suggests - divide before you compare.
VENDOR_QUOTA = {"STT": (60_000, 1.00), "TTS": (20_000, 1.00),
                "avatar": (8_000, 0.15), "telephony": (75_000, 1.00)}


def supports(v):
    quota, attach = VENDOR_QUOTA[v]
    return int(quota / attach)


def ceiling():
    who = min(VENDOR_QUOTA, key=supports)
    return who, supports(who)


def allocate(demand, total, caps=None):
    """Hand out capacity. Without caps it is first-come, which one tenant wins."""
    if caps is None:
        left, got = total, {}
        for t in sorted(demand):                       # arrival order, deterministic
            got[t] = min(demand[t], left)
            left -= got[t]
        return got
    return {t: min(demand[t], caps[t]) for t in demand}


def main():
    print(f"\nREAL-TIME VOICE AT {CONCURRENT:,} CONCURRENT")
    print("=" * 74)
    turns_per_s = CONCURRENT / TURN_CADENCE_S
    print(f"{CONCURRENT:,} calls, a turn every {TURN_CADENCE_S:.0f}s "
          f"-> {turns_per_s:,.0f} LLM turns/second")
    print(f"budget per turn: {BUDGET_MS} ms, consumed SERIALLY\n")

    # ---------------------------------------------------------------- 1
    print("1. AUTOSCALING - on CPU vs on sessions")
    print(f"   {'signal':<16}{'boxes':>7}{'capacity':>10}{'sessions used':>15}{'dropped':>10}")
    for label, scaler in (("CPU at 60%", cpu_scaler), ("sessions +25%", session_scaler)):
        boxes = scaler(CONCURRENT, 1)
        cap = capacity(boxes)
        short = max(0, CONCURRENT - cap)
        print(f"   {label:<16}{boxes:>7}{cap:>10,}{CONCURRENT / cap:>14.0%}{short:>10,}")
    cpu_boxes = cpu_scaler(CONCURRENT, 1)
    ses_boxes = session_scaler(CONCURRENT, 1)
    assert capacity(cpu_boxes) < CONCURRENT      # the failure
    assert capacity(ses_boxes) >= CONCURRENT     # the fix
    print(f"   -> the CPU-scaled fleet is at 60% CPU and {CONCURRENT / capacity(cpu_boxes):.0%} of its")
    print("      session limit at the same instant. CPU is not the saturating resource, so")
    print("      holding it at target says nothing - and an idle-LOOKING fleet is exactly")
    print(f"      what a scale-IN rule fires on, while {CONCURRENT - capacity(cpu_boxes):,} callers get nothing.\n")

    # ---------------------------------------------------------------- 2
    print("2. THE QUEUE - rescues chat, destroys voice")
    cap_tick = int(turns_per_s)
    # a burst, not a famine: 3 ticks at 1.8x then 7 at 0.6x. Total offered is
    # UNDER total capacity, so a queue can genuinely drain it.
    arrivals = [int(turns_per_s * 1.8)] * 3 + [int(turns_per_s * 0.6)] * 7
    offered = sum(arrivals)
    c_served, c_backlog = serve_chat(arrivals, cap_tick)
    v_served, v_dropped = serve_voice(arrivals, cap_tick)
    print(f"   a 3-tick spike to 180% of capacity, then recovery")
    print(f"   offered {offered:,} turns, total capacity over the window {cap_tick * 10:,}")
    print(f"   chat   served {c_served:>7,} ({c_served / offered:>5.1%})  "
          f"peak backlog {c_backlog:,} turns - late, but served")
    print(f"   voice  served {v_served:>7,} ({v_served / offered:>5.1%})  "
          f"dead air on {v_dropped:,} turns - gone for good")
    assert c_served == offered                   # the queue drains it
    assert v_dropped > 0 and v_served < offered  # the moment passed
    print(f"   -> there was enough capacity across the window. The queue converts the")
    print("      spike into latency and chat pays it happily. Voice has nowhere to put")
    print("      the time, so the same spike is permanent loss.")
    print("      Note this is the FAVOURABLE case for queueing. Against a sustained")
    print("      shortfall the queue serves no more than voice does - it just hides the")
    print("      shortfall in a backlog that grows without bound.\n")

    # ---------------------------------------------------------------- 3
    print("3. THE TURN BUDGET - serial, and what streaming into TTS buys")
    for pct in (50, 99):
        naive, parts = turn_latency(False, pct)
        streamed, _ = turn_latency(True, pct)
        print(f"   p{pct}: wait for the full response {naive:>5} ms   "
              f"stream into TTS {streamed:>5} ms   "
              f"{'OVER' if streamed > BUDGET_MS else 'within'} the {BUDGET_MS} ms budget")
    n50, parts = turn_latency(False, 50)
    s50, _ = turn_latency(True, 50)
    assert n50 > BUDGET_MS and s50 < BUDGET_MS
    print("   p50 breakdown once you stream:")
    for name, ms in parts:
        print(f"      {name:<20}{ms:>5} ms")
    print(f"   -> streaming removes {n50 - s50} ms by never waiting for the last token.")
    print("      It is the single largest win and it costs nothing but plumbing.")
    ret99 = next(p99 for name, _, p99, _ in STAGES if name == "retrieval")
    print(f"      Retrieval alone is {ret99} ms of a {BUDGET_MS} ms budget at p99 - it is")
    print("      the stage that decides whether RAG stays in the turn at all.\n")

    # ---------------------------------------------------------------- 4
    print("4. THE REAL CEILING - vendor quota, and one tenant taking it all")
    who, cap = ceiling()
    print(f"   {'vendor':<11}{'quota':>8}{'attach':>9}{'calls supported':>18}")
    for v in sorted(VENDOR_QUOTA, key=supports):
        quota, attach = VENDOR_QUOTA[v]
        flag = "  <- binds first" if v == who else ""
        print(f"   {v:<11}{quota:>8,}{attach:>8.0%}{supports(v):>18,}{flag}")
    print(f"   -> you can run {cap:,} of {CONCURRENT:,}. No amount of your own compute")
    print(f"      changes that. {who} is a contract negotiation, not a deploy.\n")

    demand = {"acme": 34_000, "globex": 9_000, "initech": 7_000}
    fair = {t: cap // len(demand) for t in demand}
    for label, caps in (("no caps (first-come)", None), ("per-tenant caps", fair)):
        got = allocate(demand, cap, caps)
        starved = [t for t in demand if got[t] < min(demand[t], fair[t])]
        print(f"   {label:<22}" + "  ".join(f"{t}:{got[t]:>6,}" for t in sorted(got))
              + (f"   starved: {', '.join(starved)}" if starved else "   starved: none"))
    no_caps = allocate(demand, cap, None)
    with_caps = allocate(demand, cap, fair)
    assert no_caps["initech"] == 0                 # the failure
    assert with_caps["initech"] > 0                # the fix
    print("   -> without caps, acme's campaign is an outage for everyone else. The cap is")
    print("      not fairness policy, it is blast-radius control.\n")

    print("WHAT TO NOTICE")
    print("   * three of these four get WORSE as you add servers - the binding constraint")
    print("     is a vendor quota, a budget, or the speed of light")
    print("   * the CPU autoscaler does not merely fail to help, it actively scales IN")
    print("     during an outage, because an idle-looking box is the normal state here")
    print("   * every chat instinct inverts: do not queue, do not batch, do not retry a")
    print("     turn - degrade to text instead and say so out loud")
    print("   * cost is the second thing that breaks, and it arrives within hours")
    print("\nOK - scenario 6")


if __name__ == "__main__":
    main()
