# HLD-01 — News Feed (Twitter / Instagram)

## META
- difficulty: hard
- time: 45 min
- tags: fan-out, celebrity-problem, caching, ranking
- why-it-matters: **the most-asked HLD question.** Fan-out is machinery that appears nowhere else.

## PROMPT
> "Design the news feed for Twitter. A user opens the app and sees recent posts from everyone
> they follow."

## CLARIFY
- **Feed ordering — chronological or ranked?**
  → Start chronological; mention ranking as an extension. Ranking is an ML problem, not an HLD one.
- **How many people does a user follow? How many followers does a user have?**
  → Average ~200 follows. But **celebrities have 100M followers** — that asymmetry is the whole problem.
- **How fresh must the feed be?**
  → Seconds is fine. A post appearing 5s late is invisible to users. **You may be eventually consistent.**
- **Media?**
  → Text + image URLs. Actual blob storage/CDN out of scope.
- **Read:write ratio?**
  → Massively read-heavy. People scroll far more than they post.
- **Do we need "who liked this" counts?**
  → Counts yes, the full list no.

## STEP 1 — Requirements
**Functional:** post a tweet · view your feed (posts from people you follow, newest first) ·
follow/unfollow · pagination as you scroll.
**Non-functional:** feed load **< 200 ms** · **eventually consistent** is acceptable · read-heavy ·
highly available (a down feed = a down product).
**Out of scope:** ML ranking · DMs · search · trending · media storage · notifications.

### CHECKPOINTS
- States the feed can be **eventually consistent** (this permission is what unlocks caching/precompute)
- States it is **read-heavy** before computing numbers
- Scopes out ranking rather than trying to design it
- Mentions pagination (feeds are infinite; you never return "the feed", you return a page)

### TRAPS
- Treating the feed as strongly consistent — kills every precompute option
- Trying to design ML ranking — it is not what is being tested
- Forgetting follow/unfollow as an operation that *changes* everyone's feed inputs

### FOLLOWUPS
- *"Does a user need to see their own post instantly in their feed?"* (yes — special-case it, or read-your-writes)
- *"What happens when someone unfollows? Do old posts disappear from the feed?"*

## STEP 2 — Capacity
```
users            300M total, 150M DAU
posts            2M/day per 100M... say each DAU posts 0.2/day
                 -> 30M posts/day  ÷ 86,400  ≈ 350 writes/sec   (peak ~700)
feed reads       each DAU opens the app ~10x/day
                 -> 1.5B reads/day ÷ 86,400 ≈ 17,000 reads/sec  (peak ~35,000)
ratio            ~50:1 READ-HEAVY
storage          30M posts/day × 300 B ≈ 9 GB/day ≈ 3 TB/year   (text only — modest)
fan-out volume   350 posts/sec × 200 avg followers ≈ 70,000 feed-writes/sec
                 ^ THIS is the number that decides the design
```

### CHECKPOINTS
- Computes **write QPS ≈ hundreds**, **read QPS ≈ tens of thousands**
- States the **read:write ratio explicitly** (~50:1)
- **Computes the fan-out amplification** (posts/sec × avg followers) — this is the number that matters
- Notes storage is modest (text is cheap; media is the expensive part, and it's out of scope)

### TRAPS
- Computing read and write QPS but **never computing fan-out** — then the design has no justification
- Forgetting `÷ 86,400`
- Using *average* followers only and never asking what the max is (the celebrity case)

### FOLLOWUPS
- *"You said 200 average followers. What if someone has 100 million?"* ← this is the trap door into the deep dive

## STEP 3 — API
```
POST /api/v1/posts            {text, media_urls}      -> 201 {post_id}
GET  /api/v1/feed?cursor=…&limit=20                   -> 200 {posts[], next_cursor}
POST /api/v1/users/{id}/follow                        -> 204
DELETE /api/v1/users/{id}/follow                      -> 204
```

### CHECKPOINTS
- Feed uses **cursor pagination**, not offset
- Feed returns a **page**, never the whole thing

### TRAPS
- `?page=5&size=20` — offset pagination **breaks on a live feed**: new posts arrive while you scroll,
  everything shifts down, and you see duplicates. Cursor (a post id / timestamp) is stable.

## STEP 4 — Data model + DB
```
users(user_id PK, name, …)
follows(follower_id, followee_id)        -- both directions indexed
posts(post_id, author_id, text, created_at)
feed_cache(user_id, post_id, created_at) -- the PRECOMPUTED feed, per user
```
- **posts / follows** → sharded relational or wide-column; access is by key.
- **feed_cache** → **Redis list per user** (`feed:{user_id}`), capped at ~800 entries. Nobody scrolls
  past that; anything older is served by falling back to a query.

### CHECKPOINTS
- Has a **precomputed feed store** separate from the posts table
- Caps the stored feed length (a feed is not infinite storage)
- Shards `posts` by `post_id`/`author_id`, `follows` by `follower_id`

### TRAPS
- Only having `posts` and `follows`, then computing the feed with a **JOIN at read time** — that is
  the naive design, and it is O(follows) per read at 35,000 reads/sec

## STEP 5 — Architecture
```
POST /posts ─▶ Post Service ─▶ posts DB
                    │
                    └▶ Kafka ─▶ Fan-out Service ─▶ for each follower:
                                                     LPUSH feed:{follower_id}
GET /feed  ─▶ Feed Service ─▶ Redis feed:{user_id}  (LRANGE, O(1))
                            └▶ hydrate post bodies from cache/DB
```
- **Write path:** post once → fan out to N follower lists (async, via a queue).
- **Read path:** one Redis list read. **No joins, no computation.**

### CHECKPOINTS
- Fan-out happens **asynchronously**, off the posting request (posting must not wait for 200 writes)
- The read path is **a single cache read**, not a query
- Feed entries store **post ids**, with bodies hydrated separately (so an edited/deleted post is
  handled in one place)

### FOLLOWUPS
- *"The user posts and their own feed doesn't show it for 2 seconds. Acceptable?"*
- *"How does the Fan-out Service not fall over when a big account posts?"*

## DEEP DIVE — fan-out on write vs read, and the celebrity problem

**Fan-out on WRITE (push):** when you post, immediately append your post id to every follower's list.
```
read  = O(1)  — just read your list                     ✅ reads are 50× more common
write = O(followers)                                     ❌ 100M followers = 100M writes for ONE post
```

**Fan-out on READ (pull):** store nothing; at read time, fetch recent posts from everyone you follow and merge.
```
write = O(1)  — just save the post                       ✅
read  = O(follows) queries + a merge                     ❌ at 35,000 reads/sec this is brutal
```

**Neither works alone.** Push is right for 99.9% of users and catastrophic for celebrities;
pull is the reverse.

**The answer is HYBRID:**
```
normal user posts (< ~10k followers)   -> PUSH: fan out to follower lists
celebrity posts   (> ~10k followers)   -> DON'T fan out at all

reading a feed:
    1. read your precomputed list          (everything from normal accounts)
    2. for the handful of celebrities you follow, PULL their recent posts
    3. merge the two by timestamp
```
A user follows maybe 5 celebrities, so step 2 is 5 small queries — cheap. And the celebrity's post
is written **once** instead of 100 million times.

### CHECKPOINTS
- Explains **both** strategies with their cost asymmetry (O(1) read vs O(1) write)
- Identifies the **celebrity / hot-key problem** by name
- Proposes the **hybrid**, with a follower-count **threshold**
- Describes the **merge at read time** for pulled accounts

### TRAPS
- Picking one strategy and defending it — the expected answer is that both are wrong alone
- Saying "hybrid" without saying **where the threshold is** or **how the merge works**
- Forgetting that the celebrity's followers still need their feed to *look* chronological after merging

### FOLLOWUPS
- *"Where do you put the threshold, and what happens to a user who crosses it?"*
- *"A celebrity posts. Ten million people are online. What actually happens in your system?"*

## STEP 7 — Scale
- **Fan-out workers**: partition the Kafka topic by `post_id`; a big fan-out is chunked into batches
  so one post can be spread across many workers.
- **Redis**: cluster, sharded by `user_id`. Feed lists are independent → shards perfectly.
- **Feed length cap** (~800) bounds memory: 150M DAU × 800 ids × 8 B ≈ **1 TB** across the cluster.
- **Hot read keys**: a celebrity's *post* (not feed) is read by millions → cache the post body hard,
  and push to CDN.

## STEP 8 — Failure
- **Fan-out service down** → posts queue in Kafka; feeds go stale, nothing is lost. Degrades, not breaks.
- **Redis feed lost** → **rebuild by pulling** (fan-out-on-read as the fallback). Slower, still correct.
  *That's a nice property: your fallback is the other strategy.*
- **Post DB down** → can't post; feeds still readable from cache. **Reads survive writes failing.**
- **Duplicate fan-out** (at-least-once) → feed list gets the same post twice → dedupe by post id on read.

## STEP 9 — Wrap
- **Bottleneck:** fan-out amplification, not raw QPS.
- **Tradeoffs:** push = fast reads / expensive celebrity writes · pull = cheap writes / expensive reads ·
  hybrid = both, plus a merge and a threshold to maintain.
- **Monitoring:** feed p99, fan-out lag (how far behind is Kafka), cache hit rate, posts-per-second per author.
- **Next:** ranking, media/CDN, notifications, "you might like" injection.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | posts + follows tables, JOIN at read time, "add a cache" |
| **Senior** | precomputed feed, async fan-out on write, cursor pagination, computes the amplification number |
| **Staff** | all of the above **+ identifies the celebrity problem unprompted**, designs the hybrid with a threshold, notes that pull is also the disaster-recovery path for a lost cache |

## REFERENCE
The complete flow, end to end:

**Posting (normal user, 200 followers):**
1. `POST /posts` → write to `posts` table → return 201 **immediately**
2. Emit `post_created` to Kafka
3. Fan-out worker reads it, looks up followers, `LPUSH post_id` onto 200 Redis lists, trims each to 800

**Posting (celebrity, 100M followers):**
1. Same write, same 201
2. Fan-out worker sees `follower_count > threshold` → **does nothing**. The post lives only in `posts`.

**Reading a feed:**
1. `LRANGE feed:{user_id} 0 19` → 20 post ids (O(1))
2. Look up which celebrities this user follows (small, cached set)
3. Query recent posts for those few authors
4. **Merge by timestamp**, take 20, hydrate bodies from the post cache
5. Return with a cursor = the last post's id/timestamp

**Why this is the answer:** it pays the fan-out cost exactly where it's cheap (few followers) and
avoids it exactly where it's ruinous (millions of followers), while keeping the common read path at
one cache call.

## ONE-LINER
> *"Reads are ~50× writes, so I precompute feeds — fan out on write. But that's O(followers), which
> is fatal for a 100M-follower account, so above a threshold I don't fan out at all and instead pull
> those few accounts at read time and merge. Push for the many, pull for the famous."*
