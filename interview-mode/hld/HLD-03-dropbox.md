# HLD-03 — Dropbox / Google Drive

## META
- difficulty: hard
- time: 45 min
- tags: chunking, dedup, sync, conflict-resolution, blob-storage
- why-it-matters: the only problem where **the file itself is the hard part**. Chunking + content-hash
  dedup appear nowhere else.

## PROMPT
> "Design Dropbox. Users put files in a folder; those files sync to all their devices and can be
> shared with other people."

## CLARIFY
- **File sizes?**
  → Up to a few GB. **That size is the whole problem** — you cannot treat a file as one blob.
- **How often do files change?**
  → Constantly, but usually **a small part** of a large file (think editing a slide in a 200 MB deck).
- **Do two people edit the same file simultaneously?**
  → It can happen. You need a **conflict** story, not a merge story — this isn't Google Docs.
- **Offline?**
  → Yes. Edit offline, sync on reconnect.
- **Versioning?**
  → Keep version history, 30 days.
- **Search inside files?**
  → Out of scope.

## STEP 1 — Requirements
**Functional:** upload/download files · **sync across a user's devices** · share with other users ·
version history · work offline and reconcile on reconnect.
**Non-functional:** **never corrupt or lose a file** · uploads must **resume** after a network drop ·
sync should feel fast for small edits to big files · bandwidth-efficient.
**Out of scope:** real-time collaborative editing · in-file search · previews/thumbnails.

### CHECKPOINTS
- States that **a small edit to a large file must not re-upload the whole file** ← this single line forces chunking
- Treats **resumable upload** as a requirement (a 2 GB upload *will* be interrupted)
- Says **conflict**, not merge — files are opaque bytes; you can't merge a .psd

### TRAPS
- Designing it as "POST the file" — works for 1 MB, absurd for 2 GB over hotel wifi
- Promising automatic merge — that's Google Docs (OT/CRDT), a different problem

## STEP 2 — Capacity
```
users        500M, 100M DAU
files        each user 100 files avg -> 50B files
             avg size ~1 MB          -> 50 PB raw
edits        each DAU changes 10 files/day -> 1B file-changes/day ÷ 86,400 ≈ 12,000/sec
metadata     50B rows × 500 B ≈ 25 TB   <- small enough for a sharded DB
blob         50 PB  <- object storage (S3), NOT a database
dedup win    ~30% of bytes are duplicates across users (the same PDF, the same installer)
             -> content-hash dedup saves petabytes
```

### CHECKPOINTS
- Separates **metadata size (TB)** from **blob size (PB)** — they go to completely different systems
- Estimates the **dedup saving** and uses it to justify content-addressing
- Notes edit rate, not just upload rate (edits are the common case)

### TRAPS
- Storing file bytes in the database. 50 PB in Postgres is not a plan.
- Forgetting that **metadata is tiny compared to content** — that asymmetry is what makes the design work

## STEP 3 — API
```
POST /api/v1/files                {path, size}          -> 201 {file_id, upload_session}
POST /api/v1/chunks/{hash}                              -> 204   (raw bytes; skipped if it exists!)
POST /api/v1/files/{id}/commit    {chunk_hashes[]}      -> 200 {version}
GET  /api/v1/files/{id}?version=  -> {chunk_hashes[]}   then fetch chunks (usually from CDN)
GET  /api/v1/changes?cursor=      -> 200 {changes[], next_cursor}   <- the sync feed
```

### CHECKPOINTS
- Upload is **three separate steps**: start → upload chunks → commit
- There's a way to **ask whether a chunk already exists** before sending bytes
- Sync is a **cursor-based change feed**, not "list all my files and diff"

### TRAPS
- One giant `POST /upload` — no resume, no dedup, no parallelism
- Making sync a full directory listing — that's O(files) on every poll

## STEP 4 — Data model + DB
```
files(file_id, owner_id, path, current_version, deleted)
versions(file_id, version, chunk_hashes[], size, created_at)
chunks(hash PK, size, blob_ref, refcount)     -- CONTENT-ADDRESSED
devices(device_id, user_id, last_sync_cursor)
shares(file_id, shared_with_user_id, permission)
```
- **Metadata → relational/sharded** (25 TB, needs transactions when committing a version).
- **Chunk bytes → object storage (S3)**, keyed by **the hash of the content itself**.

**Content-addressing is the trick:** the chunk's *name* is `SHA-256(bytes)`. Two users uploading the
same PDF produce the same hashes → you store it **once**. Dedup is not a background job; it's a
consequence of the naming scheme.

### CHECKPOINTS
- Chunks keyed by **content hash**, not by file/user
- A **version = an ordered list of chunk hashes** (so a version is tiny metadata, not a copy)
- Keeps a **refcount** (or GC pass) so deleting one user's file doesn't delete a chunk another user shares

### TRAPS
- Storing chunks per-file → no cross-user dedup, and 30% of your petabytes are duplicates
- Deleting chunks on file delete without refcounting → **you delete someone else's data**

## STEP 5 — Architecture
```
Client (watcher + chunker)
   │  1. file changed -> split into 4 MB chunks, hash each
   │  2. ask server: which of these hashes do you already have?
   ▼
Metadata Service ──▶ Metadata DB (files, versions, chunks)
   │
   │  3. upload ONLY the missing chunks
   ▼
Block Service ──▶ S3 (blob) ──▶ CDN (for downloads)
   │
   │  4. commit: "version N = [hash1, hash2, ...]"
   ▼
Notification Service ──▶ push "you have changes" to the user's OTHER devices
                          └─▶ they call GET /changes?cursor=…
```

### CHECKPOINTS
- The **client chunks and hashes**, before talking to the server
- Server is asked **which chunks it already has** → only the diff crosses the network
- **Commit is a separate, atomic step** — a version appears all-at-once or not at all
- Other devices are **notified**, then **pull** the change feed

### FOLLOWUPS
- *"I changed one slide in a 200 MB deck. How many bytes go over the wire?"*
- *"My upload dies at 80%. What happens when I retry?"*

## DEEP DIVE — chunking, dedup, and conflicts

### Why chunk (the number that makes the case)
200 MB presentation, you edit one slide:
```
whole-file upload:  200 MB              😱
chunked (4 MB):     hash all 50 chunks
                    49 unchanged -> server already has them -> skip
                    1 changed    -> upload 4 MB              ✅  50× less
```
Chunking also gives you, for free:
- **Resume** — the upload is 50 independent PUTs; retry only the failed ones
- **Parallelism** — upload 8 chunks at once
- **Dedup** — identical chunks anywhere in the world are stored once

**Chunk size is a tradeoff:** small chunks = better dedup + finer resume, but more metadata and more
requests. ~4 MB is the usual landing spot.

### Dedup, two levels
```
per-user:   you upload the same file twice -> second one is free
global:     10,000 people have the same textbook.pdf -> stored ONCE
```
The whole mechanism is: **name the chunk by its hash.** Same bytes → same name → already there.

> **Security caveat worth saying:** naive global dedup lets an attacker *probe* whether a file exists
> ("is the server asking me to upload this? no? then someone already has it"). Real systems mitigate
> with per-user salting or by only deduping after proof-of-possession.

### Conflicts — you cannot merge bytes
Device A and Device B both edit `report.docx` offline. Both come online.

**Version vectors** detect it: each file version records which device produced it and what it was
based on. If B's edit is based on v3 but the server is already at v4 (from A), the edits **diverged**.

What you do about it — three options, and the honest ranking:
```
1. Last-write-wins           ❌ silently destroys someone's work
2. Auto-merge                ❌ impossible for opaque binary
3. Keep BOTH, rename one     ✅  "report.docx" + "report (Bob's conflicted copy).docx"
```
Option 3 is what Dropbox actually does — because **the only safe resolution for opaque data is not to
resolve it.** Let the human decide; never lose bytes.

### CHECKPOINTS
- Quantifies the chunking win with an actual example (200 MB → 4 MB)
- Names the three freebies chunking gives: **resume, parallelism, dedup**
- Explains dedup as a **consequence of content-addressing**, not a separate process
- Detects conflicts with **version vectors** (or equivalent), not timestamps
- **Resolves conflicts by keeping both copies** — and explains *why* merging is impossible here

### TRAPS
- Saying "dedup" without saying **how** (the hash IS the key)
- Last-write-wins on user files — a data-loss bug, not a design choice
- Confusing this with Google Docs and reaching for OT/CRDT — those need *structured* text, not opaque bytes

### FOLLOWUPS
- *"Two devices edit offline, then both sync. Walk me through exactly what the user sees."*
- *"How do you know a chunk you already stored isn't corrupt?"* (the hash is also the checksum)

## STEP 7 — Scale
- **Blob → S3 + CDN**: downloads are served from the edge, never from your servers.
- **Metadata → shard by `user_id`**: a user's files stay together, so "list my folder" is one shard.
- **Chunk store**: content-hash is a perfect shard key — uniform by construction.
- **Sync fan-out**: notify a user's *devices* (a handful), not followers — this is a much smaller
  fan-out than the news feed, which is why push works fine here.
- **Hot chunk**: a viral file's chunks get CDN-cached hard.

## STEP 8 — Failure
- **Upload interrupted** → resume: re-ask which chunks exist, send only the rest. Nothing wasted.
- **Commit fails after chunks uploaded** → chunks are orphaned but harmless; a **GC pass** removes
  chunks with refcount 0 after a grace period. *(Never GC immediately — an upload may be mid-flight.)*
- **Corrupt chunk** → the hash doesn't match the content; detected on read, re-fetch from another replica.
- **Metadata DB down** → uploads stop (you can't commit a version), but downloads of known files
  continue from CDN.

## STEP 9 — Wrap
- **Bottleneck:** bandwidth and blob storage cost — which is exactly what chunk-level dedup attacks.
- **Tradeoffs:** small chunks (better dedup, more metadata) vs large (fewer requests, worse dedup) ·
  global dedup (huge saving, privacy caveat) vs per-user · conflict copies (never lose data, but the
  user sees clutter).
- **Monitoring:** dedup hit rate, upload resume rate, sync lag per device, orphaned-chunk count, conflict rate.
- **Next:** delta-within-chunk (rsync-style rolling hash), previews, in-file search, team folders.

## RUBRIC
| Level | Answer looks like |
|---|---|
| **Mid** | POST the file to S3, store a row in the DB, poll for changes |
| **Senior** | chunking + content-hash dedup + resumable upload + a cursor-based change feed |
| **Staff** | all that **+ the 200 MB / 4 MB number**, refcounting & GC for shared chunks, **conflict = keep both copies with the reason merging is impossible**, and notes the dedup privacy leak |

## REFERENCE
**Editing one slide in a 200 MB deck:**
1. Client watcher sees the file change; splits into ~50 chunks of 4 MB; SHA-256 each.
2. `POST /chunks/exists {hashes[]}` → server: "I have 49 of these."
3. Client uploads **one 4 MB chunk**.
4. `POST /files/{id}/commit {chunk_hashes[]}` → new version row = the ordered hash list.
5. Notification Service pings the user's laptop → it calls `GET /changes?cursor=…` → downloads the
   one new chunk → reassembles.

**Bytes over the wire: 4 MB instead of 200 MB — and only because the file was content-addressed.**

**Two devices edit offline:**
- Both commit versions based on v3. Server sees the second commit's parent is stale.
- It does **not** overwrite and does **not** merge. It creates
  `report (Bob's conflicted copy).docx` and syncs both to everyone.
- No bytes are lost; a human decides.

## ONE-LINER
> *"The file size is the problem, so I never treat a file as one blob — the client splits it into
> ~4 MB chunks and names each chunk by the **hash of its content**. That single decision gives me
> resumable uploads, parallel transfer, and global dedup for free, and a one-slide edit to a 200 MB
> deck moves 4 MB instead of 200. Conflicts I detect with version vectors and resolve by **keeping
> both copies** — opaque bytes can't be merged, so the only safe answer is never to lose any."*
