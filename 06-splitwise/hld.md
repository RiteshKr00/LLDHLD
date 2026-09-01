# Splitwise — HLD (quick)

Companion to [`solution.py`](solution.py) (the single-process engine).
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).

> **Framing:** the QPS here is *small* — this is not a scale problem, it's a **correctness-with-money**
> problem. Say that out loud; reaching for Cassandra and 50 microservices would be the wrong instinct.
> The one genuinely interesting tension: **the LLD's elegant "derive balances" choice does not survive
> production unchanged.**

## 1. Scope
- **Functional:** add expense (split types) · view balances · simplify debts · record settlement · group activity feed · notifications.
- **Non-functional:** **money correctness above all** (never lose/duplicate a rupee) · strong consistency on the ledger · **idempotent writes** (mobile retries are guaranteed) · offline-capable mobile clients.

## 2. Estimate — and why it matters that it's small
- 50M users, ~10M DAU. ~1 expense/user/day → 10M writes/day ≈ **~120 writes/s**.
- Balance checks ~5/user/day → 50M reads/day ≈ **~600 reads/s**. Roughly **5:1 read-heavy**, but both numbers are tiny.
- Storage: 10M expenses/day × ~500B ≈ 5GB/day → **~2TB over 5 years**. Modest.

**So:** a single Postgres primary + read replicas comfortably handles this. **The design pressure is
consistency, not throughput** — the opposite of the URL shortener.

## 3. The crux: derive vs materialize

The LLD computes balances by summing every expense on demand. Beautiful — append-only, no locks, no
drift. **It breaks in production:** a 5-year-old group with 20,000 expenses recomputes all of them on
every balance page load. That's O(history) per read, on the most-viewed screen in the app.

**Fix — materialize the balance, update it transactionally:**
```sql
BEGIN;
  INSERT INTO expenses (...);
  INSERT INTO splits (...);
  UPDATE balances SET amount = amount + ? WHERE user_id = ? AND group_id = ?;   -- per participant
COMMIT;
```
- Balance reads become **O(1)** — a single row lookup.
- The read-modify-write race the LLD *avoided* by deriving is now back — but the **DB transaction**
  handles it (row locks / atomic `UPDATE ... SET x = x + n`). Same lesson as `save_if_absent`: push
  atomicity down into the store.
- **Keep the expense log as the source of truth.** The balance table is a cached projection —
  recomputable from the log, so a periodic **reconciliation job** can verify and repair drift.
  (Same outbox/reconcile shape as the parking platform's availability counts.)

**Tradeoff to state:** derive = simple + always correct but O(history); materialize = O(1) reads but
introduces a cache that can drift → needs a transaction and a reconcile job. At this scale, materialize.

## 4. Other key decisions
- **Postgres, not NoSQL.** Money needs ACID: the expense insert and every balance update must commit
  **atomically or not at all**. A partial write here means real money is wrong. This is the clearest
  "why relational" case in the whole track.
- **Idempotency is mandatory, not optional.** Mobile clients retry on flaky networks; a retried
  "add expense" must not double-charge the group. Client sends an **idempotency key** (UUID per user
  action); server stores `key → expense_id` and returns the original result on replay.
- **Notifications** — "Bob added an expense" fans out to group members via Kafka → push service.
  Async: never block the expense write on notification delivery.
- **Offline mobile:** queue actions locally, sync when online — the idempotency key makes replay safe.
  Conflicts are rare (expenses are append-only; two people adding the same dinner is a *human*
  problem, not a merge conflict).

## 5. Scale & failure
- **Bottleneck:** none at these numbers. If groups grew huge, shard by `group_id` (all of a group's
  expenses and balances co-locate → no cross-shard transactions, which is exactly what you want when
  a single transaction must touch several balances).
- **Postgres primary down** → replica promotes; writes pause briefly. Correct behaviour: better to
  reject an expense than to record it wrongly (**fail-closed on money** — the opposite of the rate
  limiter's fail-open).
- **Notification service down** → graceful degradation; expenses still record, pushes are delayed.
- **Balance drift** → reconciliation job recomputes from the expense log and repairs.

## LLD ↔ HLD mapping
| LLD (`solution.py`) | HLD (this doc) |
|---|---|
| balances **derived** from the event list | **materialized** balance table + transactional update (O(1) reads) |
| append-only ⇒ no lock needed | DB **transaction / row lock** now provides that atomicity |
| `Expense` + `Split` objects | `expenses` + `splits` tables (the source of truth) |
| `SplitStrategy` (per-call) | unchanged — runs server-side before the insert |
| `BalanceCalculator.simplify` | unchanged, computed on demand from the balance rows |
| `Decimal` for money | `NUMERIC(12,2)` column — never `FLOAT` |
| *(single process, one user)* | idempotency keys · notification fan-out · reconciliation job |

**The line to say:** *"I'd derive balances for correctness, then materialize them for read
performance — keeping the expense log as the source of truth so the projection stays verifiable."*
