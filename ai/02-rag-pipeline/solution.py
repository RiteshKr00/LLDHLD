"""
02 - RAG end to end, and why chunking decides quality.

    python3 solution.py

The same corpus chunked three ways, the same questions, measured recall.
Then the two things that save you at query time: a relevance floor and
hybrid retrieval for exact tokens.
"""
import math, re
from collections import Counter

DOCS = {
    "notice": "Notice period. Employees serving in a permanent role must give "
              "90 days written notice. Probationary employees give 30 days.",
    "form16": "Form 16 is issued by 15 June each year. Form 26AS is a separate "
              "statement downloaded from the tax portal.",
    "leave":  "Annual leave is 24 days. Unused leave lapses on 31 March and "
              "cannot be carried forward beyond 5 days.",
}
QUESTIONS = [
    ("how much notice for a permanent employee", "notice", "90 days"),
    ("when is Form 16 issued", "form16", "15 June"),
    ("how many leave days carry forward", "leave", "5 days"),
]


# A real embedding model learns to discount these. A bag-of-words stand-in
# does not, so an out-of-corpus question would score highly on shared
# stopwords alone - which is exactly the false-confidence a relevance floor
# is meant to catch, so it has to be removed for the demo to be honest.
STOP = {"a", "an", "the", "is", "are", "was", "for", "of", "to", "in", "on",
        "and", "or", "what", "how", "when", "much", "many", "does", "do",
        "can", "i", "my", "be", "by", "each", "from", "that", "this", "it"}


def toks(s):
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP]


def embed(text):
    """A bag-of-words stand-in for an embedding: same geometry, no model."""
    c = Counter(toks(text))
    n = math.sqrt(sum(v * v for v in c.values())) or 1.0
    return {k: v / n for k, v in c.items()}


def cosine(a, b):
    return sum(v * b.get(k, 0.0) for k, v in a.items())


# --------------------------------------------------------------------------- #
# three chunking strategies
# --------------------------------------------------------------------------- #
def chunk_whole(docs):
    return [(k, v) for k, v in docs.items()]


def chunk_tiny(docs, size=4):
    out = []
    for k, v in docs.items():
        w = v.split()
        for i in range(0, len(w), size):
            out.append((k, " ".join(w[i:i + size])))          # no overlap
    return out


def chunk_sentences(docs, overlap=1):
    out = []
    for k, v in docs.items():
        sents = [s.strip() for s in v.split(".") if s.strip()]
        for i, s in enumerate(sents):
            window = sents[max(0, i - overlap):i + 1]         # overlap keeps context
            out.append((k, ". ".join(window)))
    return out


def retrieve(chunks, q, k=2):
    qe = embed(q)
    scored = sorted(((cosine(qe, embed(c)), d, c) for d, c in chunks), reverse=True)
    return scored[:k]


def bm25ish(chunks, q, k=2):
    """Keyword scoring - catches exact tokens embeddings blur."""
    qt = set(toks(q))
    scored = sorted(((len(qt & set(toks(c))), d, c) for d, c in chunks), reverse=True)
    return scored[:k]


def answer_recall(chunks, use_hybrid=False):
    hits = 0
    for q, want_doc, want_fact in QUESTIONS:
        got = retrieve(chunks, q)
        if use_hybrid:
            got = got + bm25ish(chunks, q)
        if any(want_fact in c for _, _, c in got):
            hits += 1
    return hits / len(QUESTIONS)


if __name__ == "__main__":
    print("  strategy              chunks   answer-recall")
    print("  " + "-" * 46)
    for name, chunks in (("whole document", chunk_whole(DOCS)),
                         ("tiny, no overlap", chunk_tiny(DOCS)),
                         ("sentence + overlap", chunk_sentences(DOCS))):
        print(f"  {name:<20} {len(chunks):>6}   {answer_recall(chunks):>12.0%}")

    tiny, sent = chunk_tiny(DOCS), chunk_sentences(DOCS)
    assert answer_recall(sent) >= answer_recall(tiny)

    print("\n  the exact-token problem")
    q = "when is Form 16 issued"
    v = retrieve(sent, q, k=1)[0]
    b = bm25ish(sent, q, k=1)[0]
    print(f"    vector top-1 : {v[2][:52]}...")
    print(f"    bm25   top-1 : {b[2][:52]}...")
    print("    -> 'Form 16' and 'Form 26AS' are semantically near-identical and")
    print("       operationally different. That is why hybrid exists.")

    print("\n  the relevance floor")
    FLOOR = 0.15
    for q in ("how much notice for a permanent employee",
              "what is the company pension scheme"):     # not in the corpus
        top = retrieve(sent, q, k=1)[0]
        verdict = "answer" if top[0] >= FLOOR else "REFUSE - not in corpus"
        print(f"    score {top[0]:.3f}  {verdict:<22} <- {q[:38]}")
    assert retrieve(sent, "what is the company pension scheme", 1)[0][0] < FLOOR
    print("""
  what to notice
  --------------
  * tiny chunks with no overlap split facts across boundaries, so neither
    half retrieves. Sentence chunks WITH overlap recover them.
  * whole documents score well here only because the corpus is tiny - at
    real scale the embedding blurs across every topic in the document.
  * without a relevance floor, an out-of-corpus question still returns a
    top-1 chunk and the model answers from general knowledge, confidently
    inventing company policy. The floor is what turns that into a refusal.
""")
    print("OK - topic 02")
