# Problem 8: LRU Cache (LLD)

## The prompt (as an interviewer would give it)

> "Design an LRU cache. It holds a fixed number of items; when it's full, the least
> recently used item gets evicted."

> ⚠️ **This problem is a different animal.** Problems 1–7 were about *patterns* (Strategy, State,
> Observer). This one is about **data structures** — the whole design collapses into one question:
> *which structures, combined how, give you O(1) for both operations?*

---

## Clarifying questions to ask
_Fewer than usual, and mostly about scope — the core is fixed._

1. **Eviction policy** — LRU only, or should it be **pluggable** (LFU, FIFO, random) later? *(Strategy signal.)*
2. **Capacity** — a fixed **item count**, or memory-size based (evict until under X MB)?
3. **TTL** — do entries also expire by time, or only by eviction?
4. **Thread-safety** — will many threads hit this cache at once?
5. **On a miss** — return `None`, raise, or **compute the value** (read-through cache)?
6. **Stats** — do we need hit/miss counts?

## Clarifications (locked scope from Q&A)
1. **Eviction policy:** LRU now, but **pluggable** later (LFU / FIFO). → Strategy signal.
2. **Capacity:** fixed **item count**. Memory-size-based eviction out of scope.
3. **TTL:** out of scope — items leave only by eviction.
4. **Thread-safety:** yes, many threads hit it concurrently.
5. **On miss:** return `None`. Read-through (cache computes the value itself) out of scope.
6. **Stats:** track hit / miss counts.
7. **HARD REQUIREMENT: `get` and `put` must both be O(1).** ← this is the actual problem.

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- **`put(key, value)`** — store an item
- **`get(key)`** — read an item; miss → `None`.
  ⚠️ **`get` is NOT read-only** — it also marks the key *most recently used*, i.e. it mutates order
- **Evict** the least-recently-used item when full
- **Track hit / miss** counts

### Non-functional (constraints — the "-ilities")
- **O(1) for BOTH `get` and `put`** ← the requirement that dictates the entire design
- **Extensible** — eviction policy pluggable (LRU now, LFU/FIFO later)
- **Thread-safe** — concurrent access; e.g. one thread evicting while another inserts
- **Testable**

### Explicitly out of scope (say this out loud — senior move)
- TTL / time-based expiry · memory-size-based capacity · read-through (cache computing values itself)
- Distributed / multi-node caching · persistence

> 📝 **Review note (Step 1):** `put` + eviction were there, and both real NFRs were caught — **swappable policy** (Strategy signal) and **O(1)**, with thread-safety described concretely (one thread removing while another adds). Fixes: (1) **`get` was missing** — the cache's primary operation, and the one carrying the surprise: **`get` mutates state** (it promotes the key to most-recently-used). That's exactly why reads also need the lock, and why `get` can't be treated as a cheap read-only path; (2) **out-of-scope left empty** — the habit slipped after 3 strong problems in a row; (3) hit/miss stats missing.

---

## Step 2 — Data structures  ✅ LOCKED
_The real question: what gives O(1) for BOTH get and put?_

**Neither structure alone works — they compensate for each other:**

| | Lookup by key | Delete from middle | Keeps order |
|---|---|---|---|
| `dict` alone | ✅ O(1) | ✅ O(1) | ❌ no order at all |
| DLL alone | ❌ **O(n)** — must walk to find it | ✅ O(1) *(if you already hold the node)* | ✅ |
| **Both together** | ✅ O(1) | ✅ O(1) | ✅ |

**The trick: the dict stores the NODE, not the value.**
```python
self._map: dict[Key, Node] = {}     # key -> the node living in the DLL
```
dict finds the node in O(1) → DLL unlinks it in O(1) via `prev`/`next`.

**Why DOUBLY linked, not singly:** to unlink `X` you must join its neighbours
(`A.next = B`, `B.prev = A`), so you need X's **previous** node. Singly linked → walk from the head
→ O(n). The `prev` pointer is precisely what buys O(1) removal.

**Order convention:**
```
 HEAD (most recent)                                  TAIL (least recent)
   ↓                                                        ↓
 [ K4 ] ⇄ [ K1 ] ⇄ [ K7 ] ⇄ [ K3 ] ⇄ [ K9 ]  <- evict from here
```
- `get`/`put` → move that node to the **head**
- full → drop the **tail** node (and delete its key from the dict too — both structures stay in sync)

**The pieces:**
1. **`Node`** — `key, value, prev, next`. *(Why store the **key** inside the node? On eviction you have
   the tail node and must delete it from the dict — you need its key to do that. Forgetting this is the
   classic bug: the DLL shrinks but the dict keeps growing.)*
2. **`DoublyLinkedList`** — `add_to_front(node)`, `remove(node)`, `remove_last() -> node`.
   Use **sentinel head/tail dummy nodes** so the list is never truly empty → no `if node is None`
   checks scattered through the pointer surgery.
3. **`dict[Key, Node]`** — the O(1) index into the list.
4. **`EvictionPolicy` (Strategy)** — LRU today, LFU/FIFO later.
5. **`LRUCache`** — orchestrator: `get`, `put`, capacity, lock, hit/miss stats.

> 📝 **Review note (Step 2):** the core insight was right and stated compactly — **dict + DLL compensating for each other**. Filled in the three details that make it actually work: (a) the dict maps to the **node**, not the value — that's the bridge that makes O(1) removal possible; (b) it must be **doubly** linked, because unlinking needs the *previous* node and only `prev` gives that in O(1); (c) the node must carry its **key**, because eviction starts from the tail node and has to delete the matching dict entry — otherwise the dict leaks forever. Plus sentinel head/tail nodes to kill the null-checks.

---

## Step 3 — APIs & the operation walkthrough
_Signatures, then trace exactly what happens on get / put / evict._

**Signatures:**
```python
class LRUCache:
    def __init__(self, capacity: int, policy: EvictionPolicy = None): ...
    def get(self, key) -> Optional[Any]        # the VALUE, not the node
    def put(self, key, value) -> None
    def stats(self) -> dict                    # {"hits": n, "misses": n, "hit_rate": %}

class DoublyLinkedList:
    def add_to_front(self, node: Node) -> None
    def remove(self, node: Node) -> None
    def remove_last(self) -> Optional[Node]    # returns the LRU node (caller needs node.key)
```

**A. `get(key)`**
```
1. key not in map?  -> misses += 1, return None
2. node = map[key]                       # O(1)
3. dll.remove(node); dll.add_to_front(node)   # promote to most-recently-used
4. hits += 1, return node.value          # the VALUE, not the node
```
`get` **writes** (step 3) — that's why reads need the lock too.

**B. `put(key, value)` — ORDER OF CHECKS MATTERS**
```
1. if key already in map:                # UPDATE path — cache is NOT growing
       node = map[key]; node.value = value
       dll.remove(node); dll.add_to_front(node)
       return                            # <- must return; evicting here would be WRONG
2. if len(map) >= capacity:              # EVICT BEFORE inserting
       lru = dll.remove_last()
       del map[lru.key]                  # <- BOTH structures, or the dict leaks
3. node = Node(key, value)
   dll.add_to_front(node); map[key] = node
```

**Two ordering traps:**
- **Check "already exists" FIRST.** Updating an existing key doesn't grow the cache, so evicting
  would throw away a perfectly good entry for nothing.
- **Evict BEFORE inserting, not after.** With `capacity = 1`: insert-then-evict would add the new node
  at the head and then evict the tail — **which is the node you just inserted**. Cache stays empty forever.

**C. Eviction always touches BOTH structures**
```
lru = dll.remove_last()      # out of the list
del map[lru.key]             # out of the dict   <- this is why Node stores its key
```
Miss the second line and the DLL shrinks while the dict grows forever — a silent memory leak, and
`len(map)` stops matching reality so the capacity check breaks too.

> 📝 **Review note (Step 3):** `get` (return + promote) and `put` (evict-if-full, update-if-present) were both traced correctly — the promote-on-read insight in particular. Fixes: (1) `stats` was returning **internal structure** — it should return **hit/miss counts** (clarification #6 was about monitoring hit-rate, not introspection); (2) `get` returns the **value**, not the node — callers must never touch nodes, that's an internal detail; (3) two **ordering traps** made explicit: check *key-exists* before the capacity check (an update doesn't grow the cache, so evicting would discard a good entry), and **evict before insert** (at `capacity=1`, insert-then-evict removes the node you just added); (4) eviction must delete from **both** the DLL and the dict.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

**The honest answer: a cache is a *library*, not a service** — `get`/`put` are in-process calls, and
adding HTTP would defeat the point (a network hop costs more than the DB read you are avoiding).

If it *is* exposed as a service (i.e. you are building Redis):

| LLD method | HTTP |
|---|---|
| `get(key)` | `GET /cache/{key}` -> **200** value · **404** miss |
| `put(key, value)` | `PUT /cache/{key}` -> **204** |
| `stats()` | `GET /cache/stats` -> **200** `{hits, misses, hit_rate, size}` |

> Saying *"this should not be an HTTP API"* is itself the senior answer. The real deployment is
> **L1 in-process (this code) + L2 shared (Redis)**.

## Notes / decisions (log the "why" here)
- **dict → Node, not dict → value.** That indirection is the entire trick: dict finds the node in O(1), the DLL unlinks it in O(1). Store the value directly and you'd have to *search* the list to reorder it — O(n).
- **Doubly** linked, because unlinking needs `node.prev`. Singly linked → O(n) walk to find the predecessor.
- **Node carries its own `key`** — eviction starts from the tail *node* and must delete the matching dict entry. Without it the dict leaks and `len(map)` stops matching reality.
- **Sentinel head/tail dummies** — the list is never empty, so every real node always has both neighbours. Removes every null-check from the pointer surgery.
- **`get` is a WRITE.** It promotes the key, so reads take the lock too — there is no cheap read-only path in an LRU cache.
- **Policy as Strategy:** LRU vs FIFO differ in exactly two methods (`on_access`, `evict`); FIFO's `on_access` is literally `pass`. Swapping them touches no cache code.
- **`remove()` nulls `prev`/`next`** — helps GC, and makes an accidental double-remove crash loudly instead of silently corrupting the list.
- **LFU exposed a leaky abstraction (the best lesson here).** The first `EvictionPolicy` was `on_access(dll, node)` / `evict(dll)` — the *cache* owned one DLL and passed it in. LRU ✅ FIFO ✅ … then LFU didn't fit at all: finding "least frequently used" in O(1) needs **one list per frequency** plus a `min_freq` pointer, not a single list. The interface had silently assumed *"every policy orders nodes in exactly one linked list"* — an assumption invisible while only two **similar** policies existed. **Fix:** don't hand the policy a structure; let the policy **own** whatever structure it needs (`on_insert` / `on_access` / `evict`), and the cache keeps only `dict[key → Node]`. **An abstraction isn't proven until a second, genuinely different implementation exists.**
- **LFU's O(1) trick:** `dict[freq → DLL]` + `min_freq`. On access, move the node from bucket `f` to `f+1`; if bucket `f` is now empty and `f == min_freq`, then `min_freq = f+1`. Evict from `min_freq`'s **tail** — so ties inside a frequency break by LRU.

> 📝 **Review note (Step 4 build):** the two ordering traps from Step 3 both proved out in the demo — updating an existing key does **not** evict (same 3 keys, just reordered), and at `capacity=1` the evict-before-insert order keeps the newly inserted node instead of dropping it. Policy swap verified live: with LRU, `get('a')` saved `a` so `b` was evicted; with FIFO the same read promoted nothing and `a` was evicted — **one class changed, zero edits to `LRUCache`**. Concurrency: 8 threads × 2000 mixed ops → no errors, capacity respected, and **dict and DLL stayed exactly in sync** (the assertion that catches both a missing lock and a half-done eviction).
