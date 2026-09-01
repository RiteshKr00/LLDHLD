# HLD-04 — YouTube / Netflix

## META
- difficulty: medium-hard
- time: 45 min
- tags: transcoding-pipeline, cdn, adaptive-bitrate, blob-storage
- why-it-matters: the only problem where **the CDN is the architecture**, not a footnote. Also
  introduces async worker pipelines.

## PROMPT
> "Design YouTube. Users upload videos; other users watch them."

## CLARIFY
- **Upload or watch — which matters more?**
  → **Watch, overwhelmingly.** Uploads are rare, views are constant. (Get this ratio early.)
- **Do we handle different devices/network speeds?**
  → Yes — phone on 3G and TV on fibre both play the same video. **That's adaptive bitrate.**
- **Live streaming?**
  → **Out of scope.** Live is a genuinely different system (say this — it's a big scope cut).
- **Recommendations / search?**
  → Out of scope (ML).
- **How long until an uploaded video is watchable?**
  → Minutes is fine. Uploads are **not** real-time.
- **Comments, likes?**
  → Mention as a separate simple service; don't design it.

## STEP 1 — Requirements
**Functional:** upload a video · **transcode it into multiple resolutions** · stream it with quality
that adapts to the viewer's bandwidth · basic metadata (title, views).
**Non-functional:** **playback starts fast (<2 s) and never buffers** · massively read-heavy ·
uploads may take minutes to become available (async is fine) · global audience.
**Out of scope:** live streaming · recommendations · search · monetisation · DRM.

### CHECKPOINTS
- States **read-heavy** and that **upload is async** — those two unlock the whole design
- Names **adaptive bitrate** as a requirement, not an optimisation
- Scopes out live streaming explicitly

### TRAPS
- Treating upload as synchronous ("upload returns when the video is ready") — transcoding takes minutes
- Forgetting multiple resolutions — then you're streaming 4K to a phone on 3G

## STEP 2 — Capacity
```
users        2B MAU, 500M DAU
watching     each DAU watches 5 videos -> 2.5B views/day ÷ 86,400 ≈ 30,000 views/sec
uploads      500 hours of video per MINUTE -> ~8 hours/sec of new content
             but only ~1,000 uploads/sec of REQUESTS  <- tiny vs views
ratio        views : uploads  ≈  30,000 : 1000... but in BYTES it is far more extreme
bandwidth    30,000 concurrent streams × 5 Mbps ≈ 150 Gbps   <- and this is the real number
storage      500 h/min × 60 × 24 = 720,000 h/day
             × ~1 GB/h × 5 resolutions ≈ 3.6 PB/day
```

### CHECKPOINTS
- Computes **bandwidth in Gbps**, not just QPS — for video, bytes are the constraint
- Notes that transcoding **multiplies storage** (one upload → 5+ renditions)
- Establishes read-heavy with numbers

### TRAPS
- Only computing requests/sec. 30,000 requests is nothing; **150 Gbps of egress** is everything.
- Forgetting the storage multiplier from renditions

### FOLLOWUPS
- *"150 Gbps. Are you serving that from your own servers?"* ← the CDN trapdoor

## STEP 3 — API
```
POST /api/v1/videos              {title, size}   -> 201 {video_id, upload_url}
PUT  <upload_url>                                 -> direct to blob storage (NOT through your API)
POST /api/v1/videos/{id}/complete                 -> 202 Accepted  (transcoding starts)
GET  /api/v1/videos/{id}                          -> 200 {title, status, manifest_url}
GET  <manifest_url>                               -> .m3u8 / .mpd  (list of renditions + segments)
GET  <segment_url>                                -> 6-second chunk, from CDN
```

### CHECKPOINTS
- Upload bytes go **directly to blob storage** via a pre-signed URL, not through the app servers
- `complete` returns **202** — transcoding is async
- Playback is **manifest + segments**, not one big file URL

### TRAPS
- Routing multi-GB uploads through your API tier — you've just made your app servers the bottleneck
- Serving `video.mp4` as a single file — no adaptive bitrate, no seeking, no CDN efficiency

## STEP 4 — Data model + storage
```
videos(video_id, uploader_id, title, status, duration, created_at)
renditions(video_id, resolution, bitrate, manifest_path)
segments -> object storage, path-addressed
view_counts(video_id, count)          -- approximate, aggregated async
```
- **Metadata → relational/sharded** (small).
- **Raw upload + all renditions + segments → object storage (S3)**, then **CDN in front**.
- **View counts → not a synchronous DB write.** 30,000 views/sec × a row update is silly; batch it
  through a stream and aggregate. Counts are allowed to be approximate and a bit behind.

### CHECKPOINTS
- Metadata and media in **different systems**, with the reason (KB vs PB)
- **Segments** as first-class stored objects, not a runtime slicing operation
- View counts handled **asynchronously/approximately**

### TRAPS
- `UPDATE videos SET views = views + 1` on every play — 30,000 write QPS on one hot row per viral video

## STEP 5 — Architecture
```
UPLOAD PATH (rare, slow, async)
  Client ──pre-signed URL──▶ S3 (raw)
                              │
                              ▼  event
                         Kafka ──▶ Transcoding workers (fan out per rendition)
                                      ├─ 240p  ├─ 480p  ├─ 720p  ├─ 1080p  ├─ 4K
                                      └─ split each into ~6 s SEGMENTS
                                      └─ write manifest (.m3u8)
                                      └─ mark video READY

WATCH PATH (constant, fast, cached)
  Client ──▶ CDN edge ──(miss)──▶ S3
     │ 1. GET manifest
     └ 2. GET segment, segment, segment…  choosing bitrate as it goes
```

### CHECKPOINTS
- Transcoding is a **queue + worker pool**, fanned out per rendition (they're independent → parallel)
- Video is **segmented** during transcoding, not on demand
- The watch path **terminates at the CDN** — your origin sees almost nothing
- Status flows `UPLOADED → TRANSCODING → READY`

### FOLLOWUPS
- *"A transcoding worker dies halfway through a 2-hour video. What happens?"*
- *"What fraction of your 150 Gbps actually reaches your servers?"*

## DEEP DIVE — the transcoding pipeline + adaptive bitrate

### Why transcode at all
One source file cannot serve everyone:
```
4K TV on fibre        needs 25 Mbps
laptop on wifi        needs 5 Mbps
phone on 3G           needs 0.5 Mbps  -> sending it 4K = permanent buffering
```
So you produce **the same video at many bitrates**, once, at upload time. Transcoding is CPU-expensive
(often slower than real-time) — which is exactly why it must be **async and queued**, never in the
request path.

### Why segments (the second half of the trick)
Each rendition is chopped into **~6-second segments**:
```
video/
  1080p/seg001.ts seg002.ts seg003.ts …
  720p /seg001.ts seg002.ts seg003.ts …
  480p /seg001.ts seg002.ts seg003.ts …
  manifest.m3u8   <- lists all renditions and their segments
```

### Adaptive bitrate = the *client* chooses, per segment
```
0:00  client starts at 480p (safe)          -> plays fine
0:06  measured download speed is high       -> next segment from 720p
0:12  still fast                            -> 1080p
0:30  user walks into a lift, speed drops   -> next segment from 480p
```
The switch happens **at a segment boundary**, so playback never stops. The server does nothing clever —
it just serves whatever segment is requested. **All the intelligence is in the player.**

That's the elegant bit: adaptive bitrate needs **no server-side state at all**, which is precisely
what makes it CDN-cacheable.

### The CDN is the architecture
```
without CDN:  150 Gbps from your origin. Impossible and ruinous.
with CDN:     >95% served from edge caches near the viewer
              your origin sees only cache misses (cold/rare videos)
```
Video is **perfectly cacheable**: a segment is immutable, content-addressed by path, and never
personalised. This is the ideal CDN workload — unlike, say, a news feed.

**Popularity is extremely skewed:** a tiny fraction of videos take most of the traffic, so a small
edge cache captures nearly all of it. Cold videos miss to origin, and that's fine.

### CHECKPOINTS
- Transcoding is **async, queued, and fanned out per rendition**
- Explains **segmentation (~6 s)** and that renditions are aligned so switching is seamless
- States that **the client picks the bitrate**, per segment — the server is dumb
- Identifies the **CDN as the primary serving tier**, with a number (>95% offload)
- Notes segments are **immutable → ideal for caching**

### TRAPS
- Transcoding synchronously during upload
- Serving whole files instead of segments — kills adaptive bitrate *and* CDN efficiency
- Treating the CDN as an afterthought ("and we'll add a CDN") rather than the thing carrying the load
- Forgetting that the renditions must be **segment-aligned**, or switching quality causes a glitch

### FOLLOWUPS
- *"The player switched from 1080p to 480p. What exactly did it do?"*
- *"A brand-new video goes viral. Walk me through the first 60 seconds at the CDN."*

## STEP 7 — Scale
- **Transcoding workers**: embarrassingly parallel — one job per (video × rendition). Scale by adding
  workers; use spot/preemptible instances since jobs are retryable.
- **Long videos**: split the *source* into pieces, transcode pieces in parallel, then stitch. A 2-hour
  video shouldn't be one 3-hour job.
- **Priority queues**: a popular creator's upload jumps the line ahead of a batch backfill.
- **CDN**: multi-region, tiered (edge → regional → origin) so a miss doesn't always reach S3.
- **Pre-warm** the CDN for content you *know* will be hot (a big premiere).

## STEP 8 — Failure
- **Transcoding worker dies** → the job is still on the queue; another worker retries. Idempotent because
  output paths are deterministic. **Repeated failures → DLQ** and the video is marked `FAILED`, not stuck.
- **Some renditions ready, others not** → publish what's ready; the manifest just lists fewer options.
  Users watch at 480p while 4K is still cooking. **Graceful degradation.**
- **CDN edge down** → other edges / regional tier absorb it; origin sees a spike but survives.
- **S3 unavailable** → cached content keeps playing; cold videos fail. The catalogue degrades, it
  doesn't vanish.

## STEP 9 — Wrap
- **Bottleneck:** egress bandwidth (solved by CDN) and transcoding CPU (solved by an elastic worker pool).
- **Tradeoffs:** more renditions = better experience but more storage + CPU · shorter segments = faster
  adaptation but more requests · pre-warming costs money for content that might not be hot.
- **Monitoring:** CDN hit rate (the headline metric), rebuffer ratio, startup time p95, transcode queue
  depth and lag, % of videos stuck in TRANSCODING.
- **Next:** live streaming (a genuinely different pipeline), DRM, per-title encoding, thumbnails, recommendations.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | upload to S3, save a row, "serve the mp4", maybe mentions a CDN at the end |
| **Senior** | async transcoding queue, multiple renditions, segments + manifest, CDN as the serving tier |
| **Staff** | all that **+ 150 Gbps computed and used to justify the CDN**, client-side ABR with the "server is dumb, that's why it caches" insight, parallel transcoding of long videos, and graceful publish of partial renditions |

## REFERENCE
**Upload → watchable:**
1. `POST /videos` → metadata row (`status=UPLOADING`) + a **pre-signed S3 URL**
2. Client `PUT`s bytes **straight to S3** — never through your servers
3. `POST /complete` → **202** + a `video_uploaded` event on Kafka
4. Workers pick it up and fan out: one job per rendition (240p…4K). Long videos are split, done in
   parallel, stitched.
5. Each job outputs **~6 s segments** + writes the manifest
6. `status=READY`. Elapsed: minutes — and nobody was waiting on a request.

**Watching:**
1. `GET /videos/{id}` → manifest URL
2. Player fetches the manifest → sees available bitrates
3. Player requests segments one at a time, **choosing the bitrate from its own measured bandwidth**
4. Every segment comes **from a CDN edge**; your origin is involved only on a miss
5. Bandwidth drops mid-video → the *next* segment is fetched at a lower bitrate. No stall.

## ONE-LINER
> *"The number that decides everything is **150 Gbps of egress**, not the request rate — so the CDN
> isn't an optimisation, it's the serving tier, and my origin only sees misses. To make that work the
> content has to be perfectly cacheable, which it is: I transcode asynchronously into several bitrates,
> cut each into immutable ~6-second segments, and let the **player** pick the bitrate per segment.
> The server stays completely dumb, which is exactly why it caches."*
