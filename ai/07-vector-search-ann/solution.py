"""
07 - ANN recall vs latency, and why the reranker beats the search.

    python3 solution.py

A tiny exact-vs-approximate search over toy vectors, so the recall/latency
dial is a number rather than a claim.
"""
import math, random

random.seed(11)
DIM, N, TOPK = 8, 400, 5

DOCS = [[random.gauss(0, 1) for _ in range(DIM)] for _ in range(N)]


def norm(v):
    m = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / m for x in v]


DOCS = [norm(d) for d in DOCS]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))      # unit vectors -> dot == cosine


def exact(q, k=TOPK):
    """O(n): compare against every vector. The ground truth."""
    return [i for i, _ in sorted(enumerate(DOCS), key=lambda p: -cosine(q, p[1]))[:k]]


def ann(q, num_candidates, k=TOPK):
    """Approximate: explore only `num_candidates`, then rank those.

    Stands in for HNSW's greedy walk / Atlas's numCandidates - the point is
    that a BUDGET decides how much of the index you look at.
    """
    seen = random.sample(range(N), min(num_candidates, N))
    ranked = sorted(seen, key=lambda i: -cosine(q, DOCS[i]))
    return ranked[:k], len(seen)


def recall_at_k(truth, got):
    return len(set(truth) & set(got)) / len(truth)


# a cross-encoder sees the query and doc TOGETHER, so it can use a signal the
# bi-encoder embedding never encoded
def cross_encoder(q, i):
    return cosine(q, DOCS[i]) + 0.15 * (1 if sum(DOCS[i]) > 0 else -1)


if __name__ == "__main__":
    queries = [norm([random.gauss(0, 1) for _ in range(DIM)]) for _ in range(40)]

    print("  numCandidates   comparisons   recall@5")
    print("  " + "-" * 44)
    for mult in (1, 2, 5, 10, 20, 40):
        nc = TOPK * mult
        rec, comps = 0.0, 0
        for q in queries:
            got, seen = ann(q, nc)
            rec += recall_at_k(exact(q), got)
            comps += seen
        rec /= len(queries)
        tag = "  <- the 10x default" if mult == 10 else ""
        print(f"  {nc:>13}   {comps // len(queries):>11}   {rec:>7.0%}{tag}")

    ten = sum(recall_at_k(exact(q), ann(q, TOPK * 10)[0]) for q in queries) / len(queries)
    one = sum(recall_at_k(exact(q), ann(q, TOPK * 1)[0]) for q in queries) / len(queries)
    assert ten > one, "more exploration must not reduce recall"

    print(f"\n  exact search compares all {N} vectors every time.")
    print("  The dial buys recall with comparisons - that IS the trade,")
    print("  and it is the same parameter as HNSW's ef_search.\n")

    # two-stage
    q = queries[0]
    stage1, _ = ann(q, TOPK * 4, k=20)
    stage2 = sorted(stage1, key=lambda i: -cross_encoder(q, i))[:TOPK]
    print(f"  stage 1 (bi-encoder, 20 candidates): {stage1[:5]}")
    print(f"  stage 2 (cross-encoder rerank, top 5): {stage2}")
    print("  -> the bi-encoder embedded query and doc SEPARATELY; the")
    print("     cross-encoder scores them TOGETHER, which is why it")
    print("     reorders. Slow per item, so only over the top ~20.")
    print("\nOK - topic 07")
