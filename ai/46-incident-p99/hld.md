# Tail latency, by design

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Observed | p99 3s → 25s, p50 flat | a subset, not capacity |
| 3 attempts × 8s + backoff | 25.0s | the arithmetic that matches |
| 30ms CPU at 96% loop utilisation | p99 +215%, p50 +33% | a queue, not added latency |
| Same at 99% utilisation | p99 5.34s | the cliff is not gradual |
| 2% of requests stalling | p95 still healthy | invisible below the 98th percentile |

## 2. The distinction that organises everything

**Capacity problems move p50.** Everything queues, the median rises, and more instances help.

**Subset problems move only the tail.** A specific provider, model, tenant, endpoint or code path
is affected, and scaling does nothing.

Establishing which of the two you have is the first thirty seconds of the incident, and it
determines whether the next hour is spent slicing or scaling.

## 3. Tail shape tells you the family

| Shape | Family | First check |
|---|---|---|
| Clustered at a round value | arithmetic | attempts × timeout + backoff |
| Smooth stretch | contention or size | pool exhaustion, prompt length, retrieval params |
| Bimodal | two populations | slice by provider, model, tenant, cache hit/miss |

Look at a histogram before a dashboard. The shape narrows the search more than any single metric.

## 4. Config is where it usually is

Timeouts, retry counts and backoff, connection-pool sizes, retrieval parameters
(`numCandidates`, `ef_search`, chunk count), feature flags, model selection. All of these change
tail latency and none of them appears in a code diff.

Two specifics worth internalising:

- **Removing a timeout lengthens the tail.** A timeout converts a hang into a bounded failure.
- **Retrieval parameters cost twice.** More chunks means slower search *and* a longer prompt,
  which means a longer time-to-first-token.

## 5. Async blocking is structurally different

Awaited I/O overlaps; CPU does not. A blocking call inside an async handler does not add its
duration to each request — it serialises the loop and creates a queue, so its cost scales with
concurrency rather than being constant.

Consequences: it does not reproduce at low load, it does not reproduce with a single request, and
it does not reproduce with perfectly regular arrivals. It needs bursty concurrent traffic to
exist, which production has and most test harnesses do not.

Instrument **event-loop lag** directly. It is the one metric that names this immediately.

## 6. The deploy gate

| Gate | Catches |
|---|---|
| p99, sliced by provider / model / endpoint | most tail regressions, and names the slice |
| Error taxonomy — timeouts separate from 5xx | a timeout spike, which "errors" hides |
| Canary with tail guardrails | before everyone gets it |
| Load test with bursty arrivals, tail reported | async blocking and queueing |

An aggregate p99 hides a regression confined to one slice, and "error rate" hides the difference
between two incidents that need opposite responses.

## 7. Observability

p99 and p99.9 per provider, per model, per endpoint, per tenant — sliced, always. Event-loop lag.
Connection-pool wait time and saturation. Retry count and timeout count as separate series.
Time-to-first-token separately from total latency, since prompt length hits the former hardest.
And a **latency histogram**, not just percentiles, because the shape of the tail is what tells
you which family of cause you are in.
