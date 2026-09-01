"""
Notification System — LLD solution (built step by step).

Entities (Step 2):
    Event side   : EventType (enum), Event
    Observer     : Subscriber (ABC), EventBus            <- the decoupling layer
    Notification : User, ChannelType (enum), UserPreference, NotificationTemplate,
                   Notification, NotificationChannel (Strategy ABC), RetryPolicy
    Orchestration: NotificationService (IS-A Subscriber; owns the pipeline)

THE TWO LAYERS — don't conflate them:
    Layer 1  EventBus -> Subscriber        exists ONLY to decouple. publish() calls
                                           sub.handle(event) and that is ALL it knows.
    Layer 2  recipients -> preferences -> render -> dispatch -> retry
                                           ordinary orchestration, inside ONE subscriber.
    NotificationService is the hinge: implements Subscriber, owns the pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional
import threading
import time


class DeliveryFailedError(Exception):
    """A channel could not deliver even after all retries."""


# ---------------------------------------------------------------------------
# Step 4a: the plain data — EventType, Event, ChannelType, User, Notification
#
# HINT — nothing clever here, all @dataclass / Enum:
#   EventType(Enum)   -> COMMENT_POSTED, ORDER_SHIPPED, PAYMENT_RECEIVED
#                        (labels only — no behaviour differs per value -> enum is right)
#   Event             -> event_type: EventType, payload: dict
#                        ** payload is a dict on purpose: the bus must stay generic.
#                           A typed class per event would force the bus to know them all.
#   ChannelType(Enum) -> EMAIL, SMS, PUSH, IN_APP
#                        ** this is the LABEL used in preferences (data).
#                           The Strategy that actually SENDS comes in 4c.
#   User              -> user_id, name, email, phone, device_token
#                        ** frozen=True -> hashable -> usable as a dict key
#   Notification      -> recipient: User, channel_type: ChannelType, content: str
#                        (one thing to deliver, on one channel)
# ---------------------------------------------------------------------------

class EventType(Enum):
    COMMENT_POSTED = "COMMENT_POSTED"
    ORDER_SHIPPED = "ORDER_SHIPPED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"


class Event:
    def __init__(self, event_type: EventType, payload: dict):
        self.event_type = event_type
        self.payload = payload


class ChannelType(Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"
    IN_APP = "IN_APP" 


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    email: str
    phone: str
    device_token: Optional[str] = field(default=None)

class Notification:
    def __init__(self, recipient: User, channel_type: ChannelType, content: str):
        self.recipient = recipient
        self.channel_type = channel_type
        self.content = content




# ---------------------------------------------------------------------------
# Step 4b: Subscriber (ABC) + EventBus   <- THE OBSERVER CORE, ~12 lines
#
# HINT:
#   Subscriber(ABC) -> ONE method: handle(event) -> None
#       This tiny contract is the whole point: it's what lets the bus call something
#       without knowing what that something does.
#
#   EventBus:
#       self._subscribers: dict[EventType, list[Subscriber]]
#       subscribe(event_type, sub)    -> setdefault(event_type, []).append(sub)
#       unsubscribe(event_type, sub)  -> remove if present
#       publish(event)                -> for sub in <the list>: sub.handle(event)
#
#       ** ITERATE A COPY: list(self._subscribers.get(...)) — if a handler subscribes
#          or unsubscribes during publish, mutating the list mid-iteration raises
#          RuntimeError: list changed size during iteration.
#       ** Guard the dict with a threading.Lock (subscribe/unsubscribe vs publish).
#       ** The bus must contain ZERO notification logic. If you're tempted to write
#          anything about email/SMS here, it belongs in a Subscriber instead.
# ---------------------------------------------------------------------------


class Subscriber(ABC):
    @abstractmethod
    def handle(self, event: Event) -> None:
        pass

class EventBus:
    def __init__(self):
        self._subscribers ={}
        self._lock = threading.Lock()

    def subscribe(self, event_type: EventType, subscriber: Subscriber) -> None:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(subscriber)

    def unsubscribe(self, event_type: EventType, subscriber: Subscriber) -> None:
        with self._lock:
            if event_type in self._subscribers:
                if subscriber in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(subscriber)

    def publish(self, event: Event) -> None:
        with self._lock:
            subscribers = list(self._subscribers.get(event.event_type, []))
        for subscriber in subscribers:
            try: 
                subscriber.handle(event)
            except Exception as e:
                print(f"Error occurred while handling event: {e}")
                
#   class NotificationChannel(ABC):
#       def send(self, notification: Notification) -> bool: ...
#
#   EmailChannel / SmsChannel / PushChannel / InAppChannel — each just prints for
#   this LLD (a real one would call SMTP / Twilio / FCM).
#   ** Requirement said "new channels pluggable" -> that's why this is an ABC:
#      adding WhatsApp = a new class, zero edits elsewhere (Open/Closed).
#   ** Give one of them a way to FAIL on demand, so the demo can prove the bulkhead
#      (one dead channel must not stop the others).
# ---------------------------------------------------------------------------

class NotificationChannel(ABC):
    @abstractmethod
    def send(self, notification: Notification) -> bool:
        pass

class EmailChannel(NotificationChannel):
    def send(self, notification: Notification) -> bool:
        print(f"Sending EMAIL to {notification.recipient.email}: {notification.content}")
        return True
class SmsChannel(NotificationChannel):
    def __init__(self, fail_on_send: bool = False):
        self.fail_on_send = fail_on_send

    def send(self, notification: Notification) -> bool:
        if self.fail_on_send:
            print(f"SMS failed to send to {notification.recipient.phone}")
            return False
        print(f"Sending SMS to {notification.recipient.phone}: {notification.content}")
        return True

class PushChannel(NotificationChannel):
    def send(self, notification: Notification) -> bool:
        if notification.recipient.device_token is None:
            print(f"Push failed: no device token for {notification.recipient.name}")
            return False
        print(f"Sending PUSH to {notification.recipient.device_token}: {notification.content}")
        return True 

class InAppChannel(NotificationChannel):
    def send(self, notification: Notification) -> bool:
        print(f"Sending IN_APP to {notification.recipient.name}: {notification.content}")
        return True

    

# ---------------------------------------------------------------------------
# Step 4d: UserPreference, NotificationTemplate, RetryPolicy
#
# HINT:
#   UserPreference       -> store of (user, event_type) -> set[ChannelType]
#                           channels_for(user, event_type) -> set[ChannelType]
#                           Sensible default when nothing is set (e.g. IN_APP only).
#   NotificationTemplate -> render(event) -> str, from a format string + event.payload
#                           e.g. "{author} commented on your {target}"
#                           ** keeps callers dumb — they send data, not sentences.
#   RetryPolicy          -> max_attempts; should_retry(attempt) -> bool
#                           delay(attempt) -> float   (exponential backoff: base * 2**attempt)
# ---------------------------------------------------------------------------
class UserPreference:
    def __init__(self):
        self.preferences = {}  # (user_id, event_type) -> set[ChannelType]

    def set_preferences(self, user: User, event_type: EventType, channels: set[ChannelType]):
        self.preferences[(user.user_id, event_type)] = channels

    def channels_for(self, user: User, event_type: EventType) -> set[ChannelType]:
        return self.preferences.get((user.user_id, event_type), {ChannelType.IN_APP})


class NotificationTemplate:
    def __init__(self, template_str: str):
        self.template_str = template_str

    def render(self, event: Event) -> str:
        try:
            return self.template_str.format(**event.payload)
        except KeyError as e:
            print(f"Error rendering notification template: missing key {e}")
            raise

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay(self, attempt: int) -> float:
        return self.base_delay * (2 ** attempt)

class RetryPolicy:
    def __init__(self, max_attempts: int = 3, base_delay: float = 1.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay(self, attempt: int) -> float:
        return self.base_delay * (2 ** attempt)
    
# ---------------------------------------------------------------------------
# Step 4e: NotificationService (a Subscriber) + demo
#
# HINT — this is the pipeline from Step 3. handle(event) does:
#   1. recipients = self.recipient_resolver(event)      # who cares about this event?
#   2. for each user:
#        wanted = preferences.channels_for(user, event.event_type)
#        content = self.templates[event.event_type].render(event)
#        for channel_type in wanted:
#            channel = self.channels[channel_type]      # label -> behaviour
#            try:    self._send_with_retry(channel, notification)
#            except: record failure                     # <- BULKHEAD lives here
#
#   ** the try/except INSIDE the loop IS the "dead channel must not block others" NFR.
#   ** _send_with_retry: loop attempts, ask RetryPolicy whether to go again.
#   ** NotificationService must implement Subscriber -> the bus can hold it without
#      knowing anything about notifications.
# ---------------------------------------------------------------------------
class NotificationService(Subscriber):
    """IS-A Subscriber, so the bus can hold it without knowing notifications exist.
    Owns the whole layer-2 pipeline."""

    def __init__(self, user_preferences: UserPreference,
                 templates: dict[EventType, NotificationTemplate],
                 channels: dict[ChannelType, NotificationChannel],
                 retry_policy: RetryPolicy,
                 recipient_resolver: Callable[[Event], list[User]]):
        self.user_preferences = user_preferences
        self.templates = templates
        self.channels = channels
        self.retry_policy = retry_policy
        # INJECTED: every event finds its recipients differently (comment -> photo
        # owner, order -> buyer), so this is a collaborator, not hard-coded logic.
        self.recipient_resolver = recipient_resolver

    def handle(self, event: Event) -> None:
        recipients = self.recipient_resolver(event)
        for user in recipients:
            wanted_channels = self.user_preferences.channels_for(user, event.event_type)
            content = self.templates[event.event_type].render(event)
            for channel_type in wanted_channels:
                channel = self.channels[channel_type]
                notification = Notification(user, channel_type, content)
                try:
                    self._send_with_retry(channel, notification)
                except DeliveryFailedError as e:
                    # BULKHEAD: this except sits INSIDE the channel loop, so a dead
                    # channel is logged and the loop moves on to the next one.
                    print(f"   [!] gave up on {channel_type.value} for {user.name}: {e}")

    def _send_with_retry(self, channel: NotificationChannel, notification: Notification) -> None:
        attempt = 0
        while True:
            # Handle BOTH failure styles: our channels return False, but a real
            # provider (SMTP/Twilio) raises. Only checking the return value would
            # let a raised exception escape the retry loop entirely.
            try:
                if channel.send(notification):
                    return
                reason = "returned False"
            except Exception as exc:
                reason = f"raised {type(exc).__name__}: {exc}"

            attempt += 1
            if not self.retry_policy.should_retry(attempt):
                raise DeliveryFailedError(f"{reason} after {attempt} attempt(s)")
            wait = self.retry_policy.delay(attempt)
            print(f"   ... {reason}; retry #{attempt} in {wait}s")
            time.sleep(wait)

# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    alice = User("1", "Alice", "alice@x.com", "+91-111", "tok-alice")
    bob   = User("2", "Bob",   "bob@x.com",   "+91-222", "tok-bob")

    # --- wire up the notification side ---
    prefs = UserPreference()
    prefs.set_preferences(alice, EventType.COMMENT_POSTED,
                          {ChannelType.PUSH, ChannelType.SMS, ChannelType.IN_APP})
    # Bob sets nothing -> falls back to the default {IN_APP}

    sms = SmsChannel(fail_on_send=True)            # <-- provider is DOWN
    channels = {
        ChannelType.EMAIL:  EmailChannel(),
        ChannelType.SMS:    sms,
        ChannelType.PUSH:   PushChannel(),
        ChannelType.IN_APP: InAppChannel(),
    }
    templates = {
        EventType.COMMENT_POSTED: NotificationTemplate("{author} commented on your {target}"),
        EventType.ORDER_SHIPPED:  NotificationTemplate("Your order {order_id} has shipped"),
    }

    def resolve_recipients(event):
        return [alice] if event.event_type is EventType.COMMENT_POSTED else [bob]

    notifier = NotificationService(prefs, templates, channels,
                                   RetryPolicy(max_attempts=2, base_delay=0.05),
                                   resolve_recipients)

    # --- an UNRELATED subscriber, to prove the bus is generic ---
    class AnalyticsSubscriber(Subscriber):
        def handle(self, event):
            print(f"   [analytics] recorded {event.event_type.value}")

    bus = EventBus()
    bus.subscribe(EventType.COMMENT_POSTED, notifier)
    bus.subscribe(EventType.COMMENT_POSTED, AnalyticsSubscriber())
    bus.subscribe(EventType.ORDER_SHIPPED,  notifier)

    print("=== publish COMMENT_POSTED (Alice wants PUSH + SMS + IN_APP; SMS is dead) ===")
    bus.publish(Event(EventType.COMMENT_POSTED, {"author": "Bob", "target": "photo"}))

    print("\n=== publish ORDER_SHIPPED (Bob set nothing -> default IN_APP only) ===")
    bus.publish(Event(EventType.ORDER_SHIPPED, {"order_id": "A-42"}))

    print("\n=== publish PAYMENT_RECEIVED (nobody subscribed) ===")
    bus.publish(Event(EventType.PAYMENT_RECEIVED, {}))
    print("   ...nothing happened, no crash - publisher doesn't care if anyone listens")
