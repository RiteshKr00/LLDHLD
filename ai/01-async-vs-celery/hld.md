# Async and queues at scale

## 1. Numbers first
600k background jobs/day, 4s average → **~7 jobs/sec**, peak 10× = **70/sec**.
Little's Law: 70 × 4s = **280 concurrent in flight**. That's a worker-pool sizing problem, not
a code problem.

## 2. Sizing the pools, per workload
| Workload | Bound by | Concurrency per worker |
|---|---|---|
| LLM calls | provider latency, I/O | **high** (50–200) — mostly waiting |
| Image/doc processing | CPU | **low** (= cores) — the GIL is real |
| DB writes | connection pool | ≤ pool size, or you exhaust connections |

**The trap:** one pool tuned for the average is wrong for both. That's the argument for
separate queues restated as capacity planning.

## 3. What breaks, in order
1. **Broker as SPOF** — Redis dies, nothing queues. Sentinel/HA or managed.
2. **Connection-pool exhaustion** — high worker concurrency × a small DB pool = timeouts that
   look like DB problems. Size the pool *from* worker concurrency.
3. **Queue depth unbounded** — an infinite queue is a slow failure with worse latency. Cap it
   and shed load with a clear error.
4. **Poison messages** — one bad payload retried forever. Dead-letter after N attempts.
5. **Thundering herd on recovery** — the broker comes back and 280 workers hit the provider at
   once. Jitter, and ramp.

## 4. Delivery semantics — pick deliberately
`acks_late=True` gives **at-least-once**: safe against worker death, and **requires
idempotency**. Without it you have at-most-once, and a worker crash silently drops work.
Say which you chose and why — most candidates don't know they chose.

## 5. Scheduling and ordering
Celery gives no ordering guarantee across workers. If order matters, you need a partition key
and one consumer per partition — which is a Kafka-shaped problem, not a Celery-shaped one.
Recognising that boundary is the senior answer.

## 6. Observability
Queue depth **per queue** (the leading indicator) · task duration p50/p95/p99 · retry rate ·
dead-letter rate · worker saturation · **age of the oldest queued task**, which is the number
that actually tells you whether you're falling behind.
