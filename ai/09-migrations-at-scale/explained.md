# Migrations — explained

**Your code:** `AI-Studio-ResumeFlow/backend/database.py:66` — `init_db()`, containing **10
`CREATE TABLE IF NOT EXISTS` and 63 `ADD COLUMN`** statements, run on every boot.
Full course: `~/projects/fastapi-crash-course/docs/03-alembic-migrations.md`.

---

## What you have, and the five things it gives up

`init_db()` is a hand-rolled migration runner. It is **correct** — because almost every
statement is `IF NOT EXISTS`, it's idempotent. What it gives up:

1. **No down path.** No inverse of `init_db()`. A bad schema deploy can't be rolled back.
2. **No version record.** Nothing stores what's been applied; correctness rests entirely on
   every statement being individually re-runnable, forever.
3. **Order is implicit.** It's a script — new statements must be appended, and reordering two
   silently changes behaviour.
4. **It only grows.** 63 `ADD COLUMN`s today, and none can ever be deleted because you don't
   know which databases have run them.
5. **Only the empty-table path is tested.** Tests run `init_db()` against a **scratch
   database**, so tables are always created fresh. The dangerous path — altering a
   *populated* table — is never exercised.

**Point 5 is the one that bites**, and it's your best honest-weakness answer anywhere on the
resume.

---

## The concrete bug hiding in your own code

`database.py:257-260`:

```sql
ALTER TABLE employee_records ALTER COLUMN record_month SET DEFAULT to_char(CURRENT_DATE,'YYYY-MM');
ALTER TABLE employee_records ALTER COLUMN record_month SET NOT NULL;
```

On an **empty** table: always succeeds. On a **populated** table: **fails**, if any existing
row has `record_month` NULL.

**Why:** `SET DEFAULT` applies to *future inserts*. It does **not** backfill existing rows.
This is the single most common migration misconception, and your test suite structurally
cannot catch it because the table is always new.

> *"Adding a NOT NULL column there would pass CI and fail in production."*

That sentence, said unprompted, is worth more than any passing metric.

---

## The correct shape: expand → migrate → contract

```python
def upgrade():
    # 1. EXPAND — nullable, so it cannot fail on existing rows
    op.add_column("employee_records", sa.Column("record_month", sa.String(7)))

    # 2. MIGRATE — backfill every existing row
    op.execute("""UPDATE employee_records
                     SET record_month = to_char(created_at, 'YYYY-MM')
                   WHERE record_month IS NULL""")

    # 3. CONTRACT — now the constraint can hold
    op.alter_column("employee_records", "record_month", nullable=False)
```

Three steps, in that order, always. And at a million rows:

- **batch the backfill** — one giant `UPDATE` holds locks and bloats WAL
- **`SET NOT NULL` takes an `ACCESS EXCLUSIVE` lock** while Postgres validates every row —
  that's downtime on a big table. The production pattern is to add a **`NOT VALID` check
  constraint** (instant, no full scan) then **`VALIDATE CONSTRAINT`** separately, which takes
  a weaker lock

Knowing the `NOT VALID` / `VALIDATE` two-step is the detail that marks you as having actually
done this rather than read about it.

---

## `RunPython` — what it's for and what breaks

It runs Python instead of DDL, for data backfills or logic DDL can't express. What goes wrong
at scale:

- **runs in one transaction by default** → a large backfill holds locks and can exhaust memory
- **must be batched, resumable and idempotent** — a migration that dies halfway must be safe
  to re-run
- **needs a reverse function** or the migration is one-way
- **never import your app models** — use `apps.get_model()` in Django, or `sa.text()` in
  Alembic. Models change; the migration must keep meaning what it meant the day it was written

Your resume mentions custom `RunPython` helpers for "MySQL edge cases" — those were conditional
index drops and FK-backed index conflicts, which standard operations couldn't express.

---

## Django migrations vs Alembic

| Django | Alembic |
|---|---|
| `makemigrations` | `alembic revision --autogenerate -m "..."` |
| `migrate` | `alembic upgrade head` |
| numbered files `0003_x.py` | hash-named, chained by `down_revision` |
| `django_migrations` table | `alembic_version` — one row, one column |
| `RunPython(fwd, rev)` | `op.execute(...)` in `upgrade`/`downgrade` |
| a **numbered sequence** per app | a **linked list** — can branch, needs explicit merge |

**The structural difference:** Django's numbering serialises everything, so branches can't
happen. Alembic makes them visible — two developers branching from one parent gives you
**multiple heads**, and `alembic merge` creates an empty revision with two parents to rejoin
the graph.

**What autogenerate cannot detect** — the list to know:

| Not detected | You get | Consequence |
|---|---|---|
| **column/table renames** | `drop_column` + `add_column` | **silent data loss** |
| `CheckConstraint` | nothing | constraint never created |
| indexes on expressions | nothing | missing index |
| type changes | nothing **unless** `compare_type=True` | silent drift |
| server-default changes | nothing **unless** `compare_server_default=True` | silent drift |

Both those flags default to **False**, which surprises everyone. And renames must be
hand-written — autogenerate emitting drop+add is the most dangerous default in the tool.

---

## Introducing migrations to a legacy database — the `stamp` answer

This is what ResumeFlow actually needs, and it's a common interview question:

1. Write **one baseline revision** whose `upgrade()` creates the schema exactly as `init_db()`
   leaves it today (autogenerate against a prod-like DB gets you most of the way).
2. On every **existing** database run `alembic stamp head` — writes the revision id into
   `alembic_version` **without executing anything**. You're asserting "this DB is already at
   that revision."
3. **Fresh** databases run `alembic upgrade head` normally and get the baseline.
4. From then on every change is a new revision, and `init_db()` shrinks instead of growing.

`stamp` is the whole trick.

---

## Why write `downgrade()` even if you never run it

It's the cheapest possible design review: **if you can't express the inverse, the migration is
destructive** — and you've learned that *before* deploying rather than after. Dropping a
column has no inverse because the data is gone. Discovering that while writing `downgrade()`
costs a minute; discovering it in production costs the data.

---

## One-line summary
> "Expand, migrate, contract — and `SET DEFAULT` doesn't backfill, which is why a NOT NULL
> addition passes on an empty test DB and fails on a populated one. That's the gap in my
> current setup: no down path, no version record, and the risky path untested."

## The trap answer to avoid
Saying "I add the column with a default and set NOT NULL." That's the bug. On a populated
table it fails, and if it doesn't fail it's because you got lucky with existing data.
