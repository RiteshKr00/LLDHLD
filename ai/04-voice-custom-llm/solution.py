"""
04 - the voice path: purpose-scoped tokens, the OpenAI chunk envelope,
     and re-fire suppression.

    python3 solution.py
"""
import hashlib, hmac, json, time

SECRET = b"jwt-secret"
VOICE_PURPOSE = "voice-llm"
TTL = 30 * 60


# --------------------------------------------------------------------------- #
# 1. a purpose-scoped, short-lived token (a JWT without the dependency)
# --------------------------------------------------------------------------- #
def mint(claims, purpose, ttl=TTL):
    body = {**claims, "purpose": purpose, "exp": int(time.time()) + ttl}
    raw = json.dumps(body, sort_keys=True).encode()
    sig = hmac.new(SECRET, raw, hashlib.sha256).hexdigest()[:16]
    return raw.decode() + "." + sig


def verify(token, required_purpose):
    raw, _, sig = token.rpartition(".")
    if not hmac.compare_digest(
            sig, hmac.new(SECRET, raw.encode(), hashlib.sha256).hexdigest()[:16]):
        return None, "bad signature"
    body = json.loads(raw)
    if body["exp"] < time.time():
        return None, "expired"
    if body.get("purpose") != required_purpose:
        return None, f"wrong purpose ({body.get('purpose')})"
    return body, "ok"


def app_api(token):
    """The normal auth middleware. It requires a SESSION purpose."""
    return verify(token, "session")


def voice_llm_endpoint(token):
    return verify(token, VOICE_PURPOSE)


# --------------------------------------------------------------------------- #
# 2. the response envelope - every chunk must be a valid OpenAI chunk
# --------------------------------------------------------------------------- #
def chunk(content=None, role=None, finish=None):
    delta = {}
    if role:
        delta["role"] = role
    if content:
        delta["content"] = content
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk",
            "created": int(time.time()), "model": "persona-1",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def stream(text):
    yield chunk(role="assistant")                    # first chunk sets the role
    for word in text.split():
        yield chunk(content=word + " ")
    yield chunk(finish="stop")


def platform_parses(chunks):
    """What the voice platform does. A wrong shape is DISCARDED silently."""
    out = []
    for c in chunks:
        if c.get("object") != "chat.completion.chunk" or "choices" not in c:
            return None, "discarded (HTTP 200, no error)"
        out.append(c["choices"][0]["delta"].get("content", ""))
    return "".join(out).strip(), "ok"


# --------------------------------------------------------------------------- #
# 3. re-fire suppression
# --------------------------------------------------------------------------- #
def normalize(s):
    return " ".join(s.lower().split()).rstrip(".?!")


def is_refire(prev, nxt):
    return prev is not None and normalize(prev) == normalize(nxt)


if __name__ == "__main__":
    session = mint({"user": "u1"}, "session")
    voice = mint({"user": "u1", "convId": "c9"}, VOICE_PURPOSE)

    print("  token boundary - the vendor holds the VOICE token")
    for name, tok in (("session token", session), ("voice token", voice)):
        _, a = app_api(tok)
        _, b = voice_llm_endpoint(tok)
        print(f"    {name:<15} /api/users: {a:<22} /voice/llm: {b}")
    assert app_api(voice)[0] is None, "a leaked voice token must not reach the app API"
    assert voice_llm_endpoint(session)[0] is None
    expired = mint({"user": "u1"}, VOICE_PURPOSE, ttl=-1)
    assert voice_llm_endpoint(expired)[0] is None
    print("    -> not secrecy, BLAST RADIUS: assume a vendor credential leaks\n")

    print("  the stream envelope")
    text, status = platform_parses(list(stream("Grounded in my own documents.")))
    print(f"    correct shape -> {status}: {text!r}")
    broken = [{"choices": [{"delta": {"content": "hi"}}]}]      # missing 'object'
    text2, status2 = platform_parses(broken)
    print(f"    wrong shape   -> {status2}")
    assert text2 is None
    print("    -> the worst failure class: success status, ZERO output.")
    print("       The twin simply never speaks and nothing errors.\n")

    print("  re-fire suppression (endpointing fires twice)")
    turns = ["What's the roadmap?", "What's the roadmap", "And the timeline?"]
    prev, answered = None, []
    for t in turns:
        if is_refire(prev, t):
            print(f"    {t!r:<28} SUPPRESSED (duplicate turn)")
        else:
            answered.append(t)
            print(f"    {t!r:<28} answered")
        prev = t
    assert len(answered) == 2
    print("    -> without this the twin answers the same question twice,")
    print("       talking over itself on a live call.")
    print("\nOK - topic 04")
