# Problem 11: Food Delivery (LLD) — the capstone

## The prompt (as an interviewer would give it)

> "Design a food delivery system like Swiggy/Zomato. A customer orders from a restaurant,
> the restaurant prepares it, a delivery partner picks it up and delivers it."

> 🎓 **This is the integrative one.** Almost every pattern from problems 1–10 shows up here.
> The skill being tested isn't "do you know Observer" — it's **can you tell which pattern each
> part of a messy real system needs, and keep them from tangling into each other.**

---

## Clarifying questions to ask
1. **Order lifecycle** — what are the stages, and can an order be cancelled? At which stages?
2. **Delivery partner matching** — how is a partner chosen? Nearest? Least busy? Should it be swappable?
3. **Notifications** — who gets told what, and when? (customer, restaurant, partner)
4. **Pricing** — item total + delivery fee + surge? Should pricing be swappable?
5. **Search** — browse restaurants by location/cuisine, or is the restaurant already chosen?
6. **Payment** — in scope, or assume a result arrives?
7. **Concurrency** — can two orders grab the same delivery partner at the same moment?

## Clarifications (locked scope from Q&A)
1. **Assignment:** the **SYSTEM** assigns a partner (push), the partner does not pick. Rule = nearest available. **The rule must be swappable** (least-busy / rating-based later).
2. **Lifecycle:** `PLACED → ACCEPTED → PREPARING → READY → PICKED_UP → DELIVERED`, plus `CANCELLED`.
   `ACCEPTED` = restaurant confirmed (it may also **reject**).
3. **Notifications:** each transition notifies the **relevant** actors — not everyone gets everything.
4. **Cancellation:** the customer may cancel until `PREPARING` starts. After that, no (food is being cooked).
5. **No partner found:** retry with a **widening radius** (2km → 5km → 8km), 3 attempts. Still nothing → order sits in a **pending queue**, do NOT auto-cancel. Assign when someone frees up.
6. **Pricing:** item total + delivery fee. **Swappable** (surge later).
7. **Payment:** out of scope — assume a result arrives.
8. **Concurrency:** two orders can target the same partner at the same instant.
9. **Live tracking:** out of scope — status updates only.

**Actors and what each does** *(from the initial brain-dump, corrected)*
```
customer   -> place order · get notified at each stage · cancel (before PREPARING)
restaurant -> accept / reject · mark PREPARING · mark READY
partner    -> receive an ASSIGNED order · mark PICKED_UP · mark DELIVERED
platform   -> match a partner, drive the lifecycle, notify everyone
              ^ assignment lives HERE, not on the restaurant
```

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- **Place an order** (customer → restaurant, with items) and **price** it
- **Restaurant accepts or rejects** it
- **Assign a delivery partner** — nearest available; **retry with a widening radius**, then park the
  order in a **pending queue** if nobody is free (never auto-cancel)
- **Drive the lifecycle:** `PLACED → ACCEPTED → PREPARING → READY → PICKED_UP → DELIVERED`
- **Notify the right actors** on each transition (not everyone gets everything)
- **Cancel** — customer, allowed only before `PREPARING`

### Non-functional (constraints — the "-ilities")
- **Extensible ×2** — **pricing** *and* **partner-matching** rules both swappable
- **Thread-safe** — two orders must never be assigned the same partner
- **Loosely coupled** — the order flow must not know *who* is listening to it
- Testable

### Explicitly out of scope (say this out loud — senior move)
- Payment · live GPS tracking · restaurant browse/search · ratings & reviews · refunds · scheduled orders

> 📝 **Review note (Step 1):** **both** extensibility points caught this time (pricing **and** matching) — that was the repeat miss from the parking lot, now fixed. Concurrency stated concretely ("one partner must not get two orders"). Fixes: (1) **assignment does NOT belong to the restaurant** — the platform matches partners; the restaurant only accepts/rejects and cooks (leftover from the initial brain-dump); (2) **cancellation** missing; (3) the **no-partner-found retry** was missing — and that's the third time a *good question you asked* didn't get carried into the requirements (Splitwise: simplify-debts, then money-correctness). **Habit to build: after the interviewer answers, immediately write that answer into the requirement list.** (4) Added **low coupling** as an NFR — with three actors reacting to every transition, that's the Observer signal.

---

## Step 2 — Entities  (nouns → classes)
_Watch for the patterns. There are at least FOUR hiding in here._

**Actors**
1. **Customer** — `customer_id, name, location`
2. **Restaurant** — `restaurant_id, name, location, menu: list[MenuItem]`
3. **DeliveryPartner** — `partner_id, name, location, status: PartnerStatus`
   *(`AVAILABLE / BUSY` — matching needs this, and it's what the race is over)*
4. **Location** *(value object)* — `lat, lng`, `distance_to(other)` — "nearest" needs a notion of where

**Order**
5. **MenuItem** — `item_id, name, price` (belongs to a restaurant)
6. **OrderItem** — **one line of an order** — `menu_item, quantity`
   *(same idea as `Split` in Splitwise: an order isn't one item, it's a list of line items)*
7. **Order** — `order_id, customer, restaurant, items: list[OrderItem], status, partner?, amount, created_at`
8. **OrderStatus** *(enum)* + **`ALLOWED_TRANSITIONS`** map — see the note below

**Swappable ×2**
9. **PricingStrategy** *(Strategy)* — `calculate(order) -> Decimal`
10. **PartnerAssignmentStrategy** *(Strategy)* — `find_partner(order, partners, radius) -> Optional[DeliveryPartner]`

**Decoupling**
11. **OrderEvent** + **Subscriber** *(Observer)* — the order flow publishes; listeners register
12. **CustomerNotifier / RestaurantNotifier / PartnerNotifier** — concrete subscribers

**Orchestration**
13. **OrderService** — `place_order`, `accept`, `reject`, `advance`, `cancel`, `assign_partner`
14. **PendingOrderQueue** — orders that found no partner, retried when someone frees up

> 📝 **Review note (Step 2):** **all four patterns identified unprompted** — two Strategies (pricing, matching), Observer for notifications ("pub/sub model" written directly), and the lifecycle. That's the capstone's actual test, passed.
>
> **The judgment call — `OrderStatus`: enum, correctly.** Run the test: in the elevator, `step()` did *completely different work* per state → behaviour → State pattern. Here, every transition does the **same shape** of work (validate → change → notify); the only thing that differs is **which transitions are legal**, and that's a **table** — i.e. data. So: enum + an `ALLOWED_TRANSITIONS` map, exactly like parking's `FIT_RULE`. Worth saying out loud though: *"if states start doing their own work — PREPARING starts a timer, READY triggers assignment — I'd switch to the State pattern."*
>
> Missing entities added: **`OrderItem`** (an order is a list of line items, like `Split` in Splitwise — quantity matters), **`Location`** (you can't compute "nearest" without one), **`PartnerStatus`** (`AVAILABLE/BUSY` — this flag is what the concurrency race is actually over), and the **`PendingOrderQueue`** (the no-partner-found answer needed a home).

---

## Step 3 — Relationships & APIs

**Relationships:**
```
OrderService ──uses (DI)──▶ PricingStrategy
             ──uses (DI)──▶ PartnerAssignmentStrategy
             ──publishes──▶ EventBus ──▶ Subscriber[]   (never calls notifiers directly)
             ──owns──────▶ PendingOrderQueue

Order ──has──▶ Customer, Restaurant, list[OrderItem], OrderStatus, Optional[DeliveryPartner]
Restaurant ──has──▶ list[MenuItem], Location
DeliveryPartner ──has──▶ Location, PartnerStatus
```

**Signatures:**
```python
# OrderService (orchestrator)
def place_order(customer, restaurant, items) -> Order      # PLACED + priced
def accept_order(order_id) -> None                          # PLACED -> ACCEPTED
def reject_order(order_id) -> None                          # PLACED -> CANCELLED
def advance(order_id, to: OrderStatus) -> None              # validated transition
def assign_partner(order_id) -> Optional[DeliveryPartner]   # the racy one
def cancel_order(order_id) -> None                          # only before PREPARING

# PricingStrategy
def calculate(self, order: Order) -> Decimal

# PartnerAssignmentStrategy
def find_partner(self, order, partners, radius_km) -> Optional[DeliveryPartner]

# Subscriber (Observer)
def handle(self, event: OrderEvent) -> None
```

### When to assign the partner — a real tradeoff

| Assign at | Pro | Con |
|---|---|---|
| `PLACED` | partner lined up early | wasted if the restaurant rejects |
| `ACCEPTED` / `PREPARING` | partner arrives *as* the food is ready ← what real apps do | partner may idle briefly |
| `READY` | zero partner idle time | **the food waits** while a partner travels over |

Either is defensible — **stating the tradeoff is what matters**, not the choice.

### `assign_partner` — the race (7th appearance)

```python
with self._lock:                                   # ONE critical section
    for radius in (2, 5, 8):                       # widening retry
        partner = self.assignment.find_partner(order, self._partners, radius)
        if partner:
            partner.status = PartnerStatus.BUSY    # <- CLAIM
            order.partner = partner
            return partner
    self._pending.add(order)                       # nobody free -> park it, don't cancel
    return None
```

The gap is between **`find_partner` returning an AVAILABLE partner** and **setting them BUSY**. Two
orders can both be handed the same partner in that gap. Same shape as every previous problem:

```
exists+save · find+claim · get+set · balance+= · matchmaking · check+hold · find+assign
```

### Notifications — publish, never call directly

```python
# ❌ OrderService knows every listener
customer.notify(...); restaurant.notify(...); partner.notify(...)

# ✅ OrderService knows nobody
self._bus.publish(OrderEvent(OrderEventType.STATUS_CHANGED, order))
```
Subscribers register for the events they care about — so adding an SMS notifier, an analytics
listener or a badge counter **never touches `OrderService`**. That's the "low coupling" NFR.

> 📝 **Review note (Step 3):** all three answered correctly — the flow, **the exact location of the race** ("ready hone pe lock karna hoga" — the find→claim gap, 7th appearance), and the Observer model (service publishes events, each subscriber registers for what it wants). Added: the **assign-timing tradeoff** (READY is defensible but means the food waits; real apps assign around ACCEPTED/PREPARING so the partner arrives as it's ready) — in an interview the *tradeoff statement* scores, not the choice. Also made explicit that `advance()` must **validate against `ALLOWED_TRANSITIONS`**, and that the widening-radius retry plus the pending queue live inside the same locked block.



> 📝 Review note (Step 3): _pending_

---

## Notes / decisions (log the "why" here)
- **Four patterns, deliberately not tangled:** Strategy ×2 (pricing, matching) · Observer (notifications) · enum + transition table (lifecycle). Each owns one axis of change.
- **`OrderStatus` is an enum, not the State pattern** — every transition does the *same shape* of work (validate → change → publish); only *which* transitions are legal differs, and that's a table. Contrast the elevator, where each state did genuinely different work. Say the caveat out loud: *"if PREPARING starts a timer and READY triggers assignment, I'd switch to State."*
- **`_transition()` is the single gate** — it asks `can_transition_to()`, which reads `ALLOWED_TRANSITIONS`. **There is no `if status ==` anywhere in the service.** The one honest exception: `advance()` branches on the *target* (`if to is OrderStatus.DELIVERED: self._free_partner(order)`) — that's an action hung off a transition, not the lifecycle being decided by an if/elif.
- **Strategy chooses, service claims.** `NearestPartnerStrategy` returns a partner but never sets `BUSY`; the claim happens in `assign_partner` inside the lock. Same separation as parking (strategy finds, lot claims).
- **`OrderService` never calls a notifier** — it publishes. Adding an SMS notifier touches zero existing code.
- **Bulkhead at the subscriber level too** — `EventBus.publish` wraps each `handle()` in try/except, so one broken listener can't stop the rest. (This was the gap deliberately left open in problem 07.)
- **`_free_partner` calls `assign_partner` OUTSIDE the lock** — `threading.Lock` isn't reentrant; re-entering would deadlock.
- **`_transition` and `_free_partner` are both critical sections too** (fixed after review). Both were originally check-then-act with the check *outside* the lock — the same shape `assign_partner` gets right. `_transition` let two threads both pass `can_transition_to` and both write; `_free_partner` read `order.partner` before locking, so two callers could see the same live partner and the loser would flip a partner who'd already been re-claimed back to `AVAILABLE`. Neither fired in 300 random runs — CPython's window is too narrow — but both reproduce every time under a forced interleaving. **The lesson: "is it racy?" is a question about the code shape, not about whether your stress test caught it.**
- **No partner → pending queue, never auto-cancel**, and the queue is drained the moment a partner frees up.

> 📝 **Review note (Step 4 build):** demo proved all four patterns working together — Observer delivering notifications with the service knowing no listeners; the table rejecting `PLACED→DELIVERED` and `PREPARING→CANCELLED`; one class swap taking the price 710→810; and the widening-radius search parking an unreachable order as PENDING while keeping it alive. **Concurrency: 200 orders rushed one partner → exactly 1 winner, 199 pending** — the 7th and final appearance of check-then-claim, handled the same way as the first.
