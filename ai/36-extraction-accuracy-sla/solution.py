"""
Scenario 22 - document extraction against a 99% accuracy SLA.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. the compounding arithmetic hidden in "99% accuracy"
  2. confidence-routed review vs reviewing everything or nothing
  3. per-FIELD routing, so one uncertain field does not re-review nineteen
  4. deterministic validators, and cross-field consistency
  5. the aggregate that hides one broken field

Population: 50,000 invoices a month, 20 fields each. Seeded.

What to notice: no model improvement fixes section 1. The arithmetic says
human review is the architecture, not a fallback, and everything else in the
design exists to make the review queue affordable.
"""
import random

random.seed(22)

DOCS = 50_000
FIELDS = 20
PER_FIELD = 0.99
REVIEW_COST = 0.42          # £ per document reviewed, loaded
MODEL_COST = 0.011          # £ per document extracted


def doc_perfect(p_field, n=FIELDS):
    return p_field ** n


def field_acc_for(doc_target, n=FIELDS):
    return doc_target ** (1.0 / n)


# --------------------------------------------------------------------------- #
# per-field difficulty: the thing an aggregate hides
# --------------------------------------------------------------------------- #
FIELD_ACC = {
    "invoice_number": 0.998, "invoice_date": 0.995, "due_date": 0.990,
    "supplier_name": 0.994, "supplier_vat": 0.988, "currency": 0.999,
    "subtotal": 0.996, "tax_amount": 0.993, "total": 0.997,
    "po_number": 0.972, "payment_terms": 0.981, "bank_account": 0.9995,
    "bank_sort_code": 0.9993, "line_1_desc": 0.964, "line_1_qty": 0.985,
    "line_1_price": 0.986, "line_2_desc": 0.961, "line_2_qty": 0.984,
    "line_2_price": 0.985, "handwritten_note": 0.782,
}


def confidence(correct):
    """Calibrated-ish: confident when right, usually hesitant when wrong.

    The spread matters more than the mean. A confidence signal whose noise is
    large relative to the error rate flags something in almost every document,
    which collapses 'route by confidence' into 'review everything'.
    """
    spread = 0.02 if correct else 0.15
    return max(0.0, 1.0 - abs(random.gauss(0, spread)))


def simulate(n_docs, route_per_field, floor=0.95):
    """Returns (docs touched by a reviewer, fields reviewed, escaped errors)."""
    touched = fields_reviewed = escaped = 0
    for _ in range(n_docs):
        doc_touched = False
        for f, acc in FIELD_ACC.items():
            correct = random.random() < acc
            if confidence(correct) < floor:
                fields_reviewed += 1
                doc_touched = True
            elif not correct:
                escaped += 1
        if doc_touched:
            touched += 1
            if not route_per_field:
                fields_reviewed += FIELDS - 1     # whole document re-checked
    return touched, fields_reviewed, escaped


# --------------------------------------------------------------------------- #
# 4. deterministic validators
# --------------------------------------------------------------------------- #
def validators(doc):
    """Things arithmetic can prove, so the model need not be trusted on them."""
    bad = []
    if abs((doc["subtotal"] + doc["tax_amount"]) - doc["total"]) > 0.005:
        bad.append("subtotal + tax != total")
    if doc["line_total"] and abs(doc["line_total"] - doc["subtotal"]) > 0.005:
        bad.append("line items do not sum to subtotal")
    if doc["due_date"] < doc["invoice_date"]:
        bad.append("due before invoice date")
    if doc["vat"] and not (7 <= len(doc["vat"]) <= 14):
        bad.append("VAT number wrong length")
    return bad


def main():
    print("\nDOCUMENT EXTRACTION AGAINST A 99% SLA")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. THE ARITHMETIC HIDDEN IN '99% ACCURACY'")
    print(f"   {'per-field':>11}{'docs perfect':>15}{'bad docs / month':>19}")
    for p in (0.99, 0.995, 0.999, 0.9995):
        dp = doc_perfect(p)
        print(f"   {p:>11.4f}{dp:>14.1%}{int(DOCS * (1 - dp)):>19,}")
    need = field_acc_for(0.99)
    print(f"\n   {FIELDS} fields x {PER_FIELD:.0%} each = {doc_perfect(PER_FIELD):.0%} "
          f"of documents perfect")
    print(f"   -> {int(DOCS * (1 - doc_perfect(PER_FIELD))):,} imperfect documents a month.")
    print(f"      For 99% PER DOCUMENT you need {need:.4f} per field, which no model")
    print("      does unaided. So human review is not a fallback, it is the")
    print("      architecture - and the rest of the design exists to make it affordable.\n")
    assert doc_perfect(PER_FIELD) < 0.83
    assert need > 0.9994

    # ---------------------------------------------------------------- 2
    print("2. ROUTING - review everything, nothing, or by confidence")
    sample = 3_000
    touched, freviewed, escaped = simulate(sample, route_per_field=True)
    scale = DOCS / sample
    options = [
        ("review nothing", 0, int(DOCS * (1 - doc_perfect(PER_FIELD))), DOCS * MODEL_COST),
        ("review everything", DOCS, 0, DOCS * (MODEL_COST + REVIEW_COST)),
        ("confidence-routed", int(touched * scale), int(escaped * scale),
         DOCS * MODEL_COST + touched * scale * REVIEW_COST),
    ]
    print(f"   {'strategy':<20}{'docs reviewed':>15}{'errors escaping':>18}{'£/month':>11}")
    for name, rev, esc, cost in options:
        print(f"   {name:<20}{rev:>15,}{esc:>18,}{cost:>11,.0f}")
    assert options[2][3] < options[1][3]
    caught = 1 - options[2][2] / options[0][2]
    print(f"   -> reviewing everything costs {options[1][3] / options[2][3]:.1f}x the routed "
          f"option. Routing catches")
    print(f"      {caught:.0%} of errors while touching "
          f"{options[2][1] / DOCS:.0%} of documents. The residual is not")
    print("      a bug to fix, it is the number you negotiate the SLA around.\n")

    # ---------------------------------------------------------------- 3
    print("3. PER-FIELD vs PER-DOCUMENT ROUTING")
    _, per_field_work, _ = simulate(sample, route_per_field=True)
    _, per_doc_work, _ = simulate(sample, route_per_field=False)
    print(f"   fields a reviewer must look at, per {sample:,} documents:")
    print(f"      per-field routing    {per_field_work:>8,}")
    print(f"      per-document routing {per_doc_work:>8,}")
    assert per_doc_work > per_field_work * 3
    print(f"   -> {per_doc_work / per_field_work:.1f}x the reviewer time for the same")
    print("      accuracy. Confidence belongs on the FIELD; re-reading nineteen correct")
    print("      fields because the twentieth was uncertain is the whole difference")
    print("      between a review queue and a department.\n")

    # ---------------------------------------------------------------- 4
    print("4. VALIDATORS - do not spend model confidence on arithmetic")
    docs = [
        {"subtotal": 100.0, "tax_amount": 20.0, "total": 120.0, "line_total": 100.0,
         "invoice_date": 20260101, "due_date": 20260131, "vat": "GB123456789"},
        {"subtotal": 100.0, "tax_amount": 20.0, "total": 100.0, "line_total": 100.0,
         "invoice_date": 20260101, "due_date": 20260131, "vat": "GB123456789"},
        {"subtotal": 100.0, "tax_amount": 20.0, "total": 120.0, "line_total": 88.0,
         "invoice_date": 20260201, "due_date": 20260115, "vat": "GB12"},
    ]
    for i, d in enumerate(docs, 1):
        bad = validators(d)
        print(f"   document {i}: {('; '.join(bad)) if bad else 'all invariants hold'}")
    assert validators(docs[0]) == []
    assert len(validators(docs[2])) == 3
    print("   -> every one of these is provable without a model. Catching them")
    print("      deterministically means the review queue holds only the genuinely")
    print("      ambiguous, which is what makes the queue affordable.\n")

    # ---------------------------------------------------------------- 5
    print("5. THE AGGREGATE THAT HIDES A BROKEN FIELD")
    agg = sum(FIELD_ACC.values()) / len(FIELD_ACC)
    errs = {f: DOCS * (1 - a) for f, a in FIELD_ACC.items()}
    total_err = sum(errs.values())
    worst = sorted(FIELD_ACC.items(), key=lambda kv: kv[1])[:4]
    print(f"   aggregate field accuracy: {agg:.2%}  - reads as a near miss you could tune away")
    print(f"   {'worst fields':<20}{'accuracy':>10}{'errors / month':>17}{'share of all':>14}")
    for f, a in worst:
        print(f"   {f:<20}{a:>10.1%}{int(errs[f]):>17,}{errs[f] / total_err:>13.0%}")
    share = errs["handwritten_note"] / total_err
    assert share > 0.4 and min(FIELD_ACC.values()) < 0.80
    print(f"\n   one field is {share:.0%} of every error in the system - "
          f"more than the next three combined.")
    print("   -> the aggregate makes this look like a broad 1.3-point shortfall to be")
    print("      closed with a better model. It is one field that should never have been")
    print("      promised. Report per field, always. And note bank_account sits at 99.95%")
    print("      because it is VALIDATED, not because it is easy - the fields that matter")
    print("      most should be the ones you refuse to trust a model on.\n")

    print("WHAT TO NOTICE")
    print("   * no model improvement fixes section 1 - it is arithmetic, not quality")
    print("   * per-FIELD confidence is what keeps the review queue from becoming a")
    print("     department; per-document routing costs several times more for the same")
    print("     accuracy")
    print("   * validators are free accuracy: never spend model confidence on something")
    print("     addition can prove")
    print("   * an aggregate accuracy number is the enemy - it is how one broken field")
    print("     survives a quarter")
    print("\nOK - scenario 22")


if __name__ == "__main__":
    main()
