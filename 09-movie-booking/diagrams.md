# Movie Booking — Diagrams

## 0. THE HALL AT START — what the data actually looks like

```
                    ┌──────────────────────────┐
                    │         SCREEN           │
                    └──────────────────────────┘

   RECLINER   C1    C2    C3                      ₹500
             [ ]   [ ]   [ ]

   PREMIUM    B1    B2    B3    B4                ₹350
             [ ]   [ ]   [ ]   [ ]

   REGULAR    A1    A2    A3    A4    A5          ₹200
             [ ]   [ ]   [ ]   [ ]   [ ]

             [ ] = AVAILABLE    [~] = HELD    [X] = BOOKED
```

### The same hall, three different shows

```
   Screen 1 has ONE set of physical seats:
        Seat("A1", REGULAR), Seat("A2", REGULAR), ... Seat("C3", RECLINER)
        ^ these have NO status. Ever.

   But three shows run on it today:

   3pm show          6pm show          9pm show
   A1 [ ]            A1 [X]            A1 [~]
   A2 [ ]            A2 [X]            A2 [ ]
   A3 [X]            A3 [ ]            A3 [ ]
   ...               ...               ...

   ONE Seat("A1")  ──┬── ShowSeat(3pm) : AVAILABLE
                     ├── ShowSeat(6pm) : BOOKED
                     └── ShowSeat(9pm) : HELD by Bob, expires 20:47
```

**That's the whole reason `ShowSeat` exists.** Put `status` on `Seat` and booking A1 for the 6pm show
would book it for every show of the day.

### In memory it's this

```python
# static catalogue — built once
screen.seats = [Seat("A1", REGULAR), Seat("A2", REGULAR), ..., Seat("C3", RECLINER)]

# per-show state — one dict per show, built by register_show()
service._show_seats = {
    "3pm_show": {"A1": ShowSeat(AVAILABLE), "A2": ShowSeat(AVAILABLE), ...},
    "6pm_show": {"A1": ShowSeat(BOOKED),    "A2": ShowSeat(BOOKED),    ...},
    "9pm_show": {"A1": ShowSeat(HELD, held_by=Bob, expires=20:47), ...},
}

service._locks = {"3pm_show": Lock(), "6pm_show": Lock(), "9pm_show": Lock()}
                   ^ ONE LOCK PER SHOW — the 3pm rush must not block 9pm buyers
```

---

## 1. Seat lifecycle (the crux of this problem)

```mermaid
stateDiagram-v2
    [*] --> AVAILABLE : show registered
    AVAILABLE --> HELD : hold_seats(user)<br/>held_by = user<br/>hold_expires_at = now+5min
    HELD --> BOOKED : confirm()<br/>payment ok<br/>hold_expires_at = None
    HELD --> AVAILABLE : 5-min timeout<br/>(lazy check OR sweeper)
    BOOKED --> AVAILABLE : cancel()
    note right of HELD
        THE crux state.
        Everything hard in this
        problem exists because of it:
        - the race (2 users hold same seat)
        - the leak (hold never expires)
    end note
```

## 2. Booking lifecycle (runs in parallel with the seat)

```mermaid
stateDiagram-v2
    [*] --> PENDING : hold_seats()
    PENDING --> CONFIRMED : confirm() (payment ok)
    PENDING --> EXPIRED : hold timed out
    CONFIRMED --> CANCELLED : cancel()
```

> **Two state machines, kept in sync.** A `Booking` is PENDING while its seats are HELD; it becomes
> CONFIRMED when they become BOOKED. `confirm()` re-checks the seats precisely because these two can
> drift apart (payment took too long → seats expired but booking still says PENDING).

## 3. Class diagram

```mermaid
classDiagram
    class Movie {
        +str movie_id
        +str title
    }
    class Screen {
        +str screen_id
        +List~Seat~ seats
    }
    class Seat {
        +str seat_id
        +SeatType seat_type
        NOTE: no status!
    }
    class Show {
        +str show_id
        +datetime start_time
    }
    class ShowSeat {
        +SeatStatus status
        +User held_by
        +datetime hold_expires_at
        +is_hold_expired() bool
        +hold(user)
        +release()
    }
    class Booking {
        +str booking_id
        +Decimal amount
        +BookingStatus status
    }
    class PricingStrategy {
        <<abstract>>
        +calculate(show, seats) Decimal
    }
    class SeatTypePricing
    class WeekendPricing
    class BookingService {
        +hold_seats(user, show, ids) Booking
        +confirm(booking_id)
        +cancel(booking_id)
        +release_expired() int
    }

    Screen "1" *-- "many" Seat : owns
    Show "1" --> "1" Screen : plays on
    Show "1" --> "1" Movie : shows
    ShowSeat --> Show
    ShowSeat --> Seat : per-show state OF
    Booking "1" *-- "many" ShowSeat
    Booking --> User
    PricingStrategy <|-- SeatTypePricing
    SeatTypePricing <|-- WeekendPricing
    BookingService --> PricingStrategy : uses (DI)
    BookingService "1" *-- "many" ShowSeat : owns
    BookingService "1" *-- "many" Booking
```

**The split to notice:** `Seat` (physical, on the Screen) has **no status**. `ShowSeat` is the
per-show state. One `Seat` → many `ShowSeat`s, one per show.

```
Seat "A5"  ──┬── ShowSeat(3pm show)  : AVAILABLE
             ├── ShowSeat(6pm show)  : BOOKED
             └── ShowSeat(9pm show)  : HELD
```

## 4. hold_seats() flow

```mermaid
flowchart TD
    A[hold_seats user, show, seat_ids] --> B[acquire PER-SHOW lock]
    B --> C[lazily expire any timed-out holds]
    C --> D{ALL requested seats AVAILABLE?}
    D -->|no| E[raise SeatUnavailableError<br/>hold NOTHING]
    D -->|yes| F[mark ALL as HELD<br/>set held_by + expiry]
    F --> G[calculate price via Strategy]
    G --> H[create Booking PENDING]
    H --> I[release lock]
    E --> I
```

**Why the check loop finishes before any mutation:** all-or-nothing. If a user asks for 3 seats and
only 2 are free, holding those 2 would strand them — nobody else can take them, and this user can't
complete either.
