"""
Scenario 2 - an LLM gateway: streaming passthrough, shared buckets, one retry.

    python3 solution.py

Four mechanics, each with the failure it prevents shown happening first.
"""
import random, time
from collections import defaultdict

random.seed(5)


# --------------------------------------------------------------------------- #
# adapters: normalise auth, shape, and the ERROR TAXONOMY
# --------------------------------------------------------------------------- #
class RateLimited(Exception): pass
class Unavailable(Exception): pass


class Adapter:
    """One per provider. The router can only decide on normalised errors."""

    def __init__(self, name, fail_with=None):
        self.name, self.fail_with = name, fail_with

    def stream(self, prompt):
        if self.fail_with:
            raise self.fail_with(f"{self.name} said no")
        for word in f"answer from {self.name} about {prompt}".split():
            yield word + " "


# --------------------------------------------------------------------------- #
# 1. STREAMING PASSTHROUGH - tally usage WITHOUT buffering
#    prevents: destroying time-to-first-token
# --------------------------------------------------------------------------- #
def stream_buffered(adapter, prompt, ledger):
    """THE BUG: collect everything so you can count, then return."""
    chunks = list(adapter.stream(prompt))          # caller waits for ALL of it
    ledger.append((adapter.name, len(chunks)))
    for c in chunks:
        yield c


def stream_passthrough(adapter, prompt, ledger):
    """Yield immediately, tally as a side effect, write once at the end."""
    n = 0
    for c in adapter.stream(prompt):
        n += 1
        yield c                                    # caller gets chunk 1 at once
    ledger.append((adapter.name, n))               # async write in reality


def time_to_first_chunk(gen):
    t0 = time.perf_counter()
    next(gen)
    ttfc = time.perf_counter() - t0
    list(gen)
    return ttfc


class SlowAdapter(Adapter):
    def stream(self, prompt):
        for word in ("a b c d e f g h").split():
            time.sleep(0.01)                       # provider generation time
            yield word + " "


# --------------------------------------------------------------------------- #
# 2. SHARED TOKEN BUCKET - prevents N instances admitting N x the rate
# --------------------------------------------------------------------------- #
class SharedBucket:
    """Stands in for Redis: ONE store, all instances read and write it."""

    def __init__(self, capacity):
        self.store = defaultdict(lambda: capacity)

    def take(self, key, n=1):
        if self.store[key] >= n:
            self.store[key] -= n
            return True
        return False


class LocalBucket:
    """THE BUG: per-process state."""

    def __init__(self, capacity):
        self.capacity, self.tokens = capacity, capacity

    def take(self, key, n=1):
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


# --------------------------------------------------------------------------- #
# 3. RETRY IN ONE PLACE - prevents 3 x 3 = 9 amplification
# --------------------------------------------------------------------------- #
CALLS = {"n": 0}


def provider_call(fail_times):
    CALLS["n"] += 1
    if CALLS["n"] <= fail_times:
        raise Unavailable("503")
    return "ok"


def retry(fn, attempts=3, jitter=True):
    for i in range(attempts):
        try:
            return fn()
        except (Unavailable, RateLimited):
            if i == attempts - 1:
                raise
            delay = (2 ** i) * 0.001
            if jitter:
                delay *= random.uniform(0.5, 1.5)   # prevents a thundering herd
            time.sleep(delay)


if __name__ == "__main__":
    print("1. STREAMING - buffered vs passthrough")
    led = []
    a = SlowAdapter("provider-A")
    b = time_to_first_chunk(stream_buffered(a, "q", led))
    p = time_to_first_chunk(stream_passthrough(a, "q", led))
    print(f"   buffered    time-to-first-chunk: {b * 1000:5.1f} ms   <- waited for ALL of it")
    print(f"   passthrough time-to-first-chunk: {p * 1000:5.1f} ms")
    print(f"   usage still recorded either way: {led[-1]}")
    assert p < b / 3, "passthrough must be dramatically faster to first chunk"
    print("   -> buffering to count tokens spends the entire latency budget,")
    print("      and no non-streaming test will ever catch it\n")

    print("2. RATE LIMIT - 10 gateway instances, provider quota of 10/s")
    for name, cls in (("per-process buckets", LocalBucket), ("SHARED in Redis", SharedBucket)):
        buckets = [cls(10) for _ in range(10)]      # one per instance
        admitted = sum(bk.take("provider-A") for bk in buckets for _ in range(10))
        flag = "  <- 10x over-admitted -> 429s anyway" if admitted > 10 else "  <- correct"
        print(f"   {name:<22} admitted {admitted:>3} of a 10/s quota{flag}")
    shared = SharedBucket(10)
    assert sum(shared.take("p") for _ in range(30)) == 10
    print()

    print("3. RETRY - one place vs two")
    CALLS["n"] = 0
    try:
        retry(lambda: retry(lambda: provider_call(99), attempts=3), attempts=3)
    except Unavailable:
        pass
    nested = CALLS["n"]
    CALLS["n"] = 0
    try:
        retry(lambda: provider_call(99), attempts=3)
    except Unavailable:
        pass
    single = CALLS["n"]
    print(f"   client retry x3 AROUND gateway retry x3 -> {nested} provider calls")
    print(f"   gateway only                            -> {single} provider calls")
    assert nested == 9 and single == 3
    print("   -> 9 calls for one logical request, aimed at a service that is")
    print("      already failing. Retries belong in exactly one layer.\n")

    print("4. ADAPTERS - normalised error taxonomy drives the fallback")
    chain = [Adapter("A", RateLimited), Adapter("B", Unavailable), Adapter("C")]
    for ad in chain:
        try:
            out = "".join(ad.stream("q"))
            print(f"   {ad.name}: served -> {out.strip()[:34]}")
            break
        except (RateLimited, Unavailable) as e:
            print(f"   {ad.name}: {type(e).__name__:<13} -> next in chain")
    print("   -> the router can only decide on errors the adapter NORMALISED.")
    print("      Raw provider strings are not a taxonomy.")
    print("\nOK - scenario 2")
