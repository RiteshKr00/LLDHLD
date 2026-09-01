# Problem 3: Elevator System (LLD)

## The prompt (as an interviewer would give it)

> "Design an elevator system for a building."

Deliberately vague. **Your job is to make it concrete** — that's Step 1.

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **How many elevators** — one car, or a bank of N? *(With N, "which car answers this call" becomes the real problem — a dispatcher exists only if N > 1.)*
2. **Request types** — is a button pressed **in the hallway** different from one pressed **inside the car**? *(Yes — and that asymmetry is the heart of the design.)*
3. **Scheduling goal** — minimise wait time? total travel? Should the rule be **swappable**? *(Strategy signal.)*
4. **Building shape** — how many floors? Capacity/weight limit per car?
5. **Special modes** — fire/emergency, maintenance, express floors? *(Usually scope-cut.)*
6. **Concurrency** — can many people press buttons simultaneously? *(Shared target-set mutation.)*

---

## Clarifications (locked scope from Q&A)
- **3 elevators** (N cars) → a **dispatcher** decides which car answers a hall call.
- **Two request types:** **hall call** (at a floor, with a direction up/down → dispatcher assigns a car) vs **car call** (destination floor, from inside → that car only).
- **Goal:** minimize wait + travel → the classic **SCAN / elevator algorithm**; the scheduling rule is **swappable**.
- **5 floors**; **capacity limit** (~240 kg / a few people) — a car can be full.

---

## Step 1 — Requirements  ✅ LOCKED

### Functional (what it DOES — the verbs)
- **Hall call:** request from a floor with a direction (up/down) → a car is dispatched there
- **Car call:** request a destination floor from inside a car → that car goes there
- **Dispatch:** assign the best car to a hall call (swappable rule)
- **Move** between floors, serving requests en route
- **Open / close doors** at a stop
- **Respect capacity** — refuse boarding when full

### Non-functional (constraints — the "-ilities")
- **Extensible** — swappable scheduling / dispatch strategy
- **Thread-safe** — concurrent hall/car calls must not corrupt state
- **Testable**

### Explicitly out of scope (say this out loud — senior move)
- Physical motor / motion control · fire & emergency mode · emergency call · alarm / security

> 📝 **Review note (Step 1):** nailed the crux — **hall call (floor + direction)** vs **car call (destination)** modeled as *distinct* request types (conflating them is the classic mistake). NFs right: extensible scheduling (Strategy breadcrumb), thread-safe (concurrent presses), testable. Added **respect-capacity** as a functional constraint. Least-travel → **SCAN/elevator algorithm** with a swappable rule.

---

## Step 2 — Entities  (nouns → classes)  ← YOUR TURN
_Format: `Name — single responsibility — key attributes/methods`_

1. **Elevator (Car)** — one physical car; where it is + what it must serve — `id, current_floor, direction, state, targets: set[int]`
2. **HallRequest** (outside) — a call at a floor going a way — `source_floor, direction` *(no destination)*
3. **CarRequest** (inside) — a destination pressed in a car — `destination_floor` *(no direction; belongs to one car)*
4. **Direction** *(enum)* — `UP / DOWN / IDLE`
5. **ElevatorSystem / Controller** — orchestrator; receives requests, dispatches a car, routes car calls — `elevators[], request_hall(floor, dir), request_car(car, floor), step()`
6. **SchedulingStrategy** *(swappable)* — picks which car answers a hall call + orders its stops — `select_car(request, elevators)`

> 📝 **Review note (Step 2):** entities right; key correction — a **hall call has no destination** (`source_floor + direction` only); a **car call has no direction** (`destination_floor`). That asymmetry is the whole scheduling problem. Named `Direction` as an enum. Orchestrator = `ElevatorSystem`; the swappable rule = `SchedulingStrategy` (Strategy, like parking's assignment). `state` on the Car → the State pattern in Step 4.

---

## Step 3 — Relationships & APIs
_Signatures before bodies._

**Relationships:**
```
ElevatorSystem ──composition──▶ Elevator[]        (owns the N cars)
ElevatorSystem ──uses (DI)────▶ SchedulingStrategy
Elevator ──has──▶ targets: set[int], state
HallRequest / CarRequest ──▶ received by ElevatorSystem (inputs from buttons), routed to a car
```

**Signatures:**
```python
# ElevatorSystem (orchestrator)
def request_hall(self, floor: int, direction: Direction) -> None   # ⬆/⬇ pressed in a hallway
def request_car(self, car_id: int, dest_floor: int) -> None        # floor pressed inside a car
def step(self) -> None                                             # one tick: advance every elevator

# SchedulingStrategy (swappable)
def select_car(self, request: HallRequest, elevators: list[Elevator]) -> Elevator

# Elevator
def add_target(self, floor: int) -> None
def step(self) -> None      # behavior depends on state -> State pattern (Step 4)
```

> 📝 **Review note (Step 3):** relationships right (composition + DI). Minor: requests are **received** from users/buttons (inputs the orchestrator *routes*), not generated by it; system-level tick named **`step()`** (advance all cars), not `next_floor()`. Open decision: `Elevator.step()` behaves differently per state → **State pattern vs enum**, settled entering Step 4 (states have different *behavior* → State pattern earns it, unlike parking's data-only enum).

---

---

## REST API mapping  (LLD method -> HLD endpoint)

| LLD method | HTTP |
|---|---|
| `request_hall(HallRequest(floor, dir))` | `POST /api/v1/calls` `{floor, direction}` -> **202** `{assigned_car, eta}` · **503** `NoAvailableCarError` |
| `request_car(car_id, CarRequest(dest))` | `POST /api/v1/elevators/{car_id}/destinations` `{floor}` -> **202** |
| *(read model)* | `GET /api/v1/elevators` -> **200** `[{id, floor, state, direction}, ...]` |
| `step()` | **not an endpoint** — it is the real-time control tick, which per the HLD stays **on the edge**, never a cloud call |

**202, not 200** — the lift has not arrived; we have only *accepted* the request.

## Notes / decisions (log the "why" here)
- **State pattern** for elevator behavior (Idle/Moving/DoorOpen) — states differ by *behavior*, so State earns it (opposite of parking's data-only enum). Zero `if state==` in the codebase; `Elevator.step()` just delegates to `self.state.step(self)`.
- Each state owns its transition + one job: Moving *moves*, DoorOpen *services* (`targets.discard`), Idle *waits*.
- `targets` = `set[int]` (dedup); MovingState picks **nearest** target (SCAN/direction-aware = noted optimization).
- Scheduling = **Strategy** (`NearestCarStrategy`), capacity-aware (skips full cars); DI into `ElevatorSystem`.
- **Discrete `step()` tick** models motion without real time (mini game-loop).

> 📝 **Review note (Step 4–5 build):** State pattern clean (ABC + 3 states + delegation). Fixes en route: `field(default_factory=...)` for `state`/`targets` (mutable-default rule → saved to `LLD-patterns.md`); `MovingState` picks nearest target (was FIFO `[0]` on a set = bug); DoorOpen owns the serve. Step-5 completions: **capacity** (dispatcher skips full cars, `NoAvailableCarError` when all full), O(1) `_by_id` routing, custom errors. Honest simplification: occupancy set externally (auto pickup/dropoff needs pickup-vs-dropoff intent on targets = extension). Thread-safe: all request/step bodies under one lock.
