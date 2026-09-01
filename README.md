# LLD Interview Prep

Mentor-guided track for Low-Level Design interviews. Language: **Python**.

## What an LLD interview actually tests

LLD (Low-Level Design) is **not** algorithms and **not** distributed-systems scaling.
It tests one thing: *can you turn a fuzzy requirement into clean, extensible object-oriented code?*

| | HLD / System Design | LLD (this track) |
|---|---|---|
| Altitude | Boxes & arrows, services, DBs, load balancers | Classes, methods, relationships |
| "URL shortener" means | Sharding, cache, 100M QPS | `ShortenerService`, `URLRepository`, encoding strategy |
| Success looks like | Right tradeoffs at scale | Code that's easy to read, test, and extend |

The interviewer is silently grading: *Would I want this person committing to my codebase?*

---

## The 5-step framework (memorize this — it works on every problem)

**1. Clarify & scope** — Never start coding. Ask questions, then state the requirements back.
   - *Functional*: what must it DO? (the verbs)
   - *Non-functional*: constraints (thread-safe? persistence? scale hints?)
   - *Explicitly out of scope*: say what you're NOT building. This is a senior move.

**2. Find the entities** — Underline the **nouns**. Each real-world noun is a candidate class.
   - Nouns → classes/attributes. Verbs → methods.

**3. Design relationships & APIs** — How do objects connect, and what's the public interface?
   - Relationship types: *composition* (owns, dies together), *aggregation* (has, independent life),
     *association* (uses), *inheritance* (is-a — use sparingly, prefer composition).
   - Write method signatures BEFORE bodies. The signatures are the design.

**4. Apply SOLID / patterns where they earn their place** — Don't pattern-dump. Reach for a
   pattern only when a specific pain (rigidity, duplication, hard-to-test) shows up.

**5. Edge cases, concurrency, extensibility** — "What happens if two threads call this?",
   "How would I add feature X later?" Answering these unprompted is what separates senior from mid.

---

## The HLD framework (the *sister* round — 6 steps)

LLD and HLD are usually **separate interview rounds**. This track is LLD-first, but each problem
gets an HLD companion (e.g. `01-url-shortener/hld.md`) because the strongest answers connect the two.

**Golden rule: the estimate drives the design** — every box exists because a *number* demanded it.

1. **Scope** — functional + non-functional. Non-functional here = *scale, latency, availability, consistency*.
2. **Estimate** — QPS (read vs write), storage, key space. These numbers justify every later choice.
3. **API + data model** — public endpoints, then schema + DB choice (from the access pattern).
4. **Architecture** — draw the boxes (client → LB → app → cache → DB → queues); trace a read and a write path.
5. **Deep dive** — the 1–2 hard parts unique to the problem. Where the round is won.
6. **Scale & tradeoffs** — bottlenecks, sharding, replication, cache, SPOFs, consistency; end with "what's next".

> **Connect the rounds:** the LLD ↔ HLD mapping (interfaces → components) is the highest-signal thing
> you can show — e.g. an `save_if_absent` repository method *is* a DB unique constraint at scale.

**HLD references (reusable across all problems) — 3 tiers, use in this order:**
- `HLD-revision.md` — **flow**: the 9-step spine + reasoning pattern + one-page checklist (revise ASAP before an interview).
- `HLD-method-bank.md` — **menu**: per-phase superset of every method/strategy (scaling, caching, reliability…). Scan a phase, pick only what the problem justifies.
- `HLD-reference.md` — **depth**: longer explanation of each strategy (what → why → how → tradeoff → failure), ≈ a spoken interview answer each. The permanent reference; grow it as new methods appear.
- `01-url-shortener/hld.md` — a fully worked HLD example.

---

## SOLID — the 5 rules good OO code obeys (define each on first use)

- **S**ingle Responsibility — a class has one reason to change. (Don't mix URL-encoding with DB storage.)
- **O**pen/Closed — open to extension, closed to modification. (Add a new encoding strategy without editing existing code.)
- **L**iskov Substitution — a subclass must work anywhere its parent is expected.
- **I**nterface Segregation — many small interfaces beat one fat one.
- **D**ependency Inversion — depend on abstractions (interfaces), not concrete classes. (Service talks to `Repository` interface, not `MySQLRepository`.)

## Patterns we'll meet (introduced just-in-time, never dumped)

Strategy, Factory, Singleton, Observer, Builder, Repository. Each gets explained the first
time a problem actually needs it — not before.

**Reference:** `LLD-patterns.md` — the glossary (patterns + SOLID + YAGNI + concurrency/TOCTOU),
each entry grounded in the solved problems. `LLD-HLD-process.md` — the side-by-side solve steps.
`LLD-entity-playbook.md` — the checklists for Step 1 (which clarifying questions actually change the
design) and Step 2 (nouns→classes): find the orchestrator, scan NFRs for Strategy words, decide
data-vs-behavior.
**`python-classes-cheatsheet.md`** — 🐍 plain class vs `@dataclass` vs `frozen=True`, with real
runnable outputs: printing, equality, dict keys, why frozen unlocks hashing, the mutable-default trap,
a decision tree, and what every class in all 11 problems used and why.
**`LLD-pain-to-pattern.md`** — ⭐ read this when a pattern feels arbitrary. For all 7 problems: the
naive code everyone writes first, exactly where it hurts, and the pattern that fixes it. Patterns are
answers to pain, not vocabulary to memorise.

---

## The plan (agreed 2026-08-29)

```
1. Finish the last 3 LLD          -> DONE. 11/11.
2. MOCK INTERVIEWS (start early!) -> 45 min, no hints, think out loud   <-- YOU ARE HERE
3. HLD track                      -> DONE. 10 rounds in interview-mode/hld/
4. Interleave maintenance         -> 1 cold drill + 1 mock every 2-3 sessions
```

**Step 2 is the only thing left, and it has been the only thing left for a while.** Steps 1 and 3
both got finished ahead of it. The content is not the bottleneck any more — the app can run a full
mock end to end (`mobile/`, Mock tab). See [`NEXT-SESSION.md`](NEXT-SESSION.md) for the small
loose ends.

> **Why mocks come before the HLD track:** everything so far has been unlimited-time, with hints, and
> corrected step by step. A real round is 45 minutes, no hints, thinking out loud, with the
> interviewer interrupting — and *you* deciding what to skip. That skill is completely untested.
> Two mocks early will show what's actually weak, so the rest of the practice can target it.

---

## The two other folders

| Folder | What it is |
|---|---|
| [`interview-mode/`](interview-mode/) | The 10 HLD rounds, written prompt-first for *practice* rather than as worked solutions. [`FORMAT.md`](interview-mode/FORMAT.md) is the parser contract; [`HLD-BASICS.md`](interview-mode/HLD-BASICS.md) is the beginner on-ramp; [`INDEX.md`](interview-mode/INDEX.md) is the manifest and suggested order. |
| [`mobile/`](mobile/) | The study app — all of the above on your phone, offline. Home is an LLD/HLD track chooser; **Mock** runs 21 timed rounds with self-scored checkpoints; Revise is Leitner flashcards; Search is full-text. `python serve.py --port 8010` (**not 8000** — a stale service worker is cached against that origin). |

---

## Problems

Each folder:
- `problem.md` — clarifying questions + requirements + per-step 📝 review notes
- `solution.py` — runnable, with "HINT (to rebuild)" blocks
- **`explained.md`** — the same problem walked through in **Hinglish**: what the naive code is,
  exactly where it hurts, and why each decision was made. Read this one when a pattern isn't clicking.
- **`diagrams.md`** — 📊 **UML class diagram + state diagrams + flow diagrams** (mermaid, renders in
  the IDE). Many LLD interviews ask you to *draw* the class diagram — this is what that looks like.
  Also has the ASCII visuals for the things that are hard to picture (seat lifecycle, dict+DLL, the
  fit-rule table, elevator states).
- `hld.md` — the HLD companion. **All 11 problems now have one**, so each problem can be worked
  as an LLD round, an HLD round, or both back to back.

### ✅ Done

| # | Problem | New muscle it drilled |
|---|---|---|
| 1 | `01-url-shortener/` | Strategy · Repository · DI · **atomic claim** (`save_if_absent`) · TOCTOU |
| 2 | `02-parking-lot/` | **enum + rule-map** (data-driven rules) · two Strategies · Builder · find→claim race |
| 3 | `03-elevator-system/` | **State pattern** · discrete `step()` tick simulation |
| 4 | `04-rate-limiter/` | 3 swappable algorithms · **ISP** (narrow store per algorithm) · Redis/Lua atomicity |
| 5 | `05-chess/` | **polymorphic behaviour** via injected strategy · simulate-and-undo · rule engines |
| 6 | `06-splitwise/` | **graph/ledger modelling** · derive-don't-store (killed the race by *modelling*, no lock) · money correctness (`Decimal`, paisa redistribution) |
| 7 | `07-notification-system/` | **Observer / pub-sub** · **bulkhead** (per-channel try/except) · channel as *both* enum and Strategy |
| 8 | `08-lru-cache/` | **data-structure design** (dict→Node + DLL, O(1) both ops) · LFU exposed a **leaky abstraction** |
| 9 | `09-movie-booking/` | **hold-with-expiry** under contention · Seat vs ShowSeat · per-show lock · lazy expiry + sweeper |
| 10 | `10-text-editor/` | **Command + Memento** · action-as-object · two-stack undo/redo · redo-clearing rule |
| 11 | `11-food-delivery/` | 🎓 **CAPSTONE** — 4 patterns at once: Strategy ×2 + Observer + enum/transition-table, kept untangled |
| 12 | `12-thread-pool/` | a concurrency **primitive**, not just locking — bounded queue, graceful shutdown, exceptions that surface without killing a worker |
| 13 | `13-discount-engine/` | **Chain of Responsibility** — ordered, halt-able rule pipeline; order-of-application changes the total |
| 14 | `14-logging-framework/` | **Decorator** (composable handler wrappers) + **Singleton** (named honestly, cost to testability included) |
| 15 | `15-expression-evaluator/` | **Interpreter + Composite** — first *recursive structure* problem; tokenise → parse → evaluate |
| 16 | `16-connection-pool/` | **resource lifecycle** — borrow/return, leak reclamation, health checks, the Nth check-then-act race |

### ✅ LLD track COMPLETE — 16/16

**What's next:** mock interviews (see the plan at the top). The HLD track is already done.

**Lower value now (largely redundant):** Vending Machine & ATM & Traffic Signal (State again — done),
Snake&Ladder / Tic-Tac-Toe (simpler than Chess), Hotel booking (≈ movie booking).

**All originally-unmet patterns now covered:** Chain of Responsibility (13) · Decorator (14) · Singleton (14) ·
Interpreter + Composite (15).

> Problems 12–16 do not carry `📝 Review note` blocks — that shape records real coaching on work
> actually done, and these were added for pattern coverage rather than worked interviewer-led. They
> carry forward-looking `📝 Trap` lines instead, and an italic line under the h1 says so. Each still
> needs `diagrams.md`, `explained.md` and `hld.md` — reasonable to leave until actually worked through.

---

## HLD problems (separate round — different roadmap)

HLD is its own interview round with its own machinery. These are ranked by **what new method
they add to `HLD-method-bank.md`**, not by fame.

### ✅ HLD done (as companions to the LLD problems)

| Problem | Machinery it taught |
|---|---|
| URL shortener | read-heavy design · cache-aside · KGS/ID generation at scale · 301 vs 302 · shard by key |
| Parking platform | **geospatial** (geohash/bbox+haversine) · **consistency split** (AP search / CP reserve) · **outbox** for dual-write drift · TTL + reaper |
| Elevator fleet | **write-heavy ingest** (1M/s) · Kafka → **time-series DB** · **edge vs cloud** boundary |
| Rate limiter | shared Redis as global arbiter · **Lua atomicity** · **fail-open vs fail-closed** · two-tier local+shared cache |
| Chess multiplayer | **WebSocket push** vs REST · server-authoritative validation (anti-cheat) · matchmaking race |
| Splitwise | **derive → materialize reversal** (the elegant LLD choice is O(history) in prod) · ACID because money · **fail-CLOSED** (opposite of rate limiter) |
| Notification fan-out | **amplification** (1 event × N recipients × M channels) · per-channel topics = bulkhead in infra · outbox · dedup keys · priority lanes |
| Text editor | **collaborative editing** — OT vs CRDT · per-user undo in a shared doc · op log + snapshots · presence as deliberately-not-persisted |
| Food delivery | matching over a **moving** fleet · write-heavy geo index · batched vs greedy dispatch · surge pinned at order time |
| Movie booking | **waiting room / virtual queue** · where the atomic claim lives · read/write split · hold expiry at scale |
| Distributed cache | **consistent hashing** (why `hash%N` empties the whole cache) · stampede/avalanche/penetration · L1 local + L2 shared |

### ✅ HLD standalone rounds — all 15 written

These live in [`interview-mode/hld/`](interview-mode/hld/) and are **prompt-first**, not worked
solutions: the prompt, clarifying questions with the interviewer's answers, per-step checkpoints,
traps, quotable follow-ups, a rubric, and the reference answer revealed **last**. They are what the
app's Mock tab runs. Suggested order is in [`interview-mode/INDEX.md`](interview-mode/INDEX.md).

| # | Round | Machinery it forces |
|---|---|---|
| 01 | **News feed** (Twitter/Instagram) | **fan-out on write vs read** · the **celebrity/hot-key** problem · feed ranking + pagination. *The* most-asked HLD question. |
| 02 | **Chat / WhatsApp** | **presence** · delivery & read receipts · **message ordering** (per-conversation sequence numbers) · offline queue |
| 03 | **Dropbox / Google Drive** | **file chunking** · **dedup by content hash** · sync protocol · **conflict resolution** |
| 04 | **YouTube / Netflix** | **transcoding pipeline** (async workers) · **CDN** strategy · client-side adaptive bitrate |
| 05 | **Payment / wallet** | **double-entry ledger** · **exactly-once** · **idempotency keys** · **saga** for distributed txns |
| 06 | **Typeahead / autocomplete** | in-memory **trie** + prefix sharding · precomputed top-k · aggressive edge caching |
| 07 | **Web crawler** | distributed **frontier queue** · politeness scheduling · URL dedup at scale (**Bloom filters**, and which way the false positive hurts) |
| 08 | **Ticketmaster** | inventory locking under extreme contention · **waiting-room queue** for fairness · atomic claim |
| 09 | **Distributed job scheduler** | **leader election** + leases · at-least-once execution · cron at scale · retries/DLQ |
| 10 | **Leaderboard / analytics** | Redis **sorted sets** · **approximate counting** (HyperLogLog, Count-Min Sketch) |
| 11 | **Search & ranking** (Elasticsearch) | **inverted index** vs the typeahead trie · scatter-gather across shards · deep-pagination trap |
| 12 | **Ad serving / RTB** | a **hard real-time latency budget** (the only round with one) · second-price auction · budget pacing as deliberate fail-open |
| 13 | **Data pipeline / warehouse** | batch vs stream · **Lambda vs Kappa** · watermarks + event-time vs processing-time |
| 14 | **Recommendation serving** | the one **ML-infra** round — two-stage funnel, ANN/embeddings (same machinery as a RAG vector store), training/serving skew |
| 15 | **Distributed coordination** (ZooKeeper/etcd) | **Raft/quorum** in plain terms · the **fencing token** · why job-scheduler's leader election works at all |

**Threads that repeat across them** (worth knowing as threads, not as ten separate facts):
at-least-once + dedup keys · derive-vs-materialise · TTL/lease self-healing · fail-open vs
fail-closed · push atomicity into the shared store.

> **Pairing tip:** several LLD problems have a natural HLD partner — do them together to practise the
> LLD↔HLD mapping: *Notification system* (LLD Observer) ↔ *fan-out at scale*; *Movie booking* (LLD
> hold-with-expiry) ↔ *Ticketmaster*; *LRU Cache* (LLD) ↔ *distributed cache*.
