# Text Editor — HLD (collaborative editing: Google Docs / Notion)

Companion to [`solution.py`](solution.py) (the single-process editor).
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).

> **Framing:** the LLD had one `Document`, two stacks, **one writer**. Let two people type at once and
> `InsertCommand.pos` is suddenly measured against a document that has moved — and **Ctrl+Z stops
> meaning "reverse the last thing that happened" and starts meaning "reverse the last thing *I* did".**
> That second one is the centrepiece.

## 1. Scope
- **Functional:** many editors per doc · edits appear live · **per-user undo/redo** · presence + remote cursors · version history and named revisions · edit offline, reconnect.
- **Non-functional:** **local echo instant** (typing can't wait for a round trip) · **replicas converge** · no silently lost edits · a doc survives losing the box serving it.
- **Out of scope:** rich formatting beyond a marker op, comments, ACL model, export.

## 2. Estimate — it immediately forces a decision
10M people who actually *edit* on a given day, each typing ~1,000 characters:
**10M × 1,000 = 10^10 keystrokes/day ÷ 86,400 ≈ 116K/s average, ×2 for peak ≈ 230K/s.**

**230K server ops/sec for people typing is absurd — so don't send keystrokes.** The client coalesces a
typing run into one op (flush on 200 ms idle, cursor move, or 20 chars). ~5× off, and free: a run of
characters is already one `InsertCommand`.
- **2B ops/day** → `2×10^9 ÷ 86,400` ≈ **23K ops/s** avg, **~46K/s peak**.
- **Storage:** 2B × ~120 B/op ≈ **240 GB/day**, ~7 TB/month.
- **Sockets:** 10M × 15-min sessions = 150M user-min ÷ 1,440 ≈ 104K avg, **~210K peak**. At ~1.2 editors/doc = **~175K live docs in memory** — 20 boxes × 10K docs, ~2.3K ops/s each. Small *per box*.
- **The surprise:** edits egress 46K × 1.2 × 120 B ≈ **6.6 MB/s**; cursors at 5/s/socket are 210K × 5 × 60 B ≈ **63 MB/s** — **10× the edit traffic, 0× the storage.** Held for (g).

## 3. Architecture
```
  Browsers — local Document + queue of unacked ops; edits echo INSTANTLY
      │ WebSocket, one per open doc
      ▼
  WS Gateway ── routes by doc_id, NOT round-robin ──▶ Redis: SET own:{doc} box NX EX 30
      ▼
  ┌───────────────────────────────────────┐  ops   ┌──────────────┐
  │ DOCUMENT SERVER — owns this doc       │──────▶ │ fan-out tier │
  │  in-memory text   ← the LLD Document  │ pubsub │ read-only    │
  │  sequencer v, v+1 ← the total order   │        │ viewers      │
  │  transform(op, ops since base_version)│        └──────────────┘
  │  per-USER command stacks ← the two    │
  └───┬─────────────────────┬─────────────┘
      │ batched append      │ presence/cursors — never written to disk
      ▼                     ▼
  OP LOG (the TRUTH)     Redis              Postgres
  pk doc_id, ck version  presence TTL,      metadata, ACL,
      │ every 1,000 ops   ownership leases  named revisions
      ▼
  SNAPSHOTS (S3) — opening a doc = latest snapshot + replay the tail
```

## 4. The key decisions

### (a) Why last-write-wins is wrong here
- Doc is `"report"`. A appends `" v2"` at the end, B fixes offset 0 to `"Report"`. Both read v10, both write v11.
- LWW keeps one whole document and drops the other. **No error, no conflict marker — a paragraph vanishes.** Both edits were valid and didn't even overlap.
- It's the repo's **check-then-act (TOCTOU)** race in slow motion: read state, write the whole state back, clobber what committed in between. The usual fix — **push atomicity into the shared store** — applies with a twist: not a lock, but **changing the merge unit**. Send the *delta*; let the store order deltas.
- LWW is right when a value is opaque and atomic (a display name). A document is a **composition of independent edits**, so the operation is the unit and both must survive.

### (b) OT vs CRDT
**OT.** Each op carries the `base_version` it was written against. A central server owns the total
order: it transforms an incoming op against everything committed since that version, assigns the next
version, broadcasts; clients mirror the transform locally. **Cost:** the doc stays a plain string, no
per-character overhead — but the transform must be right for every *pair* of op types, a matrix that
grows with the alphabet (insert/delete/replace/format). One server means you only need TP1; go
peer-to-peer and you need TP2, which is where OT implementations famously die.

**CRDT.** Each character gets a globally unique immutable id and a place in a dense order that never
changes (RGA "insert after id X", or a fractional index). Insert and delete-as-tombstone are
commutative and idempotent, so ops arrive **in any order, any number of times, from any peer** and
every replica converges with no central authority. **Cost:** metadata per character, often bigger than
the character (run-length encoding in Yjs/Automerge shrinks it, doesn't remove it), and tombstones need
a causal-stability protocol before collection. Be precise about the promise — and about *which*
CRDT, because the sloppy version of this point gets corrected: **CRDTs guarantee CONVERGENCE, not
intent preservation.** A **fractional-index** CRDT (Logoot/LSEQ) can interleave `abc` and `xyz` typed
at the same cursor into `axbycz`. **RGA/YATA** (the Yjs and Automerge family) do not: the `abc` run
hangs off the subtree of its own `a`, so each run stays contiguous and you get `abcxyz` or `xyzabc`
— but *which* of the two, and therefore whose sentence lands first, is still picked arbitrarily by
id order. So the headline survives in both families: every replica agrees, neither author gets what
they meant. Kleppmann et al. (PaPoC 2019) is exactly this split — say "Logoot interleaves, RGA
doesn't, and neither preserves intent," never "Yjs gives you `axbycz`."

| | OT | CRDT |
|---|---|---|
| Central sequencer | **required** | not needed |
| Hard part | transform matrix (TP1/TP2) | metadata size, tombstone GC |
| Offline 3 hours | transform against everything since | just merge |
| E2E-encrypted doc | **impossible** — server must read to transform | fine |

**Pick OT for a Docs-style product** — not because it's simpler (it isn't): the central server already
exists for auth, ACL, persistence and history, so the ordering authority is free rather than a new
dependency; that order reduces the problem to TP1; and the doc stays compact for everything else that
reads it (indexing, export, print). **CRDT wins the moment the server is optional or blind:**
offline-first, local-first, peer-to-peer, E2E. *Notion cheats:* its unit is a **block**, so two people
in different blocks never conflict at all, which deletes most of this section.

### (c) The transform, with the offsets actually checked
`D0 = "abcdef"`. A does `Insert("X", 3)`, B does `Delete(1, 2)` (removes `"b"`) — both against `D0`.
```
A local: "abcdef" + Insert("X",3)  ->  "abcXdef"
B local: "abcdef" + Delete(1,2)    ->  "acdef"

At B, A's op lands — B's doc lost 1 char BEFORE offset 3:
  naive  Insert("X",3) on "acdef"        ->  "acdXef"  WRONG, X went after 'd'
  T(A,B) delete at 1 < 3, len 1 -> pos 2 ->  "acXdef"  correct
At A, B's op lands — A's insert was at 3, AFTER the deleted range:
  T(B,A) 1 < 3, Delete(1,2) unchanged on "abcXdef" ->  "acXdef"  correct
```
- Converges on `"acXdef"` — also what the two humans meant. **Note which op moved: the one at the
  HIGHER offset.** The delete at 1 needed nothing; the insert at 3 shifted down by 1.
- Rule: an insert of length L shifts later offsets **up** by L, a delete shifts them **down** by L;
  offsets before the change are untouched.
- **Skipping the transform gives a crash or silent corruption, not a conflict** — `Document.delete`
  raises `IndexError(f"range {start}:{end} out of range")` when the offsets no longer exist, and when
  they *do* exist it deletes the wrong characters.
- Cases the naive rule misses: **concurrent inserts at the same offset** need a deterministic tie-break
  (site id) or replicas interleave differently and diverge; **overlapping deletes** must shrink to the
  remainder. `ReplaceCommand` is worst — a delete+insert pair, transform both halves.

### (d) One owner per document — statefulness, bought and paid for
- **One process owns a doc in memory**; every WebSocket for that doc lands there, and that owner **is**
  the sequencer. No consensus, no distributed lock — the LLD needed no lock because there was one
  writer, and this preserves that at scale.
- **Route by `doc_id`, not by connection** — round-robin breaks it on request one. `doc_id → box` in
  Redis, claimed with `SET own:{doc} box NX EX 30`: **the atomic claim in the shared store, in another
  costume**, renewed while serving. Box dies → lease lapses → someone else claims it. **TTL/lease
  self-healing**, no sweeper.
- **The bill:** deploys stop being free. A rolling restart must drain — refuse new sessions, flush the
  log, drop the lease, make clients reconnect (a path that already exists for flaky wifi).
- **Split brain is the real risk:** two owners = two sequencers = divergence. The atomic lease is
  necessary but not sufficient — the log append is **conditional on `expected_version`**, fencing a
  zombie owner's writes at the store.

### (e) Per-user undo — the LLD's two stacks in a shared document
- `CommandHistory` becomes **per `(doc_id, user_id)`** and is **filtered to my own commands**, or Ctrl+Z
  reverses my colleague's sentence.
- **Filtering alone is not enough — this is the part that gets missed.** The LLD undoes
  `InsertCommand("X", 3)` with `doc.delete(self.pos, self.pos + len(self.text))`. `self.pos` was true
  when I typed it; by Ctrl+Z time, other people's ops have landed. **The inverse must itself be
  transformed forward** through every op since that entry's `base_version` — the arithmetic in (c).
- **Never rewrite the log.** Server-side `Command.undo` doesn't pop history; it **emits a new inverse op
  appended forward**, so the log stays append-only, collaborators see the undo, and it's redoable.
- The mini-mementos matter *more*: `DeleteCommand._removed` / `ReplaceCommand._old_text` are the only
  record of text already gone.
- **The redo-clear rule changes meaning.** `CommandHistory.push()` clears `_redo` on any edit; shared,
  that must be **any edit of MINE** — a remote op isn't me branching away from my future.
- **No LLD equivalent:** I insert `"X"`, someone deletes the paragraph containing it, I press Ctrl+Z.
  The inverse transforms to a **no-op** and must silently succeed — `False` there reads as a dead key.

### (f) Op log + snapshots, and the version history that falls out
- **Truth = an append-only op log**, partitioned by `doc_id`, clustered by `version` — "everything after
  v" is one range scan. Appends conditional on `expected_version`: optimistic concurrency and the
  fencing token from (d) in one mechanism.
- **Derive-vs-materialise:** the text is *derived* from the log, but replaying a million ops to open a
  doc is unacceptable, so **snapshot every ~1,000 ops** and materialise. Open = snapshot + bounded tail.
  The snapshot is a cache with a correctness guarantee — reproducible, so a corrupt one replays back.
- **Version history isn't built, it's already there.** Ops carry `(user, ts)`, so "restore to Tuesday
  3pm" = nearest snapshot + replay to that version; attribution is the same log by offset range. A
  **named revision** is one row `{doc_id, version, label, created_by}` and zero new bytes.
- **Restoring is not rewinding** — it *appends* ops turning current text into historical text, so the
  log stays append-only and the restore is itself undoable. Retention: full ops 30 days, then compact.

### (g) Presence and cursors — what you deliberately do NOT store
- Highest-frequency traffic in the system (63 MB/s vs 6.6 MB/s of real edits) and the least valuable.
  Throttle client-side to ~5/s, ride the same socket, broadcast, forget.
- Owner memory + Redis with a short TTL so "who's here" rebuilds on reconnect — a crashed client **ages
  out by itself**.
- **Nobody has ever needed to know where a colleague's cursor was on Tuesday.** Losing all of it costs
  one heartbeat of wrongness. Naming what you refuse to persist is the cheapest decision here.
- Ephemeral ≠ exempt: a remote cursor at offset 40 still shifts when I insert at 10 — same transform, on
  a bare offset instead of an op.

## 5. Failure
- **Document server dies mid-session.** Acked ops are in the log; ops the client never got an ack for
  sit in its pending queue and are **replayed** against whatever version the new owner reports. That is
  **at-least-once delivery**, so every op carries a **dedup key `(site_id, client_seq)`** and the new
  owner drops what it already has — without it a reconnect duplicates the last few characters, which
  users spot instantly. **The op log is what makes a dead owner a reconnect instead of a data loss.**
- **The numbers:** RTO per doc ≈ lease TTL (30 s) + snapshot load; RPO ≈ one append batch (~200 ms), and
  effectively **zero** for connected clients, because they replay their own tail.
- **Op-log store unavailable — neither fail-open nor fail-closed.** Keep the session live and keep
  buffering: the users are mid-sentence and cutting them off *guarantees* the loss you were preventing.
  Show "changes not saved", refuse *new* sessions on that doc, go read-only only past a buffer/time
  bound. Ticketing fails closed because a bad write costs a seat; here the cost of blocking is the
  paragraph still in the user's head.
- **A client offline for hours** must transform against everything since — **this is where OT visibly
  gives up.** Bound it: past N ops or T hours, fork a "recovered copy" to merge by hand.
- **Region partition, doc owned elsewhere** → those users go read-only. One owner per doc makes this
  **CP by construction**; say so rather than pretending otherwise.

## 6. Scale
- **Shard by `doc_id`** — the ideal key, because no transaction ever spans two documents. Ownership *is*
  the shard, so growth is just more document servers.
- **The hot doc is what more boxes don't fix:** a 500-person all-hands doc has one owner fanning out to
  500 sockets. Split roles — **editors** hold a socket to the owner, **viewers** subscribe to the op
  stream via the **fan-out tier**, so the owner broadcasts once.
- **Why cross-region latency is invisible:** the client applies its own op **optimistically** and only
  reconciles when the transformed version returns, so 150 ms RTT never touches typing.
- **10×:** more doc servers (linear), op log scales by partition key, snapshots to object storage,
  presence already ephemeral. Metrics: **divergence count (must be 0)**, transform depth, ack p99,
  reconnect rate.

---

## LLD ↔ HLD mapping
| LLD (`solution.py`) | HLD |
|---|---|
| `Document._content` — one string, one process | one doc owned in memory by **one** server; the **op log** is the truth |
| `Document.insert(text,pos)` / `delete(start,end)` | same primitives — offsets now **version-relative**, transform before applying |
| `Document.delete` raising `IndexError` | exactly what an **un-transformed** remote op does on arrival |
| `InsertCommand(text, pos)` | an op on the wire: `{doc_id, site_id, client_seq, base_version, type, pos, text}` |
| `DeleteCommand._removed` · `ReplaceCommand._old_text` | the mini-mementos, **more** vital — the only record of text already gone |
| `Command.execute()` / `Command.undo()` | execute = apply + append; undo = a **new inverse op appended forward**. Never rewrite the log |
| `CommandHistory._undo` (deque) | **per `(doc_id, user_id)`**, filtered to my ops, each carrying its `base_version` |
| `CommandHistory.push()` clearing `_redo` | cleared only by **my** next edit — a remote op must not kill my redo |
| `MAX_HISTORY = 50` | a client-side UI cap. The server keeps **every** op — that *is* version history |
| `TextEditor._run` (execute, then push) | apply **optimistically**, send, reconcile when the transformed version returns |
| no lock needed (single writer) | one owner per doc = the sequencer. **Ordering, not locking** |
| *(nothing)* | OT, presence, snapshots, leases, reconnect + dedup, named revisions |

**The line to say:**
> *"Single-user, undo is easy because the document can't move under the stack. Shared, offsets are only
> valid at the version they were written against, so every op **and every inverse** has to be
> transformed against what landed since — and undo becomes **per-user**, so the two stacks get filtered
> to my own commands. **OT over CRDT** because the central server already exists and keeps the document
> compact; CRDT the moment I need offline-first or E2E. The **append-only op log plus snapshots** is the
> source of truth, which is what makes a dead document server a reconnect rather than a data loss."*
