"""
Connection Pool - LLD solution (Problem 16).

THE PATTERN: Object Pool + resource lifecycle.
A bounded set of expensive resources that callers BORROW and RETURN - and the
borrower is not trustworthy. Everything hard here follows from that one sentence:

    the pool is bounded     -> what does acquire() do when it is empty?  (exhaustion)
    the borrower may vanish -> a connection never returned drains it     (leak)
    the resource can die    -> an idle connection goes stale silently    (health)
    the borrower may lie    -> double-release / releasing a foreign conn (ownership)
    many borrowers          -> "is one free?" + "take it" must be atomic (the race)

DATA vs BEHAVIOR, applied twice in one file:
  * ConnectionFactory -> BEHAVIOUR -> ABC + @abstractmethod. Opening/validating a
    Postgres conn vs a Redis conn is genuinely different CODE.
  * Exhaustion policy -> DATA -> one float, NOT a Strategy hierarchy: fail fast is
    timeout=0, blocking is timeout=2.0, growing is a bigger max_size. Contrast the
    thread pool (problem 12), where caller-runs vs discard-oldest really do run
    different code and Strategy earns its place. Do the two back to back.

NO REAL SOCKETS: FakeConnection carries an `is_alive` flag you flip by hand.
TIME uses time.monotonic(), never time.time() - an NTP or DST jump moves the wall
clock, and a timeout measured on it fires early or never at all.
"""

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Deque, Dict, List, Optional, Set
import itertools
import threading
import time


# HINT (to rebuild) - the exception family:
#   One base to catch the whole family, one subclass per failure MODE, because
#   error TYPES become HTTP status codes (exhausted -> 503 + Retry-After,
#   revoked -> 410, double/alien release -> 500 caller bug).
#   ** Never return None instead: a pool that returns None on exhaustion becomes
#      an AttributeError three stack frames from the real problem.

class PoolError(Exception):
    """Base for every pool failure."""

class PoolExhaustedError(PoolError):
    """Every connection is out and the wait ran out of time."""

class PoolClosedError(PoolError):
    """acquire() after close(), or close() while you were waiting."""

class DoubleReleaseError(PoolError):
    """Released a connection that is already sitting idle in the pool."""

class UnknownConnectionError(PoolError):
    """Released a connection this pool never issued."""

class ConnectionRevokedError(PoolError):
    """The leak reaper took it back before you returned it."""

class ConnectionDeadError(PoolError):
    """Used a connection whose backend has gone away."""

class ConnectionCreationError(PoolError):
    """The factory could not produce a connection."""


# HINT (to rebuild) - the pooled resource:
#   A stand-in for a real DB connection, deliberately fake so the file runs
#   anywhere: no sockets, no driver. Needs a stable id (the pool keys its books
#   on it), an is_alive flag you flip by hand to fake "the server hung up and
#   did not tell us", idle bookkeeping, and a use that refuses when dead.
#   ** NOT frozen - it mutates. The snapshots in this file are frozen instead.

@dataclass
class FakeConnection:
    conn_id: str
    is_alive: bool = True
    idle_since: float = field(default_factory=time.monotonic)
    use_count: int = 0

    def execute(self, sql: str) -> str:
        if not self.is_alive:
            raise ConnectionDeadError(f"{self.conn_id} is dead")
        return f"[{self.conn_id}] {sql} -> ok"

    def close(self) -> None:
        self.is_alive = False


# HINT (to rebuild) - the ONE polymorphic axis:
#   An ABC covering the whole lifecycle: open one, ask whether it is still alive,
#   close it for good. The pool knows nothing about what it pools, so Postgres ->
#   Redis is a new subclass and zero edits to ConnectionPool (Open/Closed + DI).
#   ** @abstractmethod on EVERY method. A missing one lets a half-implemented
#      subclass instantiate happily and blow up at 3am instead of at import.
#   ** Liveness is a QUESTION, so neither the probe nor the close may raise.

class ConnectionFactory(ABC):
    @abstractmethod
    def create(self) -> FakeConnection:
        """Open a new connection. Expensive - that is why a pool exists."""

    @abstractmethod
    def validate(self, conn: FakeConnection) -> bool:
        """Cheap liveness probe (`SELECT 1`). False if dead. MUST NEVER RAISE -
        the pool guards it anyway (_probe_ok), because this is the contract most
        likely to be broken by a factory written in a hurry."""

    @abstractmethod
    def destroy(self, conn: FakeConnection) -> None:
        """Close it for good. Must not raise either."""


# HINT (to rebuild):
#   The concrete factory, stdlib only. Counts created/validated/destroyed so the
#   demo can PROVE its claims with numbers instead of prose, and fakes the cost
#   of opening a real connection with a small sleep.

class FakeConnectionFactory(ConnectionFactory):
    def __init__(self, open_cost: float = 0.0) -> None:
        self.open_cost = open_cost
        self.created = 0
        self.validated = 0
        self.destroyed = 0
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def create(self) -> FakeConnection:
        if self.open_cost:
            time.sleep(self.open_cost)          # a real open is 50-200ms
        with self._lock:
            self.created += 1
            n = next(self._ids)
        return FakeConnection(conn_id=f"conn-{n}")

    def validate(self, conn: FakeConnection) -> bool:
        with self._lock:
            self.validated += 1
        return conn.is_alive

    def destroy(self, conn: FakeConnection) -> None:
        with self._lock:
            self.destroyed += 1
        conn.close()


# HINT (to rebuild) - what to do about a borrower that never gives it back:
#   Two policies. LOG is the safe default (HikariCP leakDetectionThreshold):
#   record who held what for how long, touch nothing. RECLAIM takes it back
#   (Commons-DBCP removeAbandoned) and the late release must then be refused.
#   ** Enum + two branches, not Strategy: they differ in bookkeeping, not shape.
#      Promote to Strategy the day a third policy needs real logic (YAGNI).

class LeakPolicy(Enum):
    LOG = "log"
    RECLAIM = "reclaim"


# HINT (to rebuild) - every knob in one FROZEN dataclass:
#   Beats an 8-argument __init__, and frozen means nobody mutates the contract at
#   runtime. Needs the idle floor, the hard ceiling, a default acquire timeout
#   (there is NO "wait forever"), the two staleness ages, the leak policy, and
#   where to probe - on borrow (safe, a round trip) or on return (weaker).
#   ** Validate in __post_init__: a config error must fail at construction, not
#      at 3am when the pool quietly has max_size=0.

@dataclass(frozen=True)
class PoolConfig:
    min_idle: int = 1
    max_size: int = 10
    acquire_timeout: float = 5.0
    max_idle_seconds: Optional[float] = 300.0
    leak_threshold: Optional[float] = 30.0
    leak_policy: LeakPolicy = LeakPolicy.LOG
    validate_on_borrow: bool = True
    validate_on_return: bool = False

    def __post_init__(self) -> None:
        if self.max_size < 1:
            raise ValueError("max_size must be >= 1")
        if self.min_idle < 0 or self.min_idle > self.max_size:
            raise ValueError("min_idle must be between 0 and max_size")
        if self.acquire_timeout < 0:
            raise ValueError("acquire_timeout must be >= 0 (0 means fail fast)")


# HINT (to rebuild) - the borrow record, the entity everyone forgets:
#   One per connection currently OUT, carrying who took it, when (monotonic),
#   and whether its leak has already been reported.
#   ** Without it the pool knows only HOW MANY are out. With it it knows WHO
#      holds WHAT SINCE WHEN - the prerequisite for leak detection, double
#      release and alien release alike. Age it against the monotonic clock.

@dataclass
class Lease:
    conn: FakeConnection
    borrower: str
    borrowed_at: float
    leak_reported: bool = False

    def age_seconds(self) -> float:
        return time.monotonic() - self.borrowed_at


# HINT (to rebuild) - two FROZEN snapshots:
#   PoolStats is what GET /admin/db-pool returns: the census (size/idle/in_use),
#   the queue depth, and the lifetime counters you page on.
#   ** `waiting` is the number that predicts an outage - waiting > 0 and rising
#      means the pool IS the bottleneck and your latency is queueing time.
#   SweepReport is what one maintenance pass did. Frozen because a snapshot you
#   can mutate after the fact is a lie.

@dataclass(frozen=True)
class PoolStats:
    size: int
    idle: int
    in_use: int
    waiting: int
    borrowed: int
    timeouts: int
    stale_discarded: int
    leaks_reclaimed: int


@dataclass(frozen=True)
class SweepReport:
    leaks_found: int = 0
    leaks_reclaimed: int = 0
    stale_evicted: int = 0
    refilled: int = 0


# HINT (to rebuild) - the context manager, Python's RAII:
#   __enter__ acquires and hands the connection over; __exit__ gives it back and
#   RETURNS FALSE. This - not discipline, not code review - is what actually
#   prevents leaks in production: the release runs even when the body raises.
#   ** TRAP: returning True from __exit__ SWALLOWS the body's exception. The
#      connection comes back, the pool looks healthy, the bug vanishes.

class PoolGuard:
    def __init__(self, pool: "ConnectionPool", timeout: Optional[float] = None) -> None:
        self._pool = pool
        self._timeout = timeout
        self._conn: Optional[FakeConnection] = None

    def __enter__(self) -> FakeConnection:
        self._conn = self._pool.acquire(self._timeout)
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                self._pool.release(conn)
            except PoolError:
                # Letting __exit__ raise its OWN error erases the body's just as
                # completely as returning True would (RECLAIM makes it reachable:
                # the reaper revokes the lease mid-body, release() then raises).
                # The body's exception outranks a failed hand-back, so swallow
                # ours only when there IS one to protect.
                if exc_type is None:
                    raise
        return False            # never swallow the body's exception


# ---------------------------------------------------------------------------
# ConnectionPool - the orchestrator
#
# HINT (to rebuild):
#   Four collections under ONE threading.Condition: the free ones, the leases for
#   the ones out on loan, everything the pool owns (that is what max_size counts),
#   and the ids it revoked - so a late release gets a SPECIFIC error.
#   acquire: reuse an idle one, else grow lazily, else WAIT until a deadline and
#   raise. release: prove ownership before touching anything. Plus a `with` form,
#   a maintenance sweep (reap leaks, evict stale, refill the floor), stats, close.
#   ** THE RACE: "is one free?" and "take it" must be ONE critical section, or two
#      callers see the same free connection and both take it.
#   ** The health probe may RAISE (`SELECT 1` on a closed socket does). Funnel
#      every probe through one non-throwing helper, or a connection ends up in no
#      collection at all while still counting against max_size.
# ---------------------------------------------------------------------------

class ConnectionPool:

    def __init__(self, factory: ConnectionFactory,
                 config: Optional[PoolConfig] = None) -> None:
        self.factory = factory
        self.config = config or PoolConfig()

        # ONE condition variable guards ALL the state below - not one lock per
        # field. The invariant that matters ("idle + in_use <= max_size") spans
        # them all, so they share a lock.
        self._cv = threading.Condition()
        self._idle: Deque[FakeConnection] = deque()
        self._in_use: Dict[str, Lease] = {}
        self._all: Dict[str, FakeConnection] = {}
        self._revoked: Set[str] = set()
        self._waiting = 0
        self._closed = False

        # The pool keeps its OWN counters - stats() must not depend on a
        # collaborator that only happens to count.
        self._borrowed = 0
        self._timeouts = 0
        self._stale_discarded = 0
        self._leaks_reclaimed = 0
        self.leak_log: List[str] = []
        # Nothing is opened here: the pool starts EMPTY and grows to demand.
        # Lazy = fast boot, one slow first request; eager prefill (HikariCP) =
        # slow boot, no cold-start spike.

    def acquire(self, timeout: Optional[float] = None) -> FakeConnection:
        """Borrow a connection; block up to `timeout`, then raise. timeout=0 is
        fail-fast, and there is deliberately no "wait forever" - a caller blocked
        with no deadline looks like a hang, and hangs do not page anyone.
        """
        if timeout is None:
            timeout = self.config.acquire_timeout
        if timeout < 0:
            raise ValueError("timeout must be >= 0")
        deadline = time.monotonic() + timeout

        # CHECK-THEN-ACT: "is one free?" and "take it" are ONE critical section.
        # Split them into two locked blocks and two callers both see the same free
        # connection and both take it.
        with self._cv:
            if self._closed:
                raise PoolClosedError("pool is closed")
            while True:
                conn = self._take_idle_locked()          # check ...
                if conn is not None:
                    return self._lease_locked(conn)      # ... and take, same lock
                if len(self._all) < self.config.max_size:
                    return self._lease_locked(self._create_locked())

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._timeouts += 1
                    raise PoolExhaustedError(
                        f"no connection within {timeout:.3f}s (max_size="
                        f"{self.config.max_size}, in_use={len(self._in_use)})")

                self._waiting += 1
                try:
                    self._cv.wait(remaining)             # RELEASES the lock
                finally:
                    self._waiting -= 1
                if self._closed:
                    raise PoolClosedError("pool closed while waiting")
                # then loop and RE-CHECK (`while`, never `if`): the lock was open
                # while we waited, so what woke us may already be gone.

    def release(self, conn: FakeConnection) -> None:
        """Give a connection back. Ownership is checked BEFORE anything else:
        silently accepting a stranger queues the same object in _idle twice and
        two callers get handed one connection.
        """
        with self._cv:
            lease = self._in_use.pop(conn.conn_id, None)
            if lease is None:
                if conn.conn_id in self._revoked:
                    self._revoked.discard(conn.conn_id)
                    raise ConnectionRevokedError(
                        f"{conn.conn_id} was reclaimed as a leak; take a fresh one")
                if conn.conn_id in self._all:
                    raise DoubleReleaseError(
                        f"{conn.conn_id} is already idle - releasing it again "
                        f"would queue the same object twice")
                raise UnknownConnectionError(
                    f"{conn.conn_id} was never issued by this pool")

            try:
                if self._closed:
                    self._destroy_locked(conn)      # shutting down: do not re-pool
                # _probe_ok, never factory.validate directly: the lease is already
                # popped, so a probe that raises loses the connection while it
                # still counts against max_size.
                elif self.config.validate_on_return and not self._probe_ok(conn):
                    self._stale_discarded += 1
                    self._destroy_locked(conn)
                else:
                    conn.idle_since = time.monotonic()
                    self._idle.append(conn)
            finally:
                # notify_all, not notify: after a destroy the woken waiter may find
                # nothing idle and only be able to CREATE. Every waiter has a
                # deadline, so a spurious wake costs one re-check.
                self._cv.notify_all()

    def connection(self, timeout: Optional[float] = None) -> PoolGuard:
        """`with pool.connection() as conn:` - the form you should actually use."""
        return PoolGuard(self, timeout)

    def sweep(self) -> SweepReport:
        """Reap leaks, evict stale idle conns, refill min_idle. A daemon thread
        runs this every few seconds in production; a plain method here so the demo
        is deterministic. Self-healing lease: state carries a deadline, a
        background pass takes back anything past it, nobody has to remember.
        """
        found = reclaimed = evicted = refilled = 0
        with self._cv:
            # 1. leaks - a borrow that has been out too long
            threshold = self.config.leak_threshold
            if threshold is not None:
                for conn_id, lease in list(self._in_use.items()):
                    if lease.age_seconds() < threshold:
                        continue
                    found += 1
                    if self.config.leak_policy is LeakPolicy.RECLAIM:
                        self._in_use.pop(conn_id, None)
                        self._revoked.add(conn_id)
                        # DESTROY, never re-pool: the leaker may still be mid-query,
                        # and re-issuing it recreates the two-owners bug.
                        self._destroy_locked(lease.conn)
                        self._leaks_reclaimed += 1
                        reclaimed += 1
                    elif not lease.leak_reported:
                        lease.leak_reported = True       # log once, not every sweep
                        self.leak_log.append(
                            f"LEAK {conn_id} held by {lease.borrower} for "
                            f"{lease.age_seconds():.2f}s")

            # 2. stale idle connections - the server may have hung up on them
            keep: Deque[FakeConnection] = deque()
            try:
                while self._idle:
                    conn = self._idle[0]                        # PEEK, do not pop
                    usable = self._usable_locked(conn, probe=True)   # ALWAYS probe
                    self._idle.popleft()                        # decided - now take it
                    if usable:
                        keep.append(conn)
                    else:
                        self._stale_discarded += 1
                        self._destroy_locked(conn)
                        evicted += 1
            finally:
                # CRASH-SAFE DRAIN, both halves needed: PEEK-THEN-POP above, and
                # this finally. Survivors sit in a LOCAL deque, so a raise partway
                # through would strand everything drained so far - and the pass
                # whose whole job is SELF-HEALING must not shrink the pool.
                keep.extend(self._idle)
                self._idle = keep

            # 3. refill to the min_idle floor
            while (len(self._idle) < self.config.min_idle
                   and len(self._all) < self.config.max_size
                   and not self._closed):
                fresh = self._create_locked()
                self._idle.append(fresh)
                refilled += 1

            self._cv.notify_all()
        return SweepReport(found, reclaimed, evicted, refilled)

    def stats(self) -> PoolStats:
        with self._cv:
            return PoolStats(
                size=len(self._all), idle=len(self._idle),
                in_use=len(self._in_use), waiting=self._waiting,
                borrowed=self._borrowed, timeouts=self._timeouts,
                stale_discarded=self._stale_discarded,
                leaks_reclaimed=self._leaks_reclaimed)

    def close(self) -> None:
        """Destroy idle connections now; in-flight ones die as they come back."""
        with self._cv:
            self._closed = True
            while self._idle:
                self._destroy_locked(self._idle.popleft())
            self._cv.notify_all()

    # -- internals: every one of these assumes the lock is HELD -------------

    def _take_idle_locked(self) -> Optional[FakeConnection]:
        """First USABLE idle connection, destroying stale ones on the way. FIFO
        rotates usage evenly, LIFO would keep the hot ones warm - name the choice.
        COST: a queue of corpses turns ONE acquire() into N probes under the lock.
        """
        while self._idle:
            conn = self._idle[0]                                # PEEK, do not pop
            usable = self._usable_locked(conn, probe=self.config.validate_on_borrow)
            self._idle.popleft()                                # decided - now take it
            if usable:
                return conn
            self._stale_discarded += 1
            self._destroy_locked(conn)
        return None

    def _usable_locked(self, conn: FakeConnection, probe: bool) -> bool:
        """Age cap first (free), then the probe (a round trip, under the lock -
        HikariCP reserves the slot and validates outside it). `probe` is the
        CALLER's call, never the config's: sweep() passes True unconditionally,
        which is exactly what makes validate_on_borrow=False safe.
        """
        cap = self.config.max_idle_seconds
        if cap is not None and time.monotonic() - conn.idle_since > cap:
            return False
        return not probe or self._probe_ok(conn)

    def _probe_ok(self, conn: FakeConnection) -> bool:
        """factory.validate(), made NON-THROWING: an exception IS a negative answer.

        `SELECT 1` RAISES on a closed socket rather than returning False. Let that
        escape and the connection sits in no collection while still counting in
        _all - one max_size slot leaked per corpse - and the caller gets a raw
        OSError that walks past the PoolError -> HTTP mapping.
        """
        try:
            return bool(self.factory.validate(conn))
        except Exception:               # a driver can raise anything
            return False

    def _create_locked(self) -> FakeConnection:
        """Lazy. NOTE: runs under the lock, serialising opens - real pools create
        OUTSIDE it (a socket is 50-200ms). Correct first, then narrow.
        """
        try:
            conn = self.factory.create()
        except Exception as exc:
            self._cv.notify_all()   # do not strand waiters behind a failed create
            raise ConnectionCreationError(f"factory.create() failed: {exc}") from exc
        self._all[conn.conn_id] = conn
        conn.idle_since = time.monotonic()
        return conn

    def _lease_locked(self, conn: FakeConnection) -> FakeConnection:
        self._in_use[conn.conn_id] = Lease(
            conn, threading.current_thread().name, time.monotonic())
        conn.use_count += 1
        self._borrowed += 1
        return conn

    def _destroy_locked(self, conn: FakeConnection) -> None:
        self._all.pop(conn.conn_id, None)
        try:
            self.factory.destroy(conn)
        except Exception:
            pass          # cleanup must not take the pool down with it


# Demo - each block PROVES one design claim
if __name__ == "__main__":

    def line(title: str) -> None:
        print("\n=== " + title + " ===")

    small = PoolConfig(min_idle=0, max_size=2, max_idle_seconds=None)

    line("1. reuse: the SAME object comes back - that is what saves the time")
    f = FakeConnectionFactory(open_cost=0.05)     # a real open is 50-200ms
    p1 = ConnectionPool(f, small)
    t0 = time.monotonic()
    a = p1.acquire()                              # cold: pays for the open
    cold = time.monotonic() - t0
    print("   borrowed:", a.execute("SELECT 1"))
    p1.release(a)
    t0 = time.monotonic()
    b = p1.acquire()                              # warm: reuses the object
    print(f"   second acquire -> {b.conn_id}  SAME object? {a is b}")
    print(f"   cold {cold * 1000:.1f}ms vs warm "
          f"{(time.monotonic() - t0) * 1000:.1f}ms, opens={f.created} for 2 borrows")
    assert a is b and f.created == 1, "reuse is the entire point of a pool"
    p1.release(b)

    line("2. exhaustion: acquire() blocks, then raises PoolExhaustedError")
    p2 = ConnectionPool(FakeConnectionFactory(), small)
    held = [p2.acquire(), p2.acquire()]
    t0 = time.monotonic()
    try:
        p2.acquire(timeout=0.25)
    except PoolExhaustedError as e:
        print(f"   full at {p2.stats().in_use}/2; raised after "
              f"{time.monotonic() - t0:.2f}s - it WAITED first")
        print(f"   {type(e).__name__}: {e}")
    t0 = time.monotonic()
    try:
        p2.acquire(timeout=0)                     # fail fast == the same code path
    except PoolExhaustedError:
        print(f"   timeout=0 -> fail fast in {time.monotonic() - t0:.4f}s")

    woke: List[float] = []                        # a release WAKES a waiter

    def latecomer() -> None:
        start = time.monotonic()
        p2.release(p2.acquire(timeout=3.0))
        woke.append(time.monotonic() - start)

    t = threading.Thread(target=latecomer, name="latecomer")
    t.start()
    time.sleep(0.15)
    print(f"   threads waiting right now: {p2.stats().waiting}")
    p2.release(held.pop())                        # <- this wakes it
    t.join()
    print(f"   waiter served in {woke[0]:.2f}s - the release woke it, not the 3s")
    p2.release(held.pop())

    line("3. leak: a borrower that never gives it back")
    leaky = PoolConfig(min_idle=1, max_size=2, max_idle_seconds=None,
                       leak_threshold=0.15)
    for policy in (LeakPolicy.LOG, LeakPolicy.RECLAIM):
        p3 = ConnectionPool(FakeConnectionFactory(), replace(leaky, leak_policy=policy))
        lost = p3.acquire()                       # ... and never released
        time.sleep(0.2)
        r = p3.sweep()
        print(f"   {policy.name:7s} -> found={r.leaks_found} "
              f"reclaimed={r.leaks_reclaimed} in_use now {p3.stats().in_use}")
        for entry in p3.leak_log:                 # LOG records, RECLAIM acts
            print(f"             {entry}")
    assert p3.stats().in_use == 0, "RECLAIM must heal the pool"
    try:
        p3.release(lost)                          # the leaker finally shows up
    except ConnectionRevokedError as e:
        print(f"   late release refused -> {type(e).__name__}: {e}")

    line("4. health: a connection dies while idle, and is replaced")
    p5 = ConnectionPool(FakeConnectionFactory(), replace(small, min_idle=1))
    c1 = p5.acquire()
    p5.release(c1)
    c1.is_alive = False                           # the server hung up, silently
    c2 = p5.acquire()
    print(f"   {c1.conn_id} died idle; next acquire -> {c2.conn_id}  "
          f"same object? {c2 is c1}  stale_discarded={p5.stats().stale_discarded}")
    assert c2 is not c1, "a pool that hands out dead connections is worse than none"
    print("   the replacement works:", c2.execute("SELECT 1"))
    print(f"   idle={p5.stats().idle} < min_idle=1 -> sweep refills: {p5.sweep()}")
    p5.release(c2)

    line("5. context manager: released even though the body raised")
    f6 = FakeConnectionFactory()
    p6 = ConnectionPool(f6, replace(small, max_size=1))
    try:
        with p6.connection() as conn:
            print(f"   in the with-block holding {conn.conn_id}, "
                  f"in_use={p6.stats().in_use}")
            raise RuntimeError("business logic exploded")
    except RuntimeError as e:
        print(f"   exception propagated (__exit__ returned False): {e}")
    print(f"   after the block: in_use={p6.stats().in_use} idle={p6.stats().idle}")
    assert p6.stats().in_use == 0, "the guard must return it no matter what"

    line("6. ownership: the pool refuses to be corrupted")
    x = p6.acquire()
    p6.release(x)
    try:
        p6.release(x)
    except DoubleReleaseError as e:
        print(f"   double release -> {type(e).__name__}: {e}")
    try:
        p6.release(FakeConnection(conn_id="conn-from-somewhere-else"))
    except UnknownConnectionError as e:
        print(f"   alien release  -> {type(e).__name__}: {e}")
    print(f"   pool is still sane: size={p6.stats().size} idle={p6.stats().idle}")

    line("7. 60 threads rush a pool of 4 - nobody ever shares a connection")
    f7 = FakeConnectionFactory()
    p7 = ConnectionPool(f7, replace(small, max_size=4, acquire_timeout=5.0))
    held_by: Dict[str, str] = {}
    violations: List[str] = []
    seen: Set[str] = set()
    audit = threading.Lock()

    def worker() -> None:
        me = threading.current_thread().name
        with p7.connection() as conn:             # the leak-proof form
            with audit:
                seen.add(conn.conn_id)
                if conn.conn_id in held_by:       # two owners = the race was lost
                    violations.append(f"{conn.conn_id}: {held_by[conn.conn_id]}+{me}")
                held_by[conn.conn_id] = me
            conn.execute("SELECT 1")
            time.sleep(0.002)
            with audit:
                held_by.pop(conn.conn_id, None)

    threads = [threading.Thread(target=worker, name=f"w{i}") for i in range(60)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    s = p7.stats()
    print(f"   two threads on one connection at once: {len(violations)} (must be 0)")
    print(f"   distinct connections used: {len(seen)} (must be <= 4)")
    print(f"   borrowed={s.borrowed} opened={f7.created} size={s.size} "
          f"in_use={s.in_use} timeouts={s.timeouts}")
    assert not violations and len(seen) <= 4 and s.size <= 4, violations
    assert s.borrowed == 60 and s.in_use == 0

    line("8. close(): nothing is left open")
    out = p7.acquire()
    p7.close()
    print(f"   idle destroyed now; one still on loan: in_use={p7.stats().in_use}")
    p7.release(out)                               # returned -> destroyed, not re-pooled
    print(f"   once it comes back: size={p7.stats().size} idle={p7.stats().idle} "
          f"(opened={f7.created}, closed={f7.destroyed})")
    try:
        p7.acquire(timeout=0)
    except PoolClosedError as e:
        print(f"   acquire after close -> {type(e).__name__}: {e}")
    assert f7.created == f7.destroyed, "every connection opened must be closed"

    line("9. every ConnectionFactory method really is abstract")
    assert set(ConnectionFactory.__abstractmethods__) == {"create", "validate", "destroy"}
    print(f"   abstract: {sorted(ConnectionFactory.__abstractmethods__)}")
    print("   a subclass missing one is refused at CONSTRUCTION, not at 3am")
