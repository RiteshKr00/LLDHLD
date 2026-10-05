"""
Scenario 25 - making scanned pages, tables and charts answerable.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. the recall ceiling a text-only pipeline cannot exceed
  2. a table flattened into prose, and why the numbers stop meaning anything
  3. vision-at-query-time vs extracting structure once at ingest
  4. OCR confidence, and silently indexing garbage
  5. numeric grounding: refusing to state a figure that is not in a table

Toy documents, real arithmetic. Seeded, so reruns match exactly.

What to notice: section 1 is a CEILING, not a quality gap. No model improves
past it, because the information is not in the text layer at all.
"""
import random
import re

random.seed(25)

PAGES = 400_000
QUERIES_PER_MONTH = 120_000
VISION_PER_PAGE = 0.012          # £ per page through a vision model
TEXT_EMBED_PER_PAGE = 0.00004


# --------------------------------------------------------------------------- #
# where the salient numbers live
# --------------------------------------------------------------------------- #
LOCATION = {"body text": 0.70, "tables": 0.22, "figures": 0.08}


def recall_ceiling(covered):
    return sum(v for k, v in LOCATION.items() if k in covered)


# --------------------------------------------------------------------------- #
# 2. a table, and the same table flattened
# --------------------------------------------------------------------------- #
TABLE = {
    "caption": "Table 3: Revenue by region, FY2025 (£m)",
    "columns": ["Region", "Q1", "Q2", "Q3", "Q4"],
    "rows": [["EMEA", 12.4, 13.1, 11.8, 15.2],
             ["Americas", 21.0, 19.7, 22.4, 24.9],
             ["APAC", 8.3, 9.1, 9.9, 10.4]],
}


def flatten(t):
    """What a text-only extractor produces: reading order, structure gone."""
    out = [t["caption"], " ".join(t["columns"])]
    for r in t["rows"]:
        out.append(" ".join(str(c) for c in r))
    return "  ".join(out)


def structured_lookup(t, region, quarter):
    ci = t["columns"].index(quarter)
    for r in t["rows"]:
        if r[0] == region:
            return r[ci]
    return None


def flat_lookup(text, region, quarter):
    """Recover a cell from flattened text: you cannot, without the grid.

    The number is present. What is gone is which column it belongs to, and a
    number without its column is not an answer.
    """
    m = re.search(re.escape(region) + r"((?:\s+[\d.]+)+)", text)
    if not m:
        return None
    nums = m.group(1).split()
    return {"candidates": nums, "which_column": "unknown"}


# --------------------------------------------------------------------------- #
# 4. OCR confidence
# --------------------------------------------------------------------------- #
def ocr_page(quality):
    """Returns (text, mean confidence). Poor scans produce confident nonsense."""
    if quality == "clean":
        return "Total revenue for the period was 41.2 million pounds", 0.97
    if quality == "faxed":
        return "Tota1 revenne fnr the periud was 4l.2 rnillion pounds", 0.71
    return "1 |  ,, . ~ l1 1", 0.34


def main():
    print("\nMULTIMODAL DOCUMENT PIPELINE")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. THE CEILING - not a quality gap")
    print(f"   where the salient numbers actually live:")
    for k, v in LOCATION.items():
        print(f"      {k:<12}{v:>6.0%}")
    text_only = recall_ceiling({"body text"})
    with_tables = recall_ceiling({"body text", "tables"})
    full = recall_ceiling(set(LOCATION))
    print(f"\n   {'pipeline':<34}{'ceiling on numeric recall':>26}")
    print(f"   {'text layer only':<34}{text_only:>25.0%}")
    print(f"   {'+ table extraction':<34}{with_tables:>25.0%}")
    print(f"   {'+ figure captioning':<34}{full:>25.0%}")
    assert text_only < 0.75 and full > 0.99
    print(f"   -> a text-only pipeline cannot answer {1 - text_only:.0%} of numeric")
    print("      questions, and no model fixes that, because the information is not in")
    print("      the text layer at all. This is the sentence that justifies the design.\n")

    # ---------------------------------------------------------------- 2
    print("2. A FLATTENED TABLE - the numbers survive, the meaning does not")
    flat = flatten(TABLE)
    print(f"   flattened: {flat[:96]}...")
    q = ("EMEA", "Q3")
    print(f"\n   question: {q[0]} revenue in {q[1]}")
    print(f"      structured lookup -> {structured_lookup(TABLE, *q)}")
    got = flat_lookup(flat, *q)
    print(f"      from flat text    -> candidates {got['candidates']}, "
          f"column {got['which_column']}")
    assert structured_lookup(TABLE, *q) == 11.8
    assert got["which_column"] == "unknown"
    print("   -> all four numbers are present and the model must guess which is Q3.")
    print("      It will guess confidently. A number without its row and column is")
    print("      not a number, and flattening is how a table becomes plausible noise.\n")

    # ---------------------------------------------------------------- 3
    print("3. VISION AT QUERY TIME vs STRUCTURE AT INGEST")
    pages_per_q = 6
    at_query = QUERIES_PER_MONTH * pages_per_q * VISION_PER_PAGE
    at_ingest = PAGES * VISION_PER_PAGE
    steady = PAGES * TEXT_EMBED_PER_PAGE
    print(f"   {'approach':<38}{'£ first month':>15}{'£ steady state':>16}")
    print(f"   {'vision model per query':<38}{at_query:>15,.0f}{at_query:>16,.0f}")
    print(f"   {'extract structure once at ingest':<38}{at_ingest:>15,.0f}{steady:>16,.0f}")
    assert at_query > at_ingest * 1.5
    print(f"   -> the per-query approach costs £{at_query:,.0f} EVERY month and adds")
    print("      seconds of latency to every question. Ingest is a one-off that")
    print("      amortises over every future query - and it produces STRUCTURE, which")
    print("      a page screenshot never does.\n")

    # ---------------------------------------------------------------- 4
    print("4. OCR CONFIDENCE - the difference between wrong and unknown")
    THRESH = 0.80
    for quality in ("clean", "faxed", "scribbled"):
        text, conf = ocr_page(quality)
        action = "index" if conf >= THRESH else "quarantine for review"
        print(f"   {quality:<11}conf {conf:.2f}   {action}")
        print(f"   {'':<11}{text[:58]}")
    _, c_faxed = ocr_page("faxed")
    assert c_faxed < THRESH
    print("   -> the faxed page produces text that LOOKS fine to an indexer and is")
    print("      wrong in every number. Without a confidence gate you index it, it")
    print("      retrieves, and the answer is confidently false. Below threshold the")
    print("      honest state is 'we cannot read this page', which is recoverable.\n")

    # ---------------------------------------------------------------- 5
    print("5. NUMERIC GROUNDING - refuse a figure that is not in a table")
    # keyed by what the claim is ABOUT, so an unsupported quantity is caught as
    # unsupported rather than silently compared against a different figure
    tables = {("EMEA", "Q3", "revenue"): 11.8, ("Americas", "Q3", "revenue"): 22.4}

    def check(region, quarter, quantity, value):
        source = tables.get((region, quarter, quantity))
        if source is None:
            return "REFUSE - no extracted table reports this quantity"
        if abs(source - value) < 0.001:
            return f"OK - matches the extracted cell ({source})"
        return f"BLOCK - table says {source}, answer says {value}"

    for region, quarter, quantity, value in (("EMEA", "Q3", "revenue", 11.8),
                                             ("EMEA", "Q3", "revenue", 13.1),
                                             ("EMEA", "Q3", "growth", 4.2)):
        print(f"   {region + ' ' + quarter + ' ' + quantity:<22}{value:>7}   "
              f"{check(region, quarter, quantity, value)}")
    assert check("EMEA", "Q3", "revenue", 11.8).startswith("OK")
    assert check("EMEA", "Q3", "revenue", 13.1).startswith("BLOCK")
    assert check("EMEA", "Q3", "growth", 4.2).startswith("REFUSE")
    print("   -> every number in an answer is checked against the extracted tables")
    print("      before it ships. This is cheap, deterministic, and it is the only")
    print("      defence that scales - you cannot eyeball 120,000 answers a month.\n")

    print("WHAT TO NOTICE")
    print("   * section 1 is a ceiling, not a gap: the information is not in the text")
    print("   * a flattened table keeps every digit and loses the only thing that made")
    print("     the digits mean something")
    print("   * pay at INGEST, once, and retrieve structure - not pixels - at query time")
    print("   * OCR confidence turns 'confidently wrong' into 'we cannot read this',")
    print("     which is the only one of the two you can recover from")
    print("\nOK - scenario 25")


if __name__ == "__main__":
    main()
