"""
Scenario 3 - multi-tenant RAG: namespaces vs filters, and why ingest breaks first.

    python3 solution.py
"""
import heapq
from collections import defaultdict

CHUNKS = [
    ("acme",   "acme-hr",     "notice period is 90 days"),
    ("acme",   "acme-hr",     "annual leave is 24 days"),
    ("globex", "globex-hr",   "notice period is 30 days"),
    ("globex", "globex-fin",  "revenue target is 4.2m"),
]


def score(q, text):
    qs, ts = set(q.lower().split()), set(text.lower().split())
    return len(qs & ts) / (len(qs) or 1)


# --------------------------------------------------------------------------- #
# 1. ISOLATION - post-filter vs namespace
# --------------------------------------------------------------------------- #
def search_shared_index(tenant, q, k=2, filter_bug=False):
    """One index for everyone; isolation is a filter applied AFTER ranking."""
    ranked = sorted(CHUNKS, key=lambda c: -score(q, c[2]))
    if not filter_bug:
        ranked = [c for c in ranked if c[0] == tenant]
    return [(c[0], c[2]) for c in ranked[:k]]


NAMESPACES = defaultdict(list)
for t, ns, text in CHUNKS:
    NAMESPACES[(t, ns)].append(text)


def search_namespaced(tenant, q, k=2, filter_bug=False):
    """Per-tenant namespaces. The filter bug has nothing to act on."""
    pool = [(t, txt) for (t, _ns), txts in NAMESPACES.items()
            if t == tenant for txt in txts]
    ranked = sorted(pool, key=lambda c: -score(q, c[1]))
    return ranked[:k]


# --------------------------------------------------------------------------- #
# 2. THE CACHE IS A LEAK IF IT IS NOT NAMESPACED
# --------------------------------------------------------------------------- #
class Cache:
    def __init__(self, namespaced, corpus_version=1):
        self.ns, self.v, self.store = namespaced, corpus_version, {}

    def key(self, tenant, q):
        return (tenant, self.v, q) if self.ns else (q,)

    def get(self, tenant, q):
        return self.store.get(self.key(tenant, q))

    def put(self, tenant, q, ans):
        self.store[self.key(tenant, q)] = (tenant, ans)


# --------------------------------------------------------------------------- #
# 3. INGEST BREAKS FIRST - shared queue vs per-tenant queues
# --------------------------------------------------------------------------- #
EMBED_RATE = 1000        # embeddings/sec, the shared resource


def drain_shared(jobs):
    """One FIFO. A 200k-doc onboarding sits in front of everyone."""
    t, waits = 0.0, {}
    for tenant, docs in jobs:
        t += docs * 20 / EMBED_RATE          # 20 chunks per doc
        waits.setdefault(tenant, t)
    return waits


def drain_fair(jobs):
    """Per-tenant queues, round-robin drain, per-tenant rate limit."""
    q = {t: docs for t, docs in jobs}
    t, waits, SLICE = 0.0, {}, 500           # docs per turn
    while q:
        for tenant in list(q):
            take = min(SLICE, q[tenant])
            t += take * 20 / EMBED_RATE
            q[tenant] -= take
            if q[tenant] <= 0:
                waits[tenant] = t
                del q[tenant]
    return waits


if __name__ == "__main__":
    print("1. ISOLATION - the same filter bug, two designs")
    for label, fn in (("shared index + post-filter", search_shared_index),
                      ("per-tenant NAMESPACE", search_namespaced)):
        ok = fn("acme", "notice period")
        bug = fn("acme", "notice period", filter_bug=True)
        leaked = [c for c in bug if c[0] != "acme"]
        print(f"   {label:<28} correct={[c[0] for c in ok]}"
              f"  with filter bug={[c[0] for c in bug]}"
              f"{'  <- LEAKED globex content' if leaked else '  <- nothing to leak'}")
    assert any(c[0] != "acme" for c in search_shared_index("acme", "notice period", filter_bug=True))
    assert all(c[0] == "acme" for c in search_namespaced("acme", "notice period", filter_bug=True))
    print("   -> a vector search RANKS across whatever is in the index. With a")
    print("      shared index the filter is the only thing standing between")
    print("      tenants; with namespaces the other tenant was never a candidate.\n")

    print("2. CACHE - the key decides whether it is a leak")
    for ns in (False, True):
        c = Cache(namespaced=ns)
        c.put("acme", "notice period", "90 days")
        hit = c.get("globex", "notice period")
        print(f"   namespaced={str(ns):<5} globex asks the same question -> "
              f"{'LEAK: ' + hit[1] if hit else 'miss (correct)'}")
    assert Cache(False).__class__  # keep linters quiet
    c1, c2 = Cache(False), Cache(True)
    c1.put("acme", "q", "secret"); c2.put("acme", "q", "secret")
    assert c1.get("globex", "q") is not None and c2.get("globex", "q") is None
    print("   -> and version the key by CORPUS too, or a re-index serves the")
    print("      old world forever\n")

    print("3. INGEST - one tenant onboarding 200k docs")
    jobs = [("whale", 200_000), ("small-a", 500), ("small-b", 500), ("small-c", 500)]
    for label, fn in (("shared FIFO queue", drain_shared),
                      ("per-tenant + fair drain", drain_fair)):
        w = fn(jobs)
        print(f"   {label:<26} small-a waits {w['small-a']:>8.0f}s   "
              f"whale finishes {w['whale']:>8.0f}s")
    ws, wf = drain_shared(jobs), drain_fair(jobs)
    assert wf["small-a"] < ws["small-a"] / 100
    print("   -> the whale finishes at about the same time either way. The")
    print("      difference is whether three other tenants were down for an hour.")
    print("      That containment IS the design goal.")
    print("\nOK - scenario 3")
