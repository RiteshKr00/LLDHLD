# Notification System — HLD (fan-out at scale)

Companion to [`solution.py`](solution.py) (the in-process engine).
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).

> **Framing:** the LLD's `EventBus` is a `dict` in one process. At scale it becomes **Kafka**, and the
> whole problem becomes **amplification** — one event turns into millions of deliveries — plus the fact
> that delivery depends on **third parties you don't control** (SMTP, Twilio, FCM).

## 1. Scope
- **Functional:** ingest events · resolve recipients · respect preferences · render · deliver across channels · retry · in-app inbox.
- **Non-functional:** **never lose a notification** (an OTP that vanishes is a broken login) · **never block the producer** · isolate channels *and* isolate tenants · **deduplicate** (don't notify twice) · respect per-user notification limits.

## 2. Capacity — the amplification is the story

- 100M users, ~10 notifications/user/day → **1B deliveries/day ≈ 12K/sec avg, ~25K/sec peak**.
- But events are far fewer: maybe **100M events/day ≈ 1.2K/sec**.
- **That gap IS the problem:** 1 event → *N recipients* → *M channels* = **N×M deliveries**.
  A single "celebrity posted" event can become **10M deliveries** by itself.

**So:** ingest is small, **fan-out is huge and spiky**. Design for the amplification, not the ingest.

## 3. Architecture

```
Producer services
   │  (outbox: event written in the SAME DB txn as the business change)
   ▼
Kafka: `events`                     <- the EventBus, grown up
   │
   ▼
Fan-out Service   (resolve recipients -> preferences -> render)
   │   ^ THIS is where 1 event becomes N x M messages
   ▼
Kafka, ONE TOPIC PER CHANNEL:   `send.email` │ `send.sms` │ `send.push` │ `send.inapp`
   │              │              │              │
   ▼              ▼              ▼              ▼
Email workers   SMS workers   Push workers   In-app writer
   │  (SMTP)      │ (Twilio)    │ (FCM)         │ -> inbox DB (users pull)
   └──────────────┴─────────────┴──▶ DLQ (poison messages, after N retries)
```

**The single nicest LLD→HLD mapping in this whole track:**

> The LLD's per-channel **`try/except` inside the loop** becomes a **separate Kafka topic + worker
> pool per channel** at scale. Same bulkhead idea, expressed in infrastructure instead of syntax.
> Twilio being down backs up `send.sms` only — `send.push` never notices.

## 4. Key decisions

**Outbox on the producer side.** If a service does `save_comment()` then `kafka.publish()`, a crash in
between silently loses the notification. Instead write the event to an **outbox table inside the same
DB transaction**, and let a relay publish it. At-least-once, nothing lost.

**Fan-out on write vs fan-out on read** (the celebrity problem):
- **Push/SMS/email must fan out on write** — you have to actually *send* to each person, there's no
  lazy option.
- **In-app inbox can fan out on read** — store the event once, let clients query "notifications for
  me" at open time. For a celebrity with 10M followers, writing 10M inbox rows is madness.
- **Hybrid is the real answer:** push-channel fan-out for everyone; in-app **push for normal users,
  pull for celebrities** (threshold on follower count).

**Priority queues.** An OTP and a marketing blast must not share a lane — a 2M-message campaign would
delay logins. Separate topics/priorities: `transactional` ≫ `marketing`.

**Deduplication / idempotency.** At-least-once delivery means a worker *will* re-process a message.
Give each delivery a deterministic key (`event_id + user_id + channel`) and check it before sending —
otherwise a retry sends the user a second SMS. **Users notice duplicates; they don't notice latency.**

**Per-user rate limit / digest.** 200 comments on a post shouldn't mean 200 pushes. Cap per user per
window (**this is literally Problem 4**), and beyond the cap **batch into a digest** ("50 new comments").

**Third-party failure handling** — this is what makes notifications different from most systems:
- **Circuit breaker** per provider: Twilio failing → stop hammering it, fail fast, let it recover.
- **Provider rate limits:** FCM/SES cap your throughput → token bucket *per provider*, not per user.
- **Fallback channel:** push fails → try SMS (only for high-value notifications; costs money).

## 5. Storage
- **Preferences + templates** → Postgres (small, relational, read-heavy → cache in Redis).
- **In-app inbox** → wide-column store (Cassandra/Dynamo), partitioned by `user_id`, sorted by time —
  the query is always "latest N for this user".
- **Delivery log** (what was sent, when, status) → append-heavy, time-partitioned, archive old.

## 6. Reliability & failure
- **Kafka down** → producers keep writing to their outbox; relay drains on recovery. Nothing lost.
- **One channel's provider down** → only that topic backs up; others unaffected (the bulkhead).
- **Poison message** (a template that always crashes) → after N retries → **DLQ** → alert, inspect, fix, replay. Never retry forever.
- **Fan-out service down** → events queue in Kafka, drained on restart. Delayed, not lost.
- **Never block the producer:** posting a comment returns as soon as the outbox row commits.

## 7. Bottleneck & scale
- **Bottleneck = fan-out amplification**, not ingest. Scale by partitioning the fan-out consumer group
  by `event_id`; shard workers per channel independently (SMS needs far fewer workers than push).
- **Hot partition:** celebrity events → split the recipient list into chunks and fan out in parallel,
  or switch that event to pull-based in-app.
- **Cost is a real constraint here** (unusual!): SMS costs real money per message. Prefer push → in-app →
  email → SMS. Cost optimisation isn't an afterthought, it's a routing rule.

## 8. Monitoring
Delivery success rate **per channel** · queue lag per topic · DLQ depth (should be ~0) · provider
error rate & circuit-breaker state · notifications-per-user (spam detection) · p99 time from event to delivery.

---

## LLD ↔ HLD mapping
| LLD (`solution.py`) | HLD (this doc) |
|---|---|
| `EventBus` (in-process dict) | **Kafka** `events` topic |
| `Subscriber.handle()` | a **consumer group** |
| `NotificationService` pipeline | **Fan-out Service** (recipients → prefs → render) |
| per-channel `try/except` **(bulkhead)** | **one topic + worker pool per channel** |
| `RetryPolicy` backoff | consumer retries → **DLQ** after N attempts |
| `NotificationChannel` (Strategy) | per-channel **worker fleets** hitting SMTP / Twilio / FCM |
| `UserPreference` dict | Postgres + Redis cache |
| *(publisher returns immediately)* | **outbox pattern** — never block the producer |
| *(nothing)* | dedup keys · priority lanes · per-user caps/digest · circuit breakers · cost routing |

**The line to say:**
> *"The LLD decoupled the producer from the consumers with an interface; the HLD decouples them with a
> **queue** — and the same per-channel isolation that was a `try/except` becomes a **separate topic and
> worker pool per channel**, so one dead provider can't back up any other."*
