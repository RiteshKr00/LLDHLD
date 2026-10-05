# The semantic cache at scale

## 1. Numbers first

600k LLM calls/day ≈ **7 QPS average, 70 peak**, ~2s service time. Little's Law gives **~140
concurrent in flight** uncached. At a 30% hit rate served in ~25ms:
`70 × (0.7 × 2.0 + 0.3 × 0.025) ≈ 98`.

| | Without | With, at 30% |
|---|---|---|
| Concurrent in flight at peak | 140 | **~98** |
| Spend | $2.4k/day, ~$72k/month | **~$50.4k/month** |
| p50 on the cached slice | ~2s | **~25ms** |

**What that forces:** the cache is a **quota** lever as much as a cost lever — it removes 30% of
the pressure on the provider rate limit, which is what breaks first. And the working set is
small: ~400k live entries × (4 KB vector + 2 KB answer) ≈ **2.4 GB**, in RAM on one node. This
is **not a distributed-systems problem**; every remaining hard question is a correctness one.
The probe is free — 12M embedding tokens/day ≈ **$0.24/day** against $2,400/day of generation,
about 1:10,000. No hit rate is low enough to make probing uneconomic.

## 2. Topology — where it sits

```
request ─► authn ─► resolve permission set (FAILS CLOSED)
                          │
             key = (tenant, sha256(scope set), corpus_v, model, prompt_v, locale)
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
      L0 exact hash (1ms)     L1 embed + ANN in-namespace (~20ms)
              │                       │
              │             threshold 0.93 ─► token guard
              └───────────┬───────────┘
                          │ miss
                    single-flight per key
                          │
                 retrieve ─► generate (~2s) ─► admission policy ─► write
                          │
                    corpus re-index event ─► corpus_v + 1
```

Before the gateway, after auth. Never in front of auth — the resolved scope is an *input* to the
key, so a cache upstream of authentication is a cross-tenant serve by construction.

## 3. The two tiers, and why both

| Tier | Cost | Catches | Failure it prevents |
|---|---|---|---|
| **L0** exact hash of normalised text | ~1ms, $0 | ~10% — retries, refreshes, bots | paying 15ms of embedding to rediscover an identical string |
| **L1** embed + ANN + threshold + guard | ~20ms, ~$4e-7 | ~20% — genuine paraphrases | an exact cache missing every rephrasing |

~30% total against a ~40% near-duplicate ceiling. The missing 10 points are the price of
namespacing, and that is the correct trade.

## 4. Calibrating the threshold — a labelled-data exercise, not a guess

~300 query pairs from real logs, labelled same-intent / different-intent; sweep the threshold;
plot false-hit rate against hit rate; take the point where false hits sit under budget, then
ship **one notch tighter** because a hand-labelled set undercounts the adversarial tail. Re-run
it whenever the embedding model, the normalisation rule or the traffic mix changes — all three
move the curve and none of them raise an error when they do.

## 5. Scaling levers, in order of payoff

1. **Widen the near-duplicate window** — better normalisation (synonyms, entity
   canonicalisation) raises the ceiling before anything else does.
2. **Two tiers** — answer cache in front, retrieval cache behind, so an answer miss still skips
   the search over the full corpus.
3. **Pre-warm on version bumps** — replay the previous day's top ~5k queries offline before the
   flip. Turns a 100%-miss morning into a normal one.
4. **Shard by namespace** only once the working set outgrows a node — namespaces already
   partition cleanly, so it is a routing map, not a rebalance.

**Fairness at 500 tenants:** per-tenant entry quotas (one tenant's automated caller must not
evict the long tail), per-tenant eviction accounting, and per-tenant hit-rate reporting — an
aggregate 30% hides a whale at 60% and forty tenants at 2%.

## What breaks, in order

1. **Correctness at the threshold** — first because it is silent, and because the symptom is a
   *rising* hit rate. Nothing errors, nothing traces, the dashboard improves.
2. **Key completeness** — a missing dimension is a leak or a stale serve. Also silent.
3. **Cold start after a version bump** — 100% miss at full rate. At peak you meet the provider's
   rate limit, and it gets triaged as a provider incident.
4. **Stampede on one hot key** — N concurrent misses, N model calls, worst on the coldest day.
5. **Miss-path latency** — ~20ms on 70% of traffic. Nothing at a 2s chat budget; ~7% of a
   sub-second voice turn.
6. **Memory and eviction** — last at 2.4 GB, first the moment you cache retrieved context too.

## Degradation — and it differs per feature

**Cache unavailable → fail open.** Serve from the model, log loudly. A missed hit costs money;
refusing traffic costs the product. Same asymmetry as the gateway's rate limiter, and the
opposite of the tenant-scope resolver, which fails closed.

**Cache suspect → fail closed.** If shadow-sample agreement drops below 98%, stop serving hits
behind a flag. Fast wrong answers are worse than none.

| Feature | Under cache pressure |
|---|---|
| RAG chat | fine — slower and pricier; nobody notices but finance |
| Voice turn | load-bearing at a sub-second budget; on failure degrade to text rather than blow the turn |
| Extraction | never serve a cached extraction across a corpus version; miss to the model |
| Clinical report | never cache the narrative at all — cache the retrieval and evidence set, regenerate the prose |

## Observability

Per tenant and per namespace, never aggregate: hit rate split **L0 / L1**, **precision on hits**
from the 1% shadow sample, the distribution of served cosines, guard rejection rate, entry age
at serve time, eviction rate, and a **stale-serve counter** — hits against a corpus version
older than current, which should be structurally zero and proves the key is wrong if it is not.

**Leading indicators — they move before anything errors:** the cosine distribution of served
hits **drifting down toward the threshold** · **guard rejection rate rising** (normalisation or
traffic mix changed) · **hit rate jumping** with no product change, which is an incident rather
than a win · **L0 share falling**, meaning someone altered the normalisation rule and silently
orphaned entries.
