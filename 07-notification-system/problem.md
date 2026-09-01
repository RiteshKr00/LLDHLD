# Problem 7: Notification System (LLD)

## The prompt (as an interviewer would give it)

> "Design a notification system. When something happens in our product, the right users
> should get notified."

Deliberately vague. **Your job is to make it concrete** — that's Step 1.

---

## Clarifying questions to ask
_This prompt is unusually vague — "something happens", "the right users", "get notified" are all
undefined. Probe all three._

1. **Channels** — email / SMS / push / in-app? Can one notification go out on *several* channels at once?
2. **User preferences** — do users configure what they receive ("email me for comments, never SMS me")? Quiet hours? Unsubscribe?
3. **Who decides the recipients** — does the code raising the event know who to notify, or does the notification system work it out? *(This decides whether senders and receivers are coupled — it's the Observer question.)*
4. **How does the system learn an event happened** — does the triggering service **call** us directly, or do we **listen** for events?
5. **Delivery guarantees** — retry on failure? What happens when the email/SMS provider is down? At-least-once or fire-and-forget?
6. **Templates** — does the notification system build the message text, or is it handed a ready string?
7. **Sync or async** — does the triggering action *wait* for the notification to be sent, or is it fired off in the background?

## Clarifications (locked scope from Q&A)
1. **Channels:** email, SMS, push, in-app. One notification can go out on **several channels at once**. More will be added later (WhatsApp, Slack) → **pluggable**.
2. **Preferences:** per user, per channel, per event type — *"push + in-app for comments, never SMS"*. Quiet hours out of scope.
3. **Recipients:** the **notification system works them out**. The code raising the event must NOT know who is listening — it just announces *"a comment was posted"*. Listeners register separately. ← *the decoupling decision (Observer)*
4. **How it learns:** services **publish events** to the system (it doesn't poll). In-process for this LLD; a real system would use a queue.
5. **Delivery:** **retry with backoff** on failure. A dead channel must not lose the notification, and must not block the other channels.
6. **Templates:** the notification system **builds the message** from a template + event data (callers stay dumb).
7. **Sync/async:** the triggering action **must not wait** — publishing returns immediately.

---

## Step 1 — Requirements  ✅ LOCKED

### Functional (what it DOES — the verbs)
- **Receive events** — an event is what triggers a notification
- **Subscribe / unsubscribe** — a pub-sub registry decides who gets notified for which event *(the publisher must not know the recipients)*
- **Respect user preferences** — per user, per channel, per event type
- **Render the message** from a template + event data
- **Deliver across multiple channels** (email / SMS / push / in-app), possibly several at once
- **Retry** failed deliveries with backoff

### Non-functional (constraints — the "-ilities")
- **Extensible** — new channels pluggable without touching existing code
- **Low coupling** — the event producer knows nothing about who consumes the event  ← *the Observer rationale*
- **Reliable / isolated** — one dead channel must not block the others (bulkhead)
- **Low latency** — publishing must not hold up the triggering action (async)
- **Testable**


### Explicitly out of scope (say this out loud — senior move)
- Notification analytics (open/click rates) · quiet hours · real provider integration (SMTP/Twilio/FCM)
- Localization/i18n · read receipts · per-user notification rate limiting

### Concurrency — a real "yes" here (unlike chess)
Shared mutable state exists: the **subscriber registry** (written by `subscribe`, read on every
`publish`) and the **retry queue**. Concrete failure mode: mutating a list while iterating it raises
`RuntimeError: list changed size during iteration` — so subscribing during an in-flight publish
crashes. Low risk if subscriptions only happen at startup; real if they're dynamic.

> 📝 **Review note (Step 1):** strongest Step 1 of the track. All six functional verbs present (events, channels, preferences, templates, retry, subscribe) — nothing missing. Five genuinely code-shaping NFRs, two of them notable: **"low coupling of event producer and notification consumer"** is not a generic "-ility" but the precise *rationale for Observer*, named as a requirement; and **"a dead channel must not block other channels"** is an **isolation/bulkhead** requirement most people only discover after the design breaks. **"pub sub model" appeared in the functional list unprompted** — the pattern surfaced in Step 1, the earliest the trigger has fired. Fixes: out-of-scope was thin (one item → expanded); the **concurrency question was skipped again** — and here it's a genuine yes, with a concrete failure (mutating the subscriber list mid-iteration).

--- 

## Step 2 — Entities  (nouns → classes)
_Format: `Name — single responsibility — key attributes/methods`_

**Event side**
1. **EventType** *(enum)* — `COMMENT_POSTED, ORDER_SHIPPED, …` — labels, no behaviour
2. **Event** — what happened — `event_type, payload: dict, source`

**Observer (the decoupling)**
3. **Subscriber** *(Observer ABC)* — anything that reacts to an event — `handle(event) -> None`
   ← *this is what the "subscriber list" is a list OF; without it there's no decoupling*
4. **EventBus** *(the Subject/publisher)* — holds `dict[EventType, list[Subscriber]]`; knows nothing about what subscribers do — `subscribe(event_type, sub)`, `unsubscribe(...)`, `publish(event)`

**Notification side**
5. **User** — recipient + their addresses — `user_id, email, phone, device_token`
6. **ChannelType** *(enum)* — `EMAIL, SMS, PUSH, IN_APP` — used as a **label** in preferences
7. **UserPreference** — which channels a user wants per event type — `user, event_type -> set[ChannelType]`
8. **NotificationTemplate** — renders text from a template + event payload — `render(event) -> str`
9. **Notification** — one thing to deliver — `recipient, channel_type, content`
10. **NotificationChannel** *(Strategy ABC)* — the **behaviour** of delivering; concrete: `EmailChannel`, `SmsChannel`, `PushChannel`, `InAppChannel` — `send(notification) -> bool`
11. **RetryPolicy** — how many attempts, what backoff — `should_retry(attempt) -> bool`, `delay(attempt)`

**Orchestration**
12. **NotificationService** — *is a `Subscriber`*; on `handle(event)`: resolve recipients → filter by preferences → render → dispatch per channel (each in its own try/except = **bulkhead**) → retry failures

> 📝 **Review note (Step 2):** 🎯 **data-vs-behaviour trigger fired again (5th rep)** — "Channel → behaviour → Strategy" written before the entity, unprompted. Gap closed. All six nouns were real. Three refinements: (1) **`Subscriber` ABC was missing** — the publisher held a "subscriber list" but nothing defined what a subscriber *is* (`handle(event)`); that ABC is the thing that makes the decoupling real. (2) **Channel is BOTH an enum AND a Strategy** — `ChannelType` is a *label* stored in preferences (data), `NotificationChannel` is the *delivery behaviour* (Strategy), linked by a `dict[ChannelType, NotificationChannel]`. Lesson: data-vs-behaviour isn't always either/or; sometimes you need the label and the implementation. (3) **Retry isn't an entity** — it's behaviour belonging to whoever dispatches; that same loop is where the **bulkhead** NFR is honoured (per-channel try/except so one dead channel can't block the rest). Also added recipient resolution (clarification 3 said the system works recipients out — something must do it).

---

## Step 3 — Relationships & APIs  ✅ LOCKED
_Signatures before bodies._

**Relationships — note the two layers:**
```
LAYER 1 — the decoupling (Observer)
  EventBus ──holds──▶ dict[EventType, list[Subscriber]]
  NotificationService ──IS-A──▶ Subscriber          (implements handle(event))
       ^ the bus only ever sees a Subscriber; it has no idea notifications exist

LAYER 2 — the notification pipeline (inside NotificationService)
  NotificationService ──uses (DI)──▶ RecipientResolver
                                  ──▶ UserPreference store
                                  ──▶ NotificationTemplate (per EventType)
                                  ──▶ dict[ChannelType, NotificationChannel]   (label -> behaviour)
                                  ──▶ RetryPolicy
```

**Signatures:**
```python
# EventBus (the Subject) — knows nothing about notifications
def subscribe(self, event_type: EventType, subscriber: Subscriber) -> None
def unsubscribe(self, event_type: EventType, subscriber: Subscriber) -> None
def publish(self, event: Event) -> None            # iterate a COPY of the list

# Subscriber (Observer ABC) — the contract that keeps the bus ignorant
def handle(self, event: Event) -> None

# NotificationChannel (Strategy ABC) — the delivery BEHAVIOUR
def send(self, notification: Notification) -> bool

# NotificationTemplate
def render(self, event: Event) -> str

# RetryPolicy
def should_retry(self, attempt: int) -> bool
def delay(self, attempt: int) -> float             # exponential backoff

# NotificationService (a Subscriber)
def handle(self, event: Event) -> None             # the pipeline below
```

**The pipeline — `NotificationService.handle(event)`:**

Worked example: `COMMENT_POSTED` — Bob commented on Alice's photo.

1. **Resolve recipients.** The event says *what happened*, not *who to tell* → the photo's owner → **Alice**.
   *(This is clarification 3: the system works recipients out, the publisher never supplies them.)*
2. **Filter by preference.** Alice's prefs for `COMMENT_POSTED` → `{PUSH, IN_APP}`. She opted out of SMS,
   so 2 notifications go out, not 4.
3. **Render the content** from the template + event payload → *"Bob commented on your photo"*.
4. **Dispatch per channel, each isolated:**
   ```python
   for channel_type in wanted:
       channel = self.channels[channel_type]        # ChannelType(label) -> Channel(behaviour)
       try:
           channel.send(Notification(user, channel_type, content))
       except Exception:
           self._schedule_retry(...)                 # <-- THIS except IS the bulkhead NFR:
                                                     #     a dead SMS can't stop PUSH
   ```
5. **Retry failures** with backoff per `RetryPolicy`.

> 📝 **Review note (Step 3):** the key structural insight is that there are **two layers**, and they must not be conflated. Layer 1 (`EventBus` ↔ `Subscriber`) exists purely to *decouple* — the bus's `publish` calls `sub.handle(event)` and that is the total extent of its knowledge. Layer 2 (the recipient → preference → render → dispatch → retry pipeline) is ordinary orchestration that happens to live inside one particular subscriber. `NotificationService` is the hinge: it **implements** `Subscriber` (layer 1) and **owns** the pipeline (layer 2). Two NFRs become single lines of code here: the per-channel `try/except` **is** the bulkhead requirement, and publishing without waiting **is** the low-latency requirement.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

| LLD method | HTTP |
|---|---|
| `bus.publish(event)` | `POST /api/v1/events` `{type, payload}` -> **202 Accepted** *(async — the caller must not wait for delivery)* |
| `bus.subscribe(type, sub)` | **not HTTP** — wiring done at startup/config, not by end users |
| `preferences.set(...)` | `PUT /api/v1/users/{id}/preferences` `{event_type: [channels]}` -> **200** |
| *(in-app inbox)* | `GET /api/v1/users/{id}/notifications?after=...` -> **200** |

**202, not 201** — you have accepted the event, not delivered anything. Returning 200 would imply the
notification was sent, which is a lie the moment a channel retries.

## Notes / decisions (log the "why" here)
- **Two layers, deliberately separate.** `EventBus` ↔ `Subscriber` exists *only* to decouple — `publish` calls `sub.handle(event)` and that is the total extent of its knowledge. The recipient→preference→render→dispatch→retry pipeline lives inside one subscriber. `NotificationService` is the hinge (implements `Subscriber`, owns the pipeline).
- **`Event.payload` is a plain `dict`** so the bus stays generic — a typed class per event would force the bus to know them all, killing the decoupling.
- **Channel is both an enum AND a Strategy:** `ChannelType` = the *label* stored in preferences (data); `NotificationChannel` = the *delivery behaviour* (Strategy). Linked by `dict[ChannelType, NotificationChannel]`. Data-vs-behaviour isn't always either/or.
- **Preferences keyed by `user_id`, not the `User` object** — IDs are the domain's stable identity; objects get rebuilt from DB/JSON/cache every time. More robust than relying on hashability.
- **`_send_with_retry` handles BOTH failure styles** — our channels `return False`, but real providers (SMTP/Twilio) **raise**. Checking only the return value would let an exception escape the retry loop.
- **`recipient_resolver` injected** — every event finds recipients differently (comment → photo owner, order → buyer), so it's a collaborator, not hard-coded logic.

> 📝 **Review note (Step 4 build):** 🎯 `EventBus.publish` was written **better than the hint** — the subscriber list is copied *inside* the lock and `handle()` is called *outside* it. That avoids two problems: holding a lock across slow I/O (email/SMS), and a **deadlock** if a handler itself calls `subscribe()` (`threading.Lock` is not reentrant). Fixes along the way: `Subscriber.handle` was missing `@abstractmethod` (toothless ABC — same trap as the URL shortener; `Subscriber()` could be instantiated and a subclass could silently forget `handle`); a stray `from symtable import Class` import; `time` was used but never imported; `get_recipients` was a placeholder returning `[]` → replaced with an injected resolver; generic `raise Exception` → `DeliveryFailedError`. **Known gap left open:** bulkhead exists at the *channel* level but not the *subscriber* level — `publish` has no try/except, so one raising subscriber would skip the rest. Worth adding: isolation belongs at every boundary, not just the innermost one.
