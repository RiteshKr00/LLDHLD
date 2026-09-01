# From Naive Code to Pattern

**Read this when a pattern feels arbitrary.** Nobody should memorise "use Strategy here." Every
pattern in this track exists because somebody wrote the obvious code first and it *hurt* in a specific,
predictable way. This file writes the obvious code for all seven problems, then shows exactly where it
hurts — because the pain is the thing worth recognising. The pattern is just the standard bandage.

**How to use it:** cover the "What it's telling you" part, read the naive code, and try to list the
problems yourself. Every complaint you find is a requirement in disguise.

> **The universal move:** when code hurts, ask *"what is changing that I keep having to edit?"*
> Whatever varies is what needs to be pulled out behind an interface.

---

## 1. URL Shortener

### What everyone writes first
```python
class URLShortener:
    def __init__(self):
        self.urls = {}          # code -> long_url
        self.counter = 0

    def shorten(self, long_url):
        self.counter += 1
        code = str(self.counter)
        self.urls[code] = long_url
        return code

    def resolve(self, code):
        return self.urls[code]
```
Honestly? This works. Run it, it shortens URLs. So what's wrong?

### Run it in your head
- **"Can we make codes unguessable instead of 1, 2, 3?"** → you edit `shorten`.
- **"We're moving to Postgres."** → you edit `shorten` *and* `resolve`. The storage is welded in.
- **"Write a unit test."** → you can't test code-generation without also touching storage. They're fused.
- **"A user wants `bit.ly/my-brand`."** → there's nowhere to pass it, and if you forced it in, it would **silently overwrite** someone else's link.
- **Two threads call `shorten` at once.** Both read `counter = 5`, both write `6`. **Two different URLs, one code.** One link is silently destroyed.

### What it's telling you
Three completely different jobs are trapped in one class: *making a code*, *storing things*, and
*coordinating the two*. That's why every change touches everything.

| The pain | The fix |
|---|---|
| "change how codes are made" | **Strategy** — `ShortCodeGenerator` interface |
| "change where things are stored" | **Repository** — `URLRepository` interface |
| "test one piece alone" | **DI** — pass both in, don't build them inside |
| "two threads, one code" | **atomic claim** — `save_if_absent`, not check-then-save |

---

## 2. Parking Lot

### What everyone writes first
```python
def park(vehicle):
    for spot in all_spots:
        if not spot.free:
            continue
        if vehicle.type == "motorcycle":
            return assign(spot)                                  # fits anywhere
        elif vehicle.type == "car" and spot.type in ("medium", "large"):
            return assign(spot)
        elif vehicle.type == "truck" and spot.type == "large":
            return assign(spot)

def fee(hours, spot_type):
    if spot_type == "small":    return hours * 1
    elif spot_type == "medium": return hours * 2
    elif spot_type == "large":  return hours * 3
```

### Run it in your head
- **"We're adding electric scooters."** → edit `park`. **"And EV charging spots."** → edit `park` *and* `fee`.
- **"What are the fit rules again?"** → you have to *read code* to find out. The rules exist only as a
  shape of `if` statements. Nobody can check them at a glance, so nobody notices when one is wrong.
- **"Prices go up on weekends."** → edit `fee`. A pricing change should never require a code deploy of
  the parking logic.
- **Two cars arrive at once.** Both loops find spot #12 free. Both park there.

### What it's telling you
The **rules are hiding inside control flow**. Rules that change should be *data you can read*, not
branches you have to trace.

```python
FIT_RULE = {                                  # now the rules are a TABLE you can just read
    VehicleType.MOTORCYCLE: {SMALL, MEDIUM, LARGE},
    VehicleType.CAR:        {MEDIUM, LARGE},
    VehicleType.TRUCK:      {LARGE},
}
```
Adding scooters is now **one line of data**, not a code change (**Open/Closed**).

| The pain | The fix |
|---|---|
| if/elif chain for fit rules | **enum + rule map** (data-driven) |
| pricing changes need code edits | **Strategy** — `CostCalculator` |
| "assign nearest instead of first" | **Strategy** — `SpotAssignmentStrategy` |
| two cars, one spot | **lock the find→claim as one critical section** |

---

## 3. Elevator

### What everyone writes first
```python
def step(self):
    if self.status == "idle":
        if self.targets:
            self.status = "moving"
    elif self.status == "moving":
        self.current_floor += 1 if self.direction == "up" else -1
        if self.current_floor in self.targets:
            self.status = "door_open"
    elif self.status == "door_open":
        self.targets.remove(self.current_floor)
        self.status = "moving" if self.targets else "idle"
```

### Run it in your head
- **"Add a maintenance mode."** → edit `step`, add a branch. **"And emergency stop."** → edit it again.
  **"And express mode."** → again. This one method becomes the place where every feature lands.
- **"What can happen after DOOR_OPEN?"** → hunt through branches to find the assignments. The state
  machine exists, but it's **smeared across the method** instead of written down anywhere.
- **"Test the door-open logic alone."** → you can't. You have to drive the elevator into that state first.
- `self.status == "moving"` — one typo (`"movng"`) and the branch silently never runs. No error.

### What it's telling you
Compare with the parking lot, because it's the *opposite* answer and this is the distinction worth owning:

| | Parking `VehicleType` | Elevator `status` |
|---|---|---|
| Do the values behave differently? | No — all vehicles just occupy a spot | **Yes** — `step()` does completely different work per state |
| What differs? | only **data** (which spot fits) | **behaviour** *and* the transition rules |
| Answer | **enum + map** | **State pattern** — a class per state |

So: **one class per state**, each owning its own `step()` *and* its own transitions.

```python
class Elevator:
    def step(self):
        self.state.step(self)      # that's it. No if. Ever.
```
Adding MAINTENANCE is now a **new class** — you never open the working ones.

---

## 4. Rate Limiter

### What everyone writes first
```python
counts = {}

def allow(user):
    counts[user] = counts.get(user, 0) + 1
    return counts[user] <= 50
```

### Run it in your head
- **The window never resets.** User #51 is blocked... forever. It's not a *rate* limiter, it's a
  lifetime quota. (The word "per minute" in the requirement has no code behind it.)
- **You deploy to 3 servers.** Each has its own `counts` dict. A user gets 50 on each = **150 requests**.
  Your limit silently became 3× what you promised.
- **"Allow short bursts, then throttle."** → different algorithm entirely. Rewrite.
- **Concurrent requests:** both read `49`, both write `50`, both allowed. That's **51 through**.

### What it's telling you
Two things are tangled: *the counting rule* and *where the counts live*. Separating them is what makes
this design survive contact with production.

| The pain | The fix |
|---|---|
| "burst vs strict vs cheap" | **Strategy** — `RateLimitAlgorithm` (fixed window / sliding / token bucket) |
| 3 servers = 3× the limit | **StateStore abstraction** — swap in-memory for **Redis**, one shared counter |
| lost updates on `+= 1` | **atomic increment** — a lock in-process, a **Lua script** in Redis |

The payoff: the algorithm classes never learn whether they're running on a dict or on Redis.

---

## 5. Chess

### What everyone writes first
```python
def can_move(piece, from_cell, to_cell, board):
    if piece.type == "rook":
        # ...25 lines of straight-line sliding...
    elif piece.type == "bishop":
        # ...25 lines of diagonal sliding...
    elif piece.type == "knight":
        # ...15 lines of L-shapes...
    elif piece.type == "queen":
        # ...40 lines (rook + bishop again, copy-pasted)...
    elif piece.type == "pawn":
        # ...30 lines, and it's the weird one...
```

### Run it in your head
- It's a **150-line function**. Nobody can hold it in their head.
- **Queen's logic is copy-pasted** from rook + bishop. Fix a sliding bug and you must remember to fix it
  in two places. You won't.
- **"Test the knight."** → you must call the giant function and hope you hit the right branch.
- **"Add a custom piece."** → edit the 150-line function that currently works. Every edit risks
  breaking rook.

### What it's telling you
Run the same test as the elevator: **do the types differ by data, or by behaviour?**

A rook's move computation is a *genuinely different algorithm* from a knight's — not a different
number in a lookup table. That's **behaviour** ⇒ polymorphism.

```python
class Piece:
    movement_rule: MovementStrategy      # injected

rook   = Piece(WHITE, cell, RookMovement())
knight = Piece(WHITE, cell, KnightMovement())
```
Now each piece's rules are ~10 lines, testable alone, and the Queen **reuses** the sliding helper
instead of copying it. The 150-line function is gone.

> And a bonus that falls out: "don't move into check" is enforced **once** in `make_move`
> (simulate → test → undo), not per-piece. That single rule also catches *pinned pieces* — a case
> nobody explicitly coded.

---

## 6. Splitwise

### What everyone writes first
```python
balances = {}          # user -> float

def add_expense(payer, amount, people):
    share = amount / len(people)
    for p in people:
        balances[p] = balances.get(p, 0) - share
    balances[payer] = balances.get(payer, 0) + amount
```

### Run it in your head
- **`float` for money.** `0.1 + 0.2` is `0.30000000000000004`. Across thousands of expenses, balances
  **drift**, and you cannot explain why to a user looking at real rupees.
- **₹1000 among 3** = 333.333… → three shares of 333.33 = **₹999.99**. A paisa vanished. Round *up*
  instead and you have **invented** money.
- **"Split by exact amounts / percentages."** → this function only knows equal. Rewrite.
- **`balances[p] -= share`** is read-modify-write → two people adding expenses at once **lose an update**.
- **"Why do I owe ₹430?"** → you cannot answer. You stored the *total*, not *how it got there*. No audit
  trail exists.

### What it's telling you
| The pain | The fix |
|---|---|
| money drifts | **`Decimal`**, never `float` |
| vanishing paisa | round **down**, then hand out the leftover paise → `sum(splits) == total` exactly |
| only equal splits | **Strategy** — `SplitStrategy` (equal / exact / percentage) |
| `-=` race | **derive** balances from the expense log — an append can't race |
| "why do I owe this?" | the log **is** the answer — balances become a *view* of it |

The elegant part: choosing "derive, don't store" fixed the race **and** the audit trail at once — no
lock required anywhere. *(And the HLD reverses it back to a stored balance for O(1) reads — see
`06-splitwise/hld.md`. Both are right at their own scale.)*

---

## 7. Notification System

### What everyone writes first
```python
def post_comment(comment):
    save_comment(comment)
    email_service.send(comment.post.owner, f"{comment.author} commented")
    sms_service.send(comment.post.owner, f"{comment.author} commented")
    push_service.send(comment.post.owner, f"{comment.author} commented")
    analytics.track("comment_posted", comment)
```

### Run it in your head
- A function about **comments** now knows that **SMTP exists**. Why?
- **"Also send a Slack alert."** → edit `post_comment`. **"Add a badge counter."** → edit it again.
  Working code gets reopened for every unrelated feature.
- **"Test posting a comment."** → mock four services first.
- **The SMS provider is slow (3s).** Posting a comment now takes 3 seconds. The user is waiting on
  something they never asked for.
- **Email throws** → push and analytics never run. One broken thing kills the rest.

### What it's telling you
The comment code shouldn't *call* anybody. It should just **announce**, and let interested parties
listen.

```python
def post_comment(comment):
    save_comment(comment)
    event_bus.publish(Event(COMMENT_POSTED, {...}))     # done. Who's listening isn't my problem.
```
```python
# elsewhere, at startup — post_comment never changes again
event_bus.subscribe(COMMENT_POSTED, notification_service)
event_bus.subscribe(COMMENT_POSTED, analytics_service)
```

> **YouTube:** a creator doesn't phone 2M people one at a time. They publish; subscribers get notified
> *because they subscribed*. Gaining a millionth subscriber doesn't change how uploading works.

| The pain | The fix |
|---|---|
| comment code knows about email/SMS/push | **Observer** — publish an event, don't call services |
| new listener = edit working code | subscribers **register themselves** |
| slow SMS blocks the user | **async** publish — return immediately |
| email throws, push dies | **bulkhead** — per-channel `try/except` inside the loop |
| "add WhatsApp later" | **Strategy** — `NotificationChannel` |

---

## 8. LRU Cache

### What everyone writes first
```python
cache = {}
order = []                      # newest first

def get(key):
    order.remove(key)           # <- the problem
    order.insert(0, key)
    return cache[key]
```

### Run it in your head
- **`order.remove(key)` is O(n).** Python must *scan* the list to find the key, then shift everything
  after it. A 100-item cache is fine. A 100,000-item cache does 100,000 steps **on every read**.
- Drop the list and use only a dict → O(1) lookup, but **no order at all**, so you can't tell who's oldest.
- Use only a linked list → O(1) removal, but **finding** a key means walking the list. O(n) again.

### What it's telling you
Neither structure is enough because each is missing what the other has.

| The pain | The fix |
|---|---|
| dict has no order | pair it with a **doubly linked list** |
| list can't find a key | **dict maps key → the NODE**, not the value |
| removing from the middle | **doubly** linked — `node.prev` is what makes unlink O(1) |
| endless `if node is None` | **sentinel** head/tail dummies |
| "add LFU later" | **Strategy** — and LFU is what proved the first interface was leaky |

> **The lesson that generalises:** an abstraction isn't proven until a **second, genuinely different**
> implementation exists. LRU and FIFO both fit a one-linked-list interface happily — and both were
> wrong about it. LFU (which needs one list *per frequency*) is what exposed it.

---

## 9. Movie Ticket Booking

### What everyone writes first
```python
def book(user, show, seat_ids):
    for sid in seat_ids:
        seat = show.seats[sid]
        if seat.is_booked:
            raise Exception("taken")
        seat.is_booked = True
    return Ticket(user, seat_ids)
```

### Run it in your head
- **Payment takes 30s–2min.** During that window, what is the seat?
  Mark it booked → payment fails → **seat blocked forever**.
  Leave it free → someone takes it → user pays and gets **"sorry"**.
  Both wrong. There is no correct answer with only two states.
- **New release, 10,000 people click seat A1.** Both threads read `is_booked == False`, both set it.
  Two people, one seat.
- **`show.seats[sid]`** puts the seat *inside* the show — but a seat is **physical**. A5 can be free
  at 3pm and booked at 6pm.
- User wants 3 seats, only 2 free → hold those 2? Now they're **stranded**: the user leaves, and
  nobody else can take them for 5 minutes either.

### What it's telling you
| The pain | The fix |
|---|---|
| gap between picking and paying | a **third state: HELD**, with an expiry |
| two users, one seat | **per-show lock** around check→claim (TOCTOU, 6th time) |
| seat booked for *every* show | split **`Seat` (physical)** from **`ShowSeat` (per-show state)** |
| partial hold strands seats | **all-or-nothing** — check all, *then* mutate |
| abandoned holds block seats forever | **lazy expiry + sweeper job** (both, defence in depth) |
| hold expires mid-payment | **`confirm()` re-checks** the hold before committing |

> Everything hard here exists because of one thing: **the gap between choosing and paying.** Remove
> that gap (like the parking lot, where the car physically arrives) and the whole problem collapses
> to trivial CRUD.

---

## 10. Text Editor with Undo/Redo

### What everyone writes first
```python
class Editor:
    def __init__(self):
        self.text = ""
    def insert(self, s, pos):
        self.text = self.text[:pos] + s + self.text[pos:]
    def delete(self, start, end):
        self.text = self.text[:start] + self.text[end:]
```

### Run it in your head
Now add undo. And… stop. **How?**
The text already changed. The deleted characters are **gone**. Nothing was saved. There is literally
no information left to undo *with*.

That's the whole realisation: **undo isn't a feature you bolt on, it's a constraint on how you
represent operations in the first place.**

### What it's telling you
An operation that is "just a function call" **disappears the moment it runs**. To reverse it, the
operation has to still *exist* afterwards — which means it must be an **object**.

| The pain | The fix |
|---|---|
| the operation vanished after running | **Command** — an object with `execute()` and `undo()` |
| how do I undo a *delete*? | the command **remembers the removed text** (a mini-**Memento**) |
| snapshotting the doc each time | 50 undos × 10 MB = **500 MB** → store the **delta**, not the state |
| redo after undo | **two stacks**; commands *move* across, so redo is just `execute()` again |
| redo after a new edit is nonsense | **clear the redo stack** on any new edit |
| unbounded history | `deque(maxlen=50)` — drops the oldest for free |

> **Bonus nobody asks for but everyone wants:** because operations are now objects, you get a **log**
> (the undo stack *is* the history), **macros** (a list of commands, replayed), **queuing** and
> **replay** — none of which is possible with a plain function call.

---

## The one page underneath all ten

Every naive version above fails in one of the same six ways. Learn to hear these complaints:

| What you hear yourself saying | What it means | Reach for |
|---|---|---|
| *"I have to edit this again to add X"* | the thing that varies isn't isolated | **Strategy / State / Observer** |
| *"the rule is buried in if/elif"* | rules should be readable data | **enum + rule map** |
| *"I can't test this without the other thing"* | dependencies are hard-wired | **DI + an interface** |
| *"two threads / servers break it"* | check-then-act with a gap | **atomic op in the shared store** |
| *"this operation is gone, I can't reverse it"* | the action was a function call, not a thing | **Command** (+ a mini-**Memento**) |
| *"one structure can't do both"* | you need two, indexing each other | **compose** (dict → node → list) |

And the meta-rule that generates all of them:

> **Find what changes. Put an interface in front of it.**
