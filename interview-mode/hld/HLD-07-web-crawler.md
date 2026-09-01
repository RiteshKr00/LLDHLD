# HLD-07 — Web Crawler

## META
- difficulty: medium-hard
- time: 45 min
- tags: frontier-queue, politeness, bloom-filter, distributed-workers, traps
- why-it-matters: the clearest "distributed worker pool over an unbounded work list" problem, and the
  only one where **being polite to strangers' servers is a hard requirement**.

## PROMPT
> "Design a web crawler that downloads the web for a search engine."

## CLARIFY
- **Scale and time budget?**
  → **1 billion pages a month.** That number decides everything.
- **How fresh?**
  → Re-crawl important pages daily, the long tail monthly. **Not everything is equal.**
- **Do we parse/index content?**
  → No — out of scope. We fetch and store; indexing is a separate system.
- **Do we respect `robots.txt`?**
  → **Yes, mandatory.** And rate-limit per domain — hammering someone's site is an outage you caused.
- **JavaScript-rendered pages?**
  → Out of scope in v1 (headless rendering is 10× the cost — worth mentioning).
- **Duplicate content?**
  → Yes, must detect it. The same article appears on hundreds of mirrors.

## STEP 1 — Requirements
**Functional:** start from seed URLs · fetch pages · extract links · add new URLs to the queue ·
store raw pages · re-crawl on a schedule.
**Non-functional:** **politeness** (obey `robots.txt`, rate-limit per domain) · **never crawl the same
URL twice** · scale horizontally · survive worker death without losing work · avoid traps.
**Out of scope:** parsing/indexing · JS rendering · ranking · images/video.

### CHECKPOINTS
- **Politeness named as a hard requirement**, not a nicety
- Dedup ("never crawl the same URL twice") stated up front
- Re-crawl treated as a first-class feature — crawling is never "done"
- Mentions **traps** (infinite URL spaces) — this is the thing that kills naive crawlers

### TRAPS
- Treating it as one-shot ("crawl the web") — it's a continuous, never-ending loop
- Forgetting politeness → you DDoS small sites and get your IP range banned

## STEP 2 — Capacity
```
target        1B pages / month  ÷ 30 ÷ 86,400 ≈ 400 pages/sec   (sustained)
page size     ~500 KB raw HTML
bandwidth     400 × 500 KB ≈ 200 MB/s  ≈ 1.6 Gbps
storage       1B × 500 KB ≈ 500 TB/month raw
              (compressed ~5:1 -> ~100 TB/month)
URLs seen     ~10B unique URLs to remember
              10B × 100 B = 1 TB just for the "have I seen this?" set   😱
              -> a plain hash set does NOT fit in memory -> Bloom filter
workers       each fetch takes ~1 s (network-bound, not CPU)
              400/sec ÷ (1 per sec per thread) -> ~400 concurrent fetches minimum,
              in practice thousands of threads across many machines
```

### CHECKPOINTS
- Computes **pages/sec** from the monthly target
- Computes the **seen-URL set size** and notices it **doesn't fit in memory** ← this is what forces the Bloom filter
- Notes fetching is **I/O-bound**, so concurrency ≫ core count

### TRAPS
- Forgetting the dedup set entirely — it's the biggest memory item in the whole system
- Sizing workers by CPU. Each worker spends its life waiting on the network.

### FOLLOWUPS
- *"You need to remember 10 billion URLs. Where do you put them?"*

## STEP 3 — Components / API (mostly internal)
```
Frontier.add(url, priority)          -> queue a URL to crawl
Frontier.next(worker_id)             -> hand out a URL, respecting politeness
SeenSet.check_and_add(url) -> bool   -> "is this new?" (atomic)
Store.put(url, html, fetched_at)
RobotsCache.allowed(domain, path) -> bool
```

### CHECKPOINTS
- `check_and_add` is **one atomic operation**, not check-then-add
- The frontier is the thing that enforces politeness — workers don't decide for themselves

### TRAPS
- `if not seen(url): mark_seen(url)` as two steps — two workers both find the same link and both
  crawl it. **The 8th appearance of check-then-act.**

## STEP 4 — Data structures
```
frontier         per-DOMAIN queues + a scheduler   (NOT one global FIFO — see deep dive)
seen_urls        Bloom filter (in memory) + exact store (disk/Redis) for confirmation
robots_cache     domain -> parsed rules, TTL 24 h
crawl_metadata   url -> last_crawled, etag, change_frequency, priority
raw_pages        object storage (S3), keyed by url_hash
content_hashes   simhash/checksum -> detect duplicate CONTENT across different URLs
```

### CHECKPOINTS
- Frontier is **per-domain**, not a single global queue
- Uses a **Bloom filter** for the seen-set and knows its property (false positives yes, false negatives never)
- Caches `robots.txt` per domain rather than refetching it constantly
- Separates **URL dedup** from **content dedup** — they're different problems

### TRAPS
- One global FIFO — see the deep dive; it makes politeness impossible
- Storing 10B URLs in a database and querying per link — that's a lookup per extracted link, ~50 per page

## STEP 5 — Architecture
```
                 ┌──────────────── FRONTIER ────────────────┐
   seeds ──▶     │  per-domain queues + politeness scheduler │ ◀── new URLs
                 └────────────────┬─────────────────────────┘
                                  │ next(url)   (only when that domain is "due")
                                  ▼
                          Fetcher workers  (thousands, I/O-bound)
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              robots check   store raw HTML   extract links
                             (S3)                  │
                                                   ▼
                                        SeenSet.check_and_add(url)
                                             new? ──▶ back to Frontier
```

### CHECKPOINTS
- It's a **loop**: fetch → extract → dedup → enqueue → fetch
- The **frontier decides when a URL may be fetched** (politeness lives there, centrally)
- `robots.txt` checked before fetching, from cache
- Extracted links go through **dedup before** re-entering the frontier

### FOLLOWUPS
- *"Two workers extract the same link at the same moment. What stops both from crawling it?"*
- *"One site has 10 million pages. What happens to everyone else?"*

## DEEP DIVE — politeness, dedup at scale, and traps

### 1. Why a single global queue fails
```
global FIFO: [wikipedia.org/a, wikipedia.org/b, wikipedia.org/c, ... ×10,000]
1,000 workers pull from it -> 1,000 simultaneous requests to Wikipedia
-> you have DDoSed them, and your IPs get banned
```
**Fix: one queue per domain, plus a scheduler that only hands out a URL when that domain is *due*.**
```
domain_queues:  wikipedia.org -> [url, url, url…]   next_allowed_at = 12:00:03
                smallblog.com -> [url]              next_allowed_at = 12:00:01
scheduler: pop from any domain whose next_allowed_at <= now
           after handing one out, set next_allowed_at = now + delay(domain)
```
The delay is **per-domain and adaptive**: `robots.txt` `Crawl-delay` if present, otherwise something
polite (e.g. 1 req/sec), and back off if the server is slow or returns 429/503.

**Consequence:** a worker is never blocked — if Wikipedia isn't due, it takes a URL from another
domain. Politeness costs you nothing in throughput as long as you're crawling many domains.

### 2. Dedup — why a Bloom filter
```
10B URLs × 100 B = 1 TB   -> a hash set doesn't fit in RAM
Bloom filter for 10B items at 1% FP ≈ 12 GB  -> fits comfortably
```
A **Bloom filter** answers "have I seen this?" with:
- **"definitely not"** → guaranteed correct → crawl it
- **"probably yes"** → might be a false positive → you skip a page you've never crawled

**False positives are acceptable here** — you miss ~1% of pages out of billions. **False negatives
would be fatal** (infinite re-crawling), and a Bloom filter never produces them. That asymmetry is
exactly why it fits this problem.

If you can't tolerate even that: Bloom filter as a **fast negative check**, and only on "probably yes"
do the exact lookup in the on-disk set. Most calls never touch disk.

**Normalise before hashing**, or dedup silently fails:
```
http://Example.com/A?b=1&a=2#frag   and   https://example.com/a?a=2&b=1
are the SAME page. Lowercase host, drop fragment, sort query params, strip tracking params.
```

### 3. Content dedup (different problem, same page)
The same article lives on hundreds of mirrors with different URLs. URL dedup won't catch it.
→ hash the **content** (simhash / minhash so near-duplicates also match) and skip storing repeats.

### 4. Crawler traps — the thing that actually kills crawlers
```
infinite calendar:   /events?date=2027-01-01 -> links to 2027-01-02 -> forever
session ids:         /page?sid=abc123 -> every visit is a "new" URL
deep nesting:        /a/b/a/b/a/b/...
spider traps:        pages that generate infinite links on purpose
```
Defences (say several — this is where experience shows):
- **Max depth** per domain
- **Max pages per domain** (a budget, so one site can't consume the crawl)
- **URL length and parameter-count limits**
- **Strip session/tracking parameters** during normalisation
- **Detect repeating path segments** (`/a/b/a/b/`)
- Notice **near-identical content** at many URLs → deprioritise that whole subtree

### CHECKPOINTS
- **Per-domain queues + a due-time scheduler**, with the DDoS reasoning
- Adaptive per-domain delay, from `robots.txt` where available, with back-off on 429/503
- **Bloom filter**, sized, with the **false-positive-OK / false-negative-fatal** asymmetry stated
- **URL normalisation** before hashing
- **Content-level dedup** as a separate mechanism from URL dedup
- Names **at least two concrete traps** and their defences

### TRAPS
- Politeness as "add a sleep" — that blocks the worker instead of scheduling the domain
- Bloom filter without mentioning false positives, or claiming it can have false negatives
- No trap defences at all → the crawler spends eternity on one calendar

### FOLLOWUPS
- *"Your Bloom filter says 'seen' for a page you've never fetched. Is that a bug?"*
- *"How do you stop one enormous site from eating your entire monthly budget?"*

## STEP 7 — Scale
- **Shard the frontier by domain hash** — all of one domain's URLs live on one frontier shard, which
  is what makes per-domain politeness enforceable locally, with no coordination.
- **Workers are stateless** → add machines freely. Distribute across **regions/IPs** so you're not
  hitting every site from one address block.
- **Priority**: re-crawl news hourly, static pages monthly. The frontier is a **priority** queue, not FIFO.
- **Bloom filter** sharded by URL hash, mirroring the frontier shards.

## STEP 8 — Failure
- **Worker dies mid-fetch** → the URL was leased, not deleted. The lease expires and it's re-handed out.
  *(Same shape as the seat hold in movie booking: lease + TTL, self-healing.)*
- **A site is down / 503** → exponential back-off for that domain, don't retry forever, requeue for later.
- **Frontier shard dies** → its domains stall until it recovers; other domains are unaffected (bulkhead by sharding).
- **Bloom filter lost** → rebuild from the exact store; meanwhile you re-crawl some pages. Wasteful, not incorrect.
- **Poison URL** (crashes the parser) → after N failures, blacklist it and move on.

## STEP 9 — Wrap
- **Bottleneck:** politeness itself — you are deliberately slower than you *could* be. Also bandwidth
  and the memory for the seen-set.
- **Tradeoffs:** Bloom filter (tiny memory, ~1% missed pages) vs exact set (perfect, 1 TB) ·
  aggressive crawling (fresher, gets you banned) vs polite (slower, sustainable) · depth limits
  (avoids traps, may miss legitimately deep content).
- **Monitoring:** pages/sec, per-domain request rate (proof you're behaving), frontier depth, Bloom
  false-positive rate, 4xx/5xx rate per domain, trap detections, re-crawl staleness.
- **Next:** JS rendering, focused/topical crawling, sitemap ingestion, change-rate prediction.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | a queue, workers, a `seen` set, "check robots.txt" |
| **Senior** | per-domain queues with politeness scheduling, Bloom filter for dedup, URL normalisation, priority re-crawl |
| **Staff** | all that **+ the false-positive/false-negative asymmetry argument for Bloom**, lease-based work handout for crash recovery, **named crawler traps with defences**, and per-domain budgets so one site can't eat the crawl |

## REFERENCE
**One page, end to end:**
1. Scheduler finds a domain whose `next_allowed_at <= now`, pops a URL, **leases** it to a worker
2. Worker checks the cached `robots.txt` → allowed
3. Fetches (~1 s, network-bound), stores raw HTML in S3
4. Sets that domain's `next_allowed_at = now + crawl_delay`
5. Extracts ~50 links → **normalises** each (lowercase host, drop fragment, sort params, strip session ids)
6. For each: `SeenSet.check_and_add(url)` — one atomic call
   - "definitely new" → push to the frontier shard for that domain
   - "probably seen" → drop (accepting ~1% loss)
7. Content hash compared → if it duplicates a known page, don't store a second copy
8. Lease released. If the worker had died, the lease would have expired and the URL been re-issued.

**Why the domain never gets hammered:** every URL for that domain sits in **one queue** on **one
frontier shard**, and that shard hands out at most one URL per `crawl_delay`. No coordination between
workers is needed at all.

## ONE-LINER
> *"Two numbers shape this: 400 pages/sec, and **10 billion URLs to remember** — which is a terabyte,
> so I use a **Bloom filter**, and the reason that's safe is the asymmetry: it can say 'seen' for
> something new (I lose ~1% of pages, fine) but it can **never** say 'new' for something seen, which
> is the failure that would matter. The other half is politeness: instead of one global queue I keep
> **one queue per domain with a due-time**, so a thousand workers can never all hit the same site —
> and a worker is never blocked, it just takes a URL from a domain that is due."*
