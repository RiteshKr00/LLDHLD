"""
LRU Cache — LLD solution (built step by step).

The whole design collapses to ONE requirement: O(1) for BOTH get and put.
    dict alone -> O(1) lookup, but no order
    DLL alone  -> O(1) unlink, but O(n) to FIND the node
    together   -> dict maps key -> NODE, so we find it in O(1) and unlink in O(1)

Order convention:
    HEAD = most recently used        TAIL = least recently used (evict here)
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
import threading


# ---------------------------------------------------------------------------
# Step 4a: Node + DoublyLinkedList   <-- YOUR TURN
#
# HINT — Node:
#   key, value, prev, next.
#   ** Store the KEY inside the node. On eviction you get the tail NODE and must
#      delete its entry from the dict — without node.key you can't, and the dict
#      leaks forever.
#
# HINT — DoublyLinkedList, using SENTINELS:
#   Create two dummy nodes in __init__ and wire them together:
#       self.head = Node(None, None)      # dummy, never holds data
#       self.tail = Node(None, None)      # dummy
#       self.head.next = self.tail
#       self.tail.prev = self.head
#   Now the list is NEVER empty, so you never write `if node is None` while doing
#   pointer surgery. Real nodes always live BETWEEN head and tail:
#       head <-> [real] <-> [real] <-> tail
#
#   add_to_front(node):   insert it just AFTER self.head
#       node.prev = self.head
#       node.next = self.head.next
#       self.head.next.prev = node        # old first node points back to us
#       self.head.next = node
#       (order matters: fix the neighbours BEFORE overwriting head.next)
#
#   remove(node):         unlink it — this is the O(1) that DLL buys us
#       node.prev.next = node.next
#       node.next.prev = node.prev
#
#   remove_last():        the real node just BEFORE self.tail
#       if self.tail.prev is self.head: return None    # empty
#       node = self.tail.prev; self.remove(node); return node
# ---------------------------------------------------------------------------


class Node:
    """One entry in the cache.

    Stores its own KEY on purpose: eviction hands us the tail NODE, and we then
    have to delete the matching dict entry. Without node.key that's impossible and
    the dict grows forever while the list shrinks.
    """

    def __init__(self, key: Any = None, value: Any = None):
        self.key = key
        self.value = value
        self.prev: Optional["Node"] = None
        self.next: Optional["Node"] = None
        self.freq = 0          # used only by LFUPolicy; ignored by LRU/FIFO


class DoublyLinkedList:
    """Order keeper. HEAD side = most recently used, TAIL side = least.

    Uses SENTINEL dummy nodes at both ends, so the list is never truly empty and
    every real node always has a prev AND a next. That removes every
    `if node is None` check from the pointer surgery below.

        head <-> [real] <-> [real] <-> tail
         ^dummy                        ^dummy
    """

    def __init__(self):
        self.head = Node()          # dummy — never holds data
        self.tail = Node()          # dummy
        self.head.next = self.tail
        self.tail.prev = self.head

    def add_to_front(self, node: Node) -> None:
        """Insert right after head = mark as most recently used."""
        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node   # fix the OLD first node first...
        self.head.next = node        # ...only then overwrite head.next
        # (reverse that order and you lose the reference to the old first node)

    def remove(self, node: Node) -> None:
        """Unlink in O(1) — this is the whole reason we use a DLL.
        node.prev is what makes it O(1); a singly linked list would need an O(n)
        walk from the head just to find the previous node."""
        node.prev.next = node.next
        node.next.prev = node.prev
        node.prev = node.next = None      # help GC, and make misuse fail loudly

    def remove_last(self) -> Optional[Node]:
        """Drop and return the least-recently-used real node (just before tail)."""
        if self.tail.prev is self.head:   # only sentinels left -> empty
            return None
        node = self.tail.prev
        self.remove(node)
        return node

    def move_to_front(self, node: Node) -> None:
        self.remove(node)
        self.add_to_front(node)

    def is_empty(self) -> bool:
        return self.head.next is self.tail      # only sentinels left

    def keys(self) -> list:
        out, n = [], self.head.next
        while n is not self.tail:
            out.append(n.key)
            n = n.next
        return out


# ---------------------------------------------------------------------------
# Step 4b: EvictionPolicy (Strategy ABC) + LRUPolicy
#
# HINT — the requirement said the policy must be pluggable. What actually varies
# between LRU / LFU / FIFO is only TWO decisions:
#     on_access(node)  -> what to do when a key is read/updated
#                         LRU: move it to the front.  FIFO: do nothing.
#     evict(dll, map)  -> which node to drop
#                         LRU & FIFO: the tail.  LFU: the lowest-frequency one.
# So the ABC has those two methods, and LRUPolicy implements them.
# ---------------------------------------------------------------------------


# === A LEAKY ABSTRACTION, AND HOW LFU EXPOSED IT ============================
#
# The first version of this interface was:
#       on_access(dll, node)      evict(dll)
# i.e. the CACHE owned one DoublyLinkedList and passed it in. That works fine for
# LRU and FIFO... and then LFU arrives and does NOT fit at all:
#
#   LFU must find "the least-frequently-used item" in O(1). One list can't do that.
#   It needs a dict of frequency -> its own list of nodes, plus a min_freq pointer.
#
# The interface had silently assumed "every policy orders nodes in exactly one
# linked list". That assumption was invisible while only LRU and FIFO existed.
#
# THE FIX: don't hand the policy a structure — let the policy OWN whatever
# structure it needs. The cache keeps only `dict[key -> Node]`; the policy answers
# one question: "who dies next?"
#
#       on_insert(node)   a new node entered the cache
#       on_access(node)   an existing node was read/updated
#       evict() -> Node   pick + unlink the victim
#
# Lesson: an abstraction is only proven once a SECOND, genuinely different
# implementation exists. Two similar ones (LRU/FIFO) can agree on a bad interface.
# ===========================================================================
class EvictionPolicy(ABC):
    """Strategy. Owns its own ordering structure — the cache only owns the dict."""

    @abstractmethod
    def on_insert(self, node: Node) -> None:
        """A brand-new node has entered the cache."""

    @abstractmethod
    def on_access(self, node: Node) -> None:
        """An existing node was read or updated."""

    @abstractmethod
    def evict(self) -> Optional[Node]:
        """Pick + unlink the victim. Caller deletes it from the dict."""

    def eviction_order(self) -> list:
        """Debug helper: keys, next-to-be-evicted FIRST."""
        return []


class LRUPolicy(EvictionPolicy):
    """Least Recently USED — touching a key makes it the newest."""

    def __init__(self):
        self._dll = DoublyLinkedList()

    def on_insert(self, node: Node) -> None:
        self._dll.add_to_front(node)

    def on_access(self, node: Node) -> None:
        self._dll.move_to_front(node)          # touched -> most recent

    def evict(self) -> Optional[Node]:
        return self._dll.remove_last()         # tail -> least recently used

    def eviction_order(self) -> list:
        return list(reversed(self._dll.keys()))


class FIFOPolicy(EvictionPolicy):
    """First In First Out — insertion order is final; reads change nothing.
    Note how tiny the difference from LRU is: on_access does NOTHING."""

    def __init__(self):
        self._dll = DoublyLinkedList()

    def on_insert(self, node: Node) -> None:
        self._dll.add_to_front(node)

    def on_access(self, node: Node) -> None:
        pass                                   # reading does not promote

    def evict(self) -> Optional[Node]:
        return self._dll.remove_last()         # tail -> oldest inserted

    def eviction_order(self) -> list:
        return list(reversed(self._dll.keys()))


class LFUPolicy(EvictionPolicy):
    """Least Frequently USED — evict whatever has been touched fewest times.

    The O(1) trick: instead of one list, keep ONE LIST PER FREQUENCY, plus a
    `min_freq` pointer so "who has the lowest count" is answered without searching.

        freq 1: [ D ] <-> [ C ]        <- min_freq = 1, evict from this list's tail
        freq 2: [ A ]
        freq 5: [ B ]

    Ties inside a frequency break by LRU (we evict that list's tail), which is the
    standard behaviour — otherwise all equally-cold items would be indistinguishable.
    """

    def __init__(self):
        self._lists: dict[int, DoublyLinkedList] = {}   # freq -> nodes with that freq
        self._min_freq = 0

    def on_insert(self, node: Node) -> None:
        node.freq = 1
        self._lists.setdefault(1, DoublyLinkedList()).add_to_front(node)
        self._min_freq = 1              # a brand-new item is always the least-used

    def on_access(self, node: Node) -> None:
        old = node.freq
        self._lists[old].remove(node)

        # If we just emptied the minimum bucket, the new minimum is old+1 —
        # because the node we're moving lands exactly there.
        if self._min_freq == old and self._lists[old].is_empty():
            self._min_freq = old + 1

        node.freq = old + 1
        self._lists.setdefault(node.freq, DoublyLinkedList()).add_to_front(node)

    def evict(self) -> Optional[Node]:
        bucket = self._lists.get(self._min_freq)
        if bucket is None or bucket.is_empty():
            return None
        return bucket.remove_last()     # coldest bucket, and LRU within it

    def eviction_order(self) -> list:
        out = []
        for freq in sorted(self._lists):
            out.extend(f"{k}(f{freq})" for k in reversed(self._lists[freq].keys()))
        return out


# ---------------------------------------------------------------------------
# Step 4c: LRUCache (orchestrator) + demo
#
# HINT — get(key):
#   miss -> misses += 1, return None
#   hit  -> policy.on_access(node); hits += 1; return node.value   (the VALUE!)
#
# HINT — put(key, value):   ORDER OF CHECKS MATTERS
#   1. key already present? -> update value, policy.on_access(node), RETURN
#                              (an update doesn't grow the cache -> must not evict)
#   2. at capacity?         -> EVICT FIRST (at capacity=1, insert-then-evict would
#                              remove the node you just inserted)
#                              lru = dll.remove_last(); del map[lru.key]   <- BOTH
#   3. create node, add_to_front, map[key] = node
#
#   ** Wrap BOTH get and put in `with self._lock:` — remember get MUTATES order,
#      so it is not a safe read-only path.
# ---------------------------------------------------------------------------
class LRUCache:
    def __init__(self, capacity: int, policy: Optional[EvictionPolicy] = None):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.policy = policy or LRUPolicy()      # DI, with a sensible default
        self._map: dict[Any, Node] = {}          # key -> NODE. The cache owns ONLY this;
                                                 # all ordering lives inside the policy.
        self._lock = threading.Lock()            # get mutates too -> reads need it
        self._hits = 0
        self._misses = 0

    def get(self, key: Any) -> Optional[Any]:
        with self._lock:
            node = self._map.get(key)
            if node is None:
                self._misses += 1
                return None
            self.policy.on_access(node)          # <- the "read" that writes
            self._hits += 1
            return node.value                    # the VALUE, not the node

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            # 1. UPDATE path — the cache is not growing, so DO NOT evict here.
            existing = self._map.get(key)
            if existing is not None:
                existing.value = value
                self.policy.on_access(existing)
                return

            # 2. EVICT BEFORE INSERT. At capacity=1 the reverse order would add the
            #    new node and then evict the tail — the same node.
            if len(self._map) >= self.capacity:
                victim = self.policy.evict()
                if victim is not None:
                    del self._map[victim.key]    # BOTH structures, or the dict leaks
                                                 # ^ this is why Node stores its key

            # 3. INSERT
            node = Node(key, value)
            self.policy.on_insert(node)
            self._map[key] = node

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total else 0.0,
                "size": len(self._map),
            }

    def eviction_order(self) -> list:
        """Debug/demo helper: keys in eviction order, next victim FIRST."""
        with self._lock:
            return self.policy.eviction_order()

    def keys(self) -> list:
        with self._lock:
            return list(self._map.keys())


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== LRU, capacity 3 ===  (lists show NEXT-VICTIM first)")
    c = LRUCache(3)
    for k, v in [("a", 1), ("b", 2), ("c", 3)]:
        c.put(k, v)
    print("put a,b,c        :", c.eviction_order())

    print("get('a')         :", c.get("a"), "->", c.eviction_order(), " a is now safest")
    c.put("d", 4)                       # full -> evicts LRU, which is now 'b'
    print("put d            :", c.eviction_order(), " b evicted")
    print("get('b')         :", c.get("b"), " <- gone, correctly a miss")

    print("\n--- update must NOT evict ---")
    before = c.eviction_order()
    c.put("a", 99)
    print(f"put a=99         : {before} -> {c.eviction_order()}  (same 3 keys)")
    print("get('a')         :", c.get("a"))

    print("\n--- the capacity=1 trap ---")
    one = LRUCache(1)
    one.put("x", 1)
    one.put("y", 2)                     # must evict x, NOT the just-inserted y
    print("cap=1, x then y  :", one.keys(), "| get('y') =", one.get("y"))

    print("\n--- SAME cache, three different policies ---")
    for name, pol in [("LRU ", LRUPolicy()), ("FIFO", FIFOPolicy()), ("LFU ", LFUPolicy())]:
        cache = LRUCache(3, pol)
        for k, v in [("a", 1), ("b", 2), ("c", 3)]:
            cache.put(k, v)
        cache.get("a"); cache.get("a"); cache.get("a")   # 'a' read 3 times
        cache.get("b")                                    # 'b' read once
        cache.put("d", 4)                                 # full -> something dies
        gone = [k for k in ("a", "b", "c") if k not in cache.keys()]
        print(f"  {name} -> evicted {gone}   remaining {sorted(cache.keys())}")

    print("""
   LRU : 'c' died  - least recently TOUCHED (a and b were read after it)
   FIFO: 'a' died  - oldest INSERTED; reads changed nothing
   LFU : 'c' died  - fewest READS (a=4, b=2, c=1)
   Same LRUCache class, zero edits. Only the injected policy changed.""")

    print("\n--- LFU internals: buckets by frequency ---")
    lfu = LRUCache(4, LFUPolicy())
    for k in ("p", "q", "r"):
        lfu.put(k, 1)
    for _ in range(4): lfu.get("p")
    for _ in range(2): lfu.get("q")
    print("  eviction order:", lfu.eviction_order(), " <- lowest freq dies first")

    print("\nstats:", c.stats())
