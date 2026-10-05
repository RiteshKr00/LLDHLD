# The gateway at scale

## 1. Numbers first
600k calls/day across 4 features ≈ **7 QPS average, 70 peak**. Each call holds a connection
for ~2s (longer when streaming), so Little's Law gives **~140 concurrent connections held
open** at peak.

That's the number that matters: the gateway is **connection-bound, not CPU-bound.** It spends
its life waiting on providers.

## 2. Which means: async, and generous file descriptors
A thread-per-connection gateway needs 140+ threads doing nothing but waiting — wasteful and
it caps you early. This is the one place where `async` genuinely earns its complexity, because
the workload is pure I/O waiting.

And raise the fd limit. 140 upstream connections plus 140 downstream plus Redis is thousands
of sockets under load, and the default limit will find you first.

## 3. Deploy it as a library or sidecar, not a remote service
A remote gateway adds a network hop **and** a failure domain to every call, for a component
whose job is to protect latency. Options, best first:

| Shape | Added latency | SPOF risk |
|---|---|---|
| **In-process library** | ~0 | none |
| **Sidecar** (same pod) | ~1ms loopback | contained |
| Central service | a full network hop | a real SPOF |

Pick the central service only when you need **global** rate state enforced in one place and
can't do it with Redis — which is rare, because Redis *is* the shared state.

## 4. Statelessness, and the one piece of state
The gateway holds no per-request state, so it scales horizontally. The exceptions all live
externally:

- **rate buckets** → Redis (shared, or the limiter is decorative)
- **circuit-breaker state** → Redis if you want breakers shared across instances, in-memory if
  per-instance is acceptable. **In-memory is usually fine and simpler**: each instance learns
  independently, and they converge quickly under real traffic
- **capability registry** → config, cached in memory, refreshed on a pub/sub signal

## 5. What breaks, in order
1. **Connection exhaustion** — fds or upstream pool limits, before CPU
2. **Redis latency on the hot path** — a bucket check per request; if Redis p99 is 5ms you've
   spent a quarter of your budget. Use a local token cache with periodic reconciliation
3. **Head-of-line blocking** — one slow provider holding connections that other traffic needs.
   Per-provider connection pools, not one shared pool
4. **Usage-ledger backpressure** — if the ledger write is synchronous it becomes the bottleneck.
   It must be fire-and-forget with a local buffer
5. **Config reload storms** — every instance reloading the registry at once

## 6. Degradation
The gateway should never be the reason a request fails. If Redis is down, **fail open on rate
limiting** (log it loudly) rather than rejecting traffic — the provider's own 429 is a safer
backstop than your limiter becoming an outage. Note this is the opposite of the tenant-scope
decision in topic 03, and the reason is the asymmetry: a missed rate limit costs money, a
missed tenant filter leaks data.

Being able to explain *why* fail-open is right here and fail-closed is right there is the
answer that shows you understand the principle rather than the slogan.

## 7. Observability
Per provider and per tenant: request rate, error rate **split by class** (429 / 5xx / timeout /
parse), p50/p95/p99, **time-to-first-token** for streams, tokens and cost, retry rate,
fallback rate, breaker state.

**Leading indicators:** fallback rate rising · retry rate rising · time-to-first-token
creeping up. All three move before the error rate does.
