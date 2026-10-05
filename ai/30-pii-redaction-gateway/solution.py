"""
Scenario 16 - a PII redaction gateway: detect cheaply, never trust a model's
offsets, tokenise reversibly, fail closed.

    python3 solution.py

Five mechanics, each showing the FAILURE before the fix so the contrast is
measured rather than asserted: a bare 12-digit regex vs the same regex plus
a Verhoeff check digit; model-reported offsets vs re-finding the span in
code; an LLM extractor on every call vs escalation as a ROUTING decision;
stream rehydration with and without a carry buffer; and a treatment table
the model may only push stricter. Seeded, stdlib only, under a second.
"""
import hashlib, hmac, math, random, re
from collections import Counter

random.seed(16)

# --------------------------------------------------------------------------- #
# 1. DETERMINISTIC DETECTION + CHECKSUM
#    prevents: two false positives for every true one, at zero latency cost
# --------------------------------------------------------------------------- #
AADHAAR_RX = re.compile(r"\b[2-9]\d{11}\b")
_D = tuple(tuple(int(c) for c in r) for r in (
    "0123456789", "1234067895", "2340178956", "3401289567", "4012395678",
    "5987604321", "6598710432", "7659821043", "8765932104", "9876543210"))
_P = tuple(tuple(int(c) for c in r) for r in (
    "0123456789", "1576283094", "5803796142", "8916043527",
    "9453126870", "4286573901", "2793806415", "7046913258"))
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff_ok(num):
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_seal(body):
    """Append the check digit - used here only to mint synthetic test data."""
    c = 0
    for i, ch in enumerate(reversed(body)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return body + str(_INV[c])


def sample_numbers():
    """60 twelve-digit numbers from one day of prompts: 20 identifiers, and
    40 order ids, invoice numbers and internal references."""
    d = lambda n: "".join(str(random.randint(0, 9)) for _ in range(n))
    real = [verhoeff_seal(str(random.randint(2, 9)) + d(10)) for _ in range(20)]
    decoy = [str(random.randint(2, 9)) + d(11) for _ in range(40)]
    return [(n, True) for n in real] + [(n, False) for n in decoy]


def detect(num, checksum):
    if not AADHAAR_RX.fullmatch(num):
        return False
    return verhoeff_ok(num) if checksum else True


# --------------------------------------------------------------------------- #
# 2. SPANS - the model returns substrings, YOU find the offsets
#    prevents: a hallucinated span corrupting the prompt AND missing the PII
# --------------------------------------------------------------------------- #
CHUNK = ("Patient Ritesh Kumar, MRN 88213, reviewed by Dr Anand; "
         "contact ritesh.kumar@example.com or 9812345670.")
PROMPT = ("You are a support assistant. Answer only from the context below, "
          "quote the source line, and never invent details not present in "
          "it.\n\n") + CHUNK


def extractor_output(chunk):
    """What an LLM extractor gives you: offsets that index THE CHUNK IT SAW,
    not the assembled prompt - plus one entity over-completed into a surname
    that appears nowhere."""
    out = []
    for frag, typ in (("Ritesh Kumar", "PERSON"),
                      ("ritesh.kumar@example.com", "EMAIL"),
                      ("Dr Anand Sharma", "PERSON")):
        i = chunk.find(frag)
        if i == -1:
            i = chunk.find("Dr Anand")           # it points at what it did see
        out.append({"text": frag, "type": typ, "start": i, "end": i + len(frag)})
    return out


def redact_by_offsets(text, spans):
    """THE BUG: trust start/end."""
    for n, s in enumerate(sorted(spans, key=lambda s: -s["start"]), 1):
        text = text[:s["start"]] + "[%s_%d]" % (s["type"], n) + text[s["end"]:]
    return text


def redact_by_refind(text, spans):
    """THE FIX: ignore the offsets, re-find the substring in what you will send."""
    seq, unlocatable = Counter(), 0
    for s in sorted(spans, key=lambda s: -len(s["text"])):
        if s["text"] not in text:
            unlocatable += 1                     # detected, not locatable
            continue
        seq[s["type"]] += 1
        text = text.replace(s["text"], "[%s_%d]" % (s["type"], seq[s["type"]]))
    return text, unlocatable                     # replace() = every occurrence


def route(destination, unlocatable):
    if destination == "third-party" and unlocatable:
        return "BLOCKED, rerouted to the in-VPC model"
    return "sent to " + destination


# --------------------------------------------------------------------------- #
# 3. LATENCY - WHERE you spend the escalation decides whether you meet 50 ms
# --------------------------------------------------------------------------- #
N, DET_MS, TIMEOUT_MS, BUDGET_MS = 20_000, 3.0, 1500.0, 50.0
CALLS_PER_DAY, TOKENS_PER_EXTRACT, GBP_PER_M = 600_000, 1500, 0.10


def pct(xs, p):
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def simulate(rate, inline):
    """Deterministic pass always; the extractor only if the design waits for it."""
    out = []
    for _ in range(N):
        ms = max(1.5, random.gauss(DET_MS, 0.6))
        if inline and random.random() < rate:
            ms += min(TIMEOUT_MS, random.lognormvariate(math.log(600), 0.36))
        out.append(ms)
    return out


def gbp_per_month(share):
    return CALLS_PER_DAY * share * TOKENS_PER_EXTRACT / 1e6 * GBP_PER_M * 30


# --------------------------------------------------------------------------- #
# 4. REVERSIBLE TOKENISATION + STREAMING REHYDRATION
#    prevents: an unusable answer, then a placeholder leaking to the user
# --------------------------------------------------------------------------- #
TENANT_KEY = b"per-tenant key from the KMS, never a literal"
TOKEN_RX = re.compile(r"\[[A-Z]+_\d+\]")


class Vault:
    """token <-> value, indexed by HMAC so one value collapses to one token."""

    def __init__(self):
        self.by_hash, self.by_token, self.seq = {}, {}, Counter()

    def tokenise(self, typ, value):
        h = hmac.new(TENANT_KEY, value.encode(), hashlib.sha256).hexdigest()[:16]
        if h not in self.by_hash:
            self.seq[typ] += 1
            tok = "[%s_%d]" % (typ, self.seq[typ])
            self.by_hash[h], self.by_token[tok] = tok, value
        return self.by_hash[h]

    def swap(self, text):
        return TOKEN_RX.sub(lambda m: self.by_token.get(m.group(0), m.group(0)), text)


def rehydrate_naive(chunks, vault):
    """THE BUG: a placeholder split across two chunks matches neither half."""
    for c in chunks:
        yield vault.swap(c)


def rehydrate_carry(chunks, vault, max_carry=32):
    """Hold back from the last unclosed '[', capped so TTFT stays bounded."""
    carry = ""
    for c in chunks:
        buf = carry + c
        i = buf.rfind("[")
        if i != -1 and "]" not in buf[i:] and len(buf) - i <= max_carry:
            out, carry = buf[:i], buf[i:]
        else:
            out, carry = buf, ""
        if out:
            yield vault.swap(out)
    if carry:
        yield vault.swap(carry)


# --------------------------------------------------------------------------- #
# 5. TREATMENT TABLE - data in code; the model may only push stricter
# --------------------------------------------------------------------------- #
STRICT = {"pass": 0, "hash": 1, "mask": 2, "tokenise": 3, "block": 4}
POLICY = {("EMAIL", "third-party"): "tokenise", ("EMAIL", "in-vpc"): "tokenise",
          ("PERSON", "third-party"): "tokenise", ("PERSON", "in-vpc"): "pass",
          ("AADHAAR", "third-party"): "block", ("AADHAAR", "in-vpc"): "tokenise"}


def treat(typ, dest, model_says=None):
    base = POLICY.get((typ, dest), "block")              # unknown type -> BLOCK
    return model_says if model_says and STRICT[model_says] > STRICT[base] else base


if __name__ == "__main__":
    print("1. DETECTION - the same regex, with and without the check digit")
    nums, res = sample_numbers(), {}
    for label, ck in (("bare 12-digit regex", False), ("+ Verhoeff check digit", True)):
        tp = sum(1 for n, real in nums if real and detect(n, ck))
        fp = sum(1 for n, real in nums if not real and detect(n, ck))
        res[ck] = (tp, fp)
        print(f"   {label:<24} true {tp:>3}   false {fp:>3}   "
              f"precision {tp / (tp + fp):>5.0%}   recall {tp / 20:>5.0%}")
    assert res[False][0] == res[True][0] == 20, "recall must not move"
    assert res[True][1] < res[False][1] / 3, "the checksum must gut false positives"
    print("   -> precision triples, recall does not move: the only kind of")
    print("      precision fix worth having in a recall-first system.\n")

    print("2. SPANS - chunk-relative offsets applied to the assembled prompt")
    spans = extractor_output(CHUNK)
    broken = redact_by_offsets(PROMPT, spans)
    fixed, unlocatable = redact_by_refind(PROMPT, spans)
    print(f"   instructions, by offsets: {broken.splitlines()[0][:74]}")
    print(f"   context,      by offsets: {broken.splitlines()[-1][:74]}")
    print(f"   context,      by re-find: {fixed.splitlines()[-1][:74]}")
    assert "Ritesh Kumar" in broken and "ritesh.kumar@example.com" in broken
    assert "Ritesh Kumar" not in fixed and "ritesh.kumar@example.com" not in fixed
    assert "quote the source line" not in broken and "quote the source line" in fixed
    print("   -> the offsets shredded the instructions and BOTH entities")
    print("      survived. It was not lying: it never saw this string.")
    print(f"   unlocatable substrings: {unlocatable} (an over-completed name)"
          f" -> {route('third-party', unlocatable)}")
    assert unlocatable == 1 and route("third-party", unlocatable).startswith("BLOCKED")
    print("   -> detected but not locatable is not clean. Fail closed.\n")

    print("3. LATENCY - a 50 ms budget, four ways to spend the extractor")
    print(f"   {'design':<32}{'p50':>8}{'p95':>9}{'p99':>9}   extractor")
    rows = [("A  extractor on EVERY call", simulate(1.00, True), 1.00),
            ("B  inline escalation on 4%", simulate(0.04, True), 0.04),
            ("B' same design, 30% escalation", simulate(0.30, True), 0.30),
            ("C  escalation ROUTES, 2% async", simulate(0.04, False), 0.02)]
    for label, xs, share in rows:
        over = "" if pct(xs, 99) <= BUDGET_MS else "  <- over budget"
        print(f"   {label:<32}{pct(xs, 50):>8.1f}{pct(xs, 95):>9.1f}"
              f"{pct(xs, 99):>9.1f}   £{gbp_per_month(share):>6,.0f}/mo{over}")
    assert pct(rows[0][1], 50) > 400, "an extractor on every call owns the p50"
    assert pct(rows[1][1], 95) < BUDGET_MS < pct(rows[1][1], 99)
    assert pct(rows[2][1], 95) > BUDGET_MS, "escalation rate is a data property"
    assert pct(rows[3][1], 99) < BUDGET_MS, "routing costs nothing at any percentile"
    print("   -> B looks fine until you read p99, and B' is one onboarding")
    print("      away from B. C holds because ambiguity picks a DESTINATION")
    print("      and nothing in the request path waits on a model.\n")

    print("4. REVERSAL - tokenise out, rehydrate back over a stream")
    v, outbound = Vault(), PROMPT
    for typ, val in (("EMAIL", "ritesh.kumar@example.com"), ("PERSON", "Ritesh Kumar")):
        outbound = outbound.replace(val, v.tokenise(typ, val))
    assert "ritesh.kumar@example.com" not in outbound and "[EMAIL_1]" in outbound
    stream = ["I have emailed ", "[EMA", "IL_1] and copied ", "[PERSON_1", "] on it."]
    naive = "".join(rehydrate_naive(stream, v))
    safe = "".join(rehydrate_carry(stream, v))
    print(f"   provider chunks: {stream}")
    print(f"   naive per chunk: {naive}")
    print(f"   with carry     : {safe}")
    assert "[EMAIL_1]" in naive and "[PERSON_1]" in naive
    assert "[EMAIL_1]" not in safe and "ritesh.kumar@example.com" in safe
    print("   -> the split placeholder matched neither half, so the user")
    print("      read the token. No non-streaming test catches this.\n")

    print("5. POLICY - a table in code, and the model may only push stricter")
    for typ, says in (("EMAIL", "pass"), ("EMAIL", "block"), ("MRN", None)):
        print(f"   {typ:<7} to third-party, model proposes {str(says):<6}"
              f" -> {treat(typ, 'third-party', says)}")
    assert treat("EMAIL", "third-party", "pass") == "tokenise"
    assert treat("EMAIL", "third-party", "block") == "block"
    assert treat("MRN", "third-party") == "block"
    print("   -> an unrecognised type blocks. Every gap in the recogniser list")
    print("      is otherwise a silent allow.\n")

    print("   what to notice:")
    print("   * the checksum buys precision and costs no recall - nothing")
    print("     else in this design is free like that")
    print("   * the model gives you substrings; the offsets are yours to find")
    print("   * 4% x 600 ms is invisible at p95 and fatal at p99, and the 4%")
    print("     is set by tenant data, not by your code")
    print("   * every failure here is silent - no exception, no error rate,")
    print("     just a prompt that left the building with a name in it")
    print("\nOK - scenario 16")
