# Zero-downtime schema change on a live table

## 1. Numbers first
`employee_records` at **10M rows**, on a database serving 70 req/s. A naive
`ALTER TABLE ... SET NOT NULL` scans every row while holding an **ACCESS EXCLUSIVE lock** —
every read and write on that table blocks for the duration.

At 10M rows that is minutes. **Minutes of a fully blocked table is an outage**, not a
migration. That single fact drives everything below.

## 2. The lock is the whole problem
| Operation | Lock | Scans the table? |
|---|---|---|
| `ADD COLUMN` (nullable, no default) | brief ACCESS EXCLUSIVE | no — metadata only |
| `ADD COLUMN` **with a volatile default** | ACCESS EXCLUSIVE | **yes** — rewrites every row |
| `SET NOT NULL` | ACCESS EXCLUSIVE | **yes** |
| `ADD CONSTRAINT ... NOT VALID` | brief | **no** |
| `VALIDATE CONSTRAINT` | SHARE UPDATE EXCLUSIVE | yes, but **reads and writes continue** |
| `CREATE INDEX` | blocks writes | yes |
| `CREATE INDEX CONCURRENTLY` | doesn't block writes | yes, two passes, slower |

**The whole zero-downtime toolkit is in that table:** prefer the operations that either don't
scan, or scan under a weaker lock.

## 3. The safe sequence
```
1. ADD COLUMN nullable, no default          -- instant, metadata only
2. deploy code that WRITES the new column   -- but does not read it yet
3. backfill in BATCHES (e.g. 10k rows,      -- keeps transactions short,
   commit between, throttled)                  WAL bounded, replicas caught up
4. ADD CONSTRAINT ... CHECK (col IS NOT NULL) NOT VALID   -- instant
5. VALIDATE CONSTRAINT                      -- scans under a WEAK lock
6. deploy code that READS the new column
```

Steps 2 and 6 are why this is **six deploys-worth of care and not one migration**: the code
and the schema move in separate steps, and each step is safe on its own.

## 4. Batched backfill — the details that matter
- **Bounded batch size**, commit between. One 10M-row `UPDATE` holds locks and bloats WAL
- **Throttle** on replica lag, not on a fixed sleep — you are protecting the replicas
- **Resumable**: track the last id processed, so a failure at 60% resumes at 60%
- **Idempotent**: `WHERE col IS NULL`, so re-running is free
- Run it **outside** the migration transaction — a migration that takes an hour is a migration
  that can't be rolled back

## 5. Backward and forward compatibility
For the window between deploys, both old and new code run simultaneously. So:
**expand → migrate → contract** applies to *code* too. Never rename a column in one step —
add the new one, dual-write, backfill, switch reads, then drop. A rename is the classic
"passed staging, took production down" change.

## 6. Doing it across 500 tenants
Shared-schema means one migration hits everyone at once. Mitigations: run the backfill
**per tenant** so a failure is isolated and the blast radius is one tenant, and roll
progressively — smallest tenants first, so a problem surfaces cheaply.

## 7. Rollback
Steps 1–3 are reversible cheaply. Step 5 onwards is not — dropping a backfilled column loses
data. **Write `downgrade()` anyway**: if you can't express the inverse, the migration is
destructive, and you have learned that before deploying rather than after.

## 8. Observability during a migration
Replica lag (the throttle signal) · lock waits on the target table · batch progress and ETA ·
error rate on the affected endpoints · WAL generation rate. And know in advance **what your
abort condition is** — "replica lag over 30s, stop the backfill" is a decision to make before
you start, not during.
