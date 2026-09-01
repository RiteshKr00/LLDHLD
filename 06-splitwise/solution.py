"""
Splitwise — LLD solution (built step by step).

Entities (Step 2):
    1. User              - a person
    2. Group             - a named set of users
    3. Split             - ONE line item of an expense (user, amount)
    4. Expense           - one shared cost: payer + total + splits
    5. SplitStrategy     - Strategy: total + participants -> list[Split]
    6. Settlement        - a payment that CLEARS debt (1 -> 1, no splits)
    7. BalanceCalculator - derives net balances; owns simplify_debts
    8. SplitwiseService  - orchestrator

MONEY RULE (from Step 1's NFR): all amounts are `Decimal`, never float.
    float can't represent 0.1 exactly -> 0.1 + 0.2 != 0.3 -> balances drift.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Optional


PAISA = Decimal("0.01")   # smallest unit -> everything rounds to 2dp


# ---------------------------------------------------------------------------
# Step 4a: User, Group, Split, Expense, Settlement   <-- YOUR TURN
#
# HINT — all five are plain data holders (@dataclass). Nothing clever:
#   User       -> user_id: str, name: str
#                 ** make it frozen=True so it's HASHABLE — balances are a
#                    dict[User, Decimal], and dict keys must be hashable
#                    (same reason Cell was frozen in chess).
#   Group      -> group_id, name, members: list[User]   (default_factory!)
#   Split      -> user: User, amount: Decimal           (one line item)
#   Expense    -> expense_id, payer: User, amount: Decimal, description,
#                 splits: list[Split], group: Optional[Group] = None
#   Settlement -> payer: User, payee: User, amount: Decimal
#                 (no splits — a settlement is always exactly 1 -> 1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class User:
    user_id: str
    name: str

@dataclass
class Group:
    group_id: str
    name: str
    members: list[User] = field(default_factory=list)

@dataclass
class Split:
    user: User
    amount: Decimal

@dataclass
class Expense:
    expense_id: str
    payer: User
    amount: Decimal
    description: str
    splits: list[Split]
    group: Optional[Group] = None

@dataclass
class Settlement:
    payer: User
    payee: User
    amount: Decimal 

# ---------------------------------------------------------------------------
# Step 4b: SplitStrategy (ABC) + EqualSplit  — where the paisa problem lives
# ---------------------------------------------------------------------------
class SplitStrategy(ABC):
    """Strategy: turn a total + participants into per-person line items.

    THE INVARIANT every implementation must guarantee:
        sum(split.amount for split in result) == total     (exactly)
    """

    @abstractmethod
    def calculate(self, total: Decimal, participants: list[User], params=None) -> list[Split]:
        ...


class EqualSplit(SplitStrategy):
    """Split evenly. Handles the vanishing-paisa problem: 1000/3 = 333.333...
    Rounding each to 333.33 sums to 999.99 -> a paisa disappears."""

    def calculate(self, total: Decimal, participants: list[User], params=None) -> list[Split]:
        n = len(participants)
        if n == 0:
            raise ValueError("no participants to split between")

        # Round DOWN deliberately: we must UNDER-allocate, so there's a remainder
        # left to hand out. Rounding up could invent money we can't take back.
        base = (total / n).quantize(PAISA, rounding=ROUND_DOWN)

        remainder = total - (base * n)            # e.g. 1000 - 999.99 = 0.01
        extra_paise = int(remainder / PAISA)      # how many 1-paisa units to give away

        # Hand one extra paisa to the first `extra_paise` people -> sum is exact.
        return [
            Split(user, base + (PAISA if i < extra_paise else Decimal("0")))
            for i, user in enumerate(participants)
        ]


# ---------------------------------------------------------------------------
# Step 4c: ExactSplit + PercentageSplit  (each VALIDATES its params)
# ---------------------------------------------------------------------------
class ExactSplit(SplitStrategy):
    """params = list[Decimal] — the exact amount each participant owes.
    Nothing to compute; everything to VALIDATE."""

    def calculate(self, total: Decimal, participants: list[User], params=None) -> list[Split]:
        if params is None or len(params) != len(participants):
            raise ValueError("exact split needs one amount per participant")
        if sum(params) != total:
            raise ValueError(f"amounts sum to {sum(params)}, expected {total}")
        return [Split(u, amt) for u, amt in zip(participants, params)]


class PercentageSplit(SplitStrategy):
    """params = list[Decimal] percentages (must total 100).
    Same rounding problem as EqualSplit: 33.33% of 1000, three times, != 1000."""

    def calculate(self, total: Decimal, participants: list[User], params=None) -> list[Split]:
        if params is None or len(params) != len(participants):
            raise ValueError("percentage split needs one percentage per participant")
        if sum(params) != Decimal("100"):
            raise ValueError(f"percentages sum to {sum(params)}, expected 100")

        amounts = [(total * pct / Decimal("100")).quantize(PAISA, rounding=ROUND_DOWN)
                   for pct in params]

        # same leftover-paisa redistribution as EqualSplit
        remainder = total - sum(amounts)
        extra_paise = int(remainder / PAISA)
        for i in range(extra_paise):
            amounts[i] += PAISA

        return [Split(u, amt) for u, amt in zip(participants, amounts)]


# ---------------------------------------------------------------------------
# Step 4d: BalanceCalculator — net_balances + simplify (greedy max-match)
# ---------------------------------------------------------------------------

class BalanceCalculator:
    """Given a list of expenses, derive net balances and simplify debts.

    net_balances: dict[User, Decimal] = how much each user owes (negative) or is owed (positive)
    simplify_debts: list[Settlement] = how to clear all debts with the fewest transactions
    """

    def net_balances(self, expenses: list[Expense], settlement: list[Settlement]) -> dict[User, Decimal]:
        balances = {}
        for exp in expenses:
            # payer gets +amount
            balances[exp.payer] = balances.get(exp.payer, Decimal("0")) + exp.amount
            # each split user gets -split.amount
            for split in exp.splits:
                balances[split.user] = balances.get(split.user, Decimal("0")) - split.amount

        # Apply settlements — SIGNS ARE THE OPPOSITE OF WHAT INTUITION SAYS.
        #
        # `balances` is NOT "how much cash you hold" — it's your POSITION in the
        # group ledger (+ = owed to you, - = you owe). Paying off a debt moves you
        # TOWARD ZERO, which is UP when you're negative.
        #
        #   Alice +600, Bob -300.  Bob settles 300 to Alice:
        #     Bob:   -300 + 300 =    0   (debt cleared)      -> payer GAINS
        #     Alice: +600 - 300 = +300   (repaid that much)  -> payee LOSES
        for s in settlement:
            balances[s.payer] = balances.get(s.payer, Decimal("0")) + s.amount
            balances[s.payee] = balances.get(s.payee, Decimal("0")) - s.amount

        return balances

    def simplify(self, balances: dict[User, Decimal]) -> list[Settlement]:
        """Greedy max-match: repeatedly settle the biggest creditor against the
        biggest debtor. Each round zeroes at least one person -> at most n-1
        transfers (vs the naive n^2 of everyone-pays-everyone).

        NOTE: greedy is a HEURISTIC, not provably optimal. The true minimum needs
        zero-sum subgroups (subset-sum) => NP-hard. Say that out loud in an interview.
        """
        # Debtors stored as POSITIVE magnitudes — makes the arithmetic symmetric.
        creditors = [[u, amt] for u, amt in balances.items() if amt > 0]
        debtors = [[u, -amt] for u, amt in balances.items() if amt < 0]

        transfers: list[Settlement] = []
        while creditors and debtors:
            creditors.sort(key=lambda pair: pair[1], reverse=True)   # biggest owed
            debtors.sort(key=lambda pair: pair[1], reverse=True)     # biggest owing

            creditor, credit = creditors[0]
            debtor, debt = debtors[0]
            amount = min(credit, debt)          # the most one transfer can move

            transfers.append(Settlement(payer=debtor, payee=creditor, amount=amount))

            creditors[0][1] -= amount
            debtors[0][1] -= amount

            # Drop whoever hit zero. At least one always does — that's what
            # guarantees termination (and the n-1 bound).
            creditors = [pair for pair in creditors if pair[1] > 0]
            debtors = [pair for pair in debtors if pair[1] > 0]

        return transfers

# --- ALTERNATIVE: MATERIALIZED balances (the production approach) ------------
#
# Everything above DERIVES balances: sum the whole event log on every read.
# Beautiful (append-only, no locks, can't drift) but the read is O(history) —
# a 5-year group with 20,000 expenses recomputes all of them every time someone
# opens the balances screen, which is the most-viewed screen in the app.
#
# The production fix: keep a running balance and update it as expenses arrive.
#   read  -> O(1) dict/row lookup instead of O(n) summation
#   cost  -> `amount += x` is a READ-MODIFY-WRITE, so the race we avoided by
#            deriving is BACK.
#   rule  -> keep the expense log as the SOURCE OF TRUTH; this is only a cached
#            projection, so a reconcile job can recompute and repair any drift.
#
# =============================================================================
# ** WHO PROVIDES THE ATOMICITY? — the recurring lesson of this whole track **
#
# `threading.Lock` only serializes threads INSIDE ONE PROCESS. Run two app
# servers and each has its OWN lock guarding its OWN memory — they know nothing
# about each other, so the lock protects nothing. The only thing all servers
# share is the DATABASE. So the DB must be the arbiter.
#
# The distinction that actually matters — WHERE the read-modify-write happens:
#
#   WRONG (gap in the app):                    RIGHT (no gap, DB does it):
#     SELECT amount FROM balances  -> 666.66     UPDATE balances
#     ...app computes 666.66 + 300               SET amount = amount + 300
#     UPDATE balances SET amount = 966.66        WHERE user_id = ?
#          ^ another server can read 666.66            ^ the DB reads, adds and
#            in this gap -> one update LOST               writes internally, as
#                                                         ONE indivisible step
#
# Do the arithmetic IN the UPDATE statement, not in your application code.
# And wrap the whole multi-row change in a transaction so it's all-or-nothing:
#     BEGIN;
#       INSERT INTO expenses (...);
#       UPDATE balances SET amount = amount + ? WHERE user_id = ?;   -- payer
#       UPDATE balances SET amount = amount - ? WHERE user_id = ?;   -- each split
#     COMMIT;
#
# Same lesson, five costumes — always "push atomicity down into the shared store":
#     URL shortener : exists()+save()  -> save_if_absent / INSERT..ON CONFLICT
#     Parking lot   : find + claim     -> one critical section / conditional insert
#     Rate limiter  : get + set        -> Redis INCR / Lua script
#     Chess         : (turn-based)     -> race only at matchmaking
#     Splitwise     : balance += x     -> UPDATE ... SET x = x + n, in a TRANSACTION
# =============================================================================
#
# class MaterializedBalanceStore:
#     """O(1) balance reads. The tradeoff: a lock, and a value that can drift."""
#
#     def __init__(self):
#         self._balances: dict[User, Decimal] = {}
#         self._lock = threading.Lock()          # needed again — += is not atomic
#
#     def apply_expense(self, expense: Expense) -> None:
#         with self._lock:                       # one critical section for the whole expense
#             self._bump(expense.payer, expense.amount)
#             for split in expense.splits:
#                 self._bump(split.user, -split.amount)
#
#     def apply_settlement(self, s: Settlement) -> None:
#         with self._lock:
#             self._bump(s.payer, s.amount)      # payer moves UP toward zero
#             self._bump(s.payee, -s.amount)
#
#     def _bump(self, user: User, delta: Decimal) -> None:
#         self._balances[user] = self._balances.get(user, Decimal("0")) + delta
#
#     def get(self, user: User) -> Decimal:
#         return self._balances.get(user, Decimal("0"))     # <-- O(1), the whole point
#
#     def recompute_from_log(self, expenses, settlements) -> None:
#         """The repair job: rebuild the projection from the source of truth."""
#         with self._lock:
#             self._balances = BalanceCalculator().net_balances(expenses, settlements)
#
# WHEN TO USE WHICH: derive while history per key is small and reads are rare;
# materialize once reads are frequent or history is unbounded. Say the tradeoff
# out loud — that's the senior move, not picking one silently.
# -----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Step 4e: SplitwiseService (orchestrator) + demo
#
# HINT (to rebuild):
#   add_expense -> call strategy.calculate(amount, participants, params) to get
#       the splits, build the Expense, APPEND to self.expenses, return it.
#       ** The strategy is passed PER CALL here (different expenses use different
#          split types) — unlike parking's assignment strategy, which was injected
#          once in __init__. Both are valid Strategy usage; the choice depends on
#          whether the algorithm varies per-OPERATION or per-INSTANCE.
#
#   settle -> build a Settlement, append, return.
#       ** Partial payments need NO special handling: a 200 settlement against a
#          500 debt just moves the balance by 200. It falls out of the arithmetic.
#
#   get_balances -> delegate to balance_calculator.net_balances(expenses, settlements).
#       If a group is given, filter self.expenses to that group first.
#
#   simplify_debts -> get balances, hand them to simplify().
#
#   Note there is NO lock anywhere: balances are DERIVED, so adding an expense is
#   an append, not a read-modify-write. That Step-2 decision removed the race.
# ---------------------------------------------------------------------------
class SplitwiseService:
    """Entry point. Owns the event log (expenses + settlements); balances are
    always DERIVED from it, never stored."""

    def __init__(self, balance_calculator: Optional[BalanceCalculator] = None):
        self.balance_calculator = balance_calculator or BalanceCalculator()
        self.expenses: list[Expense] = []
        self.settlements: list[Settlement] = []

    def add_expense(self, payer: User, amount: Decimal, participants: list[User],
                    strategy: SplitStrategy, params=None, group: Optional[Group] = None,
                    description: str = "") -> Expense:
        splits = strategy.calculate(amount, participants, params)
        expense = Expense(
            expense_id=f"e{len(self.expenses) + 1}",
            payer=payer, amount=amount, description=description,
            splits=splits, group=group,
        )
        self.expenses.append(expense)          # append-only -> no race
        return expense

    def settle(self, payer: User, payee: User, amount: Decimal) -> Settlement:
        settlement = Settlement(payer=payer, payee=payee, amount=amount)
        self.settlements.append(settlement)
        return settlement

    def get_balances(self, group: Optional[Group] = None) -> dict[User, Decimal]:
        expenses = self.expenses if group is None else [e for e in self.expenses if e.group is group]
        return self.balance_calculator.net_balances(expenses, self.settlements)

    def simplify_debts(self, group: Optional[Group] = None) -> list[Settlement]:
        return self.balance_calculator.simplify(self.get_balances(group))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    alice, bob, carol = User("1", "Alice"), User("2", "Bob"), User("3", "Carol")
    trip = Group("g1", "Goa Trip", [alice, bob, carol])
    svc = SplitwiseService()

    def show(label):
        print(f"\n{label}")
        for user, amt in svc.get_balances().items():
            state = "is owed" if amt > 0 else ("owes   " if amt < 0 else "settled")
            print(f"   {user.name:6} {state} {abs(amt)}")

    # 1. EQUAL — the vanishing-paisa case: 1000 / 3
    svc.add_expense(alice, Decimal("1000"), [alice, bob, carol], EqualSplit(),
                    group=trip, description="hotel")
    show("after hotel (Alice paid 1000, split equally):")

    # 2. EXACT — Bob paid, but Carol ate more
    svc.add_expense(bob, Decimal("600"), [alice, bob, carol], ExactSplit(),
                    params=[Decimal("100"), Decimal("200"), Decimal("300")],
                    group=trip, description="dinner")
    show("after dinner (exact split 100/200/300):")

    # 3. PERCENTAGE
    svc.add_expense(carol, Decimal("300"), [alice, bob, carol], PercentageSplit(),
                    params=[Decimal("50"), Decimal("25"), Decimal("25")],
                    group=trip, description="cab")
    show("after cab (50/25/25 %):")

    # 4. simplify — minimum transfers to settle everyone
    print("\nsimplify_debts -> minimum transfers:")
    for t in svc.simplify_debts():
        print(f"   {t.payer.name} pays {t.payee.name} {t.amount}")

    # 5. partial settlement — no special handling needed
    svc.settle(bob, alice, Decimal("100"))
    show("after Bob partially pays Alice 100:")

    print("\ninvariant — balances always sum to zero:",
          sum(svc.get_balances().values()) == 0)
