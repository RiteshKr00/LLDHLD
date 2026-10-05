"""
Scenario 21 - text-to-SQL over a warehouse, without wrong numbers.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. 12,000 columns do not fit in a prompt -> schema retrieval
  2. the fan-out join: runs, returns a plausible number, silently wrong
  3. a semantic layer, because three teams have three revenues
  4. validation: read-only, columns exist, no DDL
  5. a cost guard, because one careless question scans four terabytes

Toy tables with real arithmetic. Seeded, so reruns match exactly.

What to notice: the model is the least interesting component here. Every
mechanic below is retrieval, a definition, a parser or a cost check - and the
worst failure (section 2) produces no error at all.
"""
import random
import re

random.seed(21)

TABLES, COLS_PER_TABLE = 300, 40
TOTAL_COLUMNS = TABLES * COLS_PER_TABLE
CTX_TOKENS = 128_000
TOKENS_PER_COLUMN = 14           # name, type, a short description


# --------------------------------------------------------------------------- #
# toy warehouse
# --------------------------------------------------------------------------- #
ORDERS = [  # id, customer, amount
    (1, "acme", 100.0), (2, "acme", 250.0), (3, "globex", 75.0), (4, "initech", 400.0)]
ITEMS = {   # order_id -> line items
    1: [30.0, 70.0], 2: [250.0], 3: [25.0, 25.0, 25.0], 4: [400.0]}
REFUNDS = {2: 50.0}


def revenue_gross():
    return sum(a for _, _, a in ORDERS)


def revenue_net():
    return revenue_gross() - sum(REFUNDS.values())


def revenue_recognised():
    """Finance: net, and only orders with all line items shipped. Order 3 is partial."""
    return sum(a for oid, _, a in ORDERS if oid != 3) - sum(REFUNDS.values())


DEFINITIONS = {
    "revenue (sales team)":  ("gross order value", revenue_gross),
    "revenue (finance)":     ("net of refunds, shipped only", revenue_recognised),
    "revenue (analytics)":   ("net of refunds", revenue_net),
}


def join_fanout():
    """The bug: joining orders to line items multiplies the order row per item."""
    total = 0.0
    for oid, _, amount in ORDERS:
        for _ in ITEMS[oid]:
            total += amount            # amount counted once PER LINE ITEM
    return total


def join_correct():
    """Aggregate the child table first, then join. Or just do not join at all."""
    return sum(a for _, _, a in ORDERS)


# --------------------------------------------------------------------------- #
# 4. validation
# --------------------------------------------------------------------------- #
KNOWN = {"orders": {"id", "customer", "amount", "created_at"},
         "line_items": {"order_id", "sku", "price"}}
FORBIDDEN = re.compile(r"\b(delete|update|insert|drop|alter|truncate|create|grant|copy)\b", re.I)


def aliases(sql):
    """Map alias -> real table, so o.revenue resolves to orders.revenue.

    Without this the alias check passes anything qualified by a known alias,
    which is exactly the hallucinated-column case it exists to catch.
    """
    out = {}
    for tbl, alias in re.findall(r"\b(?:from|join)\s+(\w+)(?:\s+(?:as\s+)?(\w+))?",
                                 sql, re.I):
        if tbl.lower() in ("select", "where"):
            continue
        out[tbl] = tbl
        if alias and alias.lower() not in ("where", "on", "join", "group", "order", "limit"):
            out[alias] = tbl
    return out


def validate(sql):
    """Returns a list of reasons to refuse. Empty list means it may run."""
    bad = []
    if FORBIDDEN.search(sql):
        bad.append("not read-only: " + FORBIDDEN.search(sql).group(0).upper())
    if ";" in sql.strip().rstrip(";"):
        bad.append("multiple statements")
    amap = aliases(sql)
    for qual, col in re.findall(r"\b(\w+)\.(\w+)\b", sql):
        tbl = amap.get(qual)
        if tbl is None:
            bad.append(f"unknown table or alias {qual}")
        elif tbl not in KNOWN:
            bad.append(f"unknown table {tbl}")
        elif col not in KNOWN[tbl]:
            bad.append(f"unknown column {tbl}.{col}")
    if not re.search(r"\blimit\b", sql, re.I):
        bad.append("no LIMIT (one is injected)")
    return bad


# --------------------------------------------------------------------------- #
# 5. cost guard
# --------------------------------------------------------------------------- #
BYTES_PER_POUND = 5 * 1024 ** 4 / 25.0        # ~£25 per 5TB scanned
LIMIT_BYTES = 200 * 1024 ** 3                 # 200 GB


def explain(sql):
    """Stand-in for EXPLAIN: bytes the planner says it will scan."""
    if "created_at" in sql:
        return 8 * 1024 ** 3                  # partition pruned
    return 4 * 1024 ** 4                      # full table scan


def cost_of(b):
    return b / BYTES_PER_POUND


def main():
    print("\nTEXT-TO-SQL OVER A WAREHOUSE")
    print("=" * 74)

    # ---------------------------------------------------------------- 1
    print("1. THE SCHEMA DOES NOT FIT")
    need = TOTAL_COLUMNS * TOKENS_PER_COLUMN
    print(f"   {TABLES} tables x {COLS_PER_TABLE} columns = {TOTAL_COLUMNS:,} columns")
    print(f"   at ~{TOKENS_PER_COLUMN} tokens each -> {need:,} tokens against a "
          f"{CTX_TOKENS:,}-token window")
    print(f"   over budget by {need / CTX_TOKENS:.1f}x")
    retrieved = 6
    print(f"   retrieve the {retrieved} relevant tables instead -> "
          f"{retrieved * COLS_PER_TABLE * TOKENS_PER_COLUMN:,} tokens "
          f"({retrieved * COLS_PER_TABLE * TOKENS_PER_COLUMN / CTX_TOKENS:.1%} of the window)")
    assert need > CTX_TOKENS
    print("   -> this is a RAG problem over schema before it is a prompting problem.")
    print("      Embed table and column descriptions; retrieve, then generate.\n")

    # ---------------------------------------------------------------- 2
    print("2. THE FAN-OUT JOIN - runs, plausible, wrong")
    wrong, right = join_fanout(), join_correct()
    print(f"   SELECT SUM(o.amount) FROM orders o JOIN line_items li ON li.order_id = o.id")
    print(f"      -> {wrong:,.2f}   (no error, no warning)")
    print(f"   correct total                                    -> {right:,.2f}")
    print(f"   inflated by {wrong / right - 1:.0%}, because an order with "
          f"{max(len(v) for v in ITEMS.values())} line items is counted "
          f"{max(len(v) for v in ITEMS.values())} times")
    assert wrong > right
    print("   -> THIS is the failure that matters. An error is recoverable because")
    print("      somebody sees it. A plausible wrong number goes into a board deck.")
    print("      Defences: verified exemplar joins, showing the SQL and the row count,")
    print("      and a semantic layer that owns the join so the model never writes it.\n")

    # ---------------------------------------------------------------- 3
    print("3. THE SEMANTIC LAYER - 'revenue' is three numbers")
    for name, (desc, fn) in DEFINITIONS.items():
        print(f"   {name:<24}{fn():>10,.2f}   {desc}")
    vals = {fn() for _, fn in DEFINITIONS.values()}
    assert len(vals) == 3
    print(f"   -> three defensible answers to one English word. Without a metric store the")
    print("      model picks one at random per query, so the SAME question gives different")
    print("      numbers on different days. Highest-value component in the design, and the")
    print("      one most candidates never mention.\n")

    # ---------------------------------------------------------------- 4
    print("4. VALIDATION - before execution, not after")
    cases = [
        ("SELECT SUM(o.amount) FROM orders o LIMIT 100", "legitimate"),
        ("SELECT o.revenue FROM orders o LIMIT 10", "hallucinated column"),
        ("DELETE FROM orders WHERE customer = 'test'", "the obvious attack"),
        ("SELECT 1 FROM orders; DROP TABLE orders", "stacked statement"),
        ("SELECT o.amount FROM orders o", "no LIMIT"),
    ]
    for sql, label in cases:
        bad = validate(sql)
        verdict = "ALLOW" if not bad else "REFUSE"
        print(f"   {verdict:<7}{label:<22}{('; '.join(bad) or 'passes all checks')}")
    assert validate(cases[0][0]) == []
    assert any("DELETE" in b for b in validate(cases[2][0]))
    assert any("unknown column" in b for b in validate(cases[1][0]))
    print("   -> parse it, do not regex it, in production. The point stands either way:")
    print("      the model's output is an UNTRUSTED STRING and gets treated like one.\n")

    # ---------------------------------------------------------------- 5
    print("5. COST GUARD - one missing WHERE clause, 4 TB scanned")
    for sql, label in (("SELECT SUM(amount) FROM orders", "no partition filter"),
                       ("SELECT SUM(amount) FROM orders WHERE created_at > '2026-01-01'",
                        "partition pruned")):
        b = explain(sql)
        over = b > LIMIT_BYTES
        print(f"   {label:<22}{b / 1024 ** 3:>9,.0f} GB  £{cost_of(b):>8,.2f}   "
              f"{'REFUSE, ask for a date range' if over else 'run it'}")
    assert explain("SELECT SUM(amount) FROM orders") > LIMIT_BYTES
    print("   -> EXPLAIN before execute, refuse above a byte threshold, inject a LIMIT.")
    print("      A curious user with a text box is a denial-of-wallet vector.\n")

    print("WHAT TO NOTICE")
    print("   * the model is the least interesting component - retrieval, a definition,")
    print("     a parser and a cost check do the work")
    print("   * section 2 is the one that matters: no error, plausible number, wrong")
    print("   * run under the USER's credentials, never a service account, or the")
    print("     feature is a privilege-escalation path with a friendly interface")
    print("   * show the SQL and the row count - an unverifiable number is not an answer")
    print("\nOK - scenario 21")


if __name__ == "__main__":
    main()
