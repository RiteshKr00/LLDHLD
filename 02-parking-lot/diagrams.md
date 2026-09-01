# Parking Lot — Diagrams

## 0. THE LOT AT START — what the data actually looks like

```
   FLOOR 2      [S]  [S]      [M]  [M]      [L]
                 1    2        3    4        5

   FLOOR 1      [S]  [S]      [M]  [M]      [L]
                 1    2        3    4        5
                                              ▲
                          ENTRY ──────────────┘

   [S]=SMALL  [M]=MEDIUM  [L]=LARGE      all AVAILABLE at start
```

### Who can park where

```
                 [S]      [M]      [L]
   🏍  MOTORCYCLE  ✓        ✓        ✓      (fits anywhere)
   🚗  CAR         ✗        ✓        ✓
   🚚  TRUCK       ✗        ✗        ✓      (large only)
```

### In memory

```python
lot.floors = [
    ParkingFloor(1, [ParkingSpot("1-small-0", SMALL, floor=1, is_available=True),
                     ParkingSpot("1-small-1", SMALL, floor=1, is_available=True),
                     ParkingSpot("1-medium-0", MEDIUM, floor=1, ...), ...]),
    ParkingFloor(2, [...]),
]
lot.active_tickets = {}        # plate -> Ticket   (empty at start)
lot.lock = Lock()              # ONE lock for the whole lot
```

### After a truck parks

```
   FLOOR 1      [S]  [S]      [M]  [M]      [X]     <- 1-large-0 taken
                                              ▲
                              Ticket("MH-03-T") -> spot 1-large-0, entry 14:30

   lot.active_tickets = {"MH-03-T": Ticket(vehicle, spot, entry_time)}
                          ^ keyed by PLATE, so unpark(plate) can find it
```

---

## 1. The fit rule as a picture

```
                    SMALL    MEDIUM    LARGE
   MOTORCYCLE         ✓         ✓         ✓
   CAR                ✗         ✓         ✓
   TRUCK              ✗         ✗         ✓
```

That table **is** the code:
```python
FIT_RULE = {
    MOTORCYCLE: {SMALL, MEDIUM, LARGE},
    CAR:        {MEDIUM, LARGE},
    TRUCK:      {LARGE},
}
```
Adding a scooter = **one row of data**, not an `elif`. That's Open/Closed in practice.

## 2. Spot lifecycle (deliberately simple — compare with Movie Booking)

```mermaid
stateDiagram-v2
    [*] --> AVAILABLE
    AVAILABLE --> OCCUPIED : park() claims it
    OCCUPIED --> AVAILABLE : unpark()
```

> **Only two states here** — because a car physically arrives at the moment it parks. The movie
> problem has a third state (`HELD`) because there's a gap between *choosing* and *paying*. That gap
> is what creates all the difficulty there and none here.

## 3. `park()` — the critical section

```mermaid
flowchart TD
    A[park vehicle] --> B[acquire lock]
    B --> C{plate already parked?}
    C -->|yes| D[raise VehicleAlreadyParkedError<br/>else its old spot leaks forever]
    C -->|no| E[strategy.assign_spot<br/>find first fitting FREE spot]
    E --> F{found?}
    F -->|no| G[raise LotFullError]
    F -->|yes| H[spot.is_available = False<br/>CLAIM it]
    H --> I[create Ticket, store by plate]
    I --> J[release lock]
    D --> J
    G --> J

    style B fill:#1a3a5c,color:#fff
    style J fill:#1a3a5c,color:#fff
    style H fill:#2d5016,color:#fff
```

**The whole find→claim sequence is inside ONE lock.** Release it after `assign_spot` and two cars
both get handed the same free spot.

## 4. Class diagram

```mermaid
classDiagram
    class VehicleType {
        <<enum>>
        MOTORCYCLE
        CAR
        TRUCK
    }
    class SpotType {
        <<enum>>
        SMALL
        MEDIUM
        LARGE
    }
    class Vehicle {
        +VehicleType vehicle_type
        +str license_plate
    }
    class ParkingSpot {
        +str id
        +SpotType type
        +int floor
        +bool is_available
        +can_fit(vehicle) bool
    }
    class ParkingFloor {
        +int floor_number
        +List~ParkingSpot~ spots
    }
    class Ticket {
        +Vehicle vehicle
        +ParkingSpot spot
        +datetime entry_time
        +datetime exit_time
        +float fee
    }
    class SpotAssignmentStrategy {
        <<abstract>>
        +assign_spot(floors, vehicle) ParkingSpot
    }
    class FirstAvailableSpotAssignmentStrategy
    class CostCalculator {
        <<abstract>>
        +calculate_fee(ticket) float
    }
    class SimpleCostCalculator {
        +RATES dict
    }
    class ParkingLot {
        -Lock lock
        -dict active_tickets
        +park(vehicle) Ticket
        +unpark(plate) float
    }

    ParkingFloor "1" *-- "many" ParkingSpot
    Ticket --> Vehicle
    Ticket --> ParkingSpot
    SpotAssignmentStrategy <|-- FirstAvailableSpotAssignmentStrategy
    CostCalculator <|-- SimpleCostCalculator
    ParkingLot "1" *-- "many" ParkingFloor
    ParkingLot --> SpotAssignmentStrategy : uses (DI)
    ParkingLot --> CostCalculator : uses (DI)
    ParkingLot ..> Ticket : creates
```

**Two Strategies** — because the requirements said *two* things were swappable (pricing **and**
assignment). Spotting both is the whole trick; it's easy to catch pricing and miss assignment.

## 5. `can_fit` vs `is_available` — two different questions

```
   can_fit(vehicle)      "COULD this vehicle ever use this spot?"   -> about TYPES
   is_available          "is it free RIGHT NOW?"                    -> about STATE

   assignment strategy asks BOTH:
       if spot.is_available and spot.can_fit(vehicle):
```

Merging them into `can_fit` makes the name lie, and breaks a query like *"how many car-compatible
spots exist in total?"* (occupied ones included).
