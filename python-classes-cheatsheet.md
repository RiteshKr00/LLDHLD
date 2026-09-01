# Plain class vs `@dataclass` vs `frozen` — the one doc

> Every output below is **real** — copied from actually running the code.
> Read it once end-to-end, then use §6 (the decision tree) and §8 (the table) as reference.

---

## 1. The three levels, side by side

```python
# LEVEL 1 — plain class
class MenuItem:
    def __init__(self, item_id, name, price):
        self.item_id = item_id
        self.name = name
        self.price = price

# LEVEL 2 — @dataclass
@dataclass
class MenuItem:
    item_id: str
    name: str
    price: Decimal

# LEVEL 3 — @dataclass(frozen=True)
@dataclass(frozen=True)
class MenuItem:
    item_id: str
    name: str
    price: Decimal
```

All three **store the same data**. The difference is what Python *generates for you*:

| | writes `__init__`? | `print()` shows | `==` compares | usable as dict key / in a set | can you change fields? |
|---|---|---|---|---|---|
| **plain class** | ❌ you write it | `<MenuItem object at 0x1E17…>` | **identity** (is it the same object?) | ⚠️ yes, but keyed by *identity* | ✅ yes |
| **`@dataclass`** | ✅ free | `MenuItem(item_id='i1', name='Pizza', …)` | **values** | ❌ **TypeError** | ✅ yes |
| **`@dataclass(frozen=True)`** | ✅ free | `MenuItem(item_id='i1', …)` | **values** | ✅ yes | ❌ **no** |

---

## 2. Example: printing

```python
m = MenuItem('i1', 'Pizza', Decimal('300'))
print(m)
```
```
plain class   ->  <solution.MenuItem object at 0x000001E17AEFFE80>     😕 useless
@dataclass    ->  MenuItem(item_id='i1', name='Pizza', price=Decimal('300'))   ✅
```

This alone is worth using `@dataclass` for. Half of debugging is printing objects.

---

## 3. Example: equality

```python
m1 = MenuItem('i1', 'Pizza', Decimal('300'))
m2 = MenuItem('i1', 'Pizza', Decimal('300'))    # same data, built separately
m1 == m2
```
```
plain class   ->  False    😕  "are these the same OBJECT?"  no, two objects
@dataclass    ->  True     ✅  "do they hold the same DATA?"  yes
```

**Why plain class says False:** Python's default `==` is *identity* — literally `m1 is m2`. It never
looks inside. `@dataclass` generates an `__eq__` that compares every field.

---

## 4. Example: dict keys and sets

```python
prefs = {}
prefs[MenuItem('i1', 'Pizza', Decimal('300'))] = "veg"
prefs.get(MenuItem('i1', 'Pizza', Decimal('300')))     # same data, fresh object
```

| | Result | Why |
|---|---|---|
| plain class | **`None`** 😱 | hashed by memory address; the fresh object has a different address |
| `@dataclass` | **`TypeError: unhashable type`** | dataclass *removes* `__hash__` when it adds value-`__eq__` |
| `frozen=True` | **`"veg"`** ✅ | hash computed from the field values |

Real outputs:
```
plain class:   {a: "first", b: "second"}  ->  dict size 2   (same data, treated as 2 keys!)
@dataclass:    {Q(1): "v"}                ->  TypeError: unhashable type: 'Q'
frozen:        {P(1), P(1), P(2)}         ->  {P(x=1), P(x=2)}   (duplicate collapsed ✅)
```

> **The dangerous one is the plain class** — it doesn't crash. It silently stores your value under a
> key you can never look up again. No error, no warning, just missing data.

---

## 5. Why does `frozen` unlock hashing? (the actual reason)

A dict finds your value by `hash(key)`. So the hash **must never change** while the key is in the dict.

```python
class Bad:                       # mutable, and pretend it hashed by value
    def __init__(self, x): self.x = x

k = Bad(1)
d = {k: "hello"}     # stored in the bucket for hash(1)
k.x = 2              # you changed the key!
d[k]                 # now looks in the bucket for hash(2) -> NOTHING THERE
                     # the entry is stranded — unreachable forever
```

So Python's rule: **you only get a value-based `__hash__` if the value can't change.**
That's exactly what `frozen=True` guarantees:

```python
p = P(1)
p.x = 2
# -> FrozenInstanceError: cannot assign to field 'x'
```

**One sentence:** *frozen makes it immutable → immutable makes it safely hashable → hashable makes it
usable as a dict key.*

---

## 6. Decision tree — which one do I use?

```
Does this object's data ever CHANGE after creation?
│
├── YES  (Order.status, DeliveryPartner.status, ParkingSpot.is_available,
│         Elevator.current_floor, ShowSeat.status)
│         -> @dataclass          ** frozen is IMPOSSIBLE here, don't try **
│
└── NO   (Cell(3,4), Location(lat,lng), MenuItem, User, Money)
    │
    └── Will it ever be a dict KEY or go in a SET?
        │
        ├── YES  -> @dataclass(frozen=True)     <- REQUIRED
        │           (chess Cell, splitwise User, notification prefs key)
        │
        └── NO   -> @dataclass(frozen=True) anyway
                    (costs nothing, documents "this never changes",
                     and protects you if it becomes a key later)
```

> **"Frozen is always better" is WRONG.** Anything with changing state *cannot* be frozen. In every
> problem we built, roughly half the classes must stay mutable.

---

## 7. The mutable-default trap (different rule, often confused with the above)

```python
@dataclass
class ParkingFloor:
    spots: list = []                 # ❌ ValueError at import time
```
```
ValueError: mutable default <class 'list'> for field spots is not allowed:
            use default_factory
```

**The rule is about WHEN the default is evaluated:**

| Where | Evaluated | Result |
|---|---|---|
| `@dataclass` field `= []` | **once**, at class definition | 🐛 dataclass **raises** — it stops you |
| default parameter `def __init__(self, x=[])` | **once**, at function definition | 🐛 **silently shared** by every instance |
| inside `__init__` body: `self.x = []` | **every call** | ✅ fresh each time |

**Fix:**
```python
spots: list[ParkingSpot] = field(default_factory=list)   # "call list() fresh each time"
```

Also applies to non-list objects that *look* safe:
```python
state: State = IdleState()                      # ⚠️ dataclass allows this, but ALL
                                                #    elevators would share one object
state: State = field(default_factory=IdleState) # ✅
```
dataclass only guards `list`/`dict`/`set`. Anything else it lets through — you have to notice.

---

## 8. What we actually used, and why (all 11 problems)

| Class | Choice | Why |
|---|---|---|
| `Cell` (chess) | **frozen** | `dict[Cell, Piece]`, and (3,4) never becomes (5,6) |
| `Location` (delivery) | **frozen** | a coordinate is a value; never mutates |
| `User` (splitwise / notification) | **frozen** | used as a dict key for balances / preferences |
| `MenuItem`, `Movie`, `Seat` | **frozen** | catalogue data — never changes after setup |
| `ShortLink` | `@dataclass` | `click_count` and `is_disabled` change |
| `ParkingSpot` | `@dataclass` | `is_available` flips constantly |
| `Elevator` | `@dataclass` | floor, direction, state, targets all change |
| `ShowSeat` | `@dataclass` | `status`, `held_by`, `hold_expires_at` change |
| `Order`, `DeliveryPartner` | `@dataclass` | `status` changes — **frozen impossible** |
| `Node` (LRU) | plain class | `prev`/`next` are rewired constantly; also self-referential |
| `Ticket`, `Booking`, `Expense` | `@dataclass` | records that get completed over time |

Notice the split is almost exactly **"does it have a status/counter?"** → mutable → `@dataclass`.

---

## 9. Cheat sheet

```python
from dataclasses import dataclass, field

# value object — never changes, might be a key
@dataclass(frozen=True)
class Cell:
    x: int
    y: int

# entity with changing state
@dataclass
class Order:
    order_id: str
    status: OrderStatus = OrderStatus.PLACED         # simple default: fine
    items: list[OrderItem] = field(default_factory=list)   # mutable: factory!
    partner: Optional[Partner] = None
    created_at: datetime = field(default_factory=now)      # "call now() each time"
```

**Three rules to remember:**
1. **Changes?** → `@dataclass`. **Never changes?** → `@dataclass(frozen=True)`.
2. **Dict key or in a set?** → `frozen=True` is **mandatory**, not optional.
3. **Default is a `list`/`dict`/`set`/object?** → `field(default_factory=…)`, always.

**And the one that bites silently:** a plain class used as a dict key **works but keys by identity** —
your lookup with an equal-but-different object returns `None`, with no error at all.
