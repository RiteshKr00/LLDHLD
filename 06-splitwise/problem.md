# Problem 6: Splitwise (LLD)

## The prompt (as an interviewer would give it)

> "Design Splitwise — a expense-sharing app. A group of people share expenses, and the app
> keeps track of who owes whom."

Deliberately vague. **Your job is to make it concrete** — that's Step 1.

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **Split types** — equal only, or exact amounts / percentages / shares? Will more be added later? *(Strategy signal.)*
2. **Groups** — must an expense belong to a group, or can two people settle 1-on-1 with no group?
3. **Balances** — show raw debts ("A owes B, B owes C"), or **netted**? Is **simplify-debts** (minimum transfers) in scope? *(The algorithmic centrepiece.)*
4. **Settlements** — can users record payments to clear debt? **Partial** payments allowed?
5. **Currency** — single or multi? *(Worth actively CUTTING: multi-currency drags in FX rates and when-to-convert, with no design insight.)*
6. **Money precision** — how are fractions handled when an amount doesn't divide evenly? *(₹1000/3 — the vanishing-paisa problem.)*

---

## Clarifications (locked scope from Q&A)
- **Split types:** EQUAL, EXACT, PERCENTAGE — and more will be added later (shares, adjustment) → must be **pluggable**.
- **Groups:** both — an expense can belong to a group, OR be a plain 1-on-1 with no group.
- **Balances:** **net**, not raw (A owes B ₹500 + B owes A ₹200 → "A owes B ₹300").
- **Simplify debts: IN SCOPE** — given everyone's net position, produce the **minimum set of transfers** to settle the group. The algorithmic centrepiece.
- **Settlement:** record a payment against a debt; **partial payments allowed**.
- **Currency:** single currency — multi-currency **cut** (FX rates + when-to-convert is a rabbit hole with no design insight here).

---

## Step 1 — Requirements  ← YOUR TURN
_Ask clarifying questions first, then state these back._

### Functional (what it DOES — the verbs)
- Add an expense with a **split type** (equal / exact / percentage)
- Expense can belong to a **group** OR be a direct **1-on-1**
- Show the **net balance** per person (who owes whom, after netting)
- **Simplify debts** — minimum set of transfers to settle a group
- Record a **settlement**, including **partial** payments

### Non-functional (constraints — the "-ilities")
- **Extensible** — split types pluggable (new ones without touching existing code)
- **Correctness of money** — splits must sum EXACTLY to the total (rounding can't lose/create paise)
- **Thread-safety — a design decision, not a given:** balances are shared mutable state across
  users. If a running balance is stored as a field (`balance += x`) that's a read-modify-write race.
  If balances are **derived** from the expense log, adding an expense is just an append and the race
  disappears. Decide in Step 2.
- **Testable**

### Explicitly out of scope (say this out loud — senior move)
- Multi-currency · payment-gateway integration · auth · notifications · receipt images / comments

> 📝 **Review note (Step 1):** core verbs right, and the **extensible split type** (Strategy signal) was caught unprompted; out-of-scope written unprompted for the 3rd problem running — that habit has stuck. Misses: (1) **simplify debts** was dropped despite being explicitly in scope — it's the algorithmic centrepiece; (2) the **concurrency question was skipped entirely**. Key lesson: Splitwise is neither an automatic yes (parking: two cars, one spot) nor an automatic no (chess: turn-based) — it **depends on the design**: mutable running balance ⇒ real race; derived-from-expense-log ⇒ no race. Right move is to name the tradeoff in Step 1 and settle it in Step 2. Also added **money correctness** (splits must sum exactly — rounding is a real bug source here).

---

## Step 2 — Entities  (nouns → classes)
_Format: `Name — single responsibility — key attributes/methods`_

1. **User** — a person — `user_id, name`
2. **Group** — a named set of users — `group_id, name, members: list[User]`
3. **Split** — ONE line item of an expense: what one person owes for it — `user, amount`
4. **Expense** — one shared cost — `expense_id, payer: User, amount, description, group: Optional[Group], splits: list[Split]`
5. **SplitStrategy** *(Strategy, ABC)* — turns a total + participants into `list[Split]`; concrete: `EqualSplit`, `ExactSplit`, `PercentageSplit` — `calculate(total, participants, params) -> list[Split]`
6. **Settlement** — a payment that CLEARS debt (not one that creates it) — `payer, payee, amount` *(no splits — always 1→1)*
7. **BalanceCalculator** — derives net balances from the expense + settlement lists; also owns **simplify_debts** — `net_balances(...)`, `simplify(...)`
8. **SplitwiseService** — orchestrator; `add_expense(...)`, `settle(...)`, `get_balances(...)`

**Balance = DERIVED, not stored** (decision): for each expense, `payer` gains `amount` and each
`Split.user` loses `split.amount`; settlements move money the other way. Sum over all events.
Consequence: adding an expense is an **append**, so there's no read-modify-write race on a balance
field — the Step-1 concurrency question resolves itself.

> 📝 **Review note (Step 2):** 🎯 **the data-vs-behaviour trigger FIRED unprompted** — "split type → behaviour change, follow strategy pattern" was written *while* listing entities, not after being flagged. 4th rep, first time self-triggered. Also settled the Step-1 open question deliberately (**balance = computed**, with the reason stated) — that's the right instinct: derive ⇒ append-only ⇒ no race.
>
> Fixes: (1) **`Expense` itself was missing** — the core noun that holds payer + amount + splits; "expense calculator" was listed but not the thing it calculates. (2) Introduced **`Split`** — one line item (`user, amount`) — which is exactly what `SplitStrategy.calculate()` returns; note the payer appears in their own splits (paid ₹900, owes ₹300 ⇒ net +600). (3) `BalanceCalculator` given a home for **simplify_debts** (was unassigned). Keeping `Settlement` separate from `Expense` is a fair call (creates-debt vs clears-debt, and a settlement has no splits); the alternative is one unified ledger where balance = sum over a single event list.

---

## Step 3 — Relationships & APIs
_Signatures before bodies._

**Relationships:**
```
SplitwiseService ──composition──▶ BalanceCalculator
SplitwiseService ──uses (DI)────▶ SplitStrategy
Expense ──contains──▶ Split[], payer: User, group: Optional[Group]
Group ──has──▶ User[]
```

**Signatures:**
```python
# SplitwiseService (entry point)
def add_expense(self, payer, amount, participants, split_type, params=None, group=None) -> Expense
def settle(self, payer, payee, amount) -> Settlement
def get_balances(self, group=None) -> dict[User, Decimal]

# SplitStrategy (Strategy)
def calculate(self, total: Decimal, participants: list[User], params) -> list[Split]

# BalanceCalculator
def net_balances(self, expenses, settlements) -> dict[User, Decimal]
def simplify(self, balances) -> list[tuple[User, User, Decimal]]   # (from, to, amount)
```

**simplify_debts — greedy max-match:**
1. Net balances (positive = is owed, negative = owes; they always sum to 0).
2. Take the **largest creditor** + the **largest debtor**.
3. Transfer `min(|creditor|, |debtor|)`; record it.
4. At least one hits exactly 0 and drops out; the other keeps the remainder.
5. Repeat until all zero → **at most n−1 transfers** (vs naive n²).

> **Say this out loud:** greedy gives ≤ n−1 transfers but is NOT provably optimal — the true
> minimum requires finding zero-sum subgroups (subset-sum ⇒ **NP-hard**). Greedy is the standard
> practical answer; knowing it's a heuristic is the senior signal.

**Money correctness (the NFR from Step 1):**
- **Never `float`** — `0.1 + 0.2 != 0.3` in binary floating point; errors compound and balances
  silently drift. Use **`Decimal`**, or integer paise and divide only for display.
- **The vanishing paisa:** ₹1000 / 3 = 333.333… → rounding each to 333.33 sums to ₹999.99.
  **Invariant: `sum(splits) == total` exactly.** Fix: base share rounded down for everyone, compute
  the leftover (`total − sum(base)`), then distribute those few paise one-each (or all to the payer).
  ⇒ `[333.34, 333.33, 333.33]`. Slightly unequal, but **conserved** — which is what matters.

> 📝 **Review note (Step 3):** relationships + signatures correct. **simplify_debts intuition was right** ("pick +ve and -ve, minimise to 0") — formalised above as greedy max-match, plus the NP-hard caveat worth stating aloud. **Miss: the money/rounding question went unanswered** — and it was the candidate's OWN Step-1 NFR ("splits must sum exactly"). Two things to internalise: (1) money is `Decimal`/integer-paise, never `float`; (2) equal splits don't divide evenly, so compute base shares then redistribute the leftover paise to preserve the sum invariant. Pattern to watch: an NFR written in Step 1 wasn't carried into the design decisions in Step 3 — requirements need re-reading before each later step.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

| LLD method | HTTP |
|---|---|
| `add_expense(payer, amount, participants, strategy, params)` | `POST /api/v1/expenses` -> **201** `{expense_id, splits}` · **400** splits do not sum to total |
| `settle(payer, payee, amount)` | `POST /api/v1/settlements` -> **201** |
| `get_balances(group?)` | `GET /api/v1/groups/{id}/balances` -> **200** `{user_id: amount}` |
| `simplify_debts(group?)` | `GET /api/v1/groups/{id}/settle-up` -> **200** `[{from, to, amount}, ...]` |

> **Money endpoints need an `Idempotency-Key` header.** A retried `POST /expenses` on a flaky mobile
> connection must not double-charge the group — the server stores `key -> result` and replays it.

## Notes / decisions (log the "why" here)
- **Balance = derived, never stored.** Adding an expense is an append ⇒ no read-modify-write ⇒ **no lock anywhere in the codebase**. The Step-1 concurrency NFR was resolved by a *modelling* choice, not by synchronisation.
- **Money = `Decimal`, never `float`** (`0.1 + 0.2 != 0.3` compounds into drifting balances).
- **Rounding:** base share rounded **DOWN** (deliberately under-allocate), then hand the leftover paise out one-each ⇒ `sum(splits) == total` exactly. Rounding up could *invent* money, which can't be undone.
- **Strategy passed per-call**, not injected in `__init__` — because the split type varies per *expense*, unlike parking's assignment rule which varies per *lot*. Both are valid Strategy usage; the axis of variation decides.
- **Settlement kept separate from Expense** (creates-debt vs clears-debt; a settlement has no splits). Alternative: one unified ledger.
- **Partial/over payment needs no special code** — a settlement just moves the balance by its amount; overpaying flips a debtor into a creditor naturally.

> 📝 **Review note (Step 4 build):** three split strategies each preserving the sum invariant; the paisa-redistribution is the money NFR actually delivered. Key bug caught in `net_balances`: **settlement signs were flipped** — the trap is thinking "payer hands over cash so payer goes down", but `balances` is a *ledger position*, not a wallet: paying a debt moves you TOWARD zero, i.e. **up** when negative (payer `+=`, payee `-=`). Note the sum-to-zero check does NOT catch a sign flip — direction has to be reasoned about separately. `simplify` implemented as greedy max-match (≤ n−1 transfers), with the honest caveat that true minimisation is subset-sum ⇒ NP-hard.
