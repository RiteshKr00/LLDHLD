"""
Scenario 30 - one answer from policy documents and a live database.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. embedding database rows: staleness, and why you cannot SUM a vector search
  2. routing accuracy dominating end-to-end quality
  3. composing two sources with per-source attribution
  4. disagreement between a document and the system of record
  5. partial failure - what the answer looks like when one source is down

Seeded, so reruns match exactly.

What to notice: routing is the whole ballgame in section 2. No amount of
retrieval quality on either side rescues a question sent to the wrong source.
"""
import random

random.seed(30)

ROWS = 2_000_000
REINDEX_MINUTES = 45


# --------------------------------------------------------------------------- #
# 1. the embedded-rows trap
# --------------------------------------------------------------------------- #
ORDERS = [{"id": i, "customer": random.choice(["acme", "globex", "initech"]),
           "amount": round(random.uniform(20, 900), 2),
           "status": random.choice(["open", "shipped", "refunded"])}
          for i in range(1, 501)]


def sql_sum(rows, customer):
    return round(sum(r["amount"] for r in rows if r["customer"] == customer), 2)


def vector_topk(rows, customer, k=10):
    """A similarity search returns the k most similar rows. That is all it can do."""
    hits = [r for r in rows if r["customer"] == customer]
    return hits[:k]


def staleness(minutes_since_index):
    """Rows written since the last index build are invisible to a vector search."""
    writes_per_min = 140
    return writes_per_min * minutes_since_index


# --------------------------------------------------------------------------- #
# 2. routing
# --------------------------------------------------------------------------- #
QUESTIONS = [
    ("what is the refund window", "docs"),
    ("how much did acme spend last quarter", "db"),
    ("is acme past their refund window on order 4471", "both"),
    ("what counts as a damaged item", "docs"),
    ("how many orders are open", "db"),
    ("which customers exceeded the credit policy limit", "both"),
]


def route(question, true_source, accuracy):
    if random.random() < accuracy:
        return true_source
    return random.choice([s for s in ("docs", "db", "both") if s != true_source])


def answer_quality(routed, true_source, retrieval_quality=0.92):
    """Right source: retrieval quality decides. Wrong source: nothing rescues it."""
    if routed == true_source:
        return retrieval_quality
    if true_source == "both" and routed in ("docs", "db"):
        return 0.35                      # half the answer, presented as whole
    return 0.05


def end_to_end(routing_acc, retrieval_quality, trials=400):
    total = 0.0
    for _ in range(trials):
        q, src = random.choice(QUESTIONS)
        total += answer_quality(route(q, src, routing_acc), src, retrieval_quality)
    return total / trials


# --------------------------------------------------------------------------- #
# 4. disagreement
# --------------------------------------------------------------------------- #
def compose(doc_claim, db_claim, tolerate=True):
    if doc_claim == db_claim:
        return f"{doc_claim} (both sources agree)"
    if not tolerate:
        return f"{doc_claim}"            # silently picks one
    return (f"CONFLICT - policy document says {doc_claim}; "
            f"the system of record says {db_claim}. Both shown.")


def main():
    print("\nRAG OVER STRUCTURED AND UNSTRUCTURED DATA")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. THE EMBEDDED-ROWS TRAP")
    true_total = sql_sum(ORDERS, "acme")
    topk = vector_topk(ORDERS, "acme")
    vec_total = round(sum(r["amount"] for r in topk), 2)
    n_acme = sum(1 for r in ORDERS if r["customer"] == "acme")
    print(f"   'how much did acme spend?'")
    print(f"      SQL over {n_acme} matching rows      -> {true_total:>10,.2f}")
    print(f"      sum of the top-{len(topk)} vector hits  -> {vec_total:>10,.2f}   "
          f"({vec_total / true_total:.0%} of the answer)")
    assert vec_total < true_total * 0.5
    print(f"   -> a similarity search returns the k most SIMILAR rows. It has no notion")
    print("      of ALL. You cannot SUM a vector search, you cannot GROUP BY one, and")
    print("      you cannot JOIN one.")
    print()
    stale = staleness(REINDEX_MINUTES)
    print(f"      and freshness: {REINDEX_MINUTES} minutes since the last index build")
    print(f"      = {stale:,} writes invisible to the vector index")
    assert stale > 1000
    print("      A database answer must be current. Query it live.\n")

    # ---------------------------------------------------------------- 2
    print("2. ROUTING DOMINATES EVERYTHING")
    print(f"   {'routing accuracy':>18}{'retrieval 0.80':>18}{'retrieval 0.92':>18}")
    for racc in (1.00, 0.90, 0.80, 0.60):
        lo = end_to_end(racc, 0.80)
        hi = end_to_end(racc, 0.92)
        print(f"   {racc:>18.0%}{lo:>18.2f}{hi:>18.2f}")
    perfect_route_bad_retr = end_to_end(1.00, 0.80)
    bad_route_good_retr = end_to_end(0.80, 0.92)
    assert perfect_route_bad_retr > bad_route_good_retr
    print(f"   -> perfect routing with WEAK retrieval ({perfect_route_bad_retr:.2f}) beats")
    print(f"      80% routing with strong retrieval ({bad_route_good_retr:.2f}).")
    print("      A question sent to the wrong source is not degraded, it is unanswerable")
    print("      - so spend on the router before you spend on either retriever.\n")

    # ---------------------------------------------------------------- 3
    print("3. COMPOSITION WITH PER-SOURCE ATTRIBUTION")
    blended = "Acme is past their refund window."
    attributed = (
        "Acme's order 4471 shipped on 3 March [database, live].\n"
        "      The refund window is 30 days from shipment "
        "[policy doc v4, section 2.1].\n"
        "      Today is 8 September, so the window closed on 2 April.")
    print(f"   blended:")
    print(f"      {blended}")
    print(f"   attributed per source:")
    print(f"      {attributed}")
    assert "[database" in attributed and "[policy doc" in attributed
    print("   -> the blended version is unverifiable: a reader cannot tell which half")
    print("      came from where, so they cannot check either half. Attribution per")
    print("      source is what makes a two-source answer usable at all.\n")

    # ---------------------------------------------------------------- 4
    print("4. WHEN THE SOURCES DISAGREE")
    print(f"   silently picking one : {compose('30 days', '45 days', tolerate=False)}")
    print(f"   surfacing both       : {compose('30 days', '45 days', tolerate=True)}")
    assert "CONFLICT" in compose("30 days", "45 days", True)
    print("   -> they WILL disagree, because a policy document and a system of record")
    print("      drift apart. The model must not adjudicate: it does not know whether")
    print("      the policy is aspirational or the database is misconfigured. Surface")
    print("      both, and route the conflict to whoever owns the discrepancy.\n")

    # ---------------------------------------------------------------- 5
    print("5. PARTIAL FAILURE")
    cases = [("both available", True, True,
              "full answer, both attributions"),
             ("database down", True, False,
              "policy answer + 'live order data unavailable' - NOT a guess"),
             ("document store down", False, True,
              "the figures + 'policy text unavailable, not applying the rule'"),
             ("both down", False, False, "refuse, and say which")]
    print(f"   {'situation':<24}{'behaviour'}")
    for name, docs_ok, db_ok, behaviour in cases:
        print(f"   {name:<24}{behaviour}")
    print("   -> a two-source system fails partially far more often than it fails")
    print("      completely, so partial failure is the normal case and needs a designed")
    print("      answer. Never let a missing source become a silent omission: an answer")
    print("      built on half the evidence must say so.\n")

    print("WHAT TO NOTICE")
    print("   * you cannot SUM a vector search - aggregation is the thing embeddings")
    print("     structurally cannot do, and it is most of what people ask a database")
    print("   * routing dominates: perfect routing with weak retrieval beats the reverse")
    print("   * per-source attribution is not presentation, it is what makes the answer")
    print("     checkable")
    print("   * the model must never adjudicate a conflict between a policy and a")
    print("     system of record")
    print("\nOK - scenario 30")


if __name__ == "__main__":
    main()
