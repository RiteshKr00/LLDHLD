"""
Food Delivery — LLD solution (the capstone).

FOUR patterns, kept from tangling into each other:
    Strategy  x2  -> PricingStrategy, PartnerAssignmentStrategy   (the two "swappable" NFRs)
    Observer      -> OrderService publishes events; notifiers subscribe (the "low coupling" NFR)
    enum + table  -> OrderStatus + ALLOWED_TRANSITIONS  (lifecycle; NOT State pattern - see below)

WHY enum, not State pattern:
    Elevator: step() did completely DIFFERENT WORK per state       -> behaviour -> State pattern
    Here:     every transition does the SAME shape of work
              (validate -> change -> publish); only WHICH transitions
              are legal differs                                     -> data     -> enum + table
    Say out loud: "if states start doing their own work (PREPARING starts a timer,
    READY triggers assignment), I'd switch to the State pattern."
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
import math
import threading
import uuid


def now() -> datetime:
    return datetime.now(timezone.utc)


class OrderError(Exception):
    """Base for order failures."""


class InvalidTransitionError(OrderError):
    pass


class NoPartnerAvailableError(OrderError):
    pass


# ---------------------------------------------------------------------------
# Step 4a: Location, PartnerStatus, OrderStatus + ALLOWED_TRANSITIONS  <-- YOUR TURN
#
# HINT:
#   Location  -> @dataclass(frozen=True) with lat, lng
#                + distance_km(other) using the haversine formula.
#                (Same geo idea as the parking-platform HLD, now in code.)
#                R = 6371 km; use math.radians / sin / cos / asin.
#
#   PartnerStatus(Enum) -> AVAILABLE, BUSY
#                ** this flag is what the concurrency race is actually over
#
#   OrderStatus(Enum)   -> PLACED, ACCEPTED, PREPARING, READY, PICKED_UP,
#                          DELIVERED, CANCELLED
#
#   ALLOWED_TRANSITIONS -> dict[OrderStatus, set[OrderStatus]]
#        PLACED    -> {ACCEPTED, CANCELLED}
#        ACCEPTED  -> {PREPARING, CANCELLED}
#        PREPARING -> {READY}            <- no CANCELLED: food is being cooked
#        READY     -> {PICKED_UP}
#        PICKED_UP -> {DELIVERED}
#        DELIVERED -> set()              <- terminal
#        CANCELLED -> set()              <- terminal
#   ** This table IS the state machine. One place to read it, one line to change it.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Location:
    lat: float
    lng: float

    def distance_km(self, other: "Location") -> float:
        """Haversine formula."""
        R = 6371.0  # Earth radius in km
        lat1, lon1 = math.radians(self.lat), math.radians(self.lng)
        lat2, lon2 = math.radians(other.lat), math.radians(other.lng)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

class PartnerStatus(Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"

class OrderStatus(Enum):
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"

ALLOWED_TRANSITIONS = {
    OrderStatus.PLACED: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY},
    OrderStatus.READY: {OrderStatus.PICKED_UP},
    OrderStatus.PICKED_UP: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}

# ---------------------------------------------------------------------------
# Step 4b: the data — MenuItem, OrderItem, Customer, Restaurant, DeliveryPartner, Order
#
# HINT:
#   MenuItem   -> item_id, name, price: Decimal        (frozen)
#   OrderItem  -> menu_item, quantity                  (one LINE of an order)
#                 + a `subtotal` property = price * quantity
#   Customer   -> customer_id, name, location          (frozen -> usable as dict key)
#   Restaurant -> restaurant_id, name, location, menu: list[MenuItem]
#   DeliveryPartner -> partner_id, name, location,
#                      status: PartnerStatus = AVAILABLE
#   Order      -> order_id, customer, restaurant, items: list[OrderItem],
#                 status: OrderStatus = PLACED, partner: Optional[...] = None,
#                 amount: Decimal = 0, created_at
#                 + can_transition_to(new) -> bool   (reads ALLOWED_TRANSITIONS)
#
#   ** Money is Decimal, never float (the Splitwise lesson).
# ---------------------------------------------------------------------------

class MenuItem:
    def __init__(self, item_id: str, name: str, price: Decimal):
        self.item_id = item_id
        self.name = name
        self.price = price

class OrderItem:
    def __init__(self, menu_item: MenuItem, quantity: int):
        self.menu_item = menu_item
        self.quantity = quantity

    @property
    def subtotal(self) -> Decimal:
        return self.menu_item.price * self.quantity

class Customer:
    def __init__(self, customer_id: str, name: str, location: Location):
        self.customer_id = customer_id
        self.name = name
        self.location = location

class Restaurant:
    def __init__(self, restaurant_id: str, name: str, location: Location, menu: list[MenuItem]):
        self.restaurant_id = restaurant_id
        self.name = name
        self.location = location
        self.menu = menu

class DeliveryPartner:
    def __init__(self, partner_id: str, name: str, location: Location):
        self.partner_id = partner_id
        self.name = name
        self.location = location
        self.status = PartnerStatus.AVAILABLE   

class Order:
    def __init__(self, order_id: str, customer: Customer, restaurant: Restaurant, items: list[OrderItem]):
        self.order_id = order_id
        self.customer = customer
        self.restaurant = restaurant
        self.items = items
        self.status = OrderStatus.PLACED
        self.partner: Optional[DeliveryPartner] = None
        self.amount: Decimal = Decimal(0)
        self.created_at = now()

    def can_transition_to(self, new_status: OrderStatus) -> bool:
        return new_status in ALLOWED_TRANSITIONS[self.status]   

# ---------------------------------------------------------------------------
# Step 4c: the two Strategies
#
# HINT:
#   PricingStrategy(ABC)      -> calculate(order) -> Decimal
#     StandardPricing         -> sum(item subtotals) + flat delivery fee
#     SurgePricing            -> subclass it, multiply the delivery fee
#                                (proof the swap is real, like WeekendPricing)
#
#   PartnerAssignmentStrategy(ABC) -> find_partner(order, partners, radius_km) -> Optional[...]
#     NearestPartnerStrategy  -> among AVAILABLE partners within radius_km of the
#                                RESTAURANT (not the customer - pickup comes first),
#                                return the closest. None if nobody qualifies.
#     ** Do NOT mark them BUSY here. The strategy only CHOOSES.
#        Claiming is the orchestrator's job, inside the lock. (Same separation as
#        parking: strategy finds, service claims.)
# ---------------------------------------------------------------------------


class PricingStrategy(ABC):
    @abstractmethod
    def calculate(self, order: Order) -> Decimal:
        pass
class StandardPricing(PricingStrategy):
    def __init__(self, delivery_fee: Decimal):
        self.delivery_fee = delivery_fee

    def calculate(self, order: Order) -> Decimal:
        subtotal = sum(item.subtotal for item in order.items)
        return subtotal + self.delivery_fee
class SurgePricing(StandardPricing):
    def __init__(self, delivery_fee: Decimal, surge_multiplier: Decimal):
        super().__init__(delivery_fee)
        self.surge_multiplier = surge_multiplier

    def calculate(self, order: Order) -> Decimal:
        subtotal = sum(item.subtotal for item in order.items)
        return subtotal + (self.delivery_fee * self.surge_multiplier)
class PartnerAssignmentStrategy(ABC):
    @abstractmethod
    def find_partner(self, order: Order, partners: list[DeliveryPartner], radius_km: float) -> Optional[DeliveryPartner]:
        pass
class NearestPartnerStrategy(PartnerAssignmentStrategy):
    def find_partner(self, order: Order, partners: list[DeliveryPartner], radius_km: float) -> Optional[DeliveryPartner]:
        restaurant_location = order.restaurant.location
        available_partners = [
            p for p in partners if p.status == PartnerStatus.AVAILABLE and restaurant_location.distance_km(p.location) <= radius_km
        ]
        if not available_partners:
            return None
        return min(available_partners, key=lambda p: restaurant_location.distance_km(p.location))   

# ---------------------------------------------------------------------------
# Step 4d: Observer — OrderEvent, Subscriber, EventBus, the notifiers
#
# HINT: same shape as problem 07.
#   OrderEventType(Enum) -> ORDER_PLACED, ORDER_ACCEPTED, ORDER_REJECTED,
#                           STATUS_CHANGED, PARTNER_ASSIGNED, ORDER_CANCELLED
#   OrderEvent           -> event_type, order, extra: dict
#   Subscriber(ABC)      -> handle(event)          <- @abstractmethod! (the recurring trap)
#   EventBus             -> dict[OrderEventType, list[Subscriber]]
#                           subscribe / publish; iterate a COPY; lock the dict
#   CustomerNotifier / RestaurantNotifier / PartnerNotifier -> concrete Subscribers
#
#   ** The point: OrderService must NEVER call a notifier directly. It publishes.
#      Adding an SMS notifier later must not touch OrderService at all.
# ---------------------------------------------------------------------------
class OrderEventType(Enum):
    ORDER_PLACED = "order_placed"
    ORDER_ACCEPTED = "order_accepted"
    ORDER_REJECTED = "order_rejected"
    STATUS_CHANGED = "status_changed"
    PARTNER_ASSIGNED = "partner_assigned"
    ORDER_CANCELLED = "order_cancelled"
    NO_PARTNER_FOUND = "no_partner_found"      # order parked in the pending queue


@dataclass
class OrderEvent:
    event_type: OrderEventType
    order: "Order"
    extra: dict = field(default_factory=dict)


class Subscriber(ABC):
    """The contract that lets the bus call something without knowing what it is."""

    @abstractmethod                     # <- ABC alone has no teeth; this is what enforces it
    def handle(self, event: OrderEvent) -> None: ...


class EventBus:
    def __init__(self):
        self._subscribers: dict[OrderEventType, list[Subscriber]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: OrderEventType, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(subscriber)

    def unsubscribe(self, event_type: OrderEventType, subscriber: Subscriber) -> None:
        with self._lock:
            if subscriber in self._subscribers.get(event_type, []):
                self._subscribers[event_type].remove(subscriber)

    def publish(self, event: OrderEvent) -> None:
        # Copy INSIDE the lock, then RELEASE it before calling handle().
        # Two reasons: (1) handle() can be slow I/O and would block every
        # subscribe/unsubscribe; (2) if a handler itself calls subscribe(), holding
        # the lock would DEADLOCK — threading.Lock is not reentrant.
        with self._lock:
            subscribers = list(self._subscribers.get(event.event_type, []))
        for sub in subscribers:
            try:
                sub.handle(event)
            except Exception as exc:    # BULKHEAD at the subscriber level:
                                        # one broken listener must not stop the rest
                print(f"   [bus] {type(sub).__name__} failed: {exc}")


class CustomerNotifier(Subscriber):
    def handle(self, event: OrderEvent) -> None:
        o = event.order
        print(f"   -> [customer {o.customer.name}] {event.event_type.value}: order {o.order_id} is {o.status.value}")


class RestaurantNotifier(Subscriber):
    def handle(self, event: OrderEvent) -> None:
        o = event.order
        print(f"   -> [restaurant {o.restaurant.name}] {event.event_type.value}: order {o.order_id}")


class PartnerNotifier(Subscriber):
    def handle(self, event: OrderEvent) -> None:
        o = event.order
        who = o.partner.name if o.partner else "unassigned"
        print(f"   -> [partner {who}] {event.event_type.value}: pick up from {o.restaurant.name}")



# ---------------------------------------------------------------------------
# Step 4e: OrderService (orchestrator) + demo
#
# HINT:
#   __init__ -> inject BOTH strategies + the bus; hold partners, orders,
#               a pending queue, and a Lock.
#
#   place_order(customer, restaurant, items) -> Order
#        build Order (PLACED), price it via the strategy, store, publish ORDER_PLACED
#
#   accept_order / reject_order -> advance to ACCEPTED / CANCELLED, publish
#
#   advance(order_id, to) -> validate with can_transition_to() first!
#        raise InvalidTransitionError if illegal; else set + publish STATUS_CHANGED
#        ** when reaching DELIVERED: free the partner (status = AVAILABLE) and
#           try to serve the pending queue with them
#
#   assign_partner(order_id) -> THE RACY ONE
#        with self._lock:
#            for radius in (2, 5, 8):            # widening retry
#                p = self.assignment.find_partner(order, self._partners, radius)
#                if p:
#                    p.status = BUSY             # <- CLAIM, inside the same lock
#                    order.partner = p
#                    publish PARTNER_ASSIGNED
#                    return p
#            self._pending.append(order)         # park it, DO NOT cancel
#            return None
#
#   cancel_order(order_id) -> only if can_transition_to(CANCELLED); free any partner
# ---------------------------------------------------------------------------
class OrderService:
    """Orchestrator. Note what it does NOT do: it never calls a notifier, and it
    never decides pricing or matching itself — all three are injected/published."""

    def __init__(self,
                 pricing: PricingStrategy,
                 assignment: PartnerAssignmentStrategy,
                 bus: EventBus,
                 partners: Optional[list[DeliveryPartner]] = None):
        self.pricing = pricing              # DI: swappable #1
        self.assignment = assignment        # DI: swappable #2
        self.bus = bus                      # DI: decoupling
        self._partners: list[DeliveryPartner] = partners or []
        self._orders: dict[str, Order] = {}
        self._pending: list[Order] = []     # found no partner; retried on a free-up
        self._lock = threading.Lock()

    # -- helpers ----------------------------------------------------------
    def _get(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise OrderError(f"no order {order_id}")
        return order

    def _publish(self, event_type: OrderEventType, order: Order, **extra) -> None:
        self.bus.publish(OrderEvent(event_type, order, extra))

    # -- lifecycle ---------------------------------------------------------
    def place_order(self, customer: Customer, restaurant: Restaurant,
                    items: list[OrderItem]) -> Order:
        order = Order(str(uuid.uuid4())[:8], customer, restaurant, items)
        order.amount = self.pricing.calculate(order)      # Strategy #1
        self._orders[order.order_id] = order
        self._publish(OrderEventType.ORDER_PLACED, order)
        return order

    def accept_order(self, order_id: str) -> None:
        order = self._get(order_id)
        self._transition(order, OrderStatus.ACCEPTED)
        self._publish(OrderEventType.ORDER_ACCEPTED, order)

    def reject_order(self, order_id: str) -> None:
        order = self._get(order_id)
        self._transition(order, OrderStatus.CANCELLED)
        self._publish(OrderEventType.ORDER_REJECTED, order)

    def advance(self, order_id: str, to: OrderStatus) -> None:
        order = self._get(order_id)
        self._transition(order, to)
        self._publish(OrderEventType.STATUS_CHANGED, order)
        if to is OrderStatus.DELIVERED:
            self._free_partner(order)

    def cancel_order(self, order_id: str) -> None:
        order = self._get(order_id)
        self._transition(order, OrderStatus.CANCELLED)   # raises once PREPARING started
        self._free_partner(order)
        self._publish(OrderEventType.ORDER_CANCELLED, order)

    def _transition(self, order: Order, to: OrderStatus) -> None:
        """The TABLE is the authority — there is no if/elif about statuses anywhere.

        The check and the write are ONE critical section. Without the lock this is
        the same check-then-act shape as assign_partner: two threads both call
        advance(id, DELIVERED), both see PICKED_UP, both pass can_transition_to,
        and both write — so DELIVERED is applied twice and _free_partner runs twice.
        """
        with self._lock:
            if not order.can_transition_to(to):
                raise InvalidTransitionError(
                    f"cannot go {order.status.value} -> {to.value}")
            order.status = to

    # -- the racy one ------------------------------------------------------
    def assign_partner(self, order_id: str) -> Optional[DeliveryPartner]:
        """find -> claim must be ONE critical section, or two orders both get
        handed the same AVAILABLE partner (the 7th appearance of this race)."""
        order = self._get(order_id)
        with self._lock:
            for radius_km in (2, 5, 8):                   # widening retry
                partner = self.assignment.find_partner(order, self._partners, radius_km)
                if partner is not None:
                    partner.status = PartnerStatus.BUSY   # <- CLAIM, same lock
                    order.partner = partner
                    self._publish(OrderEventType.PARTNER_ASSIGNED, order,
                                  radius_km=radius_km)
                    return partner
            if order not in self._pending:
                self._pending.append(order)               # park it, never auto-cancel
            self._publish(OrderEventType.NO_PARTNER_FOUND, order)
            return None

    def _free_partner(self, order: Order) -> None:
        """Delivered (or cancelled) -> the partner is free again, so immediately try
        to serve whoever has been waiting in the pending queue."""
        with self._lock:
            # the READ and the guard belong inside too — reading order.partner
            # first and locking afterwards lets two callers both see the same live
            # partner, and the loser then flips a partner who has since been
            # re-claimed by another order back to AVAILABLE.
            partner = order.partner
            if partner is None:
                return                       # someone else already freed it
            partner.status = PartnerStatus.AVAILABLE
            order.partner = None
            waiting = self._pending.pop(0) if self._pending else None
        if waiting is not None:
            # OUTSIDE the lock: assign_partner takes it, and threading.Lock is
            # not reentrant — re-entering here would deadlock.
            self.assign_partner(waiting.order_id)

    # -- read model --------------------------------------------------------
    def pending_count(self) -> int:
        return len(self._pending)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    pizza = MenuItem("i1", "Pizza", Decimal("300"))
    coke = MenuItem("i2", "Coke", Decimal("60"))
    rest = Restaurant("r1", "Pizza Hut", Location(12.9352, 77.6245), [pizza, coke])
    alice = Customer("c1", "Alice", Location(12.9784, 77.6408))

    near = DeliveryPartner("p1", "Ravi", Location(12.9360, 77.6250))
    far = DeliveryPartner("p2", "Sunil", Location(12.9800, 77.6900))

    bus = EventBus()
    for et in OrderEventType:
        bus.subscribe(et, CustomerNotifier())
    bus.subscribe(OrderEventType.ORDER_PLACED, RestaurantNotifier())
    bus.subscribe(OrderEventType.PARTNER_ASSIGNED, PartnerNotifier())

    svc = OrderService(StandardPricing(Decimal("50")), NearestPartnerStrategy(),
                       bus, partners=[near, far])

    print("=== happy path ===")
    order = svc.place_order(alice, rest, [OrderItem(pizza, 2), OrderItem(coke, 1)])
    print(f"   amount = {order.amount}   (2x300 + 60 + 50 delivery)")
    svc.accept_order(order.order_id)
    svc.advance(order.order_id, OrderStatus.PREPARING)
    svc.advance(order.order_id, OrderStatus.READY)
    svc.assign_partner(order.order_id)
    svc.advance(order.order_id, OrderStatus.PICKED_UP)
    svc.advance(order.order_id, OrderStatus.DELIVERED)
    print(f"   partner freed? {near.status.value}")

    print()
    print("=== the transition TABLE is the authority ===")
    o2 = svc.place_order(alice, rest, [OrderItem(pizza, 1)])
    try:
        svc.advance(o2.order_id, OrderStatus.DELIVERED)      # PLACED -> DELIVERED
    except InvalidTransitionError as e:
        print("   rejected:", e)
    svc.accept_order(o2.order_id)
    svc.advance(o2.order_id, OrderStatus.PREPARING)
    try:
        svc.cancel_order(o2.order_id)                        # too late to cancel
    except InvalidTransitionError as e:
        print("   rejected:", e)

    print()
    print("=== nobody in range -> PENDING queue, not cancelled ===")
    remote = Restaurant("r2", "Faraway Cafe", Location(20.0, 80.0), [pizza])
    o3 = svc.place_order(alice, remote, [OrderItem(pizza, 1)])
    svc.accept_order(o3.order_id)
    svc.advance(o3.order_id, OrderStatus.PREPARING)
    svc.advance(o3.order_id, OrderStatus.READY)
    svc.assign_partner(o3.order_id)
    print(f"   status = {o3.status.value} (still alive), pending = {svc.pending_count()}")

    print()
    print("=== 200 orders rush ONE partner ===")
    solo = DeliveryPartner("p9", "Solo", Location(12.9352, 77.6245))
    svc2 = OrderService(StandardPricing(Decimal("50")), NearestPartnerStrategy(),
                        EventBus(), partners=[solo])       # silent bus for the stress test
    orders = []
    for _ in range(200):
        o = svc2.place_order(alice, rest, [OrderItem(pizza, 1)])
        svc2.accept_order(o.order_id)
        svc2.advance(o.order_id, OrderStatus.PREPARING)
        svc2.advance(o.order_id, OrderStatus.READY)
        orders.append(o)

    won = []
    def rush(o):
        if svc2.assign_partner(o.order_id) is not None:
            won.append(o.order_id)
    ts = [threading.Thread(target=rush, args=(o,)) for o in orders]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    print(f"   winners: {len(won)}  (must be exactly 1)    pending: {svc2.pending_count()}")

    print()
    print("=== swap ONE class: surge pricing ===")
    svc3 = OrderService(SurgePricing(Decimal("50"), Decimal("3")), NearestPartnerStrategy(),
                        EventBus(), partners=[near])
    o4 = svc3.place_order(alice, rest, [OrderItem(pizza, 2), OrderItem(coke, 1)])
    print(f"   surge amount = {o4.amount}   (was 710 — delivery fee tripled)")
