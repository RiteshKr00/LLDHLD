# HLD-05 — Payment / Wallet System

## META
- difficulty: hard
- time: 45 min
- tags: ledger, double-entry, exactly-once, idempotency, saga, consistency
- why-it-matters: the only problem where **being wrong costs real money**. Correctness beats
  availability here — the opposite of every other design you've done.

## PROMPT
> "Design a payments system — a wallet where users can add money, pay each other, and pay merchants."

## CLARIFY
- **Do we handle the actual card/bank rails?**
  → No — assume a **PSP (payment service provider)** you call, which returns success/failure/timeout.
  **The timeout case is the interesting one.**
- **Can a balance go negative?**
  → Never. That's a hard invariant.
- **Consistency vs availability?**
  → **Consistency, absolutely.** Refusing a payment is fine; double-charging is not.
- **Do we need a full transaction history?**
  → Yes — auditable, immutable, forever. This is a regulated domain.
- **Refunds / reversals?**
  → Yes.
- **Multi-currency?**
  → Out of scope (say it — FX is a rabbit hole).

## STEP 1 — Requirements
**Functional:** add money · pay another user · pay a merchant · check balance · transaction history ·
refund/reverse.
**Non-functional:** **money is never created or destroyed** · **exactly-once effect** (a retry must not
double-charge) · balance never negative · **fully auditable** · strongly consistent.
**Out of scope:** FX/multi-currency · fraud detection · lending/credit · KYC.

### CHECKPOINTS
- States **"money is never created or destroyed"** as the invariant
- Chooses **consistency over availability** *and says why* (fail-closed on money)
- Names **exactly-once / idempotency** in the requirements, not as an afterthought
- Treats **audit history** as functional, not optional

### TRAPS
- Optimising for availability/throughput — wrong axis entirely for this problem
- Forgetting refunds, which are where naive designs break (you can't just "subtract")

## STEP 2 — Capacity
```
users        100M, 10M DAU
payments     each DAU makes 2/day -> 20M/day ÷ 86,400 ≈ 230 writes/sec   (peak ~1,000)
balance reads  10× that           ≈ 2,500 reads/sec
storage      20M txns/day × 2 ledger entries × 200 B ≈ 8 GB/day ≈ 3 TB/year
```

### CHECKPOINTS
- Notices the **QPS is small** — and says so explicitly
- Concludes the problem is **correctness, not scale**

### TRAPS
- Reaching for Cassandra/sharding because "it's a big system". 1,000 writes/sec is one Postgres box.
  **Choosing the boring database and defending it is the senior move here.**

### FOLLOWUPS
- *"Only 1,000 writes/sec? So what's actually hard?"* ← the invitation to say "correctness"

## STEP 3 — API
```
POST /api/v1/payments        {from, to, amount}    -> 201 {payment_id, status}
      header: Idempotency-Key: <client uuid>       <- MANDATORY, not optional
GET  /api/v1/payments/{id}                          -> 200 {status}
GET  /api/v1/accounts/{id}/balance                  -> 200 {balance, as_of}
GET  /api/v1/accounts/{id}/transactions?cursor=     -> 200 {entries[]}
POST /api/v1/payments/{id}/refund                   -> 201 (a NEW payment, not an edit)
```

### CHECKPOINTS
- **`Idempotency-Key` is required** on every write
- A refund is a **new transaction**, never a mutation or deletion of the original
- Payment status is queryable (because the client will time out and need to ask)

### TRAPS
- No idempotency key → the client's retry double-pays. This is *the* classic payments bug.
- Modelling refund as `UPDATE payments SET status='refunded'` — destroys the audit trail

## STEP 4 — Data model — the ledger
```
accounts(account_id, user_id, type, currency)
ledger_entries(entry_id, txn_id, account_id, amount_signed, created_at)   -- IMMUTABLE, append-only
transactions(txn_id, idempotency_key UNIQUE, status, created_at)
balances(account_id, amount, version)      -- materialised projection of the ledger
```

### Double-entry: the core idea
**Every transaction writes at least TWO entries that sum to zero.**
```
Alice pays Bob ₹500:
   entry 1:  account=Alice   amount = -500
   entry 2:  account=Bob     amount = +500
                              -------------
                       sum  =        0     <- ALWAYS
```
Why this and not `UPDATE balance`:
- Money **cannot** be created or destroyed by construction — if the sum isn't zero, the write is a bug
  you can *detect*
- The ledger is **immutable and append-only** → a perfect audit trail
- A balance is **derivable**: `SELECT SUM(amount) WHERE account_id = ?`

### The derive-vs-materialise decision (you've met this before — Splitwise)
```
derive:      SUM over all entries       correct always, but O(history) per read
materialise: a balances row             O(1) reads, must be updated in the SAME transaction
```
**Answer: both.** Keep the ledger as the source of truth, materialise `balances` for reads, update
both **inside one DB transaction**, and run a **daily reconciliation** that recomputes from the ledger
and alarms on any drift.

### CHECKPOINTS
- Uses **double-entry**: two signed entries per transaction, summing to zero
- Ledger is **append-only and immutable** — corrections are new entries, never edits
- Balance is **materialised for reads but reconcilable from the ledger**
- `idempotency_key` has a **UNIQUE constraint** — the database enforces it, not the app

### TRAPS
- A single `balance` column mutated with `UPDATE` — no audit trail, no way to detect corruption
- Deleting or editing a ledger entry to fix a mistake (in real systems this is illegal, not just bad)

## STEP 5 — Architecture
```
Client ──Idempotency-Key──▶ Payment Service
                               │
                               ├─▶ Postgres  (ACID — the whole point)
                               │     BEGIN
                               │       INSERT transactions (idempotency_key UNIQUE)
                               │       INSERT ledger_entries × 2
                               │       UPDATE balances × 2   (with a >= 0 check)
                               │     COMMIT
                               │
                               ├─▶ PSP (external card/bank rails)  <- the risky part
                               │
                               └─▶ outbox ─▶ Kafka ─▶ notifications, analytics, reconciliation
```

### CHECKPOINTS
- **One ACID transaction** covers the ledger entries and the balance update
- The **non-negative check is in the write** (`WHERE balance >= amount`), not a read-then-check
- Events leave via an **outbox**, so a notification can't be lost or sent for a rolled-back payment

### TRAPS
- `SELECT balance` → check in app code → `UPDATE` — a TOCTOU race; two concurrent payments both pass
  the check and the balance goes negative. **Put the condition in the UPDATE.**
- Calling the PSP *inside* the DB transaction — holding a lock across a slow network call

### FOLLOWUPS
- *"Two payments from the same account arrive at the same millisecond, and the balance covers only one."*
- *"You called the PSP and got a timeout. Did the money move or not?"* ← the deep dive

## DEEP DIVE — exactly-once, and the PSP timeout

### The problem in one line
The client's phone loses signal after sending `POST /payments`. It retries. **Did the first one go through?**
Neither the client nor (initially) you know.

### Layer 1 — idempotency key (protects against the *client* retrying)
```
client generates a UUID per user ACTION (not per request), sends it as Idempotency-Key

server:  INSERT INTO transactions (idempotency_key, ...)   -- UNIQUE constraint
         ├─ succeeds  -> this is genuinely new, process it
         └─ conflict  -> we've seen it; return the STORED result, do NOT re-execute
```
The uniqueness is enforced by **the database**, not by an `if` in your code — otherwise two concurrent
retries both pass the check. *(The same "push the check into the write" lesson as `save_if_absent`.)*

### Layer 2 — the PSP timeout (protects against *the world* being uncertain)
You called the PSP. You got no answer. Three possibilities:
```
1. it never arrived              -> no charge
2. it arrived and succeeded      -> charged
3. it arrived, succeeded, and the RESPONSE was lost  -> charged, and you don't know
```
**You cannot tell these apart.** So:
- Never assume failure and retry blindly → risk of double-charging
- Mark the transaction **PENDING**, and **reconcile**: query the PSP by *your* idempotency key
  ("what happened to reference X?"). Every real PSP supports this precisely because of case 3.
- Retry with **the same key**, so a duplicate at the PSP is also rejected by the PSP.

### Layer 3 — multi-step flows: saga
"Pay merchant" might be: debit wallet → charge card → credit merchant → notify. Some steps are at
different services; **there is no distributed transaction across them.**

**Saga** = a sequence of local transactions, each with a **compensating action**:
```
debit wallet        ✔        compensate: credit wallet back
charge card         ✔        compensate: refund card
credit merchant     ✘ fails
                    └─▶ run compensations BACKWARDS
```
Note the compensation is a **new forward transaction** ("credit ₹500 back"), never an undo of history.
That's exactly why the ledger is append-only.

> **Why not two-phase commit?** 2PC holds locks across services and blocks if the coordinator dies —
> unacceptable when one participant is an external bank you don't control.

### CHECKPOINTS
- **Idempotency key enforced by a UNIQUE constraint**, and returns the *stored* result on conflict
- Distinguishes client-retry (layer 1) from world-uncertainty (layer 2) — they need different fixes
- Names the **PSP timeout ambiguity** and resolves it by **querying the PSP**, not by guessing
- Uses **saga + compensating transactions** for multi-service flows, and can say why not 2PC
- Compensation is a **new entry**, never a deletion

### TRAPS
- "Just retry the PSP call" — the double-charge bug
- Trying to use a distributed transaction across an external provider
- Implementing compensation as "delete the ledger row"

### FOLLOWUPS
- *"Your idempotency check is `SELECT` then `INSERT`. Two retries arrive simultaneously. What happens?"*
- *"The compensating refund itself fails. Now what?"* (retry it; it's idempotent too; then alert a human —
  money problems escalate, they don't get swallowed)

## STEP 7 — Scale
- **Shard by `account_id`** — a user's entries stay together, and a payment touches only two accounts.
  A cross-shard payment needs care: either co-locate related accounts or run it as a small saga.
- **Hot account** (a big merchant receiving thousands of payments/sec): the single balance row becomes
  a write hotspot. Fix: **balance sharding** — split the merchant's balance into N sub-balances,
  write to a random one, sum on read.
- **Reads**: replicas for history; balance from the materialised row.
- **Archival**: entries older than N years to cold storage — but **never deleted**.

## STEP 8 — Failure
- **DB down** → **fail closed.** Refuse payments. Better to reject than to risk inconsistency.
  *(The exact opposite of the rate limiter's fail-open — and a great contrast to state out loud.)*
- **PSP down** → mark PENDING, queue, reconcile later. Do not guess.
- **Partial saga** → compensations run backwards; if a compensation fails, retry, then alert a human.
- **Balance drift** → daily reconciliation recomputes from the ledger; any mismatch is a **P0 alarm**,
  because the ledger is truth and the balance row is only a cache.

## STEP 9 — Wrap
- **Bottleneck:** not throughput — it's hot accounts and cross-shard transactions.
- **Tradeoffs:** ACID/single-primary (correct, less available) vs eventual (unacceptable here) ·
  materialised balance (fast reads, needs reconciliation) vs pure ledger sum (always right, O(history)) ·
  saga (no distributed locks, but you must write compensations for everything).
- **Monitoring:** ledger-sum ≠ 0 (should be impossible → page immediately), balance drift, PENDING
  transactions older than N minutes, PSP timeout rate, idempotency-conflict rate.
- **Next:** multi-currency, fraud scoring, chargebacks, regulatory reporting.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | `balances` table, `UPDATE balance`, "use transactions", no idempotency |
| **Senior** | double-entry immutable ledger, ACID, idempotency key, materialised balance + reconciliation |
| **Staff** | all that **+ the PSP-timeout ambiguity and how to resolve it**, saga with compensating entries and why not 2PC, hot-account balance sharding, and explicitly choosing **fail-closed** with the contrast to fail-open systems |

## REFERENCE
**Alice pays Bob ₹500 (happy path):**
1. Client sends `Idempotency-Key: uuid-abc`
2. ```sql
   BEGIN;
     INSERT INTO transactions(txn_id, idempotency_key, status) VALUES (…, 'uuid-abc', 'PENDING');
       -- UNIQUE violation here => it's a retry => return the stored result, done
     UPDATE balances SET amount = amount - 500, version = version + 1
       WHERE account_id = 'alice' AND amount >= 500;      -- 0 rows => insufficient => ROLLBACK
     INSERT INTO ledger_entries VALUES (txn, 'alice', -500), (txn, 'bob', +500);
     UPDATE balances SET amount = amount + 500 WHERE account_id = 'bob';
     UPDATE transactions SET status='COMPLETED' WHERE txn_id = …;
   COMMIT;
   ```
3. Outbox row → Kafka → notifications

**The retry:** same key → UNIQUE violation → return the original response. **Charged once.**

**PSP timeout:** transaction stays `PENDING`; a reconciler asks the PSP "what happened to uuid-abc?"
and completes or compensates based on the real answer. **Never guessed.**

**Refund:** a *new* transaction with entries `(merchant, -500), (alice, +500)`. The original rows are
untouched, forever.

## ONE-LINER
> *"The QPS here is small — about a thousand writes a second — so this isn't a scale problem, it's a
> correctness problem, and I'd deliberately pick boring ACID Postgres. The core is a **double-entry,
> append-only ledger** where every transaction writes two signed entries summing to zero, so money
> can't be created or destroyed and drift is detectable. Retries are made safe by an **idempotency key
> with a UNIQUE constraint** — the database enforces it, not my code — and for the case where the
> external PSP times out and I genuinely don't know if the money moved, I don't guess: I hold the
> transaction PENDING and **ask the PSP by my own key**."*
