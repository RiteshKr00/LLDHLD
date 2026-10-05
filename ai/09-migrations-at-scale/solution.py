"""
09 - why a NOT NULL migration passes CI and fails in production.

    python3 solution.py

A toy table that enforces constraints, run twice: once against an empty
schema (CI) and once against a populated one (production).
"""
class Table:
    """Just enough of a table to enforce the constraints that matter."""

    def __init__(self, name, cols):
        self.name, self.cols, self.rows = name, dict(cols), []
        self.not_null, self.defaults = set(), {}

    def insert(self, **row):
        for c in self.not_null:
            if row.get(c) is None and c not in self.defaults:
                raise ValueError(f"null in NOT NULL column {c}")
        for c, d in self.defaults.items():
            row.setdefault(c, d)
        self.rows.append(row)

    # ---- DDL ----
    def add_column(self, name, default=None, nullable=True):
        self.cols[name] = "text"
        for r in self.rows:
            r[name] = None                       # existing rows get NULL
        if default is not None:
            self.defaults[name] = default        # FUTURE inserts only
        if not nullable:
            self.set_not_null(name)

    def set_default(self, name, value):
        """The misconception: this does NOT backfill existing rows."""
        self.defaults[name] = value

    def set_not_null(self, name):
        bad = [r for r in self.rows if r.get(name) is None]
        if bad:
            raise RuntimeError(
                f"ALTER ... SET NOT NULL failed: {len(bad)} existing row(s) "
                f"have NULL in {name}")
        self.not_null.add(name)

    def backfill(self, name, fn):
        n = 0
        for r in self.rows:
            if r.get(name) is None:
                r[name] = fn(r); n += 1
        return n


def migration_WRONG(t):
    """What everyone writes. Passes on an empty table."""
    t.add_column("record_month")
    t.set_default("record_month", "2026-09")
    t.set_not_null("record_month")


def migration_RIGHT(t):
    """expand -> migrate -> contract."""
    t.add_column("record_month")                                  # 1 EXPAND
    n = t.backfill("record_month", lambda r: r["created"][:7])    # 2 MIGRATE
    t.set_not_null("record_month")                                # 3 CONTRACT
    t.set_default("record_month", "2026-09")
    return n


def fresh(populated):
    t = Table("employee_records", {"id": "int", "created": "text"})
    if populated:
        for i in range(3):
            t.insert(id=i, created=f"2026-0{i + 1}-15")
    return t


if __name__ == "__main__":
    print("  scenario                          WRONG migration        RIGHT migration")
    print("  " + "-" * 76)
    for label, populated in (("CI: scratch DB, 0 rows", False),
                             ("PROD: 3 existing rows", True)):
        outs = []
        for mig in (migration_WRONG, migration_RIGHT):
            t = fresh(populated)
            try:
                mig(t); outs.append("OK")
            except RuntimeError as ex:
                outs.append("FAILS: " + str(ex).split(":")[1].strip()[:22])
        print(f"  {label:<33} {outs[0]:<22} {outs[1]}")

    # assert exactly the asymmetry that makes this a good interview answer
    t = fresh(False); migration_WRONG(t)                    # passes
    t = fresh(True)
    try:
        migration_WRONG(t); raise AssertionError("should have failed")
    except RuntimeError:
        pass
    t = fresh(True); n = migration_RIGHT(t)                 # passes

    print(f"\n  the RIGHT migration backfilled {n} rows before adding the constraint.")
    print("""
  what to notice
  --------------
  * the WRONG migration passes CI and fails production. Not because CI is
    weak, but because a scratch DB CREATES TABLES FRESH - so the risky
    path (altering a POPULATED table) is never exercised.
  * SET DEFAULT applies to FUTURE inserts. It does not backfill. That single
    misconception is the bug.
  * the fix is three statements in order: expand (nullable) -> migrate
    (batched backfill) -> contract (add the constraint).
  * at a million rows, step 3 takes an ACCESS EXCLUSIVE lock while every
    row is validated. Production pattern: add the constraint NOT VALID
    (instant), then VALIDATE CONSTRAINT separately (weaker lock).
  * to test it: migrate to the PARENT revision, seed realistic data, then
    apply one revision. That is the shape your scratch-DB tests are missing.
""")
    print("OK - topic 09")
