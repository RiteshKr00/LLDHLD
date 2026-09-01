# HLD-09 — Distributed Job Scheduler (cron at scale)

## META
- difficulty: medium-hard
- time: 45 min
- tags: leader-election, at-least-once, leases, dlq, time-partitioning
- why-it-matters: the only problem that forces **leader election** and the "who is allowed to act?"
  question. Also the cleanest at-least-once vs exactly-once discussion.

## PROMPT
> "Design a distributed job scheduler — users submit jobs to run at a time or on a cron schedule,
> and the system runs them."

## CLARIFY
- **Scale?**
  → 100M scheduled jobs, ~10,000 firing per second at peak.
- **Guarantee — at-least-once or exactly-once?**
  → **At-least-once.** Users write idempotent jobs. (Get this stated early; exactly-once is a trap.)
- **How punctual?**
  → Within a few seconds. Not hard-real-time.
- **Retries?**
  → Yes, with backoff, then give up and park it.
- **Long jobs?**
  → Some run for hours. **So a job can outlive the worker that started it** — that shapes the design.
- **Do we run user code?**
  → Assume we call a webhook / enqueue to their handler. Sandboxing is out of scope.

## STEP 1 — Requirements
**Functional:** schedule a one-off job at time T · schedule a recurring cron job · execute at the
right time · retry on failure with backoff · cancel a job · show run history.
**Non-functional:** **at-least-once execution** (never silently skip a job) · a job must not be run
**concurrently by two workers** · survive worker and scheduler death · within seconds of the target time.
**Out of scope:** running arbitrary user code sandboxed · exactly-once semantics · job dependency graphs (DAGs).

### CHECKPOINTS
- States **at-least-once** and that **jobs must be idempotent** — a shared contract with the user
- Distinguishes "never skipped" (a guarantee) from "never duplicated" (not guaranteed)
- Notes jobs can outlive workers

### TRAPS
- Promising exactly-once — see the deep dive; it's not achievable across a network you don't control
- Forgetting **cancellation**, which is awkward once a job is already dispatched

## STEP 2 — Capacity
```
jobs stored     100M scheduled jobs
firing rate     10,000 jobs/sec at peak
                ** but arrivals are SPIKY: everything scheduled for "midnight" or "the top
                   of the hour" fires at once **  <- the thundering herd of cron
storage         100M × 500 B ≈ 50 GB  (small)
history         10K/sec × 86,400 ≈ 900M runs/day × 200 B ≈ 180 GB/day -> tier/expire it
lookup pattern  "which jobs are due in the next minute?"  -> a RANGE query on time
```

### CHECKPOINTS
- Notes the **clustering at round times** — the load is not smooth, it's spiky by nature
- Identifies the core query as **a time-range scan**, which determines the index/partitioning
- Sees that run **history** dwarfs the job table

### TRAPS
- Assuming smooth load. Cron users pick `0 0 * * *`. Midnight is a wall of work.
- Ignoring history growth until it's the biggest table you own

### FOLLOWUPS
- *"Ten million jobs are all scheduled for exactly midnight. What happens at 00:00:00?"*

## STEP 3 — API
```
POST /api/v1/jobs      {name, schedule|run_at, target, payload, max_retries}  -> 201 {job_id}
DELETE /api/v1/jobs/{id}                                    -> 204   (cancel)
GET  /api/v1/jobs/{id}/runs?cursor=                         -> 200 {runs[]}
POST /api/v1/jobs/{id}/pause | /resume                      -> 204
```

### CHECKPOINTS
- Cron **and** one-off both supported by one endpoint
- Run history is queryable (users will ask "did it run?")
- Pause is separate from cancel

## STEP 4 — Data model
```
jobs(job_id, owner, schedule_expr, next_run_at, status, target, payload, max_retries)
        INDEX on (next_run_at)            <- the whole read pattern
job_runs(run_id, job_id, scheduled_for, started_at, finished_at, status, attempt, worker_id)
leases(job_id, run_id, worker_id, expires_at)     -- who currently owns this execution
```
**Time-bucketing** is the important modelling choice:
```
partition jobs by MINUTE bucket:  jobs_due:2026-08-31T14:03
-> "what's due now?" is reading ONE bucket, not scanning 100M rows
```

### CHECKPOINTS
- Indexes/partitions by **`next_run_at`** — the query is always "what's due"
- Uses **time buckets** so the due-query is a single key read
- Has an explicit **lease** concept (not just a `status='RUNNING'` flag)
- `job_runs` is separate from `jobs` — one job has many runs

### TRAPS
- `SELECT * FROM jobs WHERE next_run_at <= now()` over 100M rows every second
- Tracking execution with a boolean on `jobs` — you lose history, and a crashed worker leaves it
  stuck as "running" forever

## STEP 5 — Architecture
```
        Scheduler (LEADER only — elected)
              │  every second: read bucket for now(), push due jobs
              ▼
        Kafka / queue  ──▶  Worker pool (many, stateless)
                                 │ 1. acquire LEASE (job_id, ttl)
                                 │ 2. execute (call target)
                                 │ 3. write job_runs, release lease
                                 │ 4. compute next_run_at, re-insert into a future bucket
                                 └─ failures ─▶ retry w/ backoff ─▶ DLQ after N
```

### CHECKPOINTS
- **Only the leader schedules** — otherwise N schedulers dispatch the same job N times
- Dispatch goes through a **queue**, decoupling "it's time" from "run it"
- Workers take a **lease**, so a crash is recoverable
- Recurring jobs **re-insert themselves** for their next occurrence after running

### FOLLOWUPS
- *"You have five scheduler instances for availability. What stops all five from firing the same job?"*
- *"A worker takes a job and its machine loses power. What happens to that job?"*

## DEEP DIVE — leader election, leases, and at-least-once

### 1. Why you need a leader at all
You want multiple scheduler instances (availability). But scheduling is a **decision**, and the same
decision made five times fires the job five times.
```
5 schedulers, all reading "jobs due now" -> all 5 dispatch job X -> 5 executions
```
**Leader election:** exactly one instance is the active scheduler; the others stand by.
- Implemented with a **lease in a consistent store** — etcd/ZooKeeper/Consul, or a simple
  `SET leader:scheduler <id> NX EX 10` in Redis with continual renewal.
- The leader **renews** its lease every few seconds. If it dies, the lease expires and a standby wins
  the next attempt. Failover ≈ the lease TTL.

**The nasty detail interviewers probe:** a leader can be *paused* (GC pause, network partition),
believe it's still the leader, and act after its lease has expired — while a new leader is also
acting. Two leaders briefly.
- Mitigation: **fencing tokens** — the lease hands out a monotonically increasing number; downstream
  writes carry it, and anything with an old token is rejected.
- Or: accept it, because the **worker-side lease** (below) is your real protection against double-execution.

> Alternative worth mentioning: **shard by job_id hash** and give each scheduler its own shard.
> Then there's no single leader — each shard has one owner. Same problem, moved.

### 2. Leases at the worker — surviving crashes
```
worker: acquire lease(job_id, run_id, ttl=5 min)   -- atomic: only one can get it
        execute...
        renew the lease while still working (heartbeat)   <- for hour-long jobs
        release on completion

crash?  the lease simply EXPIRES -> another worker picks the job up
```
Note this is exactly the **hold-with-expiry** pattern from the movie-booking / Ticketmaster problems:
a lease is a claim that **self-heals** when the claimant dies. No cleanup process required.

**Long jobs need heartbeats** — otherwise a 2-hour job's 5-minute lease expires and a second worker
starts it in parallel.

### 3. At-least-once, and why exactly-once is a lie
```
worker executes the job ✔  ... then dies before recording it
lease expires -> another worker runs it again  -> DOUBLE EXECUTION
```
To avoid that you'd need "execute the side effect" and "record that we did" to be **one atomic
operation** — but the side effect is a call to *someone else's system*. You cannot make a remote HTTP
call and a local DB write atomic.

So:
- **The system guarantees at-least-once.**
- **The user's job must be idempotent** — and you make that contract explicit, and hand them a
  stable `run_id` to deduplicate with.
- "Exactly-once" in practice = **at-least-once + idempotent consumer**. Same conclusion as
  notifications (dedup keys) and payments (idempotency keys). *Third time this exact argument appears.*

### 4. The midnight thundering herd
10 million jobs all scheduled for `0 0 * * *`:
- **Jitter**: spread execution over a window (add `random(0, 60s)`) unless the user demands exactness
- **Bucket sharding**: split the `00:00` bucket into N sub-buckets processed in parallel
- **Rate-limit dispatch**: the queue absorbs the burst; workers drain at a sustainable rate — the
  jobs are late by seconds, not dropped

### CHECKPOINTS
- **Leader election** for the scheduler, with the "N schedulers = N dispatches" reason
- Knows the leader lease **can be lost while the leader thinks it holds it**, and names a mitigation
  (fencing tokens) or explains why worker leases cover it
- **Worker leases with heartbeat renewal** for long jobs
- States clearly that **exactly-once is impossible** here and why (remote side effect + local record
  can't be atomic)
- Handles the **thundering herd** with jitter / bucket sharding / queue absorption

### TRAPS
- No leader → every scheduler fires every job
- Leases without heartbeats → long jobs get double-executed at the TTL boundary
- Claiming exactly-once
- Using `status='RUNNING'` instead of an expiring lease → a crashed worker leaves the job stuck forever

### FOLLOWUPS
- *"The leader was GC-paused for 20 seconds and its lease expired. It wakes up and dispatches. Problem?"*
- *"How does a user write a job that's safe under at-least-once?"*

## STEP 7 — Scale
- **Shard by `job_id`** across scheduler shards, each with its own leader → no single global leader,
  and one shard's problems don't stop the others.
- **Workers** are stateless → scale on queue depth.
- **Time buckets** keep the due-query O(1) regardless of the 100M total.
- **History** → time-partitioned, TTL'd/archived; it's the biggest table and the least valuable.
- **Priority lanes**: a user's critical hourly report shouldn't queue behind a million low-priority pings.

## STEP 8 — Failure
- **Leader dies** → standby takes over within the lease TTL. Jobs due in that window fire slightly
  late — acceptable, since punctuality is "within seconds".
- **Worker dies mid-job** → lease expires → re-executed (at-least-once in action, and why idempotency
  is required).
- **Target endpoint down** → retry with exponential backoff; after `max_retries` → **DLQ** + alert.
  Never retry forever.
- **Queue down** → the leader can't dispatch; jobs stay in their buckets and fire late once it recovers.
  **Late, not lost.**
- **Poison job** (always fails, e.g. bad payload) → DLQ stops it from consuming the pool forever.

## STEP 9 — Wrap
- **Bottleneck:** the due-query (solved by time bucketing) and burst dispatch (solved by queue + jitter).
- **Tradeoffs:** single leader (simple, a failover gap) vs sharded leaders (more available, more moving
  parts) · at-least-once (achievable, needs idempotent jobs) vs exactly-once (not achievable) ·
  jitter (smooths load, breaks strict punctuality).
- **Monitoring:** **scheduling lag** (fired_at − scheduled_for) as the headline SLI, leader failovers,
  lease expiries (a proxy for worker crashes), DLQ depth, retry rate, queue depth at the top of the hour.
- **Next:** DAGs/dependencies, backfills, sandboxed user code, per-tenant quotas.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | a jobs table, a cron loop polling it, workers pulling |
| **Senior** | leader-elected scheduler, queue + worker pool, leases, retries with backoff and a DLQ, time-bucketed due-query |
| **Staff** | all that **+ the two-leaders/fencing-token subtlety**, heartbeat renewal for long jobs, an explicit **"exactly-once is impossible, here's the contract"** argument, and the **midnight thundering herd** with jitter |

## REFERENCE
**A cron job, one cycle:**
1. Leader (holding a renewed lease) wakes each second and reads the bucket `jobs_due:14:03`.
2. Pushes the due jobs onto the queue. It does **not** execute them — that decoupling is what lets
   the herd be absorbed.
3. A worker pulls one, **acquires a lease** (`job_id`, TTL 5 min) — an atomic claim, so only one worker
   can own this run.
4. Executes; if it's long-running, it **heartbeats** to extend the lease.
5. On success: write `job_runs`, release the lease, compute the next occurrence from the cron
   expression, and **insert into the future bucket**.
6. On failure: retry with backoff; after `max_retries` → **DLQ** and alert.

**Worker dies at step 4:** nobody cleans anything up. The lease **expires**, the job is re-dispatched,
and it runs again — which is why the contract says at-least-once and the job must be idempotent.

**Leader dies:** its Redis/etcd lease expires within ~10 s; a standby acquires it and continues from
the current bucket. Nothing is lost, some jobs are seconds late.

## ONE-LINER
> *"Two hard parts. First, **who is allowed to schedule** — if I run five schedulers for availability,
> all five will fire the same job, so exactly one holds an **elected lease** and the rest stand by.
> Second, **surviving crashes**: workers take an expiring **lease** on each run and heartbeat it for
> long jobs, so a dead worker's job is simply re-issued when the lease lapses — the same self-healing
> TTL idea as a ticket hold. That re-issue is precisely why I promise **at-least-once, not
> exactly-once**: I'd need the remote side effect and my local record to be one atomic write, and they
> can't be. So the contract is at-least-once plus idempotent jobs, and I hand the user a stable run_id
> to dedupe on."*
