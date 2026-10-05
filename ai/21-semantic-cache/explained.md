# Semantic cache — explained

**Your credibility here:** you run a **persona-namespaced response/RAG cache with similarity
matching** on the voice/video persona product — and you namespaced it per persona *after*
hitting the leak, which is the honest version and the better story. Say that, then say what you
would add next: the token guard and the sampled correctness check below.

**Related:** topic 03 (tenant isolation), topic 02 (the RAG pipeline), topic 16 (the gateway
this sits in front of).

---

## 1. The numbers force the design

| Input | Value |
|---|---|
| LLM calls | 600k/day → **7 QPS average, 70 peak** |
| Service time | ~2s → Little's Law: **~140 concurrent in flight** |
| Cost | ~$0.004/call → **$2.4k/day, ~$72k/month** |
| Near-duplicate traffic | **~40%** — the ceiling on hit rate |
| Realised hit rate after namespacing | **~30%** (10% byte-identical, 20% semantic) |
| Cache hit latency | **~25ms**, against a 2s miss |
| Live entries | ~400k × (4 KB vector + 2 KB answer) ≈ **2.4 GB** |

Three conclusions. Say all three out loud.

**Largest single lever in the system.** 30% of $72k is **~$21.6k/month**, and each point of hit
rate is **$720/month**. Nothing else in the architecture moves that much money.

**A quota lever, not only a bill lever.** Little's Law again at 30%:
`70 × (0.7 × 2.0 + 0.3 × 0.025) ≈ 98` concurrent. You have removed 30% of the pressure on the
provider rate limit — the thing that actually breaks first in scenario 1.

**Not a distributed-systems problem.** 2.4 GB fits in RAM on one node; do not buy a managed
vector database for it. **A semantic cache is a correctness problem wearing a performance
problem's clothes.** And the probe is free: 12M embedding tokens/day ≈ **$0.24/day** against
$2,400/day of generation, roughly **1:10,000**. There is no hit rate low enough to make probing
uneconomic, so the only question is ever *when am I allowed to trust what comes back*.

---

## 2. The layers, each named by the failure it prevents

### L0 · Normalise, then try an exact hash
**Prevents:** paying 15ms of embedding latency to rediscover a byte-identical string.

Lowercase, collapse whitespace, strip trailing punctuation, then `sha256` the normalised text
plus the namespace. About **10% of real traffic is byte-identical** — retries, refreshes,
double-clicks, the same automated caller. Costs 1ms and no embedding call. Version the
normalisation rule and log it: changing it silently orphans or silently merges entries.

### L1 · Embed the query, ANN inside the namespace
**Prevents:** an exact cache missing every paraphrase — "what is the notice period" against
"how long is the resignation warning".

One embedding, one ANN search **inside this request's namespace only**. Same argument as
scenario 3: a vector search ranks over whatever is in the index, so isolation has to be
structural. Nothing outside the namespace was ever a candidate; there is no filter to forget.

### L2 · The similarity threshold — necessary, not sufficient
**Prevents:** answering a *different* question. Too loose is a **correctness bug, not a
performance regression** — and it is what this scenario is really testing.

Embeddings systematically **under-weight exactly the tokens that change the answer**:

| Cached | Probe | Cosine | Same answer? |
|---|---|---|---|
| "unused leave is carried forward" | "unused leave is **not** carried forward" | **0.97** | opposite |
| "notice period for band **3**" | "notice period for band **5**" | **0.96** | different |
| "expenses under £50" | "expenses under £500" | ~0.99 | different |

Negation, numerals, dates and identifiers are one token averaged into a sentence. **No
threshold separates those from a genuine paraphrase**, because the genuine paraphrase scores
*lower* (0.94) than the negation (0.97). Raising the threshold loses real hits before it stops
false ones.

### L3 · The discriminative-token guard
**Prevents:** the row above. This is the layer that makes a semantic cache safe to ship.

Extract from both probe and candidate: **numerals, negations, dates, currency amounts, quoted
or capitalised identifiers**. Require the sets to be **equal** before serving. A regex and a set
comparison — microseconds — on top of the vector score.

> Vector similarity for recall, lexical equality for precision. The embedding decides *which*
> entry; the guard decides *whether*.

`solution.py` measures this rather than asserting it: threshold-only serves 5 hits of which
**2 are wrong**; with the guard, 3 hits and none wrong. The broken cache reports the **better**
hit rate — 50% against 30%.

### L4 · The key is the isolation primitive
**Prevents:** cross-tenant leaks, intra-tenant ACL leaks, answers from the pre-re-index world.

```
namespace = (tenant, sha256(sorted(resolved_scope_set)), corpus_version,
             model_id, prompt_version, locale)
```

The scope dimension is the subtle one. On the HR platform authorisation is **Casbin**, so a
request already resolves to a permission set before retrieval runs — hash *that set*, not the
user id. Keying on user id is correct and useless: a namespace of one never hits. Keying on
tenant alone is fast and wrong: two colleagues with different folder access share an entry.

Every dimension partitions the cache and costs hit rate. Quote the price:

| Dimension | Prevents | Hit-rate cost |
|---|---|---|
| tenant | cross-tenant leak | small — tenants ask different things anyway |
| resolved scope set | intra-tenant ACL leak | moderate; one namespace per *distinct* scope, not per user |
| corpus version | serving the pre-re-index world | zero in steady state, **100% on the day of a bump** |
| model + prompt version | replaying an answer the current prompt would not produce | a full flush per prompt change |
| locale | answering in the wrong language | proportional to locale count |

### L5 · TTL, and invalidation by version bump
**Prevents:** serving the old policy after the policy changed.

**TTL bounds how wrong you can be** when nothing told you the world moved — 24h for stable
reference answers, minutes for anything derived from live data. **Version-in-key is the actual
invalidation:** the re-index finishes, `corpus_version` increments, every old entry is
unreachable in one atomic config change. Delete-by-query over 400k entries is slower, racy, and
*will* miss some; versioning is O(1) and total.

Negative caching belongs here, on a shorter clock: refusals and below-floor misses get **15
minutes, not 24 hours**. A refusal usually marks a gap someone is about to fill by uploading the
missing document, and a day-long "not in your corpus" turns a five-minute fix into a ticket.

### L6 · Admission policy — what you must never write
**Prevents:** replaying an answer that was not fit to serve once, let alone a thousand times.

Never cache: a stream the client disconnected from (you would store a truncated answer),
anything from the **degraded or fallback path**, anything below the confidence or relevance
floor, anything with a name, date or figure interpolated for this caller, and anything whose
generation had a side effect. Caching is a **policy on the write path**, not "put it in Redis".

On the ICH E3 report generator this is a hard line: **never cache generated prose that will be
cited in a regulatory document.** Cache the retrieval and the evidence set, regenerate the
narrative. The retrieval cache still removes most of the cost.

### L7 · Single-flight on the key
**Prevents:** 200 identical concurrent misses each calling the model.

On the dealership analytics platform everybody opens the dashboard at 09:00 and asks the same
question in the same second. On a cold key that is N model calls for one logical answer, landing
exactly when the cache is emptiest — the morning after a re-index. One in-flight promise per
key: the first caller does the work, the rest await it.

### L8 · Measurement — hit rate is not the metric
**Prevents:** optimising the number that goes *up* when you break the cache.

Sample **1% of served hits**, replay them through the real model in the background, score
agreement. Below **98%** the threshold is too loose or the guard too narrow. Report **hit rate ×
precision-on-hits**; hit rate alone rewards a broken cache, which is how a loose threshold
survives a quarter.

---

## 3. What breaks first, in order

1. **Correctness at the threshold.** Not capacity. First because it is *silent*: no error, no
   trace, no alert, and the dashboard number improves while it happens.
2. **Key completeness.** One dimension forgotten — persona, scope, corpus version — and you are
   leaking or serving the old world. Also silent, also looks like a win.
3. **Cold start after a version bump.** 100% miss at full rate; bump before peak and you meet
   the provider's rate limit instead of the cache.
4. **Stampede on a single hot key.** One popular question, N concurrent misses, N model calls.
5. **Miss-path latency.** ~20ms added to 70% of traffic. Nothing against a 2s chat budget; ~7%
   of a sub-second voice turn, where it is a genuine trade.
6. **Memory and eviction.** Last at 2.4 GB — and first the moment you cache retrieved context
   alongside answers.

---

## The follow-ups, answered

**1 · "0.97 cosine and one has 'not' in it."** It scores *higher* than a genuine paraphrase, so
the threshold cannot help. The guard compares negation sets, sees `{not}` against `{}`, forces a
miss. Answer with the mechanism, never with "I'd tune the threshold".

**2 · "Re-index at 03:00. What's in the cache at 03:01?"** Nothing reachable, by construction —
the version incremented, so old entries sit in a namespace nobody will key into again. Then the
honest follow-on: the cache is cold and 09:00 is coming, so pre-warm by replaying yesterday's
top ~5k queries through the new version *before* the flip.

**3 · "What threshold, and how did you get it?"** Not by intuition. Take ~300 query pairs from
real logs, label same-intent/different-intent, sweep the threshold, plot false-hit rate against
hit rate. Choose where false hits sit under budget, then ship **one notch tighter** — a
hand-labelled set undercounts the adversarial tail. 0.93 is an output of that exercise, not an
input to it.

**4 · "Same tenant, different folder access."** No. The key carries the hash of the resolved
permission set, so they are in different namespaces. Not a filter over one namespace — a filter
is one bug away from serving B an answer grounded in documents B cannot open, with no citation
B can check.

**5 · "Hit rate is 45% and rising."** Unknown until I see precision on hits. A *rising* hit rate
with no product change is an incident signal: someone loosened the threshold, changed
normalisation, or dropped a key dimension. Look at the distribution of served cosines — mass
drifting toward the threshold means false hits are already arriving.

**6 · "Empty cache at 09:00."** Single-flight collapses duplicate misses; the queue and the
per-provider token bucket shape the rest. Then fix the cause: pre-warm before the flip, never
bump a version in business hours. Cold start is the cache failure that presents as a provider
incident.

**7 · "Answer, or chunks?"** Both, at different tiers. The **retrieval cache** (query → chunk
ids) has the higher hit rate and a far smaller blast radius when slightly wrong, because the
generator still reads the chunks and can still refuse. The **answer cache** saves more and risks
more. Answer cache in front, retrieval cache behind it.

**8 · "Where does it sit?"** After authentication and scope resolution, before the gateway.
Never before auth — you would serve across tenants. Never after generation — nothing left to
save. First thing inside the trust boundary, last thing before you spend money.

**9 · "Streaming?"** Replay the stored string as chunks; a cached answer has no
time-to-first-token problem to protect. The real bug is on the **write** side: write only when
the stream *completes*. A client disconnecting at 60% must not leave a truncated answer that
every future caller is served instantly and confidently.

---

## One-line summary

> "Exact hash first, then embed and ANN inside a namespace built from tenant, resolved
> permission set and corpus version; serve only above a calibrated threshold **and** only when
> the numerals and negations match exactly; invalidate by bumping the version rather than
> deleting; and report hit rate multiplied by sampled precision on hits, because hit rate alone
> is the number that improves when the cache starts lying."

## The trap answer to avoid

"Embed the query, cosine similarity, threshold at 0.9, Redis." That design serves the band-5
answer to the band-3 question, and "leave is carried forward" to "leave is **not** carried
forward" — at 0.97 similarity, with a hit-rate graph going up and to the right, and no error
anywhere in the system. The second trap is the one from the source: **leaving the corpus version
out of the key**, so a re-index changes nothing and you serve the old world for ever.
