"""
Movie Ticket Booking — LLD solution.

THE CRUX: a seat has a THIRD state between free and booked — HELD, with an expiry.
That one requirement creates both hard problems:
    1. the race  — two users holding the same seat  -> per-show lock around check+claim
    2. the leak  — a hold that never expires        -> lazy expiry + sweeper job

KEY MODELLING SPLIT: Seat (physical, belongs to a Screen) vs ShowSeat (per-show state).
    "A5" is one seat, but it can be free at 3pm and booked at 6pm.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
import threading
import uuid


HOLD_DURATION = timedelta(minutes=5)


def now() -> datetime:
    return datetime.now(timezone.utc)


class BookingError(Exception):
    """Base for booking failures."""


class SeatUnavailableError(BookingError):
    """At least one requested seat is not AVAILABLE."""


class BookingNotFoundError(BookingError):
    pass


class InvalidBookingStateError(BookingError):
    """e.g. confirming a booking that already expired."""


# ---------------------------------------------------------------------------
# Enums — all pure labels, nothing behaves differently per value
#
# HINT (to rebuild): three enums.
#   SeatType     -> REGULAR / PREMIUM / RECLINER   (drives pricing)
#   SeatStatus   -> AVAILABLE / HELD / BOOKED
#                   ** HELD is the whole problem. Without a third state you must
#                      either mark it booked before payment (blocked forever if
#                      payment fails) or leave it free (someone else takes it and
#                      the payer gets "sorry"). Both are wrong.
#   BookingStatus-> PENDING / CONFIRMED / CANCELLED / EXPIRED
#   All three stay ENUMS: nothing behaves differently per value, only the label
#   differs. (Contrast the elevator, where each state did different work.)
# ---------------------------------------------------------------------------
class SeatType(Enum):
    REGULAR = "regular"
    PREMIUM = "premium"
    RECLINER = "recliner"


class SeatStatus(Enum):
    AVAILABLE = "available"
    HELD = "held"
    BOOKED = "booked"


class BookingStatus(Enum):
    PENDING = "pending"          # seats held, waiting for payment
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"          # hold ran out before payment


# ---------------------------------------------------------------------------
# Catalogue — static structure
#
# HINT (to rebuild): plain data, all frozen where they're used as keys.
#   User / Movie -> ids + names
#   Seat         -> seat_id ("A5"), seat_type.
#                   ** NO status field. A seat is PHYSICAL and belongs to a Screen;
#                      whether it's free is per-SHOW. Put status here and booking A5
#                      for the 6pm show books it for every show of the day.
#   Screen       -> screen_id, name, seats: list[Seat]  (default_factory!)
#   Show         -> show_id, movie, screen, start_time
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class User:
    user_id: str
    name: str


@dataclass(frozen=True)
class Movie:
    movie_id: str
    title: str


@dataclass(frozen=True)
class Seat:
    """A PHYSICAL seat. Belongs to a Screen. Has NO status — availability is
    per-show, which is exactly why ShowSeat exists."""
    seat_id: str            # "A5"
    seat_type: SeatType


@dataclass
class Screen:
    screen_id: str
    name: str
    seats: list[Seat] = field(default_factory=list)


@dataclass
class Show:
    show_id: str
    movie: Movie
    screen: Screen
    start_time: datetime


# ---------------------------------------------------------------------------
# Per-show seat state — the entity that actually gets held and booked
#
# HINT (to rebuild): this is the entity the Seat-vs-ShowSeat split creates.
#   ShowSeat -> show, seat, status, held_by: Optional[User], hold_expires_at
#   Give it THREE small behaviours so callers don't poke at fields:
#     is_hold_expired() -> status is HELD AND hold_expires_at has passed
#     hold(user)        -> status=HELD, held_by=user, expires=now+HOLD_DURATION
#     release()         -> back to AVAILABLE, clear held_by and expiry
#   Booking -> booking_id, user, show, show_seats[], amount, status, created_at
# ---------------------------------------------------------------------------
@dataclass
class ShowSeat:
    show: Show
    seat: Seat
    status: SeatStatus = SeatStatus.AVAILABLE
    held_by: Optional[User] = None
    hold_expires_at: Optional[datetime] = None

    def is_hold_expired(self) -> bool:
        return (self.status is SeatStatus.HELD
                and self.hold_expires_at is not None
                and now() >= self.hold_expires_at)

    def release(self) -> None:
        self.status = SeatStatus.AVAILABLE
        self.held_by = None
        self.hold_expires_at = None

    def hold(self, user: User) -> None:
        self.status = SeatStatus.HELD
        self.held_by = user
        self.hold_expires_at = now() + HOLD_DURATION


@dataclass
class Booking:
    booking_id: str
    user: User
    show: Show
    show_seats: list[ShowSeat]
    amount: Decimal
    status: BookingStatus = BookingStatus.PENDING
    created_at: datetime = field(default_factory=now)


# ---------------------------------------------------------------------------
# PricingStrategy — the swappable NFR
#
# HINT (to rebuild): the requirement said pricing must be swappable -> Strategy.
#   PricingStrategy(ABC).calculate(show, seats) -> Decimal
#   SeatTypePricing -> a RATES dict keyed by SeatType (data, not if/elif)
#   WeekendPricing  -> subclass it and multiply; proves the swap is real
#   ** Decimal, never float — money (the Splitwise lesson).
# ---------------------------------------------------------------------------
class PricingStrategy(ABC):
    @abstractmethod
    def calculate(self, show: Show, seats: list[Seat]) -> Decimal: ...


class SeatTypePricing(PricingStrategy):
    RATES = {
        SeatType.REGULAR: Decimal("200"),
        SeatType.PREMIUM: Decimal("350"),
        SeatType.RECLINER: Decimal("500"),
    }

    def calculate(self, show: Show, seats: list[Seat]) -> Decimal:
        return sum((self.RATES[s.seat_type] for s in seats), Decimal("0"))


class WeekendPricing(SeatTypePricing):
    """Proof the strategy is real: +25% on Sat/Sun. One class, nothing else changes."""

    def calculate(self, show: Show, seats: list[Seat]) -> Decimal:
        base = super().calculate(show, seats)
        return base * Decimal("1.25") if show.start_time.weekday() >= 5 else base


# ---------------------------------------------------------------------------
# BookingService — orchestrator
#
# HINT (to rebuild) — three things make this correct:
#
#  1. PER-SHOW LOCKS, not one global lock. `self._locks[show_id]`. A global lock
#     would make the 3pm rush block 9pm buyers, who share nothing with them.
#
#  2. hold_seats = CHECK-THEN-CLAIM inside ONE lock (the 6th appearance of this race):
#         with lock:
#             expire stale holds (lazy)
#             check ALL requested seats are AVAILABLE  -> any taken? raise, hold NOTHING
#             only then mark them all HELD
#     ** ALL-OR-NOTHING: mutating as you go leaves stranded seats when seat #3
#        turns out to be taken.
#
#  3. TWO expiry mechanisms, deliberately:
#         lazy    (_expire_holds on every read/hold) -> correctness even if the job dies
#         sweeper (release_expired)                  -> keeps the seat map honest for
#                                                       seats nobody happens to look at
#
#  And confirm() must RE-CHECK the hold: payment takes time, the hold can lapse
#  mid-flight, and confirming blindly would double-book.
# ---------------------------------------------------------------------------
class BookingService:
    def __init__(self, pricing: Optional[PricingStrategy] = None):
        self.pricing = pricing or SeatTypePricing()
        self._show_seats: dict[str, dict[str, ShowSeat]] = {}   # show_id -> seat_id -> ShowSeat
        self._bookings: dict[str, Booking] = {}
        # PER-SHOW locks: a global lock would make unrelated shows block each other.
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- setup -------------------------------------------------------------
    def register_show(self, show: Show) -> None:
        self._show_seats[show.show_id] = {
            s.seat_id: ShowSeat(show, s) for s in show.screen.seats
        }
        with self._locks_guard:
            self._locks[show.show_id] = threading.Lock()

    def _lock_for(self, show_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[show_id]

    # -- reads -------------------------------------------------------------
    def seat_map(self, show_id: str) -> dict[str, str]:
        with self._lock_for(show_id):
            self._expire_holds(show_id)          # lazy: never show a stale HELD
            return {sid: ss.status.value for sid, ss in self._show_seats[show_id].items()}

    def available_seats(self, show_id: str) -> list[str]:
        return [sid for sid, st in self.seat_map(show_id).items() if st == "available"]

    # -- the crux ----------------------------------------------------------
    def hold_seats(self, user: User, show: Show, seat_ids: list[str]) -> Booking:
        """Check-then-claim must be ONE critical section, or two users both see
        the same seat free and both hold it."""
        with self._lock_for(show.show_id):
            self._expire_holds(show.show_id)             # 1. lazy expiry first

            seats = self._show_seats[show.show_id]
            targets = []
            for sid in seat_ids:
                ss = seats.get(sid)
                if ss is None:
                    raise SeatUnavailableError(f"no seat {sid} in this show")
                if ss.status is not SeatStatus.AVAILABLE:  # 2. check ALL first
                    raise SeatUnavailableError(f"seat {sid} is {ss.status.value}")
                targets.append(ss)

            # 3. ALL-OR-NOTHING: only now do we mutate. A partial hold would
            #    strand seats that nobody can use.
            for ss in targets:
                ss.hold(user)

            amount = self.pricing.calculate(show, [ss.seat for ss in targets])
            booking = Booking(str(uuid.uuid4())[:8], user, show, targets, amount)
            self._bookings[booking.booking_id] = booking
            return booking

    def confirm(self, booking_id: str) -> Booking:
        booking = self._get(booking_id)
        with self._lock_for(booking.show.show_id):
            if booking.status is not BookingStatus.PENDING:
                raise InvalidBookingStateError(f"booking is {booking.status.value}")
            # The hold may have expired while payment was in flight.
            if any(ss.is_hold_expired() or ss.held_by is not booking.user
                   for ss in booking.show_seats):
                booking.status = BookingStatus.EXPIRED
                self._expire_holds(booking.show.show_id)
                raise InvalidBookingStateError("hold expired before payment completed")

            for ss in booking.show_seats:
                ss.status = SeatStatus.BOOKED
                ss.hold_expires_at = None        # booked seats never expire
            booking.status = BookingStatus.CONFIRMED
            return booking

    def cancel(self, booking_id: str) -> None:
        booking = self._get(booking_id)
        with self._lock_for(booking.show.show_id):
            if booking.status is BookingStatus.CANCELLED:
                return
            for ss in booking.show_seats:
                ss.release()
            booking.status = BookingStatus.CANCELLED

    # -- expiry: mechanism 2, the sweeper ----------------------------------
    def release_expired(self) -> int:
        """Background job. Keeps the seat map honest for seats nobody happens to
        look at. The lazy check guarantees correctness even if this never runs."""
        released = 0
        for show_id in list(self._show_seats):
            with self._lock_for(show_id):
                released += self._expire_holds(show_id)
        return released

    def _expire_holds(self, show_id: str) -> int:
        """Caller must already hold the show's lock."""
        count = 0
        for ss in self._show_seats[show_id].values():
            if ss.is_hold_expired():
                ss.release()
                count += 1
        for b in self._bookings.values():
            if b.status is BookingStatus.PENDING and b.show.show_id == show_id:
                if any(s.status is SeatStatus.AVAILABLE for s in b.show_seats):
                    b.status = BookingStatus.EXPIRED
        return count

    def _get(self, booking_id: str) -> Booking:
        b = self._bookings.get(booking_id)
        if b is None:
            raise BookingNotFoundError(booking_id)
        return b


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    seats = ([Seat(f"A{i}", SeatType.REGULAR) for i in range(1, 4)] +
             [Seat(f"B{i}", SeatType.PREMIUM) for i in range(1, 3)] +
             [Seat("C1", SeatType.RECLINER)])
    screen = Screen("s1", "Screen 1", seats)
    show = Show("show1", Movie("m1", "Dune"), screen, now() + timedelta(hours=2))

    svc = BookingService()
    svc.register_show(show)
    alice, bob = User("u1", "Alice"), User("u2", "Bob")

    print("available:", svc.available_seats("show1"))

    b1 = svc.hold_seats(alice, show, ["A1", "B1"])
    print(f"\nAlice holds A1,B1 -> {b1.status.value}, amount {b1.amount}")
    print("seat map now:", svc.seat_map("show1"))

    print("\n--- Bob tries the SAME seat ---")
    try:
        svc.hold_seats(bob, show, ["A1"])
    except SeatUnavailableError as e:
        print("  rejected:", e)

    print("\n--- all-or-nothing: Bob wants A1(taken) + A2(free) ---")
    try:
        svc.hold_seats(bob, show, ["A2", "A1"])
    except SeatUnavailableError as e:
        print("  rejected:", e)
    print("  A2 still available?", "A2" in svc.available_seats("show1"), " <- nothing stranded")

    print("\n--- confirm + cancel ---")
    svc.confirm(b1.booking_id)
    print("  after confirm:", svc.seat_map("show1"))
    svc.cancel(b1.booking_id)
    print("  after cancel :", svc.seat_map("show1"))

    print("\n--- hold EXPIRY (forced) ---")
    b2 = svc.hold_seats(bob, show, ["C1"])
    print("  Bob holds C1:", svc.seat_map("show1")["C1"])
    for ss in b2.show_seats:                       # pretend 5 minutes passed
        ss.hold_expires_at = now() - timedelta(seconds=1)
    print("  sweeper released:", svc.release_expired(), "seat(s) ->", svc.seat_map("show1")["C1"])
    try:
        svc.confirm(b2.booking_id)
    except InvalidBookingStateError as e:
        print("  confirm after expiry rejected:", e)

    print("\n--- weekend pricing: one class swapped ---")
    sat = Show("show2", Movie("m1", "Dune"), screen,
               now() + timedelta(days=(5 - now().weekday()) % 7 or 7))
    for name, strat in [("weekday rates", SeatTypePricing()), ("weekend rates", WeekendPricing())]:
        s = BookingService(strat)
        s.register_show(sat)
        print(f"  {name}: {s.hold_seats(alice, sat, ['A1','C1']).amount}")
