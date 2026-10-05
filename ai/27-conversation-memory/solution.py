"""
Scenario 13 - conversation memory at scale: O(1) memory per turn, slots not logs.

    python3 solution.py

Five mechanics, each showing the failure first so the gap is measured, not asserted:
resending the transcript is O(N^2) in turns while tiered memory is O(N); summarise
on a token trigger rather than per message; keep facts in SLOTS that supersede
instead of an append-only log; rank by relevance x recency decay or a stale
preference beats today's correction; and carry provenance or you cannot honour an
erasure request. A "what to notice" block at the foot of the file reads the output.
"""
import random

random.seed(13)

TURN_TOKENS = 200        # one user+assistant exchange, averaged
VERBATIM_TURNS = 8       # last N turns kept word for word
SUMMARY_CAP = 300        # rolling summary ceiling
FACT_BUDGET = 150        # top-6 facts x ~25 tokens
SUMMARISER_COST = 2200   # 300 old summary + 1600 window in, 300 out

# 1. COST SHAPE - resend everything vs a fixed memory budget
def naive_prompt(turn):
    """THE BUG: the whole transcript rides along on every single turn."""
    return TURN_TOKENS * (turn - 1)

def tiered_prompt(turn):
    """Verbatim window + capped summary + top-k facts. Flat in turn count."""
    window = TURN_TOKENS * min(VERBATIM_TURNS, turn - 1)
    summary = SUMMARY_CAP if turn > VERBATIM_TURNS + 1 else 0
    facts = FACT_BUDGET if turn > 3 else 0
    return window + summary + facts

def summariser_calls(turns, every_turn=False):
    """Trigger on the window crossing its token threshold, not per message."""
    return turns if every_turn else (turns - 1) // VERBATIM_TURNS

def cumulative(turns, fn, with_summariser):
    total = sum(fn(i) for i in range(1, turns + 1))
    return total + (summariser_calls(turns) * SUMMARISER_COST if with_summariser else 0)

# 2/3. FACT STORE - append-only log vs slots.  (age_days, predicate, value, cosine)
FACTS = [
    (210, "diet", "user is vegetarian", 0.88),
    (12, "diet", "user eats chicken again", 0.71),
    (240, "employer", "user works at Globex", 0.20),
    (3, "tone", "user prefers short answers", 0.35),
]

def append_only(facts):
    """THE BUG: every statement is a new row. Nothing ever supersedes."""
    return list(facts)

def slotted(facts):
    """Upsert on (user, predicate). Newer wins; older keeps superseded_at."""
    live = {}
    for f in sorted(facts, key=lambda f: -f[0]):   # oldest first, newer overwrites
        live[f[1]] = f
    return list(live.values())

def top_k(facts, k=2, key=lambda f: f[3]):
    return sorted(facts, key=lambda f: -key(f))[:k]

# 4. SCORING - cosine alone vs cosine x recency decay, per fact class
HALF_LIFE = {"identity": None, "preference": 30, "state": 14}   # days

DECAY_FACTS = [
    (75, "preference", "wants exhaustive detail", 0.90),
    (1, "preference", "asked for three lines maximum", 0.62),
    (400, "identity", "name is Priya", 0.55),
    (40, "state", "is mid-way through onboarding", 0.70),
]

def decayed(fact):
    age, klass, _, cos = fact
    hl = HALF_LIFE[klass]
    return cos if hl is None else cos * 2 ** (-age / hl)

# 5. ERASURE - a prose blob vs a summary derived from turn ids
TURNS = [(1, "my name is Priya"), (2, "I work at Globex on the billing team"),
         (3, "draft me a status update"), (4, "make it shorter"),
         (5, "also I am vegetarian")]
FACT_ROWS = [("name", "Priya", [1]), ("employer", "Globex billing", [2]),
             ("diet", "vegetarian", [5])]
BLOB = "Priya works at Globex on billing, wants short updates, is vegetarian."

def regenerate(turns):
    """Stands in for the summariser: deterministic, derived from source turns."""
    return " | ".join(t for _, t in turns)

def erase(turn_ids):
    kept = [t for t in TURNS if t[0] not in turn_ids]
    facts = [f for f in FACT_ROWS if not set(f[2]) & set(turn_ids)]
    return regenerate(kept), facts


if __name__ == "__main__":
    print("1. COST - one thread, resent vs tiered")
    print("   turn |  naive/turn |  tiered/turn |   naive cum |  tiered cum | ratio")
    for n in (10, 50, 150, 300, 1000):
        nc, tc = cumulative(n, naive_prompt, False), cumulative(n, tiered_prompt, True)
        print(f"   {n:>4} | {naive_prompt(n):>11,} | {tiered_prompt(n):>12,} |"
              f" {nc:>11,} | {tc:>11,} | {nc / tc:>4.1f}x")
    assert tiered_prompt(300) == tiered_prompt(1000) == 2050, "memory must be flat in N"
    r50 = cumulative(50, naive_prompt, False) / cumulative(50, tiered_prompt, True)
    r1k = cumulative(1000, naive_prompt, False) / cumulative(1000, tiered_prompt, True)
    assert r1k > 10 * r50, "the gap must widen with turn count, not stay constant"
    assert naive_prompt(10) < tiered_prompt(10), "tiered LOSES on short threads"
    print("   -> naive is O(N^2), tiered O(N) - but tiered loses below turn 12, is\n"
          "      only 2.3x ahead at turn 50, and 43x ahead at turn 1000.\n")

    print("2. SUMMARISER TRIGGER - per message vs per 1,600 tokens")
    every, trig = summariser_calls(300, every_turn=True), summariser_calls(300)
    print(f"   every turn        -> {every:>3} summariser calls over 300 turns")
    print(f"   on token trigger  -> {trig:>3} summariser calls, same summary quality")
    assert every == 300 and trig == 37 and every / trig > 7
    print(f"   -> {every / trig:.1f}x fewer LLM calls on the write path, for identical output\n")

    print("3. CONTRADICTION - append-only log vs supersedable slots")
    for label, store in (("append-only fact log", append_only), ("SLOTS, upsert", slotted)):
        got = top_k(store(FACTS))
        diets = [f[2] for f in got if f[1] == "diet"]
        flag = "  <- both beliefs in the prompt" if len(diets) > 1 else "  <- one live belief"
        print(f"   {label:<21} top-2 = {[f[2] for f in got]}{flag}")
    assert len([f for f in top_k(append_only(FACTS)) if f[1] == "diet"]) == 2
    assert len([f for f in top_k(slotted(FACTS)) if f[1] == "diet"]) == 1
    assert "chicken" in [f for f in slotted(FACTS) if f[1] == "diet"][0][2]
    print("   -> the log hands the model 'is vegetarian' AND 'eats chicken again'\n"
          "      and it coin-flips. The slot resolved that at WRITE time.\n")

    print("4. RANKING - cosine only vs cosine x recency decay")
    cos_top = top_k(DECAY_FACTS, k=2)
    dec_top = top_k(DECAY_FACTS, k=2, key=decayed)
    for label, rows, keyfn in (("cosine only", cos_top, lambda f: f[3]),
                               ("x recency decay", dec_top, decayed)):
        shown = ", ".join(f"{keyfn(f):.2f} {f[2]} ({f[0]}d)" for f in rows)
        print(f"   {label:<16} {shown}")
    assert cos_top[0][0] == 75, "cosine alone must prefer the stale preference"
    assert dec_top[0][0] == 1, "decay must surface yesterday's correction"
    assert any(f[1] == "identity" for f in dec_top), "identity has no half-life"
    print("   -> cosine alone ranks a preference abandoned 75 days ago above the\n"
          "      correction made yesterday. Identity gets no half-life, so 'name is\n"
          "      Priya' still ranks at 400 days.\n")

    print("5. ERASURE - prose blob vs derived summary with provenance")
    print(f"   blob summary, turn 2 deleted    -> {BLOB}")
    assert "Globex" in BLOB, "the prose blob keeps the fact after the turn is gone"
    new_summary, kept_facts = erase([2])
    print(f"   derived summary, turn 2 deleted -> {new_summary}")
    print(f"   facts surviving                 -> {[f[0] for f in kept_facts]}")
    assert "Globex" not in new_summary and len(kept_facts) == 2
    assert all("Globex" not in f[1] for f in kept_facts)
    print("   -> same deletion, two outcomes. Without derived_from turn ids the fact\n"
          "      is baked into the blob: unremovable, and unprovable either way.")
    print("\nOK - scenario 13")

# --------------------------------------------------------------------------- #
# WHAT TO NOTICE
# 1. Naive per-turn climbs linearly, so naive cumulative climbs quadratically -
#    8,970,000 tokens by turn 300. Tiered per-turn stops at 2,050 forever. The
#    ratio column is the point: 0.7x at turn 10, 2.3x at 50, 43x at 1000.
#    Tiered LOSES below turn 12 per-turn and turn 19 cumulative, and every
#    fixture you would naturally write sits below both. That is why resend
#    ships and stays.
# 2. 300 -> 37 summariser calls: 8x off the write-path bill, no output change.
# 3. The log surfaces two contradictory diet facts in one top-2. The slot store
#    resolved that in March, at write time, so retrieval has nothing to decide.
# 4. Decay drops the 75-day preference 0.90 -> 0.16 and leaves yesterday's 0.62
#    at 0.61, flipping the order; identity is exempt at 400 days. Supersession
#    fixes conflict inside a slot, decay fixes staleness across slots.
# 5. Deleting the turn is the easy part. The blob still says "Globex" because
#    the fact was compiled into it; the derived summary regenerates without it.
# --------------------------------------------------------------------------- #
