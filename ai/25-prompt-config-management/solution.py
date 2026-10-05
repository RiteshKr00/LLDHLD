"""
Scenario 11 - prompt and config management: precedence, pointers, an unavoidable gate.

    python3 solution.py

Four mechanics, each showing the FAILURE first and the FIX second so the gap is measured:
  1. precedence   - a last-write-wins resolver silently clobbers 40 tuned tenants
  2. immutability - a mutable store cannot restore the exact bytes; a pointer flip can
  3. the gate     - "available" (two write paths) vs "unavoidable" (one writer)
  4. attribution  - the resolved bundle id on each request turns 12 suspects into 1

Numbers match explained.md and hld.md: 500 tenants, 600k LLM calls/day (chat 400k),
~400 config changes/year, $2 per 1M input tokens, $2,400/day of spend.
Deterministic (random.seed(11)); runs in well under a second.
"""
import hashlib
import random
from collections import defaultdict

random.seed(11)

CALLS_PER_DAY = {"chat": 400_000, "summarise": 150_000, "extract": 50_000}
INPUT_RATE = 2.0 / 1_000_000        # $ per input token
DAILY_SPEND = 2_400.0               # $/day across all features
COST_GATE = 0.10                    # block a promote adding >10% of daily spend


def bundle_id(text):
    """A version id is a content hash of the whole bundle, never a row counter."""
    return "b" + hashlib.sha256(text.encode()).hexdigest()[:8]


# --------------------------------------------------------------------------- #
# 1. PRECEDENCE - prevents one global edit clobbering every tuned tenant
# --------------------------------------------------------------------------- #
TENANTS = ["t%03d" % i for i in range(500)]
TUNED = TENANTS[:40]                                    # 40 tenants pay for a tuned prompt
GLOBAL_V1 = bundle_id("chat: answer briefly")
GLOBAL_V2 = bundle_id("chat: answer briefly, always cite sources")   # today's edit
TENANT_V = {t: bundle_id("chat tuned for " + t) for t in TUNED}
RANK = {"global": 0, "env": 1, "tenant": 2, "tenant+env": 3, "pin": 4}


def binding_rows(global_version, global_last):
    """global_last mimics the dashboard APPENDING today's edit after the overrides."""
    tenant_rows = [("tenant", t, TENANT_V[t]) for t in TUNED]
    glob = ("global", "*", global_version)
    return (tenant_rows + [glob]) if global_last else ([glob] + tenant_rows)


def resolve_naive(rows, tenant):
    """THE BUG: last matching row wins, so insertion order IS the policy."""
    out = None
    for kind, scope, version in rows:
        if kind == "global" or scope == tenant:
            out = version
    return out, "unknown"


def resolve_ordered(rows, tenant):
    """Total order on specificity. Returns the version AND the rule that won."""
    best = None
    for kind, scope, version in rows:
        if kind != "global" and scope != tenant:
            continue
        rank = RANK[kind]
        if best is None or rank > best[0]:
            best = (rank, version, "%s:%s" % (kind, scope))
        elif rank == best[0] and version != best[1]:
            raise ValueError("ambiguous precedence for %s at rank %d" % (tenant, rank))
    return best[1], best[2]


def wrong_tenants(resolver, rows):
    """How many of the 40 tuned tenants stopped getting their tuned prompt?"""
    return sum(1 for t in TUNED if resolver(rows, t)[0] != TENANT_V[t])


# --------------------------------------------------------------------------- #
# 2. IMMUTABLE VERSIONS + A POINTER - prevents rollback being a rewrite
# --------------------------------------------------------------------------- #
class MutableStore:
    """Edit in place. The previous bytes are gone; 'rollback' is a human retyping."""
    rollback_seconds = 720                       # revert PR + CI + build + deploy

    def __init__(self, text):
        self.text = text

    def edit(self, text):
        self.text = text

    def rollback(self, _version=None):
        return None                              # there is nothing to roll back TO


class VersionedStore:
    """Write-once versions, one mutable binding. Rollback is a pointer flip."""
    rollback_seconds = 30                        # snapshot push + worst-case poll skew

    def __init__(self, text):
        self.versions = {}
        self.live = self.publish(text)

    def publish(self, text):
        v = bundle_id(text)
        self.versions.setdefault(v, text)        # write-once: republishing is a no-op
        return v

    def promote(self, text):
        self.live = self.publish(text)

    def rollback(self, version):
        self.live = version
        return self.versions[version]


# --------------------------------------------------------------------------- #
# 3. THE GATE MUST BE UNAVOIDABLE, NOT AVAILABLE
# --------------------------------------------------------------------------- #
def make_changes(n=400):
    """One year of config changes: 4 features x ~2 edits/week x 50 weeks."""
    out = []
    for i in range(n):
        out.append({"id": i,
                    "surface": "dashboard" if random.random() < 0.35 else "pull request",
                    "quality_delta": random.gauss(0.0, 0.02),
                    "added_tokens": max(0, int(random.gauss(20, 130))),
                    "feature": "chat"})
    return out


def promote_gate(change):
    """Returns None to pass, or the reason the promote is blocked."""
    if change["quality_delta"] < -0.03:
        return "quality %+.3f below the hard gate" % change["quality_delta"]
    extra = change["added_tokens"] * CALLS_PER_DAY[change["feature"]] * INPUT_RATE
    if extra > COST_GATE * DAILY_SPEND:
        return "+$%.0f/day of prompt tokens" % extra
    return None


def ship(changes, single_writer):
    """single_writer=False leaves the dashboard a second, ungated write path."""
    gated = blocked = shipped_bad = 0
    for c in changes:
        reason = promote_gate(c)
        if single_writer or c["surface"] == "pull request":
            gated += 1
            if reason:
                blocked += 1
                continue
        if reason:
            shipped_bad += 1
    return gated, blocked, shipped_bad


# --------------------------------------------------------------------------- #
# 4. ATTRIBUTION - the resolved bundle id on every request
# --------------------------------------------------------------------------- #
CHANGES_THIS_WEEK = 12              # the suspect list, if requests carry no bundle id
GOOD = bundle_id("chat v6")
BAD = bundle_id("chat v7, promoted at 14:05")
STALE = bundle_id("chat v4, on a pod that missed the push")


def traffic(n=400):
    log = []
    for i in range(n):
        if i < 240:
            b, mu = GOOD, 0.82
        elif random.random() < 0.05:
            b, mu = STALE, 0.80     # one pod stuck on an old snapshot
        else:
            b, mu = BAD, 0.71
        log.append({"i": i, "bundle": b, "score": random.gauss(mu, 0.05)})
    return log


def by_bundle(log):
    agg = defaultdict(lambda: [0, 0.0, 10 ** 9])
    for r in log:
        a = agg[r["bundle"]]
        a[0] += 1
        a[1] += r["score"]
        a[2] = min(a[2], r["i"])
    return {b: (n, tot / n, first) for b, (n, tot, first) in agg.items()}


if __name__ == "__main__":
    print("1. PRECEDENCE - someone edits the GLOBAL chat prompt")
    before = binding_rows(GLOBAL_V1, global_last=False)
    after = binding_rows(GLOBAL_V2, global_last=True)
    for label, rows in (("before the edit", before), ("after the edit ", after)):
        n_naive = wrong_tenants(resolve_naive, rows)
        n_ord = wrong_tenants(resolve_ordered, rows)
        print("   %s  last-write-wins: %2d of 40 tuned tenants clobbered"
              "   |  total order: %d" % (label, n_naive, n_ord))
    assert wrong_tenants(resolve_naive, before) == 0
    assert wrong_tenants(resolve_naive, after) == 40
    assert wrong_tenants(resolve_ordered, after) == 0
    assert resolve_ordered(after, "t000")[1] == "tenant:t000"
    assert resolve_ordered(after, "t400")[1] == "global:*"
    tie = after + [("tenant", "t000", bundle_id("a rival tuned prompt"))]
    rejected = False
    try:
        resolve_ordered(tie, "t000")
    except ValueError:
        rejected = True
    assert rejected, "an equal-rank tie must be an error, not a coin toss"
    print("   t000 resolves via %s, t400 via %s; an equal-rank tie is REJECTED"
          % (resolve_ordered(after, "t000")[1], resolve_ordered(after, "t400")[1]))
    print("   -> the resolver was correct until a row was APPENDED. No error, no alert,")
    print("      40 accounts quietly worse. This is what breaks first.\n")

    print("2. ROLLBACK - mutable store vs immutable versions + a pointer")
    ORIGINAL = "You are a concise assistant. Cite the retrieved chunks."
    mut, ver = MutableStore(ORIGINAL), VersionedStore(ORIGINAL)
    v0 = ver.live
    for edit in ("v2: be warmer", "v3: add 6 few-shot examples", "v4: drop the citations"):
        mut.edit(edit)
        ver.promote(edit)
    restored_mut, restored_ver = mut.rollback(v0), ver.rollback(v0)
    print("   mutable store    restores %-12s  MTTR %4ds  (revert PR, CI, deploy)"
          % ("NOTHING", MutableStore.rollback_seconds))
    print("   versioned store  restores %-12s  MTTR %4ds  (binding flip + push)"
          % ("v0 byte-exact", VersionedStore.rollback_seconds))
    assert restored_mut is None
    assert restored_ver == ORIGINAL and bundle_id(restored_ver) == v0
    assert ver.publish(ORIGINAL) == v0 and len(ver.versions) == 4   # write-once, no dupes
    assert MutableStore.rollback_seconds == 24 * VersionedStore.rollback_seconds
    print("   -> 24x faster AND byte-exact. In the mutable store 'put it back' means")
    print("      someone retyping a prompt at 2am, producing a THIRD prompt.\n")

    print("3. THE GATE - 400 config changes/year, 35% of them from the dashboard")
    changes = make_changes()
    print("   %-34s %6s %8s %12s" % ("topology", "gated", "blocked", "bad shipped"))
    results = {}
    for label, single in (("gate AVAILABLE (2 write paths)", False),
                          ("gate UNAVOIDABLE (1 writer)", True)):
        g, b, bad = ship(changes, single)
        results[single] = bad
        print("   %-34s %6d %8d %12d" % (label, g, b, bad))
    assert results[False] > 0 and results[True] == 0
    extra = 500 * CALLS_PER_DAY["chat"] * INPUT_RATE
    assert abs(extra - 400.0) < 1e-6
    assert promote_gate({"quality_delta": 0.0, "added_tokens": 500, "feature": "chat"})
    print("   token budget check: +500 prompt tokens x 400k chat calls/day x $2/1M")
    print("      = $%.0f/day, ~$%s/month, %.0f%% of a $2,400/day bill -> BLOCKED"
          % (extra, "{:,}".format(int(extra * 30)), 100 * extra / DAILY_SPEND))
    print("   -> a gate the dashboard can walk around is decoration. One writer.\n")

    print("4. ATTRIBUTION - a quality drop, with and without the bundle id")
    log = traffic()
    first, second = log[:200], log[200:]
    m1 = sum(r["score"] for r in first) / len(first)
    m2 = sum(r["score"] for r in second) / len(second)
    print("   window mean %.3f -> %.3f. Without bundle ids the suspect list is every"
          % (m1, m2))
    print("   config change this week: %d of them." % CHANGES_THIS_WEEK)
    agg = by_bundle(log)
    print("   %-12s %6s %8s %14s" % ("bundle", "n", "mean", "first seen at"))
    for b, (n, mean, firsti) in sorted(agg.items(), key=lambda kv: kv[1][2]):
        print("   %-12s %6d %8.3f %14d" % (b, n, mean, firsti))
    culprit = min((b for b, v in agg.items() if v[0] >= 20), key=lambda b: agg[b][1])
    assert culprit == BAD
    assert agg[BAD][2] < 245, "the culprit's first request localises the promote"
    assert len(agg) == 3, "three bundles serving one feature means a pod is stuck"
    print("   culprit: %s, first served at request %d -> one promote, one timestamp."
          % (culprit, agg[culprit][2]))
    print("   -> and %s serving alongside it is the stale-snapshot pod. You only" % STALE)
    print("      see either because every request logged what resolved for it.")
    print("\nOK - scenario 11")

# --------------------------------------------------------------------------- #
# WHAT TO NOTICE
# 1. 0 -> 40 clobbered tenants with no code change at all. The naive resolver was
#    "working" for months; appending one global row changed the answer for every
#    tenant with an override. Precedence is the policy, not a lookup detail - and
#    the ordered resolver returns WHICH rule won, so the answer is auditable.
# 2. 720s vs 30s is the headline; byte-exactness matters more. The mutable store
#    restores None - there is no previous version to point at, only a memory. Note
#    republishing the original is a no-op (4 versions, not 5): a content hash makes
#    "no change" indistinguishable from no change.
# 3. "Bad shipped" is the only column that matters. Both topologies run the same
#    gate; the available one leaves a door beside it and a third of the year's
#    changes walk through. The cost check is the one nobody writes: +500 tokens is
#    $12k/month with every test still green.
# 4. The window means say "something regressed". The per-bundle table says which
#    version, from which request, and exposes a third bundle nobody promoted - the
#    pod that missed the push. Anything under 100% bundle-id coverage on requests
#    is exactly the fraction of the next incident you cannot explain.
# --------------------------------------------------------------------------- #
