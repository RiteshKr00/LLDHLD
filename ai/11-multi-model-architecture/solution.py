"""
11 - the multi-model gateway: registry, router, breaker, fallback, budget.

    python3 solution.py

Every layer is introduced by the failure it prevents, and the output shows
each failure actually happening and then being prevented.
"""
import random, time
from dataclasses import dataclass, field

random.seed(3)

# --------------------------------------------------------------------------- #
# CAPABILITY REGISTRY - model choice as DATA
#   prevents: a deprecation becoming a 20-call-site migration
# --------------------------------------------------------------------------- #
REGISTRY = {
    "small-fast":  {"provider": "A", "ctx": 8000,   "json": True,  "cost": 0.15, "status": "live"},
    "large-smart": {"provider": "A", "ctx": 128000, "json": True,  "cost": 2.50, "status": "live"},
    "alt-large":   {"provider": "B", "ctx": 128000, "json": True,  "cost": 3.00, "status": "live"},
    "self-hosted": {"provider": "C", "ctx": 32000,  "json": False, "cost": 0.02, "status": "live"},
    "old-model":   {"provider": "A", "ctx": 8000,   "json": True,  "cost": 0.10, "status": "deprecated"},
}


def capable(need_json=False, need_ctx=0):
    return [m for m, s in REGISTRY.items()
            if s["status"] == "live"
            and s["ctx"] >= need_ctx
            and (s["json"] if need_json else True)]


# --------------------------------------------------------------------------- #
# TOKEN BUCKET - SHARED state. Per-process buckets over-admit by N x.
#   prevents: 429s, and one tenant starving another
# --------------------------------------------------------------------------- #
@dataclass
class Bucket:
    capacity: int
    tokens: float = None
    rate: float = 5.0
    last: float = field(default_factory=time.time)

    def __post_init__(self):
        if self.tokens is None:
            self.tokens = self.capacity

    def take(self, n=1):
        now = time.time()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


# --------------------------------------------------------------------------- #
# CIRCUIT BREAKER - PER PROVIDER, not global
#   prevents: their outage becoming your outage, and hammering a sick service
# --------------------------------------------------------------------------- #
@dataclass
class Breaker:
    fails: int = 0
    threshold: int = 3
    opened_at: float = 0.0
    cooldown: float = 30.0

    @property
    def open(self):
        if self.fails < self.threshold:
            return False
        return (time.time() - self.opened_at) < self.cooldown

    def record(self, ok):
        if ok:
            self.fails = 0
        else:
            self.fails += 1
            if self.fails >= self.threshold:
                self.opened_at = time.time()


@dataclass
class Gateway:
    buckets: dict = field(default_factory=dict)
    breakers: dict = field(default_factory=dict)
    spend: dict = field(default_factory=dict)
    log: list = field(default_factory=list)

    def bucket(self, key, cap=4):
        return self.buckets.setdefault(key, Bucket(cap))

    def breaker(self, p):
        return self.breakers.setdefault(p, Breaker())

    # ---- provider behaviour we are defending against ----
    def _provider_call(self, model, down):
        p = REGISTRY[model]["provider"]
        if p in down:
            raise RuntimeError(f"provider {p} 503")
        return f"answer from {model}"

    def call(self, tenant, task, need_json=False, need_ctx=0,
             budget=1.0, down=(), difficulty="easy"):
        # ROUTER: capability -> difficulty (cascade) -> budget -> health
        options = capable(need_json, need_ctx)
        options.sort(key=lambda m: REGISTRY[m]["cost"])
        if difficulty == "hard":
            options.sort(key=lambda m: -REGISTRY[m]["cost"])

        spent = self.spend.get(tenant, 0.0)
        if spent >= budget:
            self.log.append((tenant, task, "budget", "DEGRADED to cheapest"))
            options = sorted(options, key=lambda m: REGISTRY[m]["cost"])[:1]

        if not self.bucket(tenant).take():
            self.log.append((tenant, task, "rate-limit", "queued"))
            return None, "queued (per-tenant bucket)"

        for model in options:                      # FALLBACK CHAIN
            p = REGISTRY[model]["provider"]
            if self.breaker(p).open:
                self.log.append((tenant, task, model, "skipped: breaker open"))
                continue
            try:
                out = self._provider_call(model, down)
                self.breaker(p).record(True)
                self.spend[tenant] = spent + REGISTRY[model]["cost"] / 1000
                self.log.append((tenant, task, model, "ok"))
                return out, model
            except RuntimeError:
                self.breaker(p).record(False)
                self.log.append((tenant, task, model, "failed -> next in chain"))
        return None, "all providers exhausted -> DEGRADED PATH"


if __name__ == "__main__":
    g = Gateway()

    print("1. REGISTRY - deprecation is a status flip, not a migration")
    print(f"   capable(json, 100k ctx) = {capable(True, 100000)}")
    print(f"   'old-model' selectable?  {'old-model' in capable()}   (deprecated)\n")

    print("2. ROUTER - cascade cheap-first")
    for diff in ("easy", "hard"):
        _, m = g.call("acme", "summarise", difficulty=diff)
        print(f"   {diff:<5} -> {m}")

    print("\n3. BREAKER + FALLBACK - provider A goes down")
    # a task only A and B can serve (needs JSON + 100k ctx), so the chain is
    # large-smart (A, cheaper) -> alt-large (B). Fresh gateway, roomy bucket.
    gb = Gateway(); gb.bucket("acme", cap=20)
    for i in range(4):
        out, m = gb.call("acme", "extract", need_json=True, need_ctx=100000,
                         down=("A",))
        print(f"   attempt {i + 1}: served by {m}"
              + ("   (A's breaker now OPEN - skipped, fail fast)"
                 if gb.breaker("A").open else "   (tried A first, fell through)"))
    assert gb.breaker("A").open, "3 failures should open A's breaker"
    assert any("skipped: breaker open" in e[3] for e in gb.log), gb.log
    print(f"   provider A breaker open? {gb.breaker('A').open}"
          f"   provider B: {gb.breaker('B').open}\n")

    print("4. RATE LIMIT - per-tenant bucket, shared state")
    g2 = Gateway()
    got = [g2.call("noisy", "bulk")[1] for _ in range(7)]
    served = sum(1 for x in got if x in REGISTRY)
    print(f"   7 rapid requests -> {served} served, {7 - served} queued")
    assert served < 7, "the bucket must shed load"
    print("   -> per-PROCESS buckets would admit 7 x N and you'd get 429s anyway\n")

    print("5. BUDGET - degrade, don't cut off")
    g3 = Gateway(); g3.spend["poor"] = 99.0
    _, m = g3.call("poor", "chat", budget=1.0, difficulty="hard")
    print(f"   over budget, asked for 'hard' -> {m}  (DOWNGRADED, still served)\n")

    print("   the failure order that proves you've run one of these:")
    print("   rate limits (daily) -> tail latency -> cost -> outage (quarterly)")
    print("   -> deprecation. Most candidates name the outage first.")
    print("\nOK - topic 11")
