"""
10 - reconciling late, out-of-band, retried cost from five providers.

    python3 solution.py

The multiplication is trivial. The engineering is idempotency, the webhook
race, constant-time verification, and one rate card.
"""
import hmac, hashlib, re, time

# ONE rate card. The ledger prices from it; the dashboard renders from it.
RATE_CARD = {
    "llm_in":    0.00000015,   # per token
    "llm_out":   0.00000060,
    "stt_min":   0.0043,
    "tts_char":  0.000018,
    "avatar_min": 0.09,
    "voice_min": 0.05,
}
SECRET = b"webhook-secret"


class Ledger:
    def __init__(self):
        self.calls = {}         # call_id -> {source: units}
        self.seen = set()       # idempotency keys

    # ---- during the call: token usage from the streaming response ----
    def record(self, call_id, source, units, key=None):
        if key is not None:
            if key in self.seen:
                return "duplicate-ignored"
            self.seen.add(key)
        c = self.calls.setdefault(call_id, {})
        c[source] = c.get(source, 0) + units
        return "recorded"

    def cost(self, call_id):
        c = self.calls.get(call_id, {})
        return round(sum(RATE_CARD[k] * v for k, v in c.items()), 6)

    def breakdown(self, call_id):
        """The dashboard renders THIS - same rate card, so displayed == billed."""
        c = self.calls.get(call_id, {})
        return {k: {"units": v, "rate": RATE_CARD[k],
                    "cost": round(RATE_CARD[k] * v, 6)} for k, v in c.items()}


CALL_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def verify(body: bytes, sig: str, secret=SECRET) -> bool:
    """Length-guarded constant-time compare. Fails CLOSED if unset."""
    if not secret:
        raise RuntimeError("503: webhook secret unset - refusing (fail closed)")
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if len(sig) != len(expected):
        return False                      # guard before compare_digest
    return hmac.compare_digest(sig, expected)


def webhook(ledger, call_id, minutes, body, sig):
    if not CALL_ID.match(call_id):        # validate BEFORE it reaches a SQL LIKE
        return "400 bad call id"
    if not verify(body, sig):
        return "401 bad signature"
    return ledger.record(call_id, "voice_min", minutes, key=f"{call_id}:voice")


if __name__ == "__main__":
    led = Ledger()
    cid = "call-abc123"

    # during the call - known immediately
    led.record(cid, "llm_in", 4200)
    led.record(cid, "llm_out", 800)
    led.record(cid, "stt_min", 3.0)
    led.record(cid, "tts_char", 1800)
    led.record(cid, "avatar_min", 3.0)
    print(f"  during the call, 4 providers priced: ${led.cost(cid)}")
    print("  ...but the authoritative voice-platform number has not arrived yet\n")

    body = b'{"call":"call-abc123","minutes":3.0}'
    good = hmac.new(SECRET, body, hashlib.sha256).hexdigest()

    print("  webhook delivery attempts")
    print(f"    1st (valid)        -> {webhook(led, cid, 3.0, body, good)}")
    print(f"    2nd (provider retry)-> {webhook(led, cid, 3.0, body, good)}"
          "   <- idempotent")
    print(f"    forged signature   -> {webhook(led, cid, 3.0, body, 'a' * 64)}")
    print(f"    bad call id (LIKE injection: 'x%') -> "
          f"{webhook(led, cid.replace(cid, 'x%'), 3.0, body, good)}")

    # the client-pull fallback racing the webhook
    pulled = led.record(cid, "voice_min", 3.0, key=f"{cid}:voice")
    print(f"    client-pull fallback -> {pulled}   <- post-fetch re-check\n")

    assert led.calls[cid]["voice_min"] == 3.0, "must not double-count"
    try:
        verify(body, good, secret=b"")
        raise AssertionError("should fail closed")
    except RuntimeError as ex:
        print(f"  secret unset in production -> {ex}\n")

    print(f"  final cost: ${led.cost(cid)}   across {len(led.calls[cid])} providers")
    print("  breakdown the dashboard renders (same rate card):")
    for k, v in led.breakdown(cid).items():
        print(f"    {k:<11} {v['units']:>8} x {v['rate']:<10} = ${v['cost']}")
    print("""
  what to notice
  --------------
  * the webhook arrived TWICE and the pull fallback ran too - three
    deliveries, one charge. Idempotency by call id is what makes that safe,
    and webhook retries are NORMAL, not exceptional.
  * the call id is regex-validated before it could reach a SQL LIKE. 'x%'
    in an unvalidated id would match unrelated rows.
  * the signature check is length-guarded and constant-time: a naive ==
    short-circuits on the first differing byte and leaks the secret through
    response timing.
  * no secret configured in production REFUSES rather than skipping
    verification. Fail closed - the same habit as topics 03 and 06.
  * one rate card prices the ledger AND renders the dashboard, so the
    displayed rate cannot drift from the billed rate.
""")
    print("OK - topic 10")
