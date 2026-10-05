"""
Scenario 7 - a semantic cache: the false hit, and the guard that stops it.

    python3 solution.py

  1. a threshold-only cache serves WRONG answers to negated and parameterised
     paraphrases - and reports a BETTER hit rate for doing so
  2. the same cache plus a discriminative-token guard: fewer hits, none wrong
  3. the key namespace (tenant + resolved scope + corpus version) as structure
     rather than a filter - those probes have nothing to rank against at all
  4. single-flight coalescing on one cold, hot key

What to notice: the broken cache scores 50% hit rate, the correct one 30%. Hit
rate is the metric that IMPROVES when you break correctness.

The "embedding" is deterministic feature hashing over concepts, weighted so that
numerals and negations count for very little - which is how real sentence
embeddings behave, and exactly why a threshold alone cannot save you.
"""
import hashlib, math, re
from collections import defaultdict, namedtuple

THRESHOLD = 0.93            # calibrated on labelled pairs, then tightened a notch
CALLS_DAY, COST_PER_CALL = 600_000, 0.004
STOP = set("what is the a an i do does can how much to for my am are of in on if it be and me".split())
SYN = {"notice": "notice", "resignation": "notice", "resign": "notice", "warning": "notice",
       "period": "period", "long": "period", "duration": "period", "leave": "leave",
       "holiday": "leave", "holidays": "leave", "annual": "leave", "carried": "carryover",
       "carry": "carryover", "rolled": "carryover", "band": "band", "grade": "band",
       "level": "band", "expense": "expense", "expenses": "expense", "claim": "expense",
       "reimbursed": "expense", "reimbursement": "expense", "not": "NEG", "no": "NEG",
       "never": "NEG", "cannot": "NEG", "without": "NEG"}
CONCEPTS = set(SYN.values()) - {"NEG"}
NEG_WORDS = {w for w, c in SYN.items() if c == "NEG"}
NUM = re.compile(r"^\d+$")
Entry = namedtuple("Entry", "vec mk intent")


def weight(c):
    """Content concepts dominate; a numeral or a negation is one token averaged
    into a whole sentence. That asymmetry IS the bug demonstrated below."""
    return 0.35 if (c == "NEG" or NUM.match(c)) else (1.0 if c in CONCEPTS else 0.4)


def embed(text):
    v = defaultdict(float)
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if tok not in STOP:
            c = SYN.get(tok, tok)
            v[c] += weight(c)
    n = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {k: x / n for k, x in v.items()}


def cos(a, b):
    return sum(x * b.get(k, 0.0) for k, x in a.items())


def marks(text):
    """Numerals and negations, extracted lexically. Microseconds, and it is what
    turns vector RECALL into answer PRECISION."""
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return (frozenset(t for t in toks if NUM.match(t)),
            frozenset(t for t in toks if t in NEG_WORDS))


def namespace(tenant, scope, corpus_v, model="gen-1", prompt_v=7):
    """Hash the RESOLVED PERMISSION SET, never the user id - a namespace of one
    never hits. corpus_v makes invalidation an O(1) config change."""
    h = hashlib.sha256(",".join(sorted(scope)).encode()).hexdigest()[:8]
    return (tenant, h, corpus_v, model, prompt_v)


class SemanticCache:
    def __init__(self, guard):
        self.guard, self.store = guard, defaultdict(list)

    def put(self, ns, text, intent):
        self.store[ns].append(Entry(embed(text), marks(text), intent))

    def lookup(self, ns, text):
        cands = self.store.get(ns, [])
        if not cands:
            return None, 0.0, "no candidates in this namespace"
        qv, qm = embed(text), marks(text)
        best = max(cands, key=lambda e: cos(qv, e.vec))
        s = cos(qv, best.vec)
        if s < THRESHOLD:
            return None, s, "below threshold"
        if self.guard and best.mk != qm:
            return None, s, "guard: %s differ" % ("numerals" if best.mk[0] != qm[0] else "negation")
        return best, s, "served"


CACHED = [("what is the notice period for band 3", "notice.band3"),
          ("unused leave is carried forward", "leave.carryover.yes"),
          ("what is the expense claim limit", "expense.limit")]
PROBES = [("how long is the resignation warning for band 3", "notice.band3"),
          ("what is the notice period for band 5", "notice.band5"),
          ("unused leave is not carried forward", "leave.carryover.no"),
          ("unused holiday rolled forward automatically", "leave.carryover.yes"),
          ("how do i get reimbursed for expenses", "expense.limit"),
          ("what is the notice period", "notice.standard"),
          ("what is the parental leave allowance", "leave.parental"),
          ("how do i book a meeting room", "facilities.rooms"),
          ("what is the sickness absence policy", "hr.sickness"),
          ("what is the office wifi password", "it.wifi")]
ACME_V1 = namespace("acme", {"hr", "finance"}, corpus_v=41)


def run(guard):
    c = SemanticCache(guard)
    for text, intent in CACHED:
        c.put(ACME_V1, text, intent)
    hits, wrong, rows = 0, 0, []
    for text, intent in PROBES:
        hit, s, why = c.lookup(ACME_V1, text)
        if hit:
            hits += 1
            wrong += hit.intent != intent
            rows.append((text, s, "HIT  ok" if hit.intent == intent else "HIT  WRONG ANSWER"))
        else:
            rows.append((text, s, "miss (%s)" % why))
    return c, hits, wrong, rows


def burst(n, coalesce):
    """200 people open the dashboard at 09:00 and ask the same thing."""
    calls, inflight = 0, set()
    for _ in range(n):
        if coalesce and "hot" in inflight:
            continue                       # joins the promise already in flight
        inflight.add("hot")
        calls += 1
    return calls


if __name__ == "__main__":
    print("1. THRESHOLD ONLY - 3 cached answers, 10 probes, threshold 0.93")
    _, lh, lw, rows = run(guard=False)
    for text, s, verdict in rows:
        print(f"   {text[:44]:<44} {s:.3f}  {verdict}")
    print(f"   -> {lh}/10 hits = {lh * 10}% hit rate, {lw} of them WRONG "
          f"(precision on hits {100 * (lh - lw) // lh}%)\n")

    print("2. THE SAME CACHE PLUS THE DISCRIMINATIVE-TOKEN GUARD")
    tight, gh, gw, rows = run(guard=True)
    for text, s, verdict in rows:
        if "guard" in verdict or "HIT" in verdict:
            print(f"   {text[:44]:<44} {s:.3f}  {verdict}")
    assert lw == 2 and gw == 0, "the guard must remove every false hit"
    assert lh > gh, "the BROKEN cache must report the BETTER hit rate"
    print(f"   -> {gh}/10 hits = {gh * 10}% hit rate, precision on hits 100%.")
    print(f"      Broken reports {lh * 10}%, correct {gh * 10}%: hit rate went DOWN.\n")

    print("3. THE KEY IS THE ISOLATION - same question, wrong namespace")
    for label, ns in (("other tenant", namespace("globex", {"hr", "finance"}, 41)),
                      ("no finance scope", namespace("acme", {"hr"}, 41)),
                      ("after a re-index", namespace("acme", {"hr", "finance"}, 42))):
        hit, s, why = tight.lookup(ns, "how do i get reimbursed for expenses")
        print(f"   {label:<18} -> {'SERVED' if hit else 'miss'}  ({why})")
        assert hit is None, "a key dimension must partition, not filter"
    print("   -> nothing to forget to filter: no candidates existed. Bumping the")
    print("      corpus 41 -> 42 makes every old entry unreachable in one config")
    print("      change - no scan, no delete-by-query, nothing missed.\n")

    print("4. SINGLE-FLIGHT - 200 identical misses on one cold key")
    print(f"   no coalescing   -> {burst(200, False):>3} model calls")
    print(f"   single-flight   -> {burst(200, True):>3} model calls")
    assert burst(200, False) == 200 and burst(200, True) == 1
    saved = gh / 10 * CALLS_DAY * COST_PER_CALL * 30

    print("\nwhat to notice")
    print("   . 0.961 and 0.975 are the WRONG answers; 0.943 is the right one.")
    print("     Both false hits score HIGHER than the genuine paraphrase, so no")
    print("     threshold on the number line separates them. Only the guard does.")
    print("   . the loose cache 'saves' more and is wrong on one hit in five. Its")
    print("     dashboard looks better. Nothing errors, nothing is traced.")
    print(f"   . at {CALLS_DAY:,} calls/day and ${COST_PER_CALL}/call the honest "
          f"{gh * 10}% is")
    print(f"     ${saved:,.0f}/month, and every single point is $720/month.")
    print("   . so report hit rate MULTIPLIED by sampled precision on hits.")
    print("\nOK - scenario 7")
