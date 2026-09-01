# HLD-02 — Chat (WhatsApp / Slack)

## META
- difficulty: hard
- time: 45 min
- tags: websockets, presence, ordering, delivery-receipts, offline-queue
- why-it-matters: the classic "long-lived connections" problem. Everything else you've designed is
  request/response; this one isn't.

## PROMPT
> "Design WhatsApp. Users send messages to each other, see when they're delivered and read,
> and messages must arrive even if the recipient is offline."

## CLARIFY
- **1-on-1 only, or group chats?**
  → Both. Groups up to 256 members. (Groups are where fan-out reappears.)
- **Delivery guarantees?**
  → **A message must never be lost.** Duplicates are bad but survivable; loss is not.
- **Receipts?**
  → Sent ✓ / Delivered ✓✓ / Read ✓✓(blue). All three.
- **Ordering?**
  → Messages within a conversation must appear **in the same order for everyone**.
- **Offline?**
  → Yes — queue and deliver when the recipient reconnects.
- **History?**
  → Server stores it (unlike real WhatsApp, which is device-local). Keep it simple.
- **E2E encryption?**
  → Out of scope. Say it explicitly — it's a rabbit hole.
- **Media?**
  → Out of scope; assume URLs.

## STEP 1 — Requirements
**Functional:** send/receive 1-1 and group messages · delivery + read receipts · **online/last-seen
presence** · offline queue · message history.
**Non-functional:** **never lose a message** · low latency (<200 ms) · **ordered within a
conversation** · survive the client dropping connection constantly (mobile).
**Out of scope:** E2E encryption · media storage · voice/video · multi-device sync.

### CHECKPOINTS
- "Never lose a message" stated as the hard guarantee (this drives persistence-before-ack)
- **Ordering scoped to a conversation**, not globally
- Presence named as a separate feature (it has completely different requirements)
- Offline delivery treated as a first-class case, not an edge case

### TRAPS
- Promising **global** ordering — impossible and unnecessary. Order matters *within a chat*.
- Forgetting that mobile clients disconnect constantly — that's the normal case, not the failure case

## STEP 2 — Capacity
```
users        500M DAU
messages     40 per user per day -> 20B/day ÷ 86,400 ≈ 230,000 msgs/sec   (peak ~500K)
connections  500M DAU, say 100M concurrent -> 100M OPEN WEBSOCKETS
             ^ THE number. One server holds ~50-100K connections
             -> 100M / 100K = ~1,000 gateway servers just to hold sockets
storage      20B msgs/day × 200 B ≈ 4 TB/day  (hot for days, archive after)
```

### CHECKPOINTS
- Computes **concurrent connections**, not just QPS ← the thing that's different about this problem
- Converts connections into **server count** (~100K sockets per box)
- Notes storage is large and needs tiering

### TRAPS
- Only computing messages/sec and never connections — but **holding the socket is the cost**, even
  when nobody is typing
- Assuming a stateless web tier; here the tier is **stateful by definition** (it holds your socket)

### FOLLOWUPS
- *"Where does a user's connection live, and how does a message find it?"* ← the routing question

## STEP 3 — API
```
WebSocket  wss://chat/connect          <- the primary channel, not REST
  → send        {to, conversation_id, client_msg_id, text}
  ← message     {msg_id, from, text, seq}
  ← receipt     {msg_id, state: delivered|read}
  ← presence    {user_id, online|last_seen}

REST (for things that aren't real-time)
GET /api/v1/conversations/{id}/messages?before=<seq>&limit=50
POST /api/v1/conversations            {members[]}
```

### CHECKPOINTS
- **WebSocket**, not polling — a chat app cannot poll
- History fetched over **REST with a cursor**, not over the socket
- Client sends a **`client_msg_id`** ← the dedup key for retries

### TRAPS
- Designing it all as REST + polling. Polling every 2s × 100M users = 50M QPS of *nothing happening*.

## STEP 4 — Data model + DB
```
messages(conversation_id, seq, msg_id, sender_id, text, created_at)
         PARTITION KEY = conversation_id, CLUSTERING KEY = seq DESC
receipts(msg_id, user_id, state, at)
conversations(conv_id, type, members[])
user_connection(user_id -> gateway_server_id)     -- Redis, ephemeral
presence(user_id -> last_heartbeat)               -- Redis with TTL
```
- **Messages → Cassandra**: write-heavy, append-only, always queried as "last N of one conversation".
  Partitioning by `conversation_id` puts a whole chat on one node → the query is one partition read.
- **Connection registry + presence → Redis**: ephemeral, TTL'd, changes constantly.

### CHECKPOINTS
- Partitions messages by **conversation_id** (so one chat = one partition = fast reads)
- Chooses a **wide-column store** for messages and justifies it (write-heavy, no joins, time-ordered)
- Keeps the **connection registry** in a fast ephemeral store, separate from durable data

### TRAPS
- Partitioning by `user_id` — then reading one conversation means gathering from both participants' partitions
- Storing presence in the main DB — it changes every 30s per user; that's 500M writes/heartbeat cycle

## STEP 5 — Architecture
```
Client ──WebSocket──▶ Gateway (holds the socket; ~100K per box)
                         │
                         ▼
                   Chat Service ──▶ Cassandra (persist FIRST)
                         │
                         ├──▶ Redis: who is user B connected to?
                         │        └─▶ route to that Gateway ──▶ push to B
                         └──▶ if offline: leave it; B pulls on reconnect

Redis: user_connection{user_id -> gateway_id}, presence{user_id -> ts, TTL 60s}
```

**Send flow (this order matters):**
1. Client sends over its socket, with `client_msg_id`
2. Chat Service **persists to Cassandra first** ← durability before acknowledgement
3. **Ack the sender** (✓ Sent)
4. Look up B's gateway in Redis → forward → gateway pushes down B's socket
5. B's client acks → ✓✓ Delivered
6. B opens the chat → ✓✓ Read

### CHECKPOINTS
- **Persist before ack** — acking first and then crashing loses a message, violating the one hard guarantee
- A **connection registry** maps user → gateway, so servers can route to each other
- Offline = simply don't push; the message is already durable and gets pulled on reconnect
- The three receipts map to three distinct points in the flow

### TRAPS
- Ack-then-persist (fast, and loses messages)
- Assuming sender and recipient are on the same gateway — with 1,000 gateways they almost never are
- Treating "offline" as an error path instead of the normal path

## DEEP DIVE — ordering, and why timestamps don't work

**The problem:** A and B both send to the same chat at "the same time". Everyone must see the same order.

**Why client timestamps fail:** clocks are wrong. A phone can be minutes off. Sort by client time and
a reply appears above the message it answers.

**Why server timestamps fail too:** two different chat servers can stamp the same millisecond, and
their clocks also drift.

**The fix — a per-conversation sequence number.** The conversation is the ordering domain (that's why
we scoped ordering to a conversation in Step 1):
```
messages(conversation_id, seq, …)     seq = 1, 2, 3, … within THIS conversation
```
- One writer per conversation assigns `seq` (a lightweight per-conversation lock, or route all writes
  for a conversation to one shard/partition owner).
- Clients render by `seq`, never by timestamp.
- **Gap detection for free:** if a client has seq 1,2,3,6 it *knows* it missed 4 and 5 and asks for them.

**And the dedup half:** delivery is at-least-once, so the client attaches a `client_msg_id` (a UUID).
The server stores it and, on a retry, returns the original result instead of inserting a second copy.
*(The same idempotency-key idea from the Splitwise/payments world.)*

### CHECKPOINTS
- Rejects both client **and** server timestamps, with the reason (clock skew)
- Proposes a **per-conversation monotonic sequence number**
- Notes that ordering only needs to hold **within a conversation** — that's what makes it tractable
- Uses **`client_msg_id`** for dedup because delivery is at-least-once
- Bonus: gaps in `seq` let the client detect and request missing messages

### TRAPS
- "Just use timestamps" — the single most common wrong answer
- Trying to make a **global** sequence — that's a distributed counter and an instant bottleneck

### FOLLOWUPS
- *"Two servers assign seq 5 to different messages in the same chat. What went wrong?"*
- *"The client's socket drops mid-conversation and reconnects. How does it catch up?"*

## STEP 7 — Scale
- **Gateways**: stateless-ish, horizontally scaled; ~100K sockets each. Scale = add boxes.
- **Sticky routing**: a user stays on one gateway for the life of the connection; Redis holds the map.
- **Groups (256 members)**: fan-out again — one message → up to 256 pushes. Same push/pull thinking
  as the news feed, but the group cap keeps it bounded (this is *why* group size is capped).
- **Presence is the hidden cost**: naive presence = every client heartbeating every 30s = 3M QPS of
  nothing. Mitigate: longer intervals, only publish presence **changes**, and only to people
  currently *viewing* that contact.
- **Cassandra**: shard by `conversation_id`; hot group chats are the hot partitions.

## STEP 8 — Failure
- **Gateway dies** → 100K clients reconnect (to other gateways), registry entries TTL out. Clients
  resync by `seq`. Messages were already durable — nothing lost.
- **Cassandra write fails** → **don't ack**. The client retries with the same `client_msg_id`; dedup
  makes the retry safe.
- **Recipient offline** → nothing special: the message is in Cassandra; the pull-on-reconnect path
  delivers it.
- **Redis (connection registry) down** → can't route pushes; messages still persist and are delivered
  on reconnect. **Degrades to store-and-forward.**

## STEP 9 — Wrap
- **Bottleneck:** concurrent connections (memory/FDs), and presence chatter — *not* message throughput.
- **Tradeoffs:** persist-before-ack costs latency but buys the durability guarantee · per-conversation
  seq gives ordering without a global counter · at-least-once + dedup instead of exactly-once.
- **Monitoring:** connected sockets per gateway, message p99, undelivered-queue depth, seq gaps
  reported by clients, reconnect rate.
- **Next:** E2E encryption, multi-device sync (hard — each device needs its own delivery state), media.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | REST + polling, timestamps for ordering, "store messages in MySQL" |
| **Senior** | WebSockets, connection registry, persist-before-ack, Cassandra partitioned by conversation, offline pull |
| **Staff** | all that **+ per-conversation seq with the clock-skew reasoning**, client_msg_id dedup, gap detection, and names **presence** as the sneaky scaling cost |

## REFERENCE
**Send, end to end:**
1. B's phone has an open WebSocket to gateway-42. Redis: `conn:B -> gateway-42`.
2. A sends `{to: B, client_msg_id: uuid, text}` over A's socket to gateway-7.
3. Chat Service assigns `seq` for that conversation, **writes to Cassandra**, and only then acks A (✓).
4. Looks up `conn:B` → gateway-42 → forwards → gateway-42 pushes down B's socket.
5. B's client acks → ✓✓ delivered. B opens the chat → ✓✓ read.

**B was offline instead:**
- Step 4 finds no connection. Nothing else happens — the message is already durable.
- B reconnects, sends `last_seen_seq`, server returns everything after it. Delivered.

**Why it's ordered:** every client renders by `seq`, which is assigned by a single writer per
conversation. No clock is ever trusted.

## ONE-LINER
> *"The unusual constraint here isn't throughput — it's holding 100M live sockets, so the web tier is
> stateful and I need a connection registry to route between gateways. I persist before I ack so a
> message can never be lost, and I order by a **per-conversation sequence number** rather than any
> timestamp, because clocks are unreliable and ordering only has to hold within one chat."*
