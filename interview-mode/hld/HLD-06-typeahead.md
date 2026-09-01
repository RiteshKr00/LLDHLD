# HLD-06 — Typeahead / Autocomplete

## META
- difficulty: medium
- time: 45 min
- tags: trie, prefix-search, top-k, aggressive-caching, precompute
- why-it-matters: the tightest latency budget you'll ever design for (**<100 ms, on every keystroke**),
  and the clearest example of "precompute everything, compute nothing at read time".

## PROMPT
> "Design search autocomplete — as the user types, show the top 10 suggestions."

## CLARIFY
- **How fast?**
  → **Under 100 ms**, ideally under 50. Slower than the user's typing = useless. This is the constraint.
- **Where do suggestions come from?**
  → **Past search queries**, ranked by popularity. Not a dictionary.
- **How fresh?**
  → **Hours is fine.** A new trending term appearing 30 minutes late is acceptable — except during
  breaking news, worth mentioning.
- **Personalised?**
  → Global first. Personalisation as an extension.
- **Typo tolerance?**
  → Out of scope (fuzzy matching is a different, much harder problem — say so).
- **How many suggestions?**
  → Top 10.

## STEP 1 — Requirements
**Functional:** given a prefix, return the **top 10 most popular** completions · update popularity as
people search · handle new/trending queries eventually.
**Non-functional:** **p99 < 100 ms** · enormous read volume · **eventual freshness is fine (hours)** ·
availability > perfect ranking (a slightly stale suggestion beats a spinner).
**Out of scope:** typo/fuzzy matching · personalisation · multi-language · spell correction.

### CHECKPOINTS
- States the **latency budget as a number** and treats it as *the* constraint
- Explicitly accepts **stale-by-hours** — that permission is what allows precomputation
- Notes the read:write asymmetry (every keystroke is a read)

### TRAPS
- Designing for real-time freshness — it destroys every precompute option for no user benefit
- Forgetting that **one search = ~20 requests** (one per character typed)

## STEP 2 — Capacity
```
searches      5B/day  ÷ 86,400 ≈ 60,000 searches/sec
BUT typeahead fires PER KEYSTROKE:
              avg query ~20 chars -> 20 requests per search
              -> 60,000 × 20 = 1,200,000 requests/sec   😱
              (mitigated by client-side debounce ~50-100 ms -> realistically ~300K/sec)
unique queries ~500M distinct, but the top few million cover almost all traffic
trie size      500M queries × 30 B ≈ 15 GB  -> FITS IN MEMORY (this is the key fact)
writes         updating popularity: batched hourly, not per search
```

### CHECKPOINTS
- **Multiplies searches by characters-per-query** — this is the number that surprises people
- Mentions **client-side debouncing** as the first line of defence
- Computes trie size and concludes **it fits in RAM** — which is what makes <100 ms possible

### TRAPS
- Computing 60K searches/sec and stopping. The system serves ~20× that.
- Assuming you must hit a database. At 300K QPS with a 100 ms budget, **you cannot touch disk.**

### FOLLOWUPS
- *"1.2M requests/sec. What's the first thing you do about that?"* (debounce on the client — it's free)

## STEP 3 — API
```
GET /api/v1/suggest?q=har&limit=10     -> 200 {suggestions: ["harry potter", "hardware", ...]}
      Cache-Control: public, max-age=3600     <- CDN/browser can cache this!
POST (internal) search-logged event    -> stream, for popularity updates
```

### CHECKPOINTS
- A single, tiny, **cacheable GET** — no auth, no personalisation, no cookies in v1
- Response is small (10 short strings) so it fits in one packet

### TRAPS
- Making it a POST or personalising it in v1 — both destroy cacheability, which is your cheapest win

## STEP 4 — Data structure — the trie
```
                (root)
                 / | \
                h  c  s
               /
              a
             /
            r
           / \
          r   d
         /     \
     "harry     "hardware"
      potter"

Each NODE stores its OWN top-10 list, precomputed:
   node("har") -> ["harry potter" (9M), "hardware" (4M), "harvard" (3M), ...]
```

**The trick: don't search at read time — precompute the answer at every node.**
```
naive:  walk to the "har" node, then traverse the WHOLE subtree, collect all
        completions, sort by popularity, take 10        -> O(subtree), way too slow

actual: walk to the "har" node (3 steps), READ its stored top-10 list  -> O(len(prefix))
```
Lookup becomes proportional to the *prefix length* (~3–20 steps), **not** to how many queries start
with that prefix. That's the whole design.

### CHECKPOINTS
- Chooses a **trie** and explains why (prefix is the access pattern)
- **Stores top-k at each node** — precomputed, not computed on traversal
- States the resulting complexity: **O(prefix length)**, independent of dataset size

### TRAPS
- `SELECT * FROM queries WHERE q LIKE 'har%' ORDER BY count DESC LIMIT 10` — a prefix scan on 500M rows,
  per keystroke, at 300K/sec. This is the naive answer and it's hopeless.
- A trie without stored top-k — you've kept the walk but reintroduced the subtree traversal

## STEP 5 — Architecture
```
READ PATH (hot, 300K/sec)
  Client ──debounce──▶ CDN/edge cache ──(miss)──▶ Suggest Service
                                                     └─ trie held IN MEMORY, read-only
                                                        (replicated across many boxes)

WRITE PATH (cold, batched — completely separate)
  search events ──▶ Kafka ──▶ aggregate counts (hourly) ──▶ REBUILD trie
                                                        ──▶ publish new trie version
                                                        ──▶ servers hot-swap it
```

**The two paths never touch.** Reads hit an immutable in-memory structure; writes build a *new* one
offline and swap it in. No locks, no contention, no read/write conflict — because the read structure
is **never mutated**.

### CHECKPOINTS
- Trie lives **in memory**, replicated — never queried from disk
- **Read path and write path are fully separated**; the serving trie is **immutable**
- Updates are a **periodic rebuild + atomic swap**, not incremental in-place edits
- Responses cached at the **CDN/edge** (the prefix "har" is asked for by millions of people)

### FOLLOWUPS
- *"How do you update the trie without taking a lock on every read?"* ← immutability is the answer
- *"A term suddenly trends. How long until it appears?"*

## DEEP DIVE — sharding, top-k maintenance, and the freshness tradeoff

### Sharding by prefix
15 GB fits on one box, but you need many replicas for 300K QPS, and eventually the dataset grows:
```
shard by FIRST 1-2 CHARACTERS:
   shard A: prefixes starting a–d
   shard B: prefixes e–h
   ...
routing is trivial: look at the first character of the query
```
This works because **a prefix query never spans shards** — everything starting with "har" is in the
"h" shard by definition. *(Compare a full-text search index, where a query genuinely spans shards.)*

**Skew is real:** "a" and "s" have far more entries than "z". Balance by splitting hot prefixes to
deeper levels (`sa`, `se`, `sh`…) rather than assuming uniform distribution.

### Keeping top-k correct
Each node's top-10 depends on its whole subtree. Rebuilding:
```
1. aggregate query counts from the last window (Kafka -> batch job)
2. build the trie bottom-up: a node's top-10 = merge of its children's top-10 lists + itself
   ^ merging pre-sorted top-10 lists is cheap; you never sort the whole subtree
3. ship the new trie to the read replicas; they swap atomically
```
Bottom-up merging is what makes a full rebuild affordable.

### The freshness tradeoff — say this out loud
```
rebuild hourly:  cheap, simple, immutable reads     BUT a trending term is up to 1 h late
rebuild live:    fresh                              BUT mutable shared structure = locks on the
                                                        hottest read path in the system
```
**Hybrid (the real answer):** the big trie rebuilds hourly, **plus** a small, separate "trending"
overlay updated every few minutes and merged into results at read time. You get freshness for the
handful of terms that need it without making the main structure mutable.

### CHECKPOINTS
- Shards by **leading characters**, and explains why a prefix query stays within one shard
- Acknowledges **skew** across letters and how to handle it
- Rebuilds top-k **bottom-up by merging children's lists**
- States the **freshness vs immutability tradeoff** and proposes the small trending overlay
- Never mutates the serving structure — swap, don't edit

### TRAPS
- Sharding by hash of the full query — now `har*` is scattered across every shard and you must
  fan out to all of them. **Hash-sharding destroys prefix locality.**
- Updating counts in place on the live trie → locks on a 300K QPS read path

### FOLLOWUPS
- *"Why not shard by hash for even distribution?"*
- *"Breaking news happens. Your rebuild is 50 minutes away. What do you do?"*

## STEP 7 — Scale
- **Replicas**: the trie is read-only, so scaling reads = adding identical copies. Perfectly horizontal.
- **CDN**: short prefixes ("a", "ha") are requested by millions → cache at the edge with a short TTL.
  A huge fraction of traffic never reaches you.
- **Client-side**: debounce (~100 ms) **and** cache locally — as the user types "har" → "harr", the
  browser often already has what it needs.
- **Truncate the tail**: queries searched fewer than N times are dropped entirely. The long tail is
  most of the storage and none of the traffic.

## STEP 8 — Failure
- **A shard dies** → prefixes in its range fail. Degrade to **returning nothing** rather than an
  error — a missing dropdown is invisible; a spinner or error is not. *(Best fail-soft in the track.)*
- **Rebuild job fails** → the old trie keeps serving. **Stale beats down**, and immutability is what
  makes that safe.
- **Corrupt trie published** → version the artifact and roll back to the previous one.
- **Traffic spike** → CDN absorbs most of it; add replicas.

## STEP 9 — Wrap
- **Bottleneck:** request volume (mitigated by debounce + CDN) and memory per replica.
- **Tradeoffs:** precomputed top-k (fast reads, slow updates) vs live computation (fresh, far too slow) ·
  hourly rebuild (simple, immutable) vs streaming updates (fresh, mutable and lock-prone) ·
  dropping the long tail (saves memory, loses rare queries).
- **Monitoring:** p99 latency (the headline), CDN hit rate, rebuild duration and lag, empty-result rate,
  memory per replica.
- **Next:** personalisation (a small per-user overlay merged at read time), typo tolerance, multi-language.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | `LIKE 'prefix%'` on a table plus a cache |
| **Senior** | in-memory trie, top-k precomputed per node, prefix sharding, CDN + debounce |
| **Staff** | all that **+ the ×20 keystroke multiplication**, immutable-trie-with-atomic-swap so reads never lock, bottom-up top-k merge, and the **trending overlay** to resolve the freshness tradeoff |

## REFERENCE
**User types "har":**
1. Client debounces ~100 ms (so "h", "ha" may never leave the device)
2. `GET /suggest?q=har` → often served by the **CDN**
3. On a miss: routed to the shard owning "h"
4. Server walks 3 nodes in an **in-memory** trie: root → h → a → r
5. Reads that node's **precomputed top-10 list** — no traversal, no sort
6. Returns; the edge caches it for the next million people typing "har"

**Total server work: three pointer hops and a list read.** That is why it fits in 100 ms.

**Someone searches something new:**
1. The search event goes to Kafka
2. The hourly job aggregates counts and **rebuilds the trie bottom-up**
3. A new version is published; replicas **atomically swap** — no lock ever taken on a read path
4. If it's genuinely trending, the minutes-level overlay surfaces it before the next full rebuild

## ONE-LINER
> *"The hidden number is that typeahead fires **per keystroke**, so 60K searches/sec is really over a
> million requests/sec — I debounce on the client and cache at the edge before anything reaches me.
> Then the design is 'compute nothing at read time': an **in-memory trie with the top-10 precomputed
> at every node**, so a lookup is O(prefix length), not O(matching queries). The serving trie is
> **immutable** — updates rebuild it offline and swap atomically — which means the hottest read path
> in the system never takes a lock."*
