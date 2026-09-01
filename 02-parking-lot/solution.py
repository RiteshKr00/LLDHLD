"""
Parking Lot — LLD solution (built step by step).

Entities (Step 2):
    1. Vehicle                 - the thing parked; carries a type (enum)
    2. ParkingSpot             - one space; type + floor + availability; can_fit()
    3. ParkingFloor            - groups spots on one level
    4. Ticket                  - one parking session (for pricing)
    5. SpotAssignmentStrategy  - picks a free, fitting spot (swappable)  [Strategy]
    6. CostCalculator          - fee from duration + spot type (swappable) [Strategy]
    7. ParkingLot              - orchestrator; park() / unpark()
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from math import ceil
from enum import Enum
from typing import Optional
import threading


# ---------------------------------------------------------------------------
# Errors — explicit, so callers can map them to API responses (409/404 etc.)
# ---------------------------------------------------------------------------
class ParkingError(Exception):
    """Base for all parking-lot errors."""


class LotFullError(ParkingError):
    """No free spot fits the vehicle."""


class VehicleAlreadyParkedError(ParkingError):
    """This plate is already parked (would leak the first spot)."""


class VehicleNotFoundError(ParkingError):
    """No active ticket for this plate on unpark."""


# ---------------------------------------------------------------------------
# Step 4a: Types & the fit rule   <-- YOUR TURN
#
# An `Enum` is a fixed set of named constants (VehicleType.CAR, SpotType.LARGE).
# Use it instead of raw strings so typos fail loudly and the set is closed.
#
# Build:
#   1. VehicleType enum  -> MOTORCYCLE, CAR, TRUCK
#   2. SpotType enum     -> SMALL, MEDIUM, LARGE
#   3. FIT_RULE          -> a dict: which SpotTypes accept which VehicleType
#                           (motorcycle -> any; car -> medium/large; truck -> large)
# ---------------------------------------------------------------------------
class VehicleType(Enum):
    MOTORCYCLE = "motorcycle"
    CAR = "car"
    TRUCK = "truck"

class SpotType(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

FIT_RULE ={
    VehicleType.MOTORCYCLE: {SpotType.SMALL, SpotType.MEDIUM, SpotType.LARGE},
    VehicleType.CAR: {SpotType.MEDIUM, SpotType.LARGE},
    VehicleType.TRUCK: {SpotType.LARGE}
}


# ---------------------------------------------------------------------------
# Step 4b: Vehicle & ParkingSpot  (data holders; ParkingSpot gets can_fit)
#
# HINT (to rebuild):
#   Vehicle     -> vehicle_type (enum) + license_plate. That's it.
#   ParkingSpot -> id, spot_type (enum), floor, is_available (defaults True).
#   can_fit(vehicle) -> ONE line: `return self.type in FIT_RULE[vehicle.type]`
#
#   ** The trap: can_fit must check TYPE FIT ONLY — do NOT also check
#      is_available. They answer different questions:
#        can_fit      = "could this vehicle EVER use this spot?" (about types)
#        is_available = "is it free RIGHT NOW?"                  (about state)
#      Merging them makes the name lie and hides a 2nd responsibility (SRP).
#      The assignment strategy combines them: `spot.is_available and spot.can_fit(v)`
#      Concretely: a merged can_fit can't answer "how many car-compatible
#      spots exist in total?" (occupied ones included).
# ---------------------------------------------------------------------------
@dataclass
class Vehicle:
    vehicle_type: VehicleType
    license_plate: str

@dataclass
class ParkingSpot:
    id :str
    type: SpotType
    floor: int
    is_available: bool = True

    def can_fit(self, vehicle: Vehicle) -> bool:
        """Check if the vehicle can fit in this spot based on the FIT_RULE."""
        return self.type in FIT_RULE[vehicle.vehicle_type]

# ---------------------------------------------------------------------------
# Step 4c: ParkingFloor & Ticket
#
# HINT (to rebuild):
#   ParkingFloor -> floor_number + spots: list[ParkingSpot]
#     ** Use field(default_factory=list), NOT `spots: list = []`.
#        A bare [] is evaluated ONCE at class-definition time, so every floor
#        would share the SAME list object. dataclass raises ValueError to stop you.
#   Ticket -> vehicle, spot, entry_time, exit_time (Optional), fee (Optional)
#     Hold a reference to the SPOT, don't copy floor/spot_type onto the ticket —
#     you get them via ticket.spot.floor, and copies can drift out of sync.
#     entry_time can auto-stamp: field(default_factory=lambda: datetime.now(timezone.utc))
# ---------------------------------------------------------------------------

@dataclass
class ParkingFloor:
    floor_number: int
    spots: list[ParkingSpot] = field(default_factory=list)

@dataclass
class Ticket:
    vehicle: Vehicle
    spot: ParkingSpot
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exit_time:Optional[datetime] = None
    fee: Optional[float] = None

# ---------------------------------------------------------------------------
# Step 4d: Strategies — SpotAssignmentStrategy (ABC) & CostCalculator (ABC)
#
# HINT (to rebuild): Step 1 said pricing AND assignment must be "swappable" —
# TWO swap-points => TWO Strategy ABCs. (Spotting both is the whole trick;
# it's easy to catch the pricing one and miss the assignment one.)
#
#   SpotAssignmentStrategy.assign_spot(floors, vehicle) -> Optional[ParkingSpot]
#     FirstAvailable: nested loop over floors -> spots; return the first where
#     `spot.is_available and spot.can_fit(vehicle)`. Return None if the lot's full
#     (the ORCHESTRATOR decides what None means — raise vs reject).
#
#   CostCalculator.calculate_fee(ticket) -> float
#     Simple: ceil(duration_hours) * RATES[spot_type]. Round UP — a started
#     hour bills as a full hour. Keep rates as a DICT (data), not if/elif.
#     ** Keep it PURE: read times, return a number, mutate NOTHING.
#        Setting ticket.exit_time in here is a state transition — that's
#        unpark()'s job. A "calculate" that secretly checks a car out is a trap
#        (asking for a price quote would silently end the session).
#        Use a local: `end = ticket.exit_time or datetime.now(timezone.utc)`
# ---------------------------------------------------------------------------
class SpotAssignmentStrategy(ABC):
    @abstractmethod
    def assign_spot(self, floors: list[ParkingFloor], vehicle: Vehicle) -> Optional[ParkingSpot]:
        """Return a free spot that fits the vehicle, or None if none available."""
        pass

class FirstAvailableSpotAssignmentStrategy(SpotAssignmentStrategy):
    def assign_spot(self, floors:list[ParkingFloor], vehicle: Vehicle) -> Optional[ParkingSpot]:
        """Return the first available spot that fits the vehicle, or None if none available."""
        for floor in floors:
            for spot in floor.spots:
                if spot.is_available and spot.can_fit(vehicle):
                    return spot
        return None

class CostCalculator(ABC):
    @abstractmethod
    def calculate_fee(self, ticket: Ticket) -> float:
        """Calculate the fee based on the ticket's entry and exit times."""
        pass
class SimpleCostCalculator(CostCalculator):

    RATES = {
        SpotType.SMALL: 1.0,   # $1 per hour
        SpotType.MEDIUM: 2.0,  # $2 per hour
        SpotType.LARGE: 3.0    # $3 per hour    
        }

    def calculate_fee(self, ticket: Ticket) -> float:
        """Calculate a simple fee based on duration and spot type."""
        
        end = ticket.exit_time or datetime.now(timezone.utc)
        duration_hours = ceil((end - ticket.entry_time).total_seconds() / 3600)    
        return duration_hours * self.RATES[ticket.spot.type]                     

# ---------------------------------------------------------------------------
# Step 4e: ParkingLot (orchestrator) — park() / unpark(), thread-safety
#
# HINT (to rebuild):
#   __init__ -> inject floors + BOTH strategies (DI). Keep active_tickets as a
#               dict keyed by license_plate so unpark(plate) can find the ticket.
#
#   park(vehicle):
#     1. reject if this plate is ALREADY parked — otherwise the dict entry is
#        overwritten and the first spot stays occupied FOREVER (a leak).
#     2. ask the strategy for a spot; None -> raise LotFullError
#     3. claim it: spot.is_available = False, build the Ticket, store it
#
#     ** THREAD-SAFETY (the whole reason this NF existed): steps 2+3 are a
#        CHECK-then-ACT. Two threads can both be handed the same free spot
#        before either marks it taken -> two cars, one spot. This is TOCTOU,
#        the same race as the URL shortener's exists()+save().
#        Fix: the ENTIRE find->claim sequence goes inside ONE `with self.lock:`.
#        Releasing between find and claim reopens the gap.
#
#   unpark(plate): pop the ticket (None -> raise), stamp exit_time HERE (state
#     transition belongs to the orchestrator), compute the fee, free the spot.
#
#   Errors: prefer raising (LotFullError / AlreadyParked / NotFound) over
#   returning None — it keeps `park() -> Ticket` clean and makes "full" impossible
#   to ignore. Named exceptions also map cleanly to HTTP codes later.
# ---------------------------------------------------------------------------
class ParkingLot:
    def __init__(self, floors: list[ParkingFloor], spot_strategy: SpotAssignmentStrategy, cost_calculator: CostCalculator):
        self.floors = floors
        self.spot_strategy = spot_strategy
        self.cost_calculator = cost_calculator
        self.active_tickets: dict[str, Ticket] = {}  # license_plate -> Ticket
        self.lock = threading.Lock()  # For thread-safety

    def park(self, vehicle: Vehicle) -> Ticket:
        """Park a vehicle and return its ticket.

        Raises VehicleAlreadyParkedError if the plate is already parked,
        LotFullError if no fitting spot is free.
        find-spot -> claim must be one critical section (else two cars, one spot).
        """
        with self.lock:
            if vehicle.license_plate in self.active_tickets:
                raise VehicleAlreadyParkedError(vehicle.license_plate)

            spot = self.spot_strategy.assign_spot(self.floors, vehicle)
            if spot is None:
                raise LotFullError(vehicle.vehicle_type)

            spot.is_available = False
            ticket = Ticket(vehicle=vehicle, spot=spot)
            self.active_tickets[vehicle.license_plate] = ticket
            return ticket

    def unpark(self, license_plate: str) -> float:
        """Unpark a vehicle by plate and return the fee.

        Raises VehicleNotFoundError if the plate has no active ticket.
        """
        with self.lock:
            ticket = self.active_tickets.pop(license_plate, None)
            if ticket is None:
                raise VehicleNotFoundError(license_plate)

            ticket.exit_time = datetime.now(timezone.utc)   # state transition lives here
            fee = self.cost_calculator.calculate_fee(ticket)
            ticket.spot.is_available = True                  # free the spot
            return fee


# ---------------------------------------------------------------------------
# Builder helper — this is where a "Factory" earns its place: stamp out the
# lot's floors/spots from a simple config, instead of hand-wiring each spot.
# ---------------------------------------------------------------------------
def build_lot(floors: int, per_floor: dict[SpotType, int]) -> list[ParkingFloor]:
    result = []
    for f in range(1, floors + 1):
        spots = []
        for spot_type, count in per_floor.items():
            for i in range(count):
                spots.append(ParkingSpot(f"{f}-{spot_type.value}-{i}", spot_type, f))
        result.append(ParkingFloor(f, spots))
    return result


# ---------------------------------------------------------------------------
# Demo / function-calling code
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 2 floors, each with 1 small / 1 medium / 1 large spot
    floors = build_lot(2, {SpotType.SMALL: 1, SpotType.MEDIUM: 1, SpotType.LARGE: 1})
    lot = ParkingLot(floors, FirstAvailableSpotAssignmentStrategy(), SimpleCostCalculator())

    # --- park three vehicle types ---
    bike = Vehicle(VehicleType.MOTORCYCLE, "MH-01-B")
    car = Vehicle(VehicleType.CAR, "MH-02-C")
    truck = Vehicle(VehicleType.TRUCK, "MH-03-T")

    for v in (bike, car, truck):
        t = lot.park(v)
        print(f"parked {v.vehicle_type.value:10} ({v.license_plate}) -> spot {t.spot.id}")

    # --- unpark the car (backdate entry 1h1m -> ceil to 2h * medium(2.0) = 4.0) ---
    car_ticket = lot.active_tickets[car.license_plate]
    car_ticket.entry_time = datetime.now(timezone.utc) - timedelta(hours=1, minutes=1)
    print(f"unpark {car.license_plate} -> fee {lot.unpark(car.license_plate)}")

    # --- error paths ---
    try:
        lot.park(bike)                              # already parked
    except VehicleAlreadyParkedError as e:
        print(f"double-park rejected: {e}")

    try:
        lot.unpark("GHOST-1")                       # never parked
    except VehicleNotFoundError as e:
        print(f"unknown plate rejected: {e}")

    try:
        # fill every LARGE spot, then one more truck -> lot full for trucks
        lot.park(Vehicle(VehicleType.TRUCK, "MH-04-T"))   # takes the 2nd large
        lot.park(Vehicle(VehicleType.TRUCK, "MH-05-T"))   # no large left
    except LotFullError as e:
        print(f"lot full rejected for: {e}")

