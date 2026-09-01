# URL Shortener — HLD (worked example, with reasoning)

Companion to [`solution.py`](solution.py) (the LLD). URL-shortener-specific answer; each decision shows the
**reasoning that earns it**. General machinery → **flow** `../HLD-revision.md` · **menu** `../HLD-method-bank.md` · **depth** `../HLD-reference.md`.

> LLD round = "design the classes". HLD round = "design the system at scale".
> **Golden rule: every box exists because a _number_ demanded it. Reason numbers → boxes.**

---

## 1. Scope

**Functional:** shorten · redirect · custom alias · expiry/TTL · disable · click analytics.
**Non-functional:** highly available · redirect p99 < ~100 ms · read-heavy · analytics eventually consistent.
**Out of scope:** accounts/auth · malware scanning · custom domains · billing.

**Why these NF requirements shape the design:**
- **Availability on redirect path** → a billboard link *must* resolve → duplicate every component, never let analytics block a redirect.
- **Read-heavy** → drives the two biggest picks: cache + read replicas (confirmed by numbers in §2).
- **Analytics eventually consistent** → *permission* to move analytics off the hot path (async) → protects redirect latency.

## 2. Capacity estimate

- Writes: 100M/mo ÷ 2.5M s ≈ **~40 writes/s**.
- Reads: 100:1 ratio → **~4,000 reads/s**.
- Storage: 6B links × ~500 B ≈ **~3 TB** (5 yr).
- Code space: base62⁷ ≈ **3.5 trillion**.

**Why each number matters:**
- 40 writes/s → tiny → **writes are never the bottleneck** → don't over-engineer the write path.
- 4,000 reads/s @ 100:1 → **read-dominated** → **cache + read replicas** (this ratio justifies half the design).
- 3 TB → shardable, not scary → single primary + replicas holds it → **shard later, not now**.
- 3.5T codes → 7 chars is plenty → kills the "won't you run out?" follow-up.

## 3. API

```
POST /shorten { long_url, custom_alias?, expiry? } -> { short_url }
GET  /{code}                                       -> 302 redirect
```

**Why:**
- Redirect is a bare `GET /{code}` → it's 99% of traffic → must be as cheap as possible.
- `custom_alias`/`expiry` optional → common path stays simple.
- 302 not 301 → §6.

## 4. Data model + DB choice

Row: `code (PK)` · `long_url` · `created_at` · `expires_at?` · `is_disabled`.

**Why this schema:** only access pattern is `code → row` (exact PK match), no joins/ranges → it's a **key-value map**.

**Why PostgreSQL first, not Cassandra:**
- < few-B rows, ~40 writes/s, needs **strongly-consistent create** (no two people claim one alias) → Postgres `UNIQUE(code)` gives it free + transactions + reporting.
- Cassandra wins only at *internet-scale writes* (AP tradeoff) → I have neither problem → it just buys ops complexity (repair, tombstones, tuning).
- **Senior line:** "start Postgres for low ops complexity; migrate read path to Cassandra/DynamoDB only when throughput/storage outgrows one primary."

**Why shard by `code` (hash):**
- Even distribution + every query is by `code`.
- Sharding by `created_at` → newest shard = hotspot. *(Depth → reference §3, §5.)*

## 5. Architecture — why each box exists

```
Client ─▶ DNS ─▶ LB ─▶ [ stateless App servers ] ─▶ Redis (cache-aside) ─▶ DB (primary + read replicas)
                              ├─▶ KGS (counter ranges)
                              └─▶ Kafka ─▶ analytics consumer (click counts)
                       (+ background job: purge expired links)
```

| Box | Why it exists (the number/requirement that forced it) |
|---|---|
| **LB + ≥2 app servers** | availability → no SPOF; stateless → autoscale on 4,000 reads/s |
| **Redis (cache-aside)** | 100:1 reads → most reads shouldn't touch DB; 80/20 viral → high hit-rate |
| **Read replicas** | 4,000 reads/s swamps one primary → writes→primary, reads→replicas |
| **KGS** | single global counter = bottleneck + SPOF → hand out ranges (§6) |
| **Kafka + consumer** | analytics must NOT block redirect → publish clicks async |

**Flows:**
- **Read:** `GET /abc` → Redis hit? serve → miss? replica → populate cache → **302**.
- **Write:** `POST /shorten` → get code → **conditional insert** (`save_if_absent`) → return.

## 6. The two decisions that win this problem

**(a) Code generation at scale** (the LLD `ShortCodeGenerator`, grown up):
- **Counter → base62:** works on 1 machine; a shared counter across N servers = **bottleneck** (coordinate every write) + **SPOF**.
- **Fix 1 — KGS ranges:** each server owns a block (1–1M) → coordinate once per *million* writes; replicate KGS so it's not a SPOF.
- **Fix 2 — random + conditional write:** 7 random chars, insert-if-absent, retry on rare clash → **zero coordination** → maps to `PutItem(attribute_not_exists)`.
- **Why not hash the URL:** (1) collisions; (2) long ugly codes; (3) no custom alias; (4) destination change → hash changes.
- **Why base62 not base64:** base64 has `+ / =` → URL-unsafe. base62 = `A–Z a–z 0–9`.

**(b) 301 vs 302 redirect:**
- **301 permanent:** browser caches → less load, **but no analytics** (repeat clicks never reach you).
- **302 found:** every click hits you → more traffic, **but full click tracking** + can change destination.
- **Decision:** analytics is a requirement → **302**.

## 7. Scale & failure (URL-shortener specifics)

- **Hot key** (viral link, 500M/day on one Redis node): CDN edge-cache · local LRU · Redis replicas · cache-warm.
- **Cache stampede** (viral key TTL expires → mass misses hit DB): single-flight / mutex · serve-stale-while-refresh.
- **Async analytics:** sync click-write would let a slow Kafka slow every redirect → publish async. (HLD form of the LLD `click_lock` note.)
- **Expiry:** `expires_at` + lazy `is_expired()` on read (no scan) + background purge.
- **Graceful degradation:** analytics/replica hiccup → redirects keep serving. **Never fail the core path for non-core work.**

---

## LLD ↔ HLD mapping (the payoff — connects both rounds)

| LLD (`solution.py`) | HLD (this doc) | Why they're the same idea |
|---|---|---|
| `ShortCodeGenerator` (Strategy) | KGS / generation approach | made swappable so it can change at scale |
| `Base62CodeGenerator` counter | distributed counter **ranges** (KGS) | same counter, distributed to kill the bottleneck |
| `RandomCodeGenerator` + `save_if_absent` | random + **conditional write** | identical atomic-claim; only backend changes |
| `URLRepository` interface | storage boundary; `InMemory` → `DynamoDBRepository` | the seam where in-memory becomes a real DB |
| `save_if_absent` (atomic claim) | **DB unique constraint** | one process → lock; across servers → DB enforces |
| `resolve` + `is_active`/`is_expired` | cache lookup + **lazy expiry** | same active/expired check, cache in front |
| `click_count` + "make it async" | **Kafka** analytics pipeline | the async note *was* the HLD decision, early |
| `click_lock` (in-process) | *gone* — DB/queue is the arbiter | in-process locks don't cross machines |

**The one line that wins both rounds:**
> "The `Repository` interface and `save_if_absent` were chosen so this exact code survives the jump
> from a dict to DynamoDB — the *service* never changes, only the *repository implementation* does."
