"""
Scenario 23 - LLM-powered search on 10M documents, 200 ms budget.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. the latency budget, and what it rules out
  2. vector-only search losing to BM25 on the queries people actually type
  3. hybrid retrieval, then a cross-encoder rerank over the top 100
  4. semantic similarity is not usefulness - click signal is
  5. where the LLM actually earns its place: offline

Toy corpus, real arithmetic. Seeded, so reruns match exactly.

What to notice: the LLM never appears in the request path, and the system is
better for it. Its value here is enrichment and training data, generated hours
earlier.
"""
import math
import random
import re
import zlib

random.seed(23)

DOCS = 10_000_000
BUDGET_MS = 200

STAGES = [
    ("network in + out",        25,  "fixed"),
    ("query understanding",      3,  "cheap"),
    ("BM25 over 10M",           18,  "inverted index"),
    ("ANN vector search",       22,  "HNSW, top 200"),
    ("fusion + dedup",           4,  "cheap"),
    ("cross-encoder rerank 100", 28, "small distilled model"),
    ("business rules + render", 12,  "boosts, snippets"),
]
LLM_GENERATION_MS = 900          # a small model, one short completion


# --------------------------------------------------------------------------- #
# toy corpus
# --------------------------------------------------------------------------- #
CORPUS = [
    ("A1", "How to reset your password", "reset password login account recover"),
    ("A2", "Password policy for administrators", "password policy admin complexity rotation"),
    ("A3", "Forgot my login details", "forgot login username email recover account"),
    ("A4", "Error code E4471 explained", "error code E4471 troubleshooting fault"),
    ("A5", "Two-factor authentication setup", "2fa mfa authenticator security setup"),
    ("A6", "Signing in on a new device", "sign in new device login trust browser"),
    ("A7", "Billing and invoices", "billing invoice payment card receipt"),
    ("A8", "Refund policy", "refund return money back policy window"),
]

# Distractors. With only eight documents a retriever that has NO signal still
# lands the right answer in the top three by luck often enough to look competent,
# which quietly flatters every baseline. Realistic corpora are large; this is the
# smallest change that stops tie-break luck from carrying the comparison.
_FILLER = ["shipping", "warranty", "api", "webhook", "export", "mobile", "sso",
           "audit", "quota", "theme", "keyboard", "print", "archive", "tags",
           "calendar", "import", "roles", "search", "backup", "status",
           "release", "glossary", "contact", "status page"]
for _i, _w in enumerate(_FILLER):
    CORPUS.append((f"B{_i:02d}", f"{_w.title()} guide", f"{_w} guide help documentation"))
    TOPIC_EXTRA = None
CLICKS = {"locked out": {"A1": 41, "A3": 33, "A6": 9},          # vector's kind
          "E4471": {"A4": 88},                                   # BM25's kind
          "cant get into my account": {"A3": 52, "A1": 21},
          "how do i get my money back": {"A8": 62, "A7": 7}}


def toks(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def bm25(query, doc, k1=1.4, b=0.75, avgdl=9.0):
    """Lexical. Exact-term matching, no notion of meaning."""
    d = toks(doc[1] + " " + doc[2])
    score = 0.0
    for q in toks(query):
        f = d.count(q)
        if not f:
            continue
        idf = math.log(1 + (len(CORPUS) - 1) / 2.0)
        score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len(d) / avgdl))
    return score


# a stand-in embedding: topic buckets, so paraphrases land together
TOPIC = {"A1": "access", "A2": "policy", "A3": "access", "A4": "error",
         "A5": "security", "A6": "access", "A7": "billing", "A8": "billing"}
for _d in CORPUS:
    TOPIC.setdefault(_d[0], "other")
QUERY_TOPIC = {"locked out": "access", "how do i get my money back": "billing",
               "cant get into my account": "access", "refund window": "billing"}


def vector(query, doc):
    """Semantic. Catches paraphrase, blind to rare exact tokens."""
    qt = QUERY_TOPIC.get(query)
    if qt is None:
        return 0.30
    base = 0.82 if TOPIC[doc[0]] == qt else 0.31
    return base + (zlib.crc32(doc[0].encode()) % 7) / 100.0


def rrf(rankings, k=60):
    """Reciprocal rank fusion - combines rankings without tuning a weight."""
    out = {}
    for r in rankings:
        for pos, doc_id in enumerate(r, 1):
            out[doc_id] = out.get(doc_id, 0.0) + 1.0 / (k + pos)
    return sorted(out, key=out.get, reverse=True)


def has_signal(fn, query, eps=0.05):
    """Did this retriever actually rank anything, or return a flat list?"""
    sc = [fn(query, d) for d in CORPUS]
    return (max(sc) - min(sc)) > eps


def rrf_gated(query, k=60):
    """Fuse only the retrievers that found something.

    Plain RRF averages ranks, so a retriever with no signal contributes an
    arbitrary ordering that actively displaces the one that worked. Gating on
    signal is what makes fusion safe when one arm is blind.
    """
    lists = []
    if has_signal(bm25, query):
        lists.append(rank_by(bm25, query))
    if has_signal(vector, query):
        lists.append(rank_by(vector, query))
    if not lists:
        return rank_by(bm25, query)
    return rrf(lists, k)


def rank_by(fn, query):
    """Ties break on a stable hash, not on corpus order.

    A retriever with no signal scores everything equally. Falling back to the
    order the documents happen to sit in flatters it whenever that order is
    meaningful, which is how a no-signal baseline ends up looking competent.
    """
    return [d[0] for d in sorted(
        CORPUS, key=lambda d: (fn(query, d), zlib.crc32(d[0].encode()) % 1000 / 1e6),
        reverse=True)]


def ndcg_at(order, truth, k=3):
    ideal = sorted(truth.values(), reverse=True)
    dcg = sum(truth.get(d, 0) / math.log2(i + 2) for i, d in enumerate(order[:k]))
    idl = sum(v / math.log2(i + 2) for i, v in enumerate(ideal[:k]))
    return dcg / idl if idl else 0.0


def main():
    print("\nSEARCH AND RANKING ON 10M DOCUMENTS, 200 ms")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. THE BUDGET - what 200 ms rules out")
    total = sum(ms for _, ms, _ in STAGES)
    print(f"   {'stage':<26}{'ms':>6}   note")
    for name, ms, note in STAGES:
        print(f"   {name:<26}{ms:>6}   {note}")
    print(f"   {'TOTAL':<26}{total:>6}   {BUDGET_MS - total} ms of headroom")
    print(f"\n   one LLM generation call: {LLM_GENERATION_MS} ms "
          f"({LLM_GENERATION_MS / BUDGET_MS:.1f}x the ENTIRE budget)")
    assert total < BUDGET_MS < LLM_GENERATION_MS
    print("   -> the LLM cannot be in the synchronous path. Not 'should not' - cannot.")
    print("      Everything below follows from that, and saying it early is the answer.\n")

    # ---------------------------------------------------------------- 2
    print("2. VECTOR-ONLY IS A WORSE SEARCH ENGINE")
    def spread(fn, query):
        """A retriever with no signal returns the same score for everything."""
        sc = [fn(query, d) for d in CORPUS]
        return max(sc) - min(sc)

    print(f"   {'query':<28}{'BM25 spread':>13}{'vector spread':>15}   who has signal")
    for query, note in (("E4471", "rare exact token"),
                        ("locked out", "paraphrase, zero term overlap")):
        bs, vs = spread(bm25, query), spread(vector, query)
        who = "BM25 only" if bs > 0 and vs < 0.1 else "vector only" if vs > 0.1 and bs == 0 else "both"
        print(f"   {query!r:<28}{bs:>13.2f}{vs:>15.2f}   {who}   ({note})")
    assert spread(bm25, "E4471") > 0 and spread(vector, "E4471") < 0.1
    assert spread(bm25, "locked out") == 0 and spread(vector, "locked out") > 0.1
    print(f"      'E4471' -> BM25 ranks A4 first; the embedding has never meaningfully")
    print(f"      seen that token, so every document scores the same.")
    print(f"      'locked out' -> no document contains either word, so BM25 has nothing")
    print(f"      to rank on at all; the embedding separates them cleanly.")
    print("   -> each is blind where the other sees. 'Embed everything and use vector")
    print("      search' is a WORSE engine than BM25 for exact terms, error codes, SKUs")
    print("      and names - which is most of what people type into a site search.\n")

    # ---------------------------------------------------------------- 3
    print("3. HYBRID, THEN RERANK")
    print(f"   {'query':<30}{'BM25':>8}{'vector':>9}{'RRF':>8}{'gated':>8}")
    tot = {"bm25": 0.0, "vec": 0.0, "naive": 0.0, "hyb": 0.0}
    mins = {"bm25": 1.0, "vec": 1.0, "naive": 1.0, "hyb": 1.0}
    for query, truth in CLICKS.items():
        b, v = rank_by(bm25, query), rank_by(vector, query)
        s = (ndcg_at(b, truth), ndcg_at(v, truth),
             ndcg_at(rrf([b, v]), truth), ndcg_at(rrf_gated(query), truth))
        for key, val in zip(("bm25", "vec", "naive", "hyb"), s):
            tot[key] += val
            mins[key] = min(mins[key], val)
        print(f"   {query[:28]:<30}{s[0]:>8.2f}{s[1]:>9.2f}{s[2]:>8.2f}{s[3]:>8.2f}")
    n = len(CLICKS)
    print(f"   {'MEAN nDCG@3':<30}{tot['bm25'] / n:>8.2f}{tot['vec'] / n:>9.2f}"
          f"{tot['naive'] / n:>8.2f}{tot['hyb'] / n:>8.2f}")
    print(f"   {'WORST query':<30}{mins['bm25']:>8.2f}{mins['vec']:>9.2f}"
          f"{mins['naive']:>8.2f}{mins['hyb']:>8.2f}")
    # The argument for hybrid is the floor. Each single retriever has a query
    # type it scores ~0 on; the mean can hide that and the worst case cannot.
    assert mins["naive"] < mins["bm25"]      # naive fusion is WORSE than one arm alone
    assert mins["hyb"] > max(mins["bm25"], mins["vec"])
    print("   -> plain RRF is worse in the worst case than BM25 on its own, because on")
    print("      'E4471' it averages a correct ranking with an arbitrary one and the")
    print("      noise displaces the signal. Gate each retriever on whether it actually")
    print("      ranked anything, and fusion becomes safe.")
    print("      Read the WORST row, not the mean. Each single retriever has a query")
    print("      type it scores near zero on, and which one that is depends entirely on")
    print("      your traffic mix. Hybrid buys a floor, not an average.")
    print("      Reciprocal rank fusion needs no weight to tune, which matters because")
    print("      the right weight differs per query type. Then a cross-encoder reranks")
    print("      the top 100 in ~28 ms: small, distilled, and it sees the query and the")
    print("      document TOGETHER, which a bi-encoder never does.\n")

    # ---------------------------------------------------------------- 4
    print("4. SIMILARITY IS NOT USEFULNESS")
    q3 = "how do i get my money back"
    sim_order = rank_by(vector, q3)
    click_order = sorted(CLICKS[q3], key=CLICKS[q3].get, reverse=True)
    print(f"   query: {q3!r}")
    print(f"      by semantic similarity: {', '.join(sim_order[:3])}")
    print(f"      by what users clicked : {', '.join(click_order)}"
          f"   (A8 {CLICKS[q3]['A8']} clicks, A7 {CLICKS[q3]['A7']})")
    print("      A7 'Billing and invoices' is topically adjacent and nobody wants it")
    print("   -> similarity is a proxy for relevance and relevance is a proxy for")
    print("      usefulness. Click data measures the thing itself, which is why")
    print("      learning-to-rank on clicks beats tuning an embedding.\n")

    # ---------------------------------------------------------------- 5
    print("5. WHERE THE LLM EARNS ITS PLACE - offline")
    jobs = [("document enrichment", "summary, keywords, synthetic questions per doc",
             "recall on paraphrase queries"),
            ("query expansion dictionary", "mined offline from logs, applied as a lookup",
             "recall on tail queries, 0 ms at serve time"),
            ("training-pair generation", "query/document pairs to train the reranker",
             "ranking quality without waiting for click data"),
            ("evaluating relevance", "LLM-as-judge on a sample, offline",
             "a metric that is not click-through")]
    for name, what, buys in jobs:
        print(f"   {name:<28}{what}")
        print(f"   {'':<28}buys: {buys}")
    print(f"   -> every one runs hours before the query, and costs 0 ms at serve time.")
    print("      The LLM makes the index and the ranker better; it never touches the")
    print("      request. That is the whole design.\n")

    print("WHAT TO NOTICE")
    print("   * the budget is the question - one generation call is 4.5x all of it")
    print("   * hybrid is not a hedge: each retriever is blind exactly where the other")
    print("     sees, and site-search traffic is full of both query types")
    print("   * the cross-encoder is the highest-leverage 28 ms in the system")
    print("   * click data is the only signal that measures usefulness rather than")
    print("     resemblance")
    print("\nOK - scenario 23")


if __name__ == "__main__":
    main()
