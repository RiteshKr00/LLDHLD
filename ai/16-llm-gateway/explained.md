# Building an LLM gateway — explained

**Your version of this:** Gemini through a **LiteLLM proxy** on the dealership platform, and
**pluggable OpenAI-compatible backends** (vLLM + remote embeddings) in CSR-Exp. You've used
one and built the swappable-backend half — say both.

---

## What a gateway is actually for

Not "abstraction". It exists to stop **N call sites** each solving the same seven problems
badly:

| Without a gateway | The gateway owns it once |
|---|---|
| every call site imports a provider SDK | one internal request shape |
| keys scattered through config | central secrets, per-tenant keys |
| each site invents its own retry | one policy, backoff **+ jitter** |
| rate limits discovered as 429s | a shared token bucket, shaping traffic *before* the provider rejects it |
| cost unattributable | usage captured on every call |
| a provider swap is an N-file migration | a routing change |
| no fallback | one ordered chain |

**The test of whether you need one:** how many files change when you add a provider? If it's
more than one, build the gateway.

---

## The latency constraint shapes everything

In the sync path the gateway must add **under ~20ms**. That single number rules out:

- an extra network hop to a separate service (use a library or a sidecar, not a remote call)
- anything that buffers the response
- a database read per request (rate state must be in Redis, policy in memory)

---

## Streaming is the hard part

The naive gateway buffers the whole response so it can count tokens and log. **That destroys
time-to-first-token**, which is the only latency users perceive.

The correct shape: **pass chunks through as they arrive, accumulate usage as a side effect,
and write the ledger entry when the stream closes.**

```
provider chunk -> yield to caller immediately
               -> tally tokens into a local counter
stream ends    -> emit one usage record (async write, off the critical path)
```

Getting this wrong is the single most common gateway bug, and it's invisible in testing
because a non-streaming test never exercises it.

---

## Rate limiting: the state must be shared

Ten gateway instances each holding their own token bucket admit **10× the intended rate**, so
you hit the provider's 429s anyway and wonder why the limiter "doesn't work".

Rate state lives in **Redis**, keyed per provider **and** per tenant. Two buckets, both
checked: the provider bucket protects the quota, the tenant bucket protects other tenants.

---

## Retries: one place only

**Gateway** handles transport errors — 429, 5xx, timeout — with backoff and **jitter**.
**Workers** handle business-level "the whole task failed, re-run it later".

**Never both.** Three client retries × three gateway retries = **nine provider calls for one
logical request**, which is a self-inflicted DDoS on a service that is already struggling.

---

## The provider adapter boundary

Each adapter translates three things: **auth**, **the request/response shape**, and **the
error taxonomy**. That last one is the one people forget — every provider signals
rate-limiting differently, and the router can't make decisions on a string it doesn't
recognise. Normalise to `RateLimited / Unavailable / Timeout / BadRequest` at the adapter.

---

## The follow-ups, answered

**"The gateway is now a SPOF."**
Concede it, then mitigate: it's **stateless**, so run N of them behind a load balancer; rate
state is external; and it should be a **library or sidecar** rather than a remote service, so
there's no extra hop to fail. A gateway that adds a network hop *and* a failure domain is a
bad trade.

**"How do you add a provider?"**
Write an adapter, add a registry row. No call site changes — that's the entire point, and it's
the answer to "why not just use the SDK".

**"How do you test it?"**
Fake providers at the adapter interface that can be told to return 429, 5xx, timeout, or
malformed JSON. Then fallback, breaker and retry logic are unit-testable with **no network**.

---

## One-line summary

> "One internal call shape, per-provider adapters that normalise auth and the error taxonomy,
> shared rate state in Redis, retries in exactly one place, and usage tallied *during* the
> stream rather than by buffering it."

## The trap answer to avoid

Buffering the response to count tokens. You were hired to protect latency and you just spent
all of it — and no non-streaming test will catch it.
