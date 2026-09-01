"""
Rate Limiter — LLD solution (built step by step).

Entities (Step 2):
    1. RateLimitRule       - the spec: limit + window_seconds (value object)
    2. StateStore          - per-key state; ATOMIC increment; InMemory now, Redis later (abstraction)
    3. RateLimitAlgorithm  - Strategy: decides allow/reject using the store
    4. RateLimiter         - orchestrator; builds the key, delegates
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import threading
import time


# ---------------------------------------------------------------------------
# Step 4a: RateLimitRule + StateStore (ABC + InMemory)   <-- YOUR TURN
#
#   1. RateLimitRule  -> @dataclass with limit: int, window_seconds: int
#   2. StateStore(ABC) -> abstract `increment(key, window_seconds) -> int`
#   3. InMemoryStore   -> atomic increment (the thread-safety lives HERE).
#        state: key -> (count, window_expiry). On each call:
#          - if the window expired (now >= expiry) -> reset count=0, expiry=now+window
#          - count += 1, store, return count
#        WRAP the read-modify-write in a lock -> that's the atomic op (Redis does INCR+EXPIRE)
# ---------------------------------------------------------------------------


@dataclass
class RateLimitRule:
    limit: int
    window_seconds: int


class StateStore(ABC):
    @abstractmethod
    def increment(self, key: str, window_seconds: int) -> int:
        pass


class InMemoryStore(StateStore):
    def __init__(self):
        self.state = {}  # key -> (count, window_expiry)
        self.lock = threading.Lock()

    def increment(self,key:str, Window_seconds:int) -> int:
        with self.lock:
            now = time.time()
            count, expiry = self.state.get(key, (0, 0))
            if now >= expiry:
                count = 0
                expiry = now + Window_seconds
            count += 1
            self.state[key] = (count, expiry)
            return count

# ---------------------------------------------------------------------------
# Step 4b: RateLimitAlgorithm (Strategy ABC) + FixedWindowCounter
#
# HINT (to rebuild) — the crux of this problem is WHERE STATE LIVES:
#   algorithm = stateless LOGIC   |   store = the per-key STATE
# So the algorithm holds NO dict and NO lock of its own — it gets a StateStore
# injected (DI) and asks it for numbers. That separation is exactly what lets
# the SAME algorithm run in-memory (one process) or on Redis (many servers)
# with zero code change — swap the store, nothing else.
#
#   FixedWindowCounter.allow_request(key, rule) is 2 lines:
#     count = self.store.increment(key, rule.window_seconds)
#     return count <= rule.limit
#
# Known tradeoff to say out loud: fixed windows allow a BOUNDARY BURST —
# 50 requests at 0:00:59 plus 50 at 0:01:00 = 100 in ~1s, both windows "legal".
# Sliding Window Counter smooths that; Token Bucket allows bursts on purpose.
# ---------------------------------------------------------------------------
class RateLimitAlgorithm(ABC):
    @abstractmethod
    def allow_request(self, key: str, rule: RateLimitRule) -> bool:
        pass

class FixedWindowCounter(RateLimitAlgorithm):
    def __init__(self, store: StateStore):
        self.store = store

    def allow_request(self, key: str, rule: RateLimitRule) -> bool:
        count = self.store.increment(key, rule.window_seconds)
        return count <= rule.limit


# ---------------------------------------------------------------------------
# Token Bucket — a DIFFERENT algorithm needs a DIFFERENT store shape.
# Fixed Window only needed one int (a count). Token Bucket needs two floats
# (tokens remaining, last-refill-time) and different math (lazy refill).
# Forcing this into `StateStore.increment` would violate ISP (a fat interface
# with a method some stores can't honestly implement) -> give it its OWN
# narrow store interface instead.
# ---------------------------------------------------------------------------
class TokenBucketStore(ABC):
    @abstractmethod
    def consume(self, key: str, capacity: int, refill_rate: float) -> bool:
        """Atomically: lazily refill tokens since last call, then try to take 1.
        Returns True if a token was available (request allowed)."""
        ...


class InMemoryTokenBucketStore(TokenBucketStore):
    def __init__(self):
        self.state: dict[str, tuple[float, float]] = {}   # key -> (tokens, last_refill_time)
        self.lock = threading.Lock()

    def consume(self, key: str, capacity: int, refill_rate: float) -> bool:
        now = time.time()
        with self.lock:                                        # same atomicity lesson as InMemoryStore
            tokens, last_refill = self.state.get(key, (capacity, now))
            elapsed = now - last_refill
            tokens = min(capacity, tokens + elapsed * refill_rate)   # lazy refill since last call
            if tokens >= 1:
                tokens -= 1
                self.state[key] = (tokens, now)
                return True
            self.state[key] = (tokens, now)                     # persist the refill even on reject
            return False


class TokenBucket(RateLimitAlgorithm):
    """Allows short bursts up to `capacity`, then throttles to `refill_rate`/sec."""

    def __init__(self, store: TokenBucketStore, refill_rate: float):
        self.store = store
        self.refill_rate = refill_rate

    def allow_request(self, key: str, rule: RateLimitRule) -> bool:
        return self.store.consume(key, rule.limit, self.refill_rate)


# ---------------------------------------------------------------------------
# Sliding Window Counter — near-strict, cheap (Step 1's recommended default).
# Needs the PREVIOUS window's count too, so it also gets its own store shape.
# ---------------------------------------------------------------------------
class SlidingWindowStore(ABC):
    @abstractmethod
    def record(self, key: str, window_seconds: int) -> tuple[int, int, float]:
        """Atomically record a hit; return (curr_count, prev_count, elapsed_fraction)
        where elapsed_fraction = how far we are INTO the current window (0..1)."""
        ...


class InMemorySlidingWindowStore(SlidingWindowStore):
    def __init__(self):
        # key -> (window_start, curr_count, prev_count)
        self.state: dict[str, tuple[float, int, int]] = {}
        self.lock = threading.Lock()

    def record(self, key: str, window_seconds: int) -> tuple[int, int, float]:
        now = time.time()
        with self.lock:
            window_start, curr, prev = self.state.get(key, (now, 0, 0))
            elapsed = now - window_start
            if elapsed >= window_seconds:                # rolled over: current becomes previous
                windows_passed = int(elapsed // window_seconds)
                window_start += windows_passed * window_seconds
                prev = curr if windows_passed == 1 else 0   # >1 window passed -> prev window was empty
                curr = 0
                elapsed = now - window_start
            curr += 1
            self.state[key] = (window_start, curr, prev)
            return curr, prev, elapsed / window_seconds


class SlidingWindowCounter(RateLimitAlgorithm):
    """Weights the previous window by how much it overlaps 'now' -> smooths the
    Fixed Window boundary-burst without Sliding Log's per-timestamp memory cost."""

    def __init__(self, store: SlidingWindowStore):
        self.store = store

    def allow_request(self, key: str, rule: RateLimitRule) -> bool:
        curr, prev, elapsed_frac = self.store.record(key, rule.window_seconds)
        estimated = curr + prev * (1 - elapsed_frac)
        return estimated <= rule.limit


# ---------------------------------------------------------------------------
# RedisStore — the DISTRIBUTED swap for StateStore. Only this class changes;
# RateLimitAlgorithm and RateLimiter are untouched (that's the whole point of
# the abstraction). Requires: pip install redis
# ---------------------------------------------------------------------------
# import redis
#
# _INCR_WITH_TTL = """
# local count = redis.call('INCR', KEYS[1])
# if count == 1 then
#     redis.call('EXPIRE', KEYS[1], ARGV[1])
# end
# return count
# """
# # A Lua script runs as ONE atomic unit on the Redis server (Redis is single-
# # threaded, so no other command can interleave mid-script) -> this is the
# # distributed equivalent of `with self.lock:` in InMemoryStore. Plain
# # INCR-then-EXPIRE as two separate calls is NOT atomic (a crash in between
# # leaves a key with no TTL) -> that's why this needs a script, not a pipeline.
#
# class RedisStore(StateStore):
#     def __init__(self, client: "redis.Redis"):
#         self.client = client
#         self._incr_script = client.register_script(_INCR_WITH_TTL)
#
#     def increment(self, key: str, window_seconds: int) -> int:
#         return self._incr_script(keys=[key], args=[window_seconds])


# ---------------------------------------------------------------------------
# Step 4c: RateLimiter (orchestrator) — build key, delegate to algorithm
#
# HINT (to rebuild): tiny class, 3 lines of body. It must NOT know which
# algorithm it's running — that's injected:
#   __init__(algorithm, rules)   rules = {endpoint: RateLimitRule}, so different
#                                endpoints can have different limits (/login
#                                stricter than /search)
#   allow(user, endpoint):
#       key  = f"{user}:{endpoint}"      <- the composite key isolates each
#                                           user PER endpoint
#       rule = self.rules[endpoint]
#       return self.algorithm.allow_request(key, rule)
#
# The proof it's a real Strategy: swapping FixedWindow -> TokenBucket ->
# SlidingWindow changes ONE constructor argument and nothing else.
# ---------------------------------------------------------------------------
class RateLimiter:
    """Entry point. Doesn't know or care WHICH algorithm it's running —
    that's injected. Swapping FixedWindow <-> TokenBucket <-> SlidingWindow
    is a one-line change here, nowhere else."""

    def __init__(self, algorithm: RateLimitAlgorithm, rules: dict[str, RateLimitRule]):
        self.algorithm = algorithm
        self.rules = rules   # endpoint -> its RateLimitRule (different endpoints, different limits)

    def allow(self, user: str, endpoint: str) -> bool:
        key = f"{user}:{endpoint}"
        rule = self.rules[endpoint]
        return self.algorithm.allow_request(key, rule)


# ---------------------------------------------------------------------------
# Demo — same RateLimiter, three algorithms swapped in with ONE line changed.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    rules = {"/search": RateLimitRule(limit=5, window_seconds=2)}

    print("--- FixedWindowCounter: 5/2s, hammer with 8 requests ---")
    limiter = RateLimiter(FixedWindowCounter(InMemoryStore()), rules)
    print([limiter.allow("alice", "/search") for _ in range(8)])
    # expect: 5 True, then 3 False (limit hit within the window)

    print("\n--- TokenBucket: capacity 5, refill 2/s, burst of 8 then wait ---")
    limiter = RateLimiter(TokenBucket(InMemoryTokenBucketStore(), refill_rate=2.0), rules)
    print("burst:", [limiter.allow("bob", "/search") for _ in range(8)])
    time.sleep(1.1)   # ~2 tokens refill
    print("after 1.1s:", [limiter.allow("bob", "/search") for _ in range(3)])

    print("\n--- SlidingWindowCounter: 5/2s, smooths the boundary burst ---")
    limiter = RateLimiter(SlidingWindowCounter(InMemorySlidingWindowStore()), rules)
    print([limiter.allow("carol", "/search") for _ in range(8)])

    print("\n--- per-user isolation: dave has his own counter, unaffected by alice ---")
    shared_algo = FixedWindowCounter(InMemoryStore())
    limiter = RateLimiter(shared_algo, rules)
    print("alice x5:", [limiter.allow("alice2", "/search") for _ in range(5)])
    print("dave x1 :", limiter.allow("dave", "/search"), "(dave's own quota, not blocked by alice2)")
