# LLD Patterns & Principles (glossary)

The vocabulary you actually *say* in an interview. Each entry: **what → why → in our code → when to reach for it.**
Grounded in the solved problems (URL shortener = `01-url-shortener`, Parking lot = `02-parking-lot`). Grow it as new patterns appear.

> **How to talk about a pattern:** name the **pain** first (rigidity, duplication, hard-to-test, a race), *then* the pattern that fixes it. Never pattern-dump.

---

## Design patterns

### Strategy
- **What:** a family of interchangeable algorithms behind one interface; pick one at runtime.
- **Why:** swap behavior without touching the caller (Open/Closed).
- **In our code:** `ShortCodeGenerator` (URL) · `SpotAssignmentStrategy`, `CostCalculator` (parking).
- **Reach for it when:** you have >1 way to do one job, or a requirement says "…should be swappable / configurable / pluggable".

### Repository
- **What:** hide storage behind an interface (`save`, `find`, `save_if_absent`); domain code doesn't know dict vs DB.
- **Why:** swap persistence with no logic rewrite (Dependency Inversion); the interface is the seam where in-memory → real DB.
- **In our code:** `URLRepository` → `InMemoryURLRepository` (swappable to DynamoDB).
- **Reach for it when:** anything is stored/fetched and might move to a real DB later.

### Dependency Injection (DI)
- **What:** a class receives its collaborators from outside (constructor) instead of building them itself.
- **Why:** decouples from concrete impls → testable + swappable.
- **In our code:** `ParkingLot(floors, spot_strategy, cost_calculator)`; `URLShortenerService(generator, repository)`.
- **Anti-pattern:** `self.x = ConcreteThing()` hard-coded inside → glued to one impl.
- **Note:** DI is *how* a Strategy/Repository gets in; those are *what* it is.

### Factory family (clarify WHICH when asked)
- **Simple Factory:** a function that builds the right object from input — `create_vehicle("car") -> Car`. *(We didn't need it — the enum decision removed the subclasses to choose between.)*
- **Factory Method (GoF):** a method a **subclass overrides** to decide which concrete product to create; defers "which class" to subclasses.
- **Abstract Factory (GoF):** creates **families** of related objects (e.g. a whole theme).
- **Builder:** assembles a complex object step-by-step / from config. **In our code:** `build_lot(floors, per_floor)`.
- **Reach for it when:** object creation is complex, conditional, or you want to centralize "which concrete class".

### Observer (pub/sub)
- **The pain first** — the naive version:
  ```python
  def post_comment(comment):
      save_comment(comment)
      email_service.send(...)      # why does a COMMENT function know about SMTP?
      sms_service.send(...)
      push_service.send(...)
      analytics.track(...)
  ```
  Every complaint about this code is an NFR: it *knows* about 4 unrelated services · adding a 5th
  means **editing working code** (Open/Closed) · untestable without 4 mocks · a slow SMS provider
  makes **posting a comment** slow · if email throws, push never runs.
- **The flip:** the publisher just **announces**; listeners **register themselves**.
  ```python
  def post_comment(comment):
      save_comment(comment)
      event_bus.publish(Event(COMMENT_POSTED, {...}))   # done. Who's listening? Not my problem.
  ```
  ```python
  # elsewhere, at startup — post_comment never changes again
  event_bus.subscribe(COMMENT_POSTED, notification_service)
  event_bus.subscribe(COMMENT_POSTED, analytics_service)
  ```
- **Analogy:** a YouTube creator doesn't phone 2M people one by one — they publish; subscribers get
  notified because they subscribed. The millionth subscriber doesn't change how uploading works.
- **The whole mechanism is ~10 lines:**
  ```python
  class EventBus:
      def __init__(self): self._subs: dict[EventType, list[Subscriber]] = {}
      def subscribe(self, et, sub): self._subs.setdefault(et, []).append(sub)
      def publish(self, event):
          for sub in self._subs.get(event.event_type, []):
              sub.handle(event)        # <- the bus has NO IDEA what handle() does
  ```
  `Subscriber` is just an ABC with `handle(event)` — that contract is what lets the bus stay ignorant.
- **Strategy vs Observer** (they look identical — an ABC with one method):

  | | Strategy | Observer |
  |---|---|---|
  | How many | pick **one** algorithm | notify **all** listeners |
  | Purpose | swap *how* something is done | decouple *who* reacts to something |
- **Reach for it when:** one action must trigger several unrelated reactions · you want to add
  reactions without editing the trigger · a requirement says "low coupling between producer and consumer".
- **In our code:** `EventBus` + `Subscriber` + `NotificationService` (07-notification-system).
- **Watch out:** the subscriber list is shared mutable state — subscribing during an in-flight
  publish raises `RuntimeError: list changed size during iteration`. Iterate a **copy**.

### Command
- **What:** turn an operation into an **object** with `execute()` and `undo()`, instead of a function
  call that happens and is gone.
- **Why:** once the operation is an object it can be *stored*, so you can reverse it, log it, replay
  it, or queue it.
- **In our code:** `InsertCommand` / `DeleteCommand` / `ReplaceCommand` (10-text-editor).
- **The freebies** (none possible with a plain function call):
  - **undo/redo** — two stacks; commands *move* between them, so redo is just `execute()` again
  - **log** — the undo stack already *is* the history
  - **macro** — a list of commands, replayed
  - **queue / remote execution** — serialise the command, run it elsewhere
- **Reach for it when:** you need undo, an audit trail, replay, deferred/queued work, or macros.
- **Watch out:** a command must capture whatever it needs to reverse itself — and often it can only
  capture that **inside `execute()`**, because at construction it hasn't seen the target state yet.

### Memento
- **What:** capture an object's state so it can be restored later, **without exposing its internals**.
- **In our code:** not used standalone — but `DeleteCommand._removed` is a **mini-memento**: a snapshot
  of just the slice that changed.
- **Command vs Memento — this is the real decision:**

  | | Command | Memento |
  |---|---|---|
  | Stores | the **delta** | the **whole state** |
  | 50 undos, 10 MB doc | a few KB | **500 MB** |
  | Requires | every op to be invertible | nothing |
- **Reach for Memento when** the operation **can't be cleanly inverted** — a lossy/complex transform,
  a game save, a checkpoint before a risky batch job.
- **In practice they combine:** Command-driven history where each command holds a tiny memento of only
  what it touched. That's how real editors work.

### (add as met)
State · Observer · Command · Singleton · Adapter · Decorator · Composite · Iterator — add each under *what → why → in our code* the first time a problem needs it.

---

## SOLID (the 5 rules)

- **S — Single Responsibility:** one class, one reason to change. *Why we split `CostCalculator` out and kept `can_fit` pure (type-fit only, not availability).*
- **O — Open/Closed:** open to extension, closed to modification. *Add a vehicle type = one line in `FIT_RULE`; add a strategy = new class, no edits.*
- **L — Liskov Substitution:** any subclass must work wherever its parent is expected. *Every `SpotAssignmentStrategy` is drop-in for the lot.*
- **I — Interface Segregation:** many small interfaces > one fat one; don't force impls to build methods nobody calls. *Why we deleted `exists()` once `save_if_absent` replaced it.*
- **D — Dependency Inversion:** depend on abstractions, not concretes. *Service talks to `URLRepository`, not `InMemoryURLRepository`.*

## Other principles

- **YAGNI** ("You Aren't Gonna Need It"): don't build abstraction you don't need yet. *Killed the 6 URL generators + the vehicle subclasses.*
- **DRY:** one source of truth. *Module-level `FIT_RULE` / `RATES` / `BASE62_ALPHABET`.*
- **Tell, Don't Ask:** let an object answer about its own state. *`spot.can_fit(v)`, `link.is_active()`.*
- **Data-driven over branching:** encode rules as a map (`FIT_RULE`, `RATES`) not `if/elif` chains → extend by editing data, not code.

## The modeling decision: enum vs subclass

- **Enum + rule-map** when subtypes differ only by **data** (which spot fits, what rate). *Parking vehicle/spot types.*
- **Subclass (+ maybe Factory)** when subtypes have genuinely different **behavior** (override methods).
- **The lens:** "different behavior, or just different data?" Data → enum. Behavior → subclass. Prevents over-engineering (YAGNI).

## Concurrency

- **TOCTOU** (Time-Of-Check-To-Time-Of-Use): a race where you **check** then **act**, and state changes in the gap. *`exists→save` (URL); `assign→occupy` (parking) — two threads both see "free", both claim.*
- **Critical section:** the code between lock-acquire and lock-release; one thread inside at a time. *find→claim must live here.*
- **Lock (`threading.Lock`, `with self._lock:`):** makes the gap uninterruptible. In-process only — doesn't cross machines (that's the HLD story).
- **Atomic operation:** collapse check+act into one indivisible step → no gap to race. *`save_if_absent` / DB unique constraint / `SET NX`.* Preferred over a coarse lock when available, and the only thing that works across processes.

### Who provides the atomicity? (the track's recurring lesson)

`threading.Lock` serializes threads **inside one process only**. Two app servers each hold their own
lock guarding their own memory — they know nothing about each other, so the lock protects nothing.
**The only thing all servers share is the datastore, so it must be the arbiter.**

The distinction that matters is **where the read-modify-write happens**:

```
WRONG — gap lives in your app:            RIGHT — no gap, the store does it:
  SELECT amount        -> 666.66            UPDATE balances
  app computes 666.66 + 300                 SET amount = amount + 300
  UPDATE amount = 966.66                    WHERE user_id = ?
       ^ another server can read the             ^ read, add and write happen
         stale 666.66 in this gap                  inside the DB as ONE step
         -> one update silently LOST
```

Do the arithmetic **in** the statement, not in application code. Wrap multi-row changes in a
transaction (`BEGIN … COMMIT`) so they're all-or-nothing.

**Same lesson, five costumes:**

| Problem | The racy pair | Pushed down into the store as |
|---|---|---|
| URL shortener | `exists()` + `save()` | `save_if_absent` / `INSERT … ON CONFLICT DO NOTHING` |
| Parking lot | find spot + mark taken | one critical section / conditional insert |
| Rate limiter | `get` + `set` counter | Redis `INCR` / Lua script |
| Chess | *(turn-based, none)* | race exists only at **matchmaking** |
| Splitwise | `balance += x` | `UPDATE … SET x = x + n`, inside a **transaction** |

---

## Python gotchas (LLD implementation)

### Identity vs value equality — when to use `@dataclass(frozen=True)`

Python has two ways to ask *"are these the same?"*:
- **Identity** — *"literally the same object in memory?"* ← what a plain class uses by default
- **Value** — *"do they hold the same data?"* ← what you almost always mean

```python
class User:                       # plain class
    def __init__(self, name): self.name = name

a, b = User("Alice"), User("Alice")
a == b            # False!  different objects, Python doesn't look at the data
```

**Why this silently breaks dictionaries.** A dict does two things on lookup:
1. `hash(key)` → find the bucket
2. `==` inside that bucket → confirm it's the right key

| | plain class (default) | `@dataclass(frozen=True)` |
|---|---|---|
| `__hash__` | derived from the **memory address** | derived from **field values** |
| `__eq__` | identity (`is`) | compares **field values** |

Both default to identity, so **two same-data objects fail both tests**:
```python
prefs[User("Alice")] = "EMAIL"
prefs.get(User("Alice"))          # -> None.  Stored under a different address.
```
No crash, no warning — the entry is simply invisible. That's the dangerous part.

**The fix:**
```python
@dataclass(frozen=True)
class User:
    user_id: str
    name: str
```
`frozen=True` generates a value-based `__eq__` **and** `__hash__`.

**Why `frozen` specifically (not just `@dataclass`)?** Because if fields could change after the
object became a dict key, its hash would go stale and the entry would be **unreachable forever**.
Python therefore only auto-generates `__hash__` for frozen dataclasses — immutability is the
precondition for being a safe key.

> **Rule of thumb:** if an object will ever be a **dict key** or live in a **set**, make it a
> `frozen` dataclass. Seen in: `Cell` (chess, `dict[Cell, Piece]`), `User` (splitwise
> `dict[User, Decimal]`; notifications `dict[(User, EventType), set[ChannelType]]`).
>
> Objects that are *never* keys (`Event`, `Notification`, `Ticket`) don't need it.

### Mutable defaults — the rule is *when the default is evaluated*, not class vs dataclass
A mutable default (`set`/`list`/`dict`/an object) is a bug **only when it's evaluated once and shared**. Three cases:

| Where the mutable lives | Evaluated | Result |
|---|---|---|
| **`@dataclass` field** `x: set = set()` | once, at class definition | 🐛 dataclass **raises** `ValueError` → use `field(default_factory=set)` |
| **default parameter** `def __init__(self, x=set())` | once, at function definition | 🐛 silently **shared** across instances → use `x=None` then `self.x = x or set()` |
| **inside `__init__` body** `self.x = set()` | every call | ✅ fresh per instance — always safe |

- `field(default_factory=set)` ≡ "run `set()` fresh in the generated `__init__`" — literally the plain-class body approach.
- A non-`set/list/dict` object (e.g. `state: State = IdleState()`) does **not** trip dataclass's guard, but it's the *same shared-instance smell* → still use `default_factory`.
- Seen in: `ParkingFloor.spots`, `Elevator.targets` / `Elevator.state`.

## How to grow this file

When a problem introduces a new pattern (State machine for an elevator, Observer for notifications, Command for undo…), add it under **Design patterns** in the same *what → why → in our code → reach for it when* shape. This stays the single LLD pattern reference. See also: `LLD-HLD-process.md` (the solve steps), `README.md` (the framework).
