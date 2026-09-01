"""
Elevator System — LLD solution (built step by step).

Entities (Step 2):
    1. Direction (enum)        - UP / DOWN / IDLE
    2. HallRequest             - outside call: source_floor + direction (no destination)
    3. CarRequest              - inside call: destination_floor (one car)
    4. ElevatorState (State)   - Idle / Moving / DoorOpen — behavior differs per state
    5. Elevator (Car)          - current_floor, direction, state, targets; step() delegates to state
    6. SchedulingStrategy      - picks which car answers a hall call (swappable) [Strategy]
    7. ElevatorSystem          - orchestrator; request_hall / request_car / step()
"""

from __future__ import annotations   # lets states type-hint Elevator before it's defined
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import threading


class NoAvailableCarError(Exception):
    """Every car is full — no car can take this hall call."""


# ---------------------------------------------------------------------------
# Step 4a: Direction + Request types
#
# HINT (to rebuild) — the ASYMMETRY is the heart of this problem. Two request
# types that look similar but carry DIFFERENT fields:
#   HallRequest (pressed OUTSIDE, in the hallway):
#       source_floor + direction  -- and NO destination! You haven't said where
#       you're going yet. The dispatcher must CHOOSE a car for it.
#   CarRequest (pressed INSIDE the car):
#       destination_floor only    -- NO direction (it's implied by dest vs current),
#       and it already belongs to one specific car — nothing to dispatch.
# Modelling them as one class with a type flag is the classic mistake: the
# fields genuinely differ, and the orchestrator treats them differently.
# Direction is a plain enum (UP/DOWN/IDLE) — labels, no behaviour.
#
#   1. Direction(Enum)  -> UP, DOWN, IDLE
#   2. HallRequest      -> source_floor: int, direction: Direction   (no destination)
#   3. CarRequest       -> destination_floor: int                    (no direction)
# ---------------------------------------------------------------------------

class Directions(Enum):
    UP = "up"
    DOWN = "down"
    IDLE = "idle"

class HallRequest:
    def __init__(self, source_floor: int, direction: Directions):
        self.source_floor = source_floor
        self.direction = direction

class CarRequest:
    def __init__(self,destination_floor: int):
        self.destination_floor = destination_floor



# ---------------------------------------------------------------------------
# Step 4b: ElevatorState (State pattern) — ABC + IdleState / MovingState / DoorOpenState
#
# HINT (to rebuild) — THE decision of this problem. `state` looks like a plain
# field, so the instinct is `state: str` + `if state == "moving": ...`.
# Run the test: DO THE TYPES DIFFER BY DATA, OR BY BEHAVIOUR?
#   Parking's vehicle types: same behaviour, only which-spot-fits differs
#       -> DATA -> enum + a lookup map. Subclasses would be YAGNI.
#   Elevator's states: step() does genuinely DIFFERENT things per state, and
#       each state has its own transition rules
#       -> BEHAVIOUR -> State pattern earns its place.
#
# Shape: an ABC with step(self, elevator), one class per state. Each state does
# its work AND sets elevator.state to the next one. The payoff: Elevator.step()
# becomes a single delegating line — zero `if state ==` anywhere in the codebase,
# and adding MAINTENANCE/EMERGENCY later is a NEW CLASS, not a bigger if-chain
# (Open/Closed).
#
# Transition table:
#   Idle     -> nothing; if targets exist -> MovingState
#   Moving   -> if already AT a target -> DoorOpenState
#               else step ONE floor toward the nearest target, set direction
#   DoorOpen -> serve THIS floor (targets.discard(current_floor)), then
#               MovingState if targets remain else IdleState
# Keep responsibilities honest: Moving MOVES, DoorOpen SERVICES (the discard
# belongs in DoorOpen — that's the moment passengers actually get out).
# Note: targets is a SET, so you can't index it — pick with
#   min(targets, key=lambda f: abs(f - current_floor))  (true SCAN is the upgrade)
# ---------------------------------------------------------------------------

class State(ABC):
    @abstractmethod
    def step(self, elevator: "Elevator") -> None:
        ...


class IdleState(State):
    """Parked. Nothing to do until a target appears."""

    def step(self, elevator):
        if elevator.targets:
            elevator.state = MovingState()


class MovingState(State):
    """Between floors. Each tick: if we're AT a target open doors, else move one floor."""

    def step(self, elevator):
        if not elevator.targets:                    # nothing left to serve
            elevator.direction = Directions.IDLE
            elevator.state = IdleState()
            return

        if elevator.current_floor in elevator.targets:   # arrived -> service it
            elevator.state = DoorOpenState()
            return

        # move ONE floor toward the nearest target (SCAN is the scheduling refinement)
        target = min(elevator.targets, key=lambda f: abs(f - elevator.current_floor))
        if target > elevator.current_floor:
            elevator.current_floor += 1
            elevator.direction = Directions.UP
        else:
            elevator.current_floor -= 1
            elevator.direction = Directions.DOWN


class DoorOpenState(State):
    """Doors open at a target floor: passengers board/exit -> the floor is served."""

    def step(self, elevator):
        elevator.targets.discard(elevator.current_floor)   # serve THIS floor
        if elevator.targets:
            elevator.state = MovingState()
        else:
            elevator.direction = Directions.IDLE
            elevator.state = IdleState()



# ---------------------------------------------------------------------------
# Step 4c: Elevator (Car) — holds state + targets; step() delegates to state
#
# HINT (to rebuild): fields = id, current_floor, capacity, occupancy, direction,
# state, targets. Methods: add_target(floor) and step().
#   step() must be ONE line: `self.state.step(self)`. If you feel the urge to
#   write any `if` about state here, stop — that logic belongs in the state classes.
#
#   ** MUTABLE DEFAULTS — the rule is about WHEN the default is evaluated:
#        `targets: set[int] = set()`             -> evaluated ONCE at class
#            definition; all elevators would share one set. dataclass RAISES
#            ValueError to stop you -> use field(default_factory=set)
#        `state: State = IdleState()`            -> same shared-instance smell,
#            but dataclass does NOT catch it (it only guards set/list/dict)
#            -> use field(default_factory=IdleState) anyway
#        `self.targets = set()` inside __init__  -> runs every call -> always safe
#      (A plain class works fine too — just never put a mutable in a DEFAULT.)
# ---------------------------------------------------------------------------
@dataclass
class Elevator:
    id: int
    current_floor: int = 0
    capacity: int = 8                                 # max riders
    occupancy: int = 0                                # current riders
    direction: Directions = Directions.IDLE
    state: State = field(default_factory=IdleState)   # fresh state per elevator
    targets: set[int] = field(default_factory=set)    # fresh set per elevator

    @property
    def is_full(self) -> bool:
        return self.occupancy >= self.capacity

    def step(self) -> None:
        """One tick of time: delegate to the current state."""
        self.state.step(self)

    def add_target(self, floor: int) -> None:
        self.targets.add(floor)
    # NOTE: `occupancy` is an input (weight sensor / boarding API); the dispatcher
    # reads `is_full` to skip full cars. Auto-updating it on pickup/dropoff needs
    # pickup-vs-dropoff intent on `targets` — a deliberate extension, left out (YAGNI).


# ---------------------------------------------------------------------------
# Step 4d: SchedulingStrategy (ABC) + a concrete (e.g. nearest-car)
# ---------------------------------------------------------------------------
class SchedulingStrategy(ABC):
    @abstractmethod
    def choose_elevator(self, elevators: list[Elevator], hall_request: HallRequest) -> Optional[Elevator]:
        ...

class NearestCarStrategy(SchedulingStrategy):
    """Nearest car to the hall floor, skipping full cars (capacity requirement)."""

    def choose_elevator(self, elevators: list[Elevator], hall_request: HallRequest) -> Optional[Elevator]:
        available = [e for e in elevators if not e.is_full]
        if not available:
            return None
        return min(available, key=lambda e: abs(e.current_floor - hall_request.source_floor))

# ---------------------------------------------------------------------------
# Step 4e: ElevatorSystem (orchestrator) — request_hall / request_car / step(), thread-safety
#
# HINT (to rebuild): this is where the Step-2 asymmetry finally pays off —
# the two request types are handled COMPLETELY differently:
#   request_hall(req)  -> no car assigned yet, so ASK THE STRATEGY to choose one
#                         (skipping full cars), then chosen.add_target(source_floor).
#                         All cars full -> raise NoAvailableCarError.
#   request_car(id, r) -> already belongs to that car; just route by id and
#                         add_target(destination). No strategy involved.
#   step()             -> one tick: loop every elevator, call its step().
#
#   Route by id with a `{id: elevator}` dict built in __init__ (O(1) + a clean
#   error on unknown id) rather than a linear scan.
#
#   THREAD-SAFETY: button presses mutate `targets` while step() reads/mutates
#   the same set -> wrap all three method bodies in `with self.lock:`.
#
#   Capacity: keep the "is this car full?" check in the STRATEGY (it filters
#   candidates), not inside the state classes. Occupancy itself is an INPUT
#   (weight sensor / boarding API) — auto-updating it would need pickup-vs-
#   dropoff intent on each target, which is a deliberate extension (YAGNI).
# ---------------------------------------------------------------------------

class ElevatorSystem:
    """Orchestrates the elevators, hall requests, and car requests."""

    def __init__(self, elevators: list[Elevator], scheduling_strategy: SchedulingStrategy):
        self.elevators = elevators
        self.scheduling_strategy = scheduling_strategy
        self._by_id = {e.id: e for e in elevators}   # O(1) car-call routing
        self.lock = threading.Lock()  # for thread-safety

    def request_hall(self, hall_request: HallRequest) -> None:
        """A hall call (outside): the dispatcher picks a non-full car."""
        with self.lock:
            chosen_elevator = self.scheduling_strategy.choose_elevator(self.elevators, hall_request)
            if chosen_elevator is None:
                raise NoAvailableCarError(f"all cars full for hall call at {hall_request.source_floor}")
            chosen_elevator.add_target(hall_request.source_floor)

    def request_car(self, elevator_id: int, car_request: CarRequest) -> None:
        """A car call (inside): route to that specific car."""
        with self.lock:
            elevator = self._by_id.get(elevator_id)
            if elevator is None:
                raise KeyError(f"no elevator with id {elevator_id}")
            elevator.add_target(car_request.destination_floor)

    def step(self) -> None:
        """One tick of time: advance all elevators."""
        with self.lock:
            for elevator in self.elevators:
                elevator.step()


if __name__ == "__main__":
    # 3 staggered cars
    e0, e1, e2 = Elevator(0, current_floor=0), Elevator(1, current_floor=4), Elevator(2, current_floor=2)
    system = ElevatorSystem([e0, e1, e2], NearestCarStrategy())

    def show(label):
        print(f"{label:>6}: " + "  ".join(
            f"E{e.id}@{e.current_floor}[{type(e.state).__name__[:-5]}] tgt={sorted(e.targets)}"
            for e in (e0, e1, e2)))

    # capacity rule: mark E2 (the nearest to floor 3) FULL → dispatcher must skip it
    e2.occupancy = e2.capacity
    system.request_hall(HallRequest(3, Directions.UP))     # E2 is nearest but full -> goes to E1
    system.request_car(0, CarRequest(5))                   # car call routed to E0

    show("start")
    for t in range(7):
        system.step()
        show(f"t={t}")

    # all cars full -> hall call is refused
    for e in (e0, e1, e2):
        e.occupancy = e.capacity
    try:
        system.request_hall(HallRequest(1, Directions.DOWN))
    except NoAvailableCarError as ex:
        print("refused:", ex)

# ===========================================================================
# REST API MAPPING  (LLD method  ->  HLD endpoint)
#
#   request_hall(HallRequest(floor, direction))
#       POST /api/v1/calls
#       body   {"floor": 3, "direction": "UP"}
#       202    Accepted {"assigned_car": 1, "eta_seconds": 25}
#       503    all cars full                     <- NoAvailableCarError
#       ^ 202 not 200: the lift hasn't arrived yet, we've only accepted the request
#
#   request_car(car_id, CarRequest(destination))
#       POST /api/v1/elevators/{car_id}/destinations
#       body   {"floor": 7}
#       202    Accepted
#
#   (read model)
#       GET /api/v1/elevators
#       200    [{"id": 0, "floor": 3, "state": "MovingState", "direction": "UP"}, ...]
#
#   step()  -> NOT an endpoint. It's the simulation tick. In a real system this is
#              the embedded controller's real-time loop, which per the HLD stays
#              ON THE EDGE and never becomes a cloud API call.
# ===========================================================================
