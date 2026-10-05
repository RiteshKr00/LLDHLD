"""
Scenario 26 - 60-minute meetings into decisions and action items, 500/day.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. does it even need chunking? and what map-reduce costs you if it does not
  2. diarisation errors, and how they propagate into unusable action items
  3. the model's prior that meetings HAVE action items - inventing them
  4. entity resolution: "Dave will send it" when there are four Daves
  5. transcript as the durable artefact, summaries as derived

Seeded, so reruns match exactly.

What to notice: the value is attributed, verifiable action items - and every
failure here attacks the attribution or the verifiability, not the prose.
"""
import random
import re

random.seed(26)

MEETINGS_PER_DAY = 500
MINUTES = 60
WORDS_PER_MIN = 150
TOKENS_PER_WORD = 1.33
CTX = 128_000


# --------------------------------------------------------------------------- #
# 1. chunking
# --------------------------------------------------------------------------- #
def transcript_tokens(minutes=MINUTES):
    return int(minutes * WORDS_PER_MIN * TOKENS_PER_WORD)


def map_reduce_loss(n_chunks):
    """Cross-chunk references a per-chunk pass cannot see.

    A decision revisited in the last ten minutes, a commitment made early and
    withdrawn later: these are relationships BETWEEN chunks, so the number of
    them a chunked pass can miss grows with the number of boundaries.
    """
    return 1.0 - (0.97 ** max(0, n_chunks - 1))


# --------------------------------------------------------------------------- #
# 2. diarisation
# --------------------------------------------------------------------------- #
UTTERANCES = [
    ("Priya", "I'll send the revised forecast by Thursday"),
    ("Marcus", "and I'll review it before the board pack goes out"),
    ("Priya", "we agreed not to change the pricing tier this quarter"),
    ("Sam", "can someone check whether legal signed off"),
]


def diarise(utterances, error_rate, speakers=("Priya", "Marcus", "Sam")):
    out = []
    for who, what in utterances:
        if random.random() < error_rate:
            wrong = [s for s in speakers if s != who]
            out.append((random.choice(wrong), what, True))
        else:
            out.append((who, what, False))
    return out


def actionable(rows):
    """An action item needs an owner. A misattributed one is worse than none."""
    good = sum(1 for who, what, err in rows
               if re.search(r"\bI'll\b|\bI will\b", what) and not err)
    wrong = sum(1 for who, what, err in rows
                if re.search(r"\bI'll\b|\bI will\b", what) and err)
    return good, wrong


# --------------------------------------------------------------------------- #
# 3. invented action items
# --------------------------------------------------------------------------- #
MEETING_KINDS = [("status update, nothing decided", 0),
                 ("planning session", 3),
                 ("informal catch-up", 0),
                 ("incident review", 4)]


def extract_actions(kind, true_count, forced_schema):
    """A schema demanding a list invites the model to fill it.

    With a required non-empty list the model produces something for every
    meeting. Allowing an explicit empty answer removes the pressure.
    """
    if forced_schema and true_count == 0:
        return 2          # invents, because the field must be populated
    return true_count


# --------------------------------------------------------------------------- #
# 4. entity resolution
# --------------------------------------------------------------------------- #
DIRECTORY = [
    {"name": "Dave Okafor", "team": "finance", "in_meeting": True},
    {"name": "Dave Lindqvist", "team": "platform", "in_meeting": False},
    {"name": "Dave Chen", "team": "sales", "in_meeting": False},
    {"name": "Davina Roy", "team": "finance", "in_meeting": True},
]


def resolve(first_name, context_topic, attendees_only=True):
    cands = [p for p in DIRECTORY if p["name"].split()[0].lower() == first_name.lower()]
    if attendees_only:
        cands = [p for p in cands if p["in_meeting"]] or cands
    if len(cands) == 1:
        return cands[0]["name"], "resolved"
    topical = [p for p in cands if p["team"] == context_topic]
    if len(topical) == 1:
        return topical[0]["name"], "resolved by topic"
    return None, f"ambiguous between {len(cands)}"


def main():
    print("\nMEETING NOTES: LONG AUDIO TO ACTIONS")
    print("=" * 74)
    toks = transcript_tokens()
    print(f"{MINUTES} min x {WORDS_PER_MIN} wpm = {MINUTES * WORDS_PER_MIN:,} words "
          f"= ~{toks:,} tokens")
    print(f"{MEETINGS_PER_DAY} meetings/day, post-hoc -> a batch queue, nobody waits\n")

    # ---------------------------------------------------------------- 1
    print("1. DOES IT NEED CHUNKING? - notice that it does not")
    print(f"   {'meeting length':>16}{'tokens':>10}{'fits 128k?':>13}{'chunks needed':>16}")
    for mins in (60, 180, 480):
        t = transcript_tokens(mins)
        n = max(1, -(-t // (CTX // 2)))
        print(f"   {str(mins) + ' min':>16}{t:>10,}{'yes' if t < CTX else 'no':>13}"
              f"{n:>16}")
    assert toks < CTX
    print(f"\n   a 60-minute transcript is {toks / CTX:.0%} of the window, so single-pass")
    print("   is available - and it is the better choice, because decisions get")
    print("   revisited and commitments get withdrawn ACROSS the meeting.")
    for n in (2, 4, 8):
        print(f"      map-reduce over {n} chunks: ~{map_reduce_loss(n):.0%} of cross-chunk "
              f"relationships lost")
    assert map_reduce_loss(8) > map_reduce_loss(2)
    print("   -> saying 'it fits, so I will not chunk' out loud is worth marks. Reach")
    print("      for map-reduce at 3+ hours, and accept the coherence cost knowingly.\n")

    # ---------------------------------------------------------------- 2
    print("2. DIARISATION - everything downstream inherits it")
    print(f"   {'speaker error rate':>20}{'correct actions':>18}{'MISATTRIBUTED':>16}")
    for err in (0.02, 0.10, 0.25):
        totals = [0, 0]
        for _ in range(400):
            g, w = actionable(diarise(UTTERANCES, err))
            totals[0] += g
            totals[1] += w
        print(f"   {err:>19.0%}{totals[0]:>18,}{totals[1]:>16,}")
    print("   -> a misattributed action item is worse than a missing one: it is a task")
    print("      assigned to someone who never agreed to it, and they find out in a")
    print("      summary email. Everything downstream inherits diarisation quality,")
    print("      which is why audio setup is a clarifying question and not a detail.\n")

    # ---------------------------------------------------------------- 3
    print("3. INVENTED ACTION ITEMS - the model's prior that meetings have them")
    print(f"   {'meeting':<32}{'true':>6}{'forced schema':>15}{'optional':>10}")
    inv_forced = inv_opt = 0
    for kind, true_n in MEETING_KINDS:
        f = extract_actions(kind, true_n, True)
        o = extract_actions(kind, true_n, False)
        inv_forced += max(0, f - true_n)
        inv_opt += max(0, o - true_n)
        print(f"   {kind:<32}{true_n:>6}{f:>15}{o:>10}")
    print(f"   {'invented total':<32}{'':>6}{inv_forced:>15}{inv_opt:>10}")
    assert inv_forced > 0 and inv_opt == 0
    print("   -> a schema with a REQUIRED non-empty list is an instruction to invent.")
    print("      Let the answer be empty, and ask for a quote and timestamp per item -")
    print("      an invented item has nothing to quote.\n")

    # ---------------------------------------------------------------- 4
    print("4. WHICH DAVE?")
    for first, topic, only in (("Dave", "finance", True),
                               ("Dave", "finance", False),
                               ("Dave", None, False)):
        who, how = resolve(first, topic, only)
        scope = "attendees only" if only else "whole directory"
        print(f"   {first} + topic={str(topic):<8} {scope:<16} -> "
              f"{who or 'ASK THE ORGANISER'}  ({how})")
    assert resolve("Dave", "finance", True)[0] == "Dave Okafor"
    assert resolve("Dave", None, False)[0] is None
    print("   -> restricting to attendees resolves most of it, because the person who")
    print("      said 'I'll do it' was in the room. When it stays ambiguous the correct")
    print("      output is an unassigned item flagged for the organiser, never a guess:")
    print("      a task on the wrong Dave's list is worse than a task on nobody's.\n")

    # ---------------------------------------------------------------- 5
    print("5. THE TRANSCRIPT IS THE ARTEFACT")
    cost_transcribe = 0.36           # £ per hour of audio, STT
    cost_summarise = 0.02            # £ per meeting, one pass
    daily_stt = MEETINGS_PER_DAY * cost_transcribe
    daily_sum = MEETINGS_PER_DAY * cost_summarise
    print(f"   transcription  £{daily_stt:>7,.0f}/day   the expensive, irreversible step")
    print(f"   summarisation  £{daily_sum:>7,.0f}/day   {daily_stt / daily_sum:.0f}x cheaper, "
          f"and repeatable")
    assert daily_stt > daily_sum * 10
    print("   -> store the transcript with speaker labels and timestamps as the durable")
    print("      artefact; treat every summary as derived and disposable. When the")
    print("      prompt improves next month you re-run over history for 5% of the")
    print("      original cost. If you keep only summaries, you cannot.\n")

    print("WHAT TO NOTICE")
    print("   * it FITS - say so, and choose single-pass for global coherence")
    print("   * the product is attributed, verifiable action items; the summary is")
    print("     the part nobody disputes")
    print("   * a required list field is an instruction to invent")
    print("   * quote-and-timestamp every decision: it makes disputes checkable and")
    print("     makes fabrication structurally harder")
    print("\nOK - scenario 26")


if __name__ == "__main__":
    main()
