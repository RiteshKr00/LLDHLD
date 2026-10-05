"""
Scenario 19 - zero-downtime embedding-model migration across 100M chunks.

    python3 solution.py

Four mechanics, each with the failure shown happening FIRST, then the fix:
  1. mixing two embedding spaces in one index - the reason 'in-place' does not exist
  2. a backfill that dies at hour 20, with and without checkpointing
  3. shadow reads and recall@k, catching a regression before anyone is served
  4. a semantic cache keyed without the model version, serving old-space answers

The embedding models here are toy projections, not real ones. What is real is
the geometry: two independently trained spaces are related by no rotation you
can recover, so a similarity computed across them is noise.

Seeded, so reruns match exactly.
"""
import math
import random
import zlib

random.seed(19)

CHUNKS = 100_000_000
EMBED_RATE = 1_000           # chunks/sec sustained, including the API round trip
DIM = 64
CORPUS = 600                 # documents in the toy retrieval demo
QUERIES = 200


# --------------------------------------------------------------------------- #
# two "models": different random projections of the same token statistics
# --------------------------------------------------------------------------- #
def make_model(seed):
    rng = random.Random(seed)
    basis = [[rng.gauss(0, 1) for _ in range(DIM)] for _ in range(96)]
    def embed(text):
        v = [0.0] * DIM
        for tok in text.split():
            row = basis[zlib.crc32(tok.encode()) % 96]
            for i in range(DIM):
                v[i] += row[i]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]
    return embed


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def topk(qv, index, k=5):
    scored = sorted(((cos(qv, v), i) for i, v in index), reverse=True)
    return [i for _, i in scored[:k]]


def recall_at_k(truth, got, k=5):
    return len(set(truth[:k]) & set(got[:k])) / k


# --------------------------------------------------------------------------- #
# 2. the backfill
# --------------------------------------------------------------------------- #
def backfill(total, rate, die_at_hour, checkpoint_every=None):
    """Returns (hours of wall clock spent, chunks actually persisted)."""
    hours_needed = total / rate / 3600
    if die_at_hour >= hours_needed:
        return hours_needed, total
    done = int(die_at_hour * 3600 * rate)
    if checkpoint_every is None:
        # no checkpoints: the job restarts from zero and runs to completion
        return die_at_hour + hours_needed, total
    kept = (done // checkpoint_every) * checkpoint_every
    lost_hours = (done - kept) / rate / 3600
    return die_at_hour + lost_hours + (total - kept) / rate / 3600, total


# --------------------------------------------------------------------------- #
# 4. the cache
# --------------------------------------------------------------------------- #
def cache_key(query, tenant, model_version=None):
    base = f"{tenant}:{query}"
    return base if model_version is None else f"{base}:{model_version}"


def main():
    print("\nZERO-DOWNTIME EMBEDDING-MODEL MIGRATION")
    print("=" * 74)
    hours = CHUNKS / EMBED_RATE / 3600
    print(f"{CHUNKS:,} chunks at {EMBED_RATE:,}/sec = {hours:.0f} hours of pure embedding")
    print("plus index build, plus double storage. This is a project, not a deploy.\n")

    old, new = make_model(1), make_model(2)
    docs = [" ".join(random.choice(["alpha", "beta", "gamma", "delta", "epsilon",
                                    "zeta", "eta", "theta", "iota", "kappa"])
                     for _ in range(8)) for _ in range(CORPUS)]
    idx_old = [(i, old(d)) for i, d in enumerate(docs)]
    idx_new = [(i, new(d)) for i, d in enumerate(docs)]

    # ---------------------------------------------------------------- 1
    print("1. MIXING SPACES - why there is no in-place migration")
    # a half-migrated index: some vectors old-space, some new-space
    mixed = [(i, (new if i % 2 == 0 else old)(d)) for i, d in enumerate(docs)]
    r_clean = r_mixed = 0.0
    for qi in range(QUERIES):
        q = docs[qi]
        truth = topk(old(q), idx_old)
        r_clean += recall_at_k(truth, topk(new(q), idx_new))
        r_mixed += recall_at_k(truth, topk(new(q), mixed))
    r_clean /= QUERIES
    r_mixed /= QUERIES
    print(f"   query with the NEW model against a clean NEW index : recall@5 {r_clean:.2f}")
    print(f"   query with the NEW model against a HALF-migrated one: recall@5 {r_mixed:.2f}")
    same = sum(1 for i in range(60) if abs(cos(old(docs[i]), new(docs[i]))) < 0.35)
    print(f"   the SAME document embedded by both models: {same} of 60 pairs have "
          f"|cosine| < 0.35")
    assert r_mixed < r_clean
    print("   -> a vector from model A and a vector from model B are not near each other,")
    print("      not far from each other - they are unrelated. A half-migrated index does")
    print("      not degrade gracefully; the two halves cannot be ranked against each")
    print("      other at all. This is why 'in-place, chunk by chunk' does not exist.\n")

    # ---------------------------------------------------------------- 2
    print("2. THE BACKFILL - 28 hours, and it dies at hour 20")
    ck = 1_000_000
    for label, cp in (("no checkpoints", None), (f"checkpoint every {ck // 1000}k", ck)):
        spent, _ = backfill(CHUNKS, EMBED_RATE, 20.0, cp)
        print(f"   {label:<26} total wall clock {spent:>5.1f} h   "
              f"(clean run is {hours:.1f} h)")
    naive, _ = backfill(CHUNKS, EMBED_RATE, 20.0, None)
    cked, _ = backfill(CHUNKS, EMBED_RATE, 20.0, ck)
    assert naive > cked + 15
    print(f"   -> checkpointing turns a {naive:.0f}-hour disaster into a {cked:.0f}-hour")
    print("      inconvenience. Resumability is not an optimisation on a job this long,")
    print("      it is the difference between finishing this week and not.\n")

    # ---------------------------------------------------------------- 3
    print("3. SHADOW READS - proving 'no quality regression' before serving")
    # Ground truth from token overlap - crude, but crucially INDEPENDENT of both
    # indexes. Labels derived from the old index would score it 1.000 by
    # construction and guarantee the new model looks like a regression.
    def truth_for(q):
        qt = set(q.split())
        scored = sorted(((len(qt & set(d.split())), -i, i) for i, d in enumerate(docs)),
                        reverse=True)
        return [i for _, _, i in scored[:5]]

    labelled = [(docs[qi], truth_for(docs[qi])) for qi in range(120)]
    r_old = sum(recall_at_k(t, topk(old(q), idx_old)) for q, t in labelled) / len(labelled)
    r_new = sum(recall_at_k(t, topk(new(q), idx_new)) for q, t in labelled) / len(labelled)
    print(f"   labelled set: {len(labelled)} queries, relevance judged INDEPENDENTLY")
    print(f"   old index recall@5 {r_old:.3f}")
    print(f"   new index recall@5 {r_new:.3f}   delta {r_new - r_old:+.3f}")
    print(f"   shadow traffic compared on BOTH, new index served to nobody yet")
    verdict = "BLOCK the cutover" if r_new < r_old - 0.02 else "proceed to canary"
    print(f"   -> verdict: {verdict}")
    assert abs(r_old - 1.0) > 1e-9, "labels must not be derived from the index under test"
    print("      The point is not the number, it is that the number exists before any")
    print("      user is affected. Without a labelled set, 'no quality regression' is")
    print("      an aspiration rather than a gate.\n")

    # ---------------------------------------------------------------- 4
    print("4. THE CACHE - warm, and full of the previous universe")
    cache = {}
    q, tenant = "what is the refund window", "t01"
    cache[cache_key(q, tenant)] = "answer grounded in OLD-space retrieval"
    cache[cache_key(q, tenant, "embed-v1")] = "answer grounded in OLD-space retrieval"
    hit_unversioned = cache.get(cache_key(q, tenant))
    hit_versioned = cache.get(cache_key(q, tenant, "embed-v2"))
    print(f"   key without model version -> {'HIT  ' + hit_unversioned}")
    print(f"   key with    model version -> {hit_versioned or 'MISS, recompute in new space'}")
    assert hit_unversioned is not None and hit_versioned is None
    print("   -> after cutover an unversioned cache keeps serving pre-migration answers")
    print("      indefinitely, and the hit rate stays high so nothing looks wrong. Put")
    print("      the embedding model version IN THE KEY and the problem deletes itself.\n")

    print("WHAT TO NOTICE")
    print("   * the two spaces are unrelated, not merely different - that single geometric")
    print("     fact rules out every in-place plan and forces dual indexes")
    print("   * 28 hours is the FLOOR: no failures, no re-runs, no index build")
    print("   * the cache is the quietest failure here, because a high hit rate on stale")
    print("     answers looks exactly like a healthy cache")
    print("   * keep the old index until you are confident, because the rollback is free")
    print("     while it exists and impossible afterwards")
    print("\nOK - scenario 19")


if __name__ == "__main__":
    main()
