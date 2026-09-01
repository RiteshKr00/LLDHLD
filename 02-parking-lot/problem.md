# Problem 2: Parking Lot (LLD)

## The prompt (as an interviewer would give it)

> "Design a parking lot. Vehicles come in, get parked in a spot, and pay when they leave."

Deliberately vague. **Your job is to make it concrete** — that's Step 1.

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **Floors** — single level or multi-level? Do we track *which* spot a car is in, or just free counts? *(A counter vs a whole spot model.)*
2. **Vehicle types & spot types** — what are they, and **which vehicle fits which spot**? *(The fit-rule is the crux of this problem.)*
3. **How is a spot chosen** — first available? Nearest to entrance? Least-used floor? Should the rule be **swappable**? *(Strategy signal.)*
4. **Pricing** — hourly, flat, tiered? Rate by spot type? Will the model change later? *(Second Strategy signal.)*
5. **Capacity/time** — max stay? Lost-ticket penalty? Can one vehicle occupy multiple spots?
6. **Entry/exit** — multiple gates operating at once? *(This is the concurrency question — two cars, one spot.)*

---

## Clarifications (locked scope from Q&A)

- **Floors:** multi-level (~3); we track *which* spot a vehicle is in, not just a free-count.
- **Vehicle types:** Motorcycle, Car, Truck.
- **Spot types:** Small, Medium, Large.
- **Fit rules:** Motorcycle → any · Car → Medium/Large · Truck → Large only · one vehicle = one spot (multi-spot = out of scope).
- **Pricing:** hourly, rate by spot type; *model must be swappable* (flat/tiered later).
- **Spot assignment:** first available that fits; *rule must be swappable* (nearest/least-used later).
- **Max time:** none — pay for however long you stay. Lost-ticket penalty = out of scope.

---

## Step 1 — Requirements  ✅ LOCKED

### Functional (what it DOES — the verbs)
- Park: **assign an available spot that fits the vehicle type**, across multiple floors
- Track the time a vehicle is parked (stamp entry time)
- Calculate cost on exit (hourly, by spot type)
- Exit / unpark: free the spot, return the fee

### Non-functional (constraints — the "-ilities")
- **Thread-safe** — two vehicles must never be assigned the same spot  ← the one that changes the code
- **Extensible** — pricing model *and* spot-assignment rule both swappable
- **Testable**

### Explicitly out of scope (say this out loud — senior move)
- Authentication of user
- Vehicle / parking analytics
- Payment-gateway integration · reservations · physical security

> 📝 **Review note (Step 1):** core verbs (park/track/price/exit) were right. Added the **fit-rule + multi-floor** — that's the crux of this problem. Relabeled the non-functionals: "handle the spot correctly" was *functional correctness*, not an "-ility"; the real code-changing NF is **thread-safety** (the two-cars-one-spot race). "Extensible" = the two swap points (pricing, assignment). Same discipline as the URL shortener's `thread-safe` NF.

---

## Step 2 — Entities  (nouns → classes)  ← YOUR TURN
_Format: `Name — single responsibility — key attributes/methods`_

1. **Ticket** — records one parking session so we can price it on exit — `vehicle, spot, entry_time, exit_time?, fee`
2. **Vehicle** — the thing being parked; carries its **type** — `type {Motorcycle|Car|Truck}, license_plate`
3. **ParkingSpot** — one parkable space; knows its type, floor, and if it's free — `id, type {Small|Medium|Large}, floor, is_available; can_fit(vehicle) -> bool`
4. **ParkingFloor** — groups the spots on one level — `floor_number, spots[]`
5. **CostCalculator** *(→ PricingStrategy)* — fee from duration + spot type; **swappable** — `calculate(ticket) -> fee`
6. **SpotAssignmentStrategy** — picks which free, fitting spot to hand out; **swappable** — `find_spot(vehicle, floors) -> spot?`
7. **ParkingLot** — orchestrator; the object clients call — `floors[], park(vehicle) -> Ticket, unpark(ticket) -> fee`

> 📝 **Review note (Step 2):** SRP split was strong (pricing as its own class, spots own their type/availability — mirrors the URL shortener's generator/repo/service). Fixes: (a) named the **type** on Vehicle & Spot — the fit-rule crux; *how* to model it (enum vs subclass) is the open Step 3/4 question that brings in **Factory**. (b) Caught the pricing swap-point but missed its twin → added **SpotAssignmentStrategy** (both were "swappable" breadcrumbs → both become Strategies in Step 4). (c) Fit logic needs a home → `ParkingSpot.can_fit(vehicle)`.

---

## Step 3 — Relationships & APIs
_Signatures before bodies._

**Type modeling decision:** **Enum** (Option A). Motorcycle/Car/Truck differ only in *which spot fits* (data), not behavior → subclasses would be YAGNI. `Vehicle.type` & `ParkingSpot.type` are enums; the fit-rule is a small map read by `ParkingSpot.can_fit`.

**Relationships:**
```
ParkingLot ──composition──▶ ParkingFloor ──composition──▶ ParkingSpot   (owns; die together)
ParkingLot ──uses (DI)────▶ SpotAssignmentStrategy, CostCalculator
Ticket ─────has-a─────────▶ Vehicle, ParkingSpot                        (association)
```

**Signatures (bodies later):**
```python
# ParkingLot (orchestrator)
def park(self, vehicle: Vehicle) -> Ticket        # system picks the spot — no floor arg
def unpark(self, ticket: Ticket) -> float         # returns the fee

# SpotAssignmentStrategy (swappable)
def find_spot(self, vehicle: Vehicle, floors: list[ParkingFloor]) -> Optional[ParkingSpot]

# ParkingSpot
def can_fit(self, vehicle: Vehicle) -> bool       # spot is self; reads the fit-map

# CostCalculator (swappable)
def calculate(self, ticket: Ticket) -> float
```


> 📝 **Review note (Step 3):** Relationships right (composition chain + DI); fixed **"ticket is-a spot"** → has-a (association). Signature fixes: (1) `find_spot` must take **`(vehicle, floors)`** — can't match a fit without the vehicle, and it searches all floors [the real bug]; (2) `park(vehicle)` — **no `floor` arg**, the strategy picks, else swappable-assignment is broken; (3) `can_fit(self, vehicle)` — the spot is `self`; (4) fee is `float`. Locked **enum** type-modeling by YAGNI (subtypes differ by data, not behavior); fit-rule lives in a map read by `can_fit`.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

| LLD method | HTTP |
|---|---|
| `park(vehicle)` | `POST /api/v1/tickets` `{plate, vehicle_type}` -> **201** `{ticket_id, spot_id}` · **409** `VehicleAlreadyParkedError` · **503** `LotFullError` |
| `unpark(plate)` | `POST /api/v1/tickets/{plate}/exit` -> **200** `{fee, duration_hours}` · **404** `VehicleNotFoundError` |
| *(read model)* | `GET /api/v1/availability?vehicle_type=CAR` -> **200** `{free_spots, by_floor}` |

> Notice the **custom exceptions map 1:1 onto status codes** — that is exactly why raising beats
> returning `None`: the error *type* carries meaning all the way out to the caller.

## Notes / decisions (log the "why" here)
- Type modeling = **enum + FIT_RULE map** (not subclasses) → adding a vehicle type = 1 line, no code change (Open/Closed, YAGNI).
- `can_fit` = *type fit only*; availability is separate → assignment strategy combines them.
- `CostCalculator` stays **pure** (reads times, no mutation); `exit_time` is stamped by `unpark` (state transition = orchestrator's job).

> 📝 **Review note (Step 4–5 build):** Two Strategies (assignment + pricing) + DI, mirroring the URL shortener. **Thread-safety crux:** `find-spot → mark-occupied` is one critical section under `self.lock` — the parking-lot form of the `save_if_absent` TOCTOU (two cars, one spot). Edge cases: raise-on-error (LotFull / AlreadyParked / NotFound) over returning `None`; double-park guard prevents spot leak. **Factory** didn't appear from the type model (enum made it YAGNI) — it landed instead in `build_lot()` for lot construction. Pending refinement (like URL shortener's coarse lock): one `self.lock` serializes all park/unpark — fine for scope; finer-grained (per-spot CAS) is the scale story.
