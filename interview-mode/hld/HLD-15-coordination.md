# HLD-15 — Distributed Coordination (ZooKeeper / etcd)

## META
- difficulty: hard
- time: 45 min
- tags: consensus, raft, quorum, leases, fencing-tokens, watches, split-brain, cp
- why-it-matters: the only round about **consensus** — the machinery under round 09's leader election — and
  the only one whose best opening move is arguing you probably **shouldn't build it**.

## PROMPT
> "Design a distributed coordination service — the thing other services use for leader election,
> distributed locks, configuration and service discovery."

## CLARIFY
- **How much data does it hold?**
  → KB to a few hundred MB of critical metadata, **never application data.** Get this in the first minute.
- **How many clients, and what write rate?**
  → A few thousand processes; writes in the low thousands/sec at most, reads ~100× that.
- **Consistency or availability during a partition?**
  → **Consistency.** A minority refuses writes — the unavailability is a feature, not a bug.
- **Do clients poll, or must they be notified?**
  → **Ordered watches**, resumable from a revision. Config rollout and discovery are the consumers.
- **What failure does the customer actually care about?**
  → Two processes both believing they hold the same lock, and both writing. That's the round.
- **Can I just use a Postgres row?**
  → **Ask this.** Often yes, and saying so scores. §1 has what forces the upgrade.

## STEP 1 — Requirements
**Functional:** create/read/delete a small key · **compare-and-swap write** · a **session with a TTL** and keys
that die with it · **ordered watch** on a key or prefix · election, locks, registration built *on top of* those.
**Non-functional:** linearizable writes · **f failures with 2f+1 nodes** · refuse writes in a minority · fits in
RAM on every node · acquire returns a **fencing token**, because a lock without one is unsafe.
**Out of scope:** application data · queues at volume · a Raft group across regions · ACLs.

### CHECKPOINTS
- Names the **primitives** (CAS write, session/ephemeral key, ordered watch), not "leader election" as one
- States **CP explicitly**: a minority refuses writes, and that is correct, not an outage to engineer away
- Bounds the data — **critical metadata that fits in memory**, never application data

### TRAPS
- "Distributed lock" as the requirement. It is *mutual exclusion the resource itself enforces* (§3)

### FOLLOWUPS
- *"Why not `UPDATE locks SET owner=… WHERE owner IS NULL` in Postgres?"* ← honest answer: you often can

## STEP 2 — Capacity
```
cluster   5 nodes -> 2f+1 with f=2 -> survives 2 dead nodes
dataset   50,000 keys × 1 KB ≈ 50 MB -> fits in RAM, replicated on EVERY node
writes    ONE write = leader fsync + RTT to the SLOWEST majority node + its fsync = a LATENCY;
          throughput needs concurrency + batched commits on top of it
          same-AZ ~1-2 ms -> ~500-1,000/sec ONE sequential client, ~10,000/sec AGGREGATE
          cross-AZ ~2-5 ms -> ~200-500/sec seq;  cross-region 60-100 ms -> ~10-16/sec ** never **
          vs one Postgres box at 50k+ writes/sec
reads     linearizable -> leader + quorum check;  stale local read -> any node, 100k+/sec
sessions  3,000 procs × 1 lease, keepalive/3 s -> 1,000/sec, LEADER-LOCAL (in-memory, no consensus),
          but lease GRANT and EXPIRY are real writes: a mass restart is a quorum spike
watches   3,000 clients × ~10 keys = 30,000 registrations, in memory on the serving node
```

### CHECKPOINTS
- Sizes it (50,000 × 1 KB ≈ 50 MB) → **fits in RAM on every node**, which licenses full replication
- Derives a write as **leader fsync + RTT to the slowest majority node + its fsync**, ~1-2 ms same-AZ
- Splits per-client latency from the **~10k/sec aggregate** vs a DB box's 50k+ → **metadata only**
- Knows **keepalives cost no Raft round trip**, but grant and expiry do — a mass restart is a write spike

### TRAPS
- Dividing 1 s by the round trip and calling it cluster throughput — that is one client's ceiling, ~10× low
- Sizing at 7 or 9 nodes "to be safe": a bigger quorum means **slower writes**, for almost no availability

### FOLLOWUPS
- *"Where does the 10,000 writes/sec ceiling physically come from? And why 5 nodes, not 6?"*

## STEP 3 — API
```
POST /v3/kv/txn          {compare[], success[], failure[]}  -> the CAS primitive; all else builds on it
PUT  /v3/kv/put          {key, value, lease_id?}            -> {revision}
GET  /v3/kv/range        {key|prefix, revision?, stale?}    -> {kvs[], revision, create_revision}
POST /v3/lease/grant     {ttl_seconds}                      -> {lease_id}
POST /v3/lease/keepalive {lease_id}                         -> stop sending = the lease lapses
GET  /v3/watch           {key|prefix, start_revision}       -> an ORDERED stream of change events
```
One monotonic **`revision`** per keyspace rides on every response: a watch resumes *from* one so a reconnect
misses nothing, and a lock's `create_revision` **is the fencing token** (§3).

### CHECKPOINTS
- Writes are **CAS on a revision**, not blind puts — the store arbitrates the race, not the client *(as in 08)*
- Responses carry a **monotonic revision** and a watch **resumes from one**, so a dropped connection loses nothing

### TRAPS
- An `acquire_lock()` returning only a boolean — you shipped the corruption bug into every caller
- Watches that only say "something changed, re-read" — a herd generator; ZK's one-shot watches are worse

### FOLLOWUPS
- *"A client's watch drops for 30 seconds. On reconnect, how does it know what it missed?"*

## STEP 4 — Data model — the replicated log and the keyspace
**Not really a KV store.** It is a replicated log applied in order; the KV map is derived state.
```
idx 41 | put /services/api/i-7 = 10.0.0.7 (lease 88)
idx 42 | put /config/rate_limit = 500
idx 43 | del /locks/reindex               (lease 61 lapsed)
   └─▶ apply in order ─▶ STATE MACHINE = the KV map every node holds in RAM
```

| Kind | Lives until | Keys |
|---|---|---|
| **Persistent** | explicitly deleted | `/config/<svc>/<key>` — flags, cluster membership |
| **Ephemeral** (lease-bound) | its **session's lease lapses** | `/locks/…`, `/leader/…`, `/services/<name>/<id>` |

### CHECKPOINTS
- Models it as a **replicated log applied in order**, KV as derived state — not "a small database we replicate"
- Splits **persistent from ephemeral (lease-bound)**, with locks, leadership and registration ephemeral
- Ordering is **global across the keyspace** (one revision), so events on different keys are comparable

### TRAPS
- A lock as a persistent key with a `released` flag: the holder crashes and it is held forever
- Discovery as persistent registration + a sweeper — **the session *is* the health check**

### FOLLOWUPS
- *"Your process is SIGKILLed holding `/locks/reindex`. Name the thing that deletes that key."*

## STEP 5 — Architecture
```
client ─write─▶ any node ─▶ LEADER: append ──fsync──▶ replicate to followers
   (forwarded)               └── commit once a MAJORITY has it durably ─▶ apply ─▶ fire watches
client ─read──▶ linearizable : leader + a quorum check that it is STILL leader
                serializable : any node, local, possibly milliseconds stale
```
A follower forwards writes, never writes locally. The client library holds one session per *process*, not per
lock — per-lock sessions multiply keepalive load and the expiries to commit when that process dies.

### CHECKPOINTS
- **All writes go through the leader**; a follower forwards, so there is one writer by construction
- An entry commits **when a majority has it durably**, not when the leader has written it locally
- Separates **linearizable (pays a quorum check) from stale local reads**, and says who can take stale — config and discovery, not lock acquisition

### TRAPS
- Assuming a leader read is fresh — a **deposed** leader serves stale data until it re-confirms with a quorum

### FOLLOWUPS
- *"The leader is partitioned from the other four. What does it do, and when?"*

## DEEP DIVE — Raft, leases, and the fencing token

### 1. The honest question first: why not a database row?
```sql
SELECT pg_advisory_lock(hashtext('reindex'));    -- real mutual exclusion, zero new infrastructure
UPDATE locks SET owner=:me, expires_at=now()+interval '30 s'      -- or a TTL version that self-heals
 WHERE name='reindex' AND (owner IS NULL OR expires_at < now());  -- rowcount tells you if you won
```

| You need | Postgres row | Coordination service |
|---|---|---|
| mutual exclusion at low rate | fine — use it | overkill |
| release when the holder dies | ends with the *connection*, and a pooler outlives the process | the cluster expires the lease on **its own clock** |
| **leader failover in seconds** | you are now building it | this *is* the product |
| ordered change notification | polling | watch resumed from a revision |
| survives losing the store | one primary | tolerates f of 2f+1 |

The failover row is the real one: **Postgres has one primary**, so promoting a replica is the same election
problem one level down. **Raft** underneath: one leader per term, a log appended in order and accepted only
from that leader, committed once a **majority including the leader** has it durably — and any node seeing a
higher term steps down at once. It guarantees a committed entry is in every future leader's log; it does not
guarantee availability in a minority, or that *your client* is safe (§3).

### 2. Why a MAJORITY is the magic number
```
5 nodes. An entry commits once {A,B,C} have it. A future leader must win a majority too, say {C,D,E}.
Two majorities of the same set MUST intersect — here at C. A vote goes only to a candidate whose log
is at least as up to date as the voter's, so C refuses to elect anyone missing that entry.
   ==> a committed entry can never be lost. That overlap is the entire trick.

nodes  majority  tolerates
  3       2         1     2f+1 with f=1
  4       3         1     <- the 4th node buys NOTHING and slows every write
  5       3         2     the usual production answer
  7       4         3     more overlap, more latency; rarely worth it
```
Lose f+1 and nothing is corrupted — the cluster **stops accepting writes**: CP made physical. The price is the
quorum round trip from STEP 2 (~10k/sec vs a DB box's 50k+): kilobytes of critical metadata, never application
data, never a work queue, never a per-request counter.

### 3. The fencing token — the idea this round exists for
A lock is a **lease** — the worker lease of the scheduler (09), the TTL seat hold of Ticketmaster (08) — with
one difference: **the cluster runs the expiry clock, not the holder**, so a partitioned client cannot keep its
lock alive by believing in it. Short TTL = fast failover but false expiries under GC pauses; long = stable but a
longer gap with nobody leading; 10-15 s. But **a lock alone does not prevent corruption:**
```
t=2   A holds /locks/reindex (lease 10 s), is writing to a shared resource, and hits a 15-second
      stop-the-world GC pause. A is frozen and CANNOT KNOW IT.
t=11  A's lease lapses; the cluster deletes the key. Nothing can tell A — it is not running.
t=12  Client B acquires the lock, correctly, and starts writing.
t=17  A wakes, last thought still "I hold the lock", and finishes its write.
      ==> two concurrent writers. Corruption. And the lock service did nothing wrong.
```
No timeout fixes this: the pause can exceed any TTL, and A cannot check the clock *atomically with* its write.
**The fix: a monotonically increasing fencing token, checked by the resource being protected.**
```
acquire returns a token from the consensus that granted the lock
   etcd: the key's create_revision    ZooKeeper: the zxid / sequential znode number
   A gets 33.  B gets 34.  Tokens NEVER go backwards.
the resource keeps last_seen_token and REJECTS anything lower
   t=12  B writes 34 -> accepted, last_seen = 34
   t=17  A writes 33 -> 33 < 34 -> REJECTED. Corruption prevented.
```
1. **The check is at the resource, not the lock service**, which is not in A's write path. "Ask if I still hold
   it, then write" fails the same way: the pause lands between the ask and the write.
2. **The token must come from the consensus that granted the lock** — a local counter, UUID or wall clock is not
   monotonic across processes.
3. **If the resource cannot be fenced** (a third-party API with no conditional write) the lock is *advisory*;
   make a duplicate harmless with **idempotency and dedup**, as in **payments (05)**. A shorter TTL is not it.

You do not prevent the second leader — you make it **harmless**.

### 4. Watches, and the thundering herd
```
1,000 instances watch /config/rate_limit; you change it ONCE -> 1,000 notifications, then 1,000
immediate GETs: a 1,000× read spike inside 50 ms, commit latency rises, elections start
```
- **Put the new value in the notification** — no follow-up read. etcd does; ZK's one-shot watches do not.
- **Client-side jitter**: sleep 0-2 s before re-reading (the scheduler's midnight-herd trick).
- **Serve the re-read from followers/learners** — it is a read, and config may be milliseconds stale.
- **Watch your predecessor, not the lock.** Each waiter makes a *sequential* ephemeral node and watches only the
  one ahead, so a release wakes **one** waiter, not N — an O(N) storm becomes O(1), FIFO fairness free.

### CHECKPOINTS
- Opens with **"a database row is often enough"** and the upgrade triggers: automatic failover, cluster-clock expiry, ordered watches
- Explains Raft as **one leader per term + replicated log + majority commit**, plus "higher term ⇒ step down"
- Explains **why a majority**: two majorities overlap and a vote needs an up-to-date log, so a committed entry survives — hence **2f+1 tolerates f**
- Names the cost as **a quorum round trip per write**, gives a number, concludes **metadata only**
- Walks the **GC pause → lapsed lease → two concurrent writers** timeline, and says the lock service did nothing wrong
- Fixes it with a **fencing token checked at the protected resource**, and why an "am I still holder?" check cannot work
- Says the token comes from **the consensus that granted the lock** — not a local counter, UUID or wall clock
- Names the **unfenceable resource** and falls back to **idempotency and dedup**, not a shorter TTL
- Bounds **watch fan-out**: value-carrying events, jitter, follower reads, or **watch-your-predecessor**

### TRAPS
- "We use ZooKeeper, so we have a distributed lock" with no fencing token. This is *the* miss of the round
- Fixing the pause with a longer TTL, or a check before writing — the pause lands between check and write
- Minting the token locally, or expecting the lock service to reject the stale writer — it never sees it

### FOLLOWUPS
- *"Round 09 said 'two leaders, briefly'. What stops the paused one's write from landing?"*
- *"The resource is a third-party API that can't reject an old token. Now what?"*

## STEP 7 — Scale
- **Reads scale by adding nodes; writes do not.** Add followers or **learners (non-voting)** and serve
  serializable reads locally — reads are ~99% of traffic, so that is most of the win.
- **Writes get *slower* as you add voters**: the commit waits on the slowest member of a bigger majority. The
  only lever is **fewer writes** — one lease per process, batched config updates, no counters here.
- **Multiple Raft groups** only when one group's ceiling is genuinely hit (CockroachDB, TiKV). **The cost is
  global ordering** — revisions across groups are incomparable, so "did X change before Y?" has no answer.
- **Geography:** one group per region; stretched over three continents it does ~100 writes/sec.
- **Compaction:** snapshot and truncate the log. **Watch history is bounded by compaction**, so a client
  resuming from a compacted revision must resync from scratch.

### CHECKPOINTS
- Says **adding nodes scales reads but slows writes**, and names the only write lever (fewer writes), not hardware
- Says **multiple Raft groups cost cross-group ordering** — the reason not to shard early
- Knows the log is **snapshotted and compacted**, and that compaction breaks a stale client's watch resume

### TRAPS
- "We'll add nodes to handle more writes" — exactly backwards for a quorum system

### FOLLOWUPS
- *"A client reconnects asking to watch from revision 900,000; the cluster compacted to 1,200,000. What then?"*

## STEP 8 — Failure
```
5 nodes, partition {A,B,C} | {D,E}
{A,B,C}  majority    -> keeps or elects a leader -> keeps committing
{D,E}    no majority -> cannot elect, cannot commit -> REFUSES writes
```
The minority must also **stop linearizable reads and let its leases lapse**, or a client there keeps a lock the
majority already reassigned. **Being unavailable in a minority is the design working** — a rate limiter fails
open because being wrong is cheap; this and **payments (05)** fail closed. The dangerous case is the whole
cluster being down, because it is your most shared dependency:

| Depends on it for | While coordination is down | Verdict |
|---|---|---|
| config already read | serve the last-known-good cached copy | **keep working** |
| service discovery | keep cached endpoints, marked stale | **keep working** |
| an already-held leadership lease | cannot renew → step down when it expires | **must stop** |
| acquiring a *new* lock or leadership | fail closed, retry with backoff | **must stop** |
| anything on the per-request path | shouldn't exist — that is a design bug | **fix the design** |

**Rule: every client caches last-known-good state and keeps serving; nothing acquires new exclusive rights.**
A client whose **session is lost** while it still runs (long GC) must assume it lost everything, step down, and
re-acquire with a *higher* token. A dead leader is replaced within about one randomized election timeout.

### CHECKPOINTS
- States the **minority refuses writes and lets leases expire**, calls it correct CP, contrasts a fail-open component
- Gives a **degradation plan for a total outage**: cached config and discovery keep serving, new locks stop
- Says a client that **loses its session must assume it lost the lock**, step down, and re-acquire with a higher token

### TRAPS
- A design where every user request touches coordination — the most fragile component made the most trafficked

### FOLLOWUPS
- *"etcd is down for twenty minutes. Which of your services keep working, and which stop?"*

## STEP 9 — Wrap
- **Bottleneck:** write throughput, floored by fsync + the quorum round trip — **not fixable by adding nodes.**
  Second: watch fan-out on one popular key.
- **Tradeoffs:** CP with real unavailability vs an AP store that would silently permit two leaders · one Raft
  group (global ordering, capped writes) vs many (scales, loses cross-key ordering) · short lease (fast failover,
  false expiries) vs long · a Postgres row (free, usually enough) vs a consensus cluster to operate.
- **Monitoring:** **leader elections per hour**, should be ~0 · commit latency p99 **per node** · quorum health ·
  active sessions vs expected process count · watch fan-out · DB size vs quota (a full etcd goes read-only).
- **Honest closer:** most teams should use the coordination service the platform already runs — etcd under
  Kubernetes, Consul, ZooKeeper under Kafka — for as few things as possible.

### CHECKPOINTS
- Names the bottleneck as **write throughput bounded by fsync + quorum round trip**, unfixable by adding nodes
- Names **leader elections per hour** as the one metric, ~0 expected, churn being the earliest symptom of everything else

### TRAPS
- Naming CPU/memory as the headline metric instead of leader-election churn

### FOLLOWUPS
- *"Would you build this, or use what's already running in your platform?"*

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | "Use ZooKeeper/etcd for a lock and leader election." Names products, consensus is a black box, no fencing token, assumes the service is always up |
| **Senior** | opens with **"a Postgres row is often enough"** and what forces the upgrade · Raft as leader + log + majority commit · **2f+1, and why odd** · a quorum round trip per write, with a number and the per-client vs aggregate split, so metadata only · leases so a dead process's lock self-heals on the *cluster's* clock · **fencing tokens checked at the resource** · minority refuses writes · a degradation plan |
| **Staff** | all that **+ why two majorities must overlap** · linearizable vs serializable reads and who takes stale · the "can't fence it, fall back to idempotency" answer · the watch herd and **watch-your-predecessor** · multiple Raft groups and the **global ordering you give up** · treating coordination as the most dangerous shared dependency, and designing every client to survive its absence |

## REFERENCE
**Leader election, end to end.**

1. **P** opens a session: `lease/grant ttl=10` → `lease_id = 88`, keepalives every 3 s answered from the
   leader's memory. One session per process, not per lock.
2. The entire election is **one compare-and-swap**:
   ```
   compare: create_revision("/leader/scheduler") == 0   # nobody holds it
   success: put("/leader/scheduler", "P", lease = 88)   # ephemeral — dies with the session
   failure: get("/leader/scheduler")                    # find out who did
   ```
3. P reads back **`create_revision` = 4,271 — that is its fencing token**, and every write to the protected
   resource carries it. Had it lost, P would **watch** from the returned revision rather than poll.
4. P's host freezes 15 s. Keepalives stop; at t+10 the lease lapses **on the cluster's clock**, which deletes
   `/leader/scheduler`. Nobody cleaned up, and P was never told. Q's watch fires, Q wins the same txn, gets **4,502**.
5. P wakes still believing it leads and writes 4,271. `4,271 < 4,502` → **rejected**, and P's library sees the
   session was lost and steps P down. **No corruption** — two leaders *did* exist, made harmless.
6. Meanwhile 5 → 4 alive, majority 3: fine. Lose a second: 3 alive, majority 3, still fine — that is f = 2. Lose
   a third: **no quorum**, writes stop, every leader steps down as its lease lapses, and everything downstream
   serves cached config and takes no new locks until quorum returns.

## ONE-LINER
> *"First I'd push back: at small scale a Postgres advisory lock or a conditional UPDATE is real mutual
> exclusion. A coordination service earns its keep when I need leader failover in seconds, expiry the cluster
> enforces on its own clock rather than on my connection, and ordered watches nothing can miss. Underneath is
> **Raft** — one leader, a replicated log, a **majority quorum** — and a majority is magic because any two
> majorities overlap, so a committed entry is in every future leader's log; that's also why it's 3 or 5 nodes,
> 2f+1 to tolerate f. It costs a **quorum round trip per write**: 1-2 ms same-AZ, so one sequential client gets
> under a thousand a second and the cluster tops out near 10k with batching, against a database box's 50k+ —
> which is why this holds kilobytes of metadata, never application data. And the part most people miss: a lock
> alone doesn't prevent corruption — a GC pause can outlive the lease, so acquire returns a **monotonically
> increasing fencing token** and the **protected resource** rejects any stale one; if it can't be fenced, the
> answer is idempotency, not a shorter TTL. Finally it's deliberately CP: a minority refuses writes, and every
> client caches config and endpoints so an outage costs us leadership changes, not traffic."*
