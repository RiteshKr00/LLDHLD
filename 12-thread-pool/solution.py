"""
Thread Pool / Task Scheduler — LLD solution.

Earlier problems USE a lock to protect state; this one BUILDS the coordination
primitive itself — "sleep until someone else changes it", not "hold the lock
while I mutate". Producers sleep when the queue is FULL, consumers when it is
EMPTY, a task exception is PARKED on its Future instead of killing a worker,
and shutdown stops accepting, drains, then wakes every sleeper.

queue.Queue and concurrent.futures are NOT imported — they are what is being
rebuilt.
"""

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import os
import threading
import time


# Errors — specific TYPES, never a bare None return: the type becomes the HTTP
# status, and "queue full, retry" (429) is a different story from "closed" (503).
class ThreadPoolError(Exception):
    """Base for every pool failure."""

class PoolShutdownError(ThreadPoolError):
    """submit() after shutdown() — closed for new work.  -> 503"""

class QueueFullError(ThreadPoolError):
    """AbortPolicy: full, the caller must back off.  -> 429"""

class TaskDiscardedError(ThreadPoolError):
    """DiscardOldestPolicy evicted this task to make room.  -> 503"""

class TaskAbandonedError(ThreadPoolError):
    """shutdown_now() dropped this task before it ran.  -> 503"""

class TaskCancelledError(ThreadPoolError):
    """Cancelled before a worker picked it up.  -> 409"""

class FutureTimeoutError(ThreadPoolError):
    """result(timeout=...) expired; the task is still running.  -> 504"""


# ---------------------------------------------------------------------------
# HINT (to rebuild) — TaskState:
#   The labels a submitter reads back off a future: both ways it can end badly,
#   plus the early exit.
#   ** Nothing branches on state to do different work -> differs by DATA, so an
#      enum. (The behaviour axis here is the rejection policy, further down.)
# ---------------------------------------------------------------------------
class TaskState(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# HINT (to rebuild) — Future:
#   The caller's handle on a value that does not exist yet: BLOCK until the
#   answer arrives, carry an exception across the thread boundary, cancel early.
#   ** THE CLASSIC BUG is a raising task leaving the gate unset for ever — every
#      exit path must settle it. cancel-vs-worker is check-then-act.
# ---------------------------------------------------------------------------
class Future:
    """A result that has not happened yet — all the submitter keeps."""

    def __init__(self, task_id: int = -1):
        self.task_id = task_id
        self._done = threading.Event()          # the "answer has arrived" gate
        self._lock = threading.Lock()           # guards _state/_value/_exc
        self._state = TaskState.PENDING
        self._value: Any = None
        self._exc: Optional[BaseException] = None

    def result(self, timeout: Optional[float] = None) -> Any:
        if not self._done.wait(timeout):
            raise FutureTimeoutError(f"task {self.task_id} unfinished in {timeout}s")
        if self._state is TaskState.CANCELLED:
            raise TaskCancelledError(f"task {self.task_id} was cancelled")
        if self._exc is not None:
            raise self._exc                     # <- the whole point of the class
        return self._value

    def state(self) -> TaskState:
        with self._lock:
            return self._state

    def cancel(self) -> bool:
        """Only while PENDING: Python cannot interrupt a running thread."""
        with self._lock:
            if self._state is not TaskState.PENDING:
                return False
            self._state = TaskState.CANCELLED
        self._done.set()                        # unblock anyone in result()
        return True

    def _start(self) -> bool:
        """PENDING -> RUNNING atomically. False = cancel() got here first."""
        with self._lock:
            if self._state is not TaskState.PENDING:
                return False
            self._state = TaskState.RUNNING
            return True

    def set_result(self, value: Any) -> None:
        with self._lock:
            if self._done.is_set():
                return                          # settled — first writer wins
            self._value = value
            self._state = TaskState.SUCCESS
        self._done.set()

    def set_exception(self, exc: BaseException) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self._exc = exc
            self._state = TaskState.FAILED
        self._done.set()


# ---------------------------------------------------------------------------
# HINT (to rebuild) — Task:
#   The envelope that travels the queue: what to call, with what, and WHERE the
#   answer goes. Mutable defaults need field(default_factory=...).
#   ** run() is the BULKHEAD — the only place a user callable is invoked, and a
#      pool that dies on one bad task takes N-1 healthy tasks with it.
# ---------------------------------------------------------------------------
@dataclass
class Task:
    task_id: int
    fn: Callable[..., Any]
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)     # NOT `= {}`
    future: Future = field(default_factory=Future)

    def __post_init__(self) -> None:
        self.future.task_id = self.task_id

    def run(self) -> None:
        """SETTLE FIRST, THEN PROPAGATE: catching only Exception would let a task
        calling sys.exit() leave its caller blocked for ever. Order, not width."""
        if not self.future._start():
            return                                   # cancelled while queued
        try:
            value = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:                 # <- BULKHEAD: settle FIRST
            self.future.set_exception(exc)
            if not isinstance(exc, Exception):
                raise                                # ...THEN propagate the exits
        else:
            self.future.set_result(value)


# ---------------------------------------------------------------------------
# HINT (to rebuild) — BoundedBlockingQueue:
#   The actual primitive: a deque + ONE lock + TWO Conditions on that lock, so
#   producers and consumers sleep on separate queues.
#   ** wait() not a spin loop; `while` not `if`; notify the OTHER condition after
#      changing the size; take() returns None only when closed AND empty — that
#      one predicate IS graceful shutdown.
# ---------------------------------------------------------------------------
class BoundedBlockingQueue:
    """FIFO hand-off with a hard capacity. Closing it wakes everybody."""

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._items: "deque[Task]" = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)   # same lock, two queues
        self._not_full = threading.Condition(self._lock)
        self._closed = False
        self._wakeups = 0          # instrumentation: proves we are not spinning

    def offer(self, task: Task) -> bool:
        """False = full. The closed-check is INSIDE the lock, so a shutdown
        landing mid-submit cannot slip a task past."""
        with self._not_full:
            if self._closed:
                raise PoolShutdownError("queue is closed; not accepting new tasks")
            if len(self._items) >= self._capacity:
                return False                     # caller decides: that is the Strategy
            self._items.append(task)
            self._not_empty.notify()             # wake ONE sleeping worker
            return True

    def offer_evicting(self, task: Task) -> Optional[Task]:
        """Evict the head if full, then enqueue, under ONE lock hold; the CALLER
        settles the victim. As poll()+offer() a racing producer takes the freed
        slot between the two and DiscardOldest degrades into Abort."""
        with self._not_full:
            if self._closed:
                raise PoolShutdownError("queue is closed; not accepting new tasks")
            full = len(self._items) >= self._capacity
            victim = self._items.popleft() if full else None
            self._items.append(task)
            self._not_empty.notify()
            return victim                        # size never DROPS -> no _not_full

    def put(self, task: Task, timeout: Optional[float] = None) -> bool:
        """Blocking enqueue — backpressure. False = timed out while still full."""
        with self._not_full:
            free = self._not_full.wait_for(
                lambda: self._closed or len(self._items) < self._capacity, timeout)
            if not free:
                return False
            if self._closed:
                raise PoolShutdownError("queue closed while waiting to enqueue")
            self._items.append(task)
            self._not_empty.notify()
            return True

    def take(self) -> Optional[Task]:
        """Block until a task arrives. None means "closed and drained — retire"."""
        with self._not_empty:
            while not self._items and not self._closed:
                self._not_empty.wait()           # <- the anti-busy-wait
                self._wakeups += 1
            if not self._items:
                return None                      # closed AND empty -> worker exits
            task = self._items.popleft()
            self._not_full.notify()              # a slot opened for some producer
            return task

    def close(self) -> None:
        """notify_ALL: one idle worker left parked would hang shutdown's join."""
        with self._not_empty:
            self._closed = True
            self._not_empty.notify_all()
            self._not_full.notify_all()

    def drain(self) -> List[Task]:
        with self._not_empty:
            items = list(self._items)
            self._items.clear()
            self._not_full.notify_all()
            return items

    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def wakeups(self) -> int:
        with self._lock:
            return self._wakeups


# ---------------------------------------------------------------------------
# HINT (to rebuild) — RejectionPolicy (Strategy, ABC):
#   ONE method, rejected(task, pool), called only when offer() said False: raise
#   · make room · run it here · park the caller — never return quietly.
#   ** Four genuinely DIFFERENT behaviours -> polymorphism, not a flag: an API
#      front-end wants Abort (429), batch ingest Block, telemetry DiscardOldest,
#      a CLI CallerRuns. @abstractmethod is mandatory.
# ---------------------------------------------------------------------------
class RejectionPolicy(ABC):
    """What to do when the bounded queue is full. The whole design decision."""

    @abstractmethod
    def rejected(self, task: Task, pool: "ThreadPool") -> None: ...


class AbortPolicy(RejectionPolicy):
    """Refuse loudly. The default: an unhandled overload should be VISIBLE."""

    def rejected(self, task: Task, pool: "ThreadPool") -> None:
        exc = QueueFullError(
            f"queue full ({pool.queue_capacity}); task {task.task_id} rejected")
        task.future.set_exception(exc)     # settle it, so nothing waits on it
        raise exc                          # ...and tell the submitter right now


class BlockPolicy(RejectionPolicy):
    """Park the submitter until a slot frees — a held connection in a handler."""

    def __init__(self, timeout: Optional[float] = None):
        self.timeout = timeout

    def rejected(self, task: Task, pool: "ThreadPool") -> None:
        if not pool.queue.put(task, timeout=self.timeout):
            exc = QueueFullError(f"still full after {self.timeout}s; "
                                 f"task {task.task_id} rejected")
            task.future.set_exception(exc)
            raise exc


class DiscardOldestPolicy(RejectionPolicy):
    """Evict the head: for decaying data (metrics, samples, a redraw queue) the
    newest item is the useful one."""

    def rejected(self, task: Task, pool: "ThreadPool") -> None:
        victim = pool.queue.offer_evicting(task)
        if victim is not None:
            # THE BUG EVERYONE WRITES: dropping the victim's Task but not its
            # Future, leaving that submitter waiting on work that is gone.
            victim.future.set_exception(
                TaskDiscardedError(f"task {victim.task_id} discarded to make room"))


class CallerRunsPolicy(RejectionPolicy):
    """Run it on the SUBMITTING thread: the producer is throttled by being busy,
    and the queue cannot grow while it is not submitting."""

    def rejected(self, task: Task, pool: "ThreadPool") -> None:
        task.run()                         # same bulkhead — still cannot raise


# ---------------------------------------------------------------------------
# HINT (to rebuild) — Worker:
#   A daemon Thread whose run() is a three-line loop: take (BLOCKS), retire on
#   None, run the task. It owns nothing.
#   ** Wrap task.run() anyway: if the pool's own bookkeeping throws the worker
#      must still not die, because a pool losing workers one at a time decays in
#      throughput and logs nothing. daemon=True is a net, not a strategy.
# ---------------------------------------------------------------------------
class Worker(threading.Thread):
    """One consumer thread: take -> run -> repeat."""

    def __init__(self, pool: "ThreadPool", name: str):
        super().__init__(name=name, daemon=True)
        self._pool = pool
        self.completed = 0                 # per-worker count -> proves the spread

    def run(self) -> None:
        while True:
            task = self._pool.queue.take()
            if task is None:               # closed AND drained
                break
            self._pool._on_start()
            try:
                task.run()
            except Exception as exc:       # outer bulkhead — the worker survives
                task.future.set_exception(exc)
            finally:
                self._pool._on_finish(task)
                self.completed += 1


# ---------------------------------------------------------------------------
# HINT (to rebuild) — PoolStats + ThreadPool:
#   Owns the queue, the workers and the policy. submit() is four lines (id ->
#   Task -> offer -> policy on False) and hands back the Future; the design is
#   all in shutdown — graceful drains, shutdown_now() abandons the backlog and
#   returns it with every future settled. Both must be IDEMPOTENT.
#   ** Poison pills DEADLOCK on a bounded queue and a polled flag wakes every
#      worker for ever. PICKED: the flag INSIDE the wait predicate.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PoolStats:
    """Read-only snapshot. Frozen so a caller cannot 'fix' the numbers."""
    workers: int
    alive: int
    queued: int
    active: int
    completed: int
    failed: int
    rejected: int


class ThreadPool:
    """A fixed pool of worker threads fed by a bounded blocking queue."""

    def __init__(self, workers: int, queue_capacity: int,
                 rejection: Optional[RejectionPolicy] = None, name: str = "pool"):
        if workers <= 0:
            raise ValueError("workers must be positive")
        self.queue_capacity = queue_capacity
        self.rejection = rejection or AbortPolicy()      # DI, sensible default
        self.queue = BoundedBlockingQueue(queue_capacity)
        self._lock = threading.Lock()                    # guards the counters only
        self._shutdown = threading.Event()
        self._next_id = 0
        self._active = self._completed = self._failed = self._rejected = 0
        self._workers = [Worker(self, f"{name}-{i}") for i in range(workers)]
        for w in self._workers:
            w.start()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        if self._shutdown.is_set():
            # Fast path only; the authoritative check is inside queue.offer(),
            # under the queue's lock, since the flag can flip in this gap.
            raise PoolShutdownError("pool is shut down; not accepting new tasks")
        with self._lock:
            self._next_id += 1
            task_id = self._next_id
        task = Task(task_id=task_id, fn=fn, args=args, kwargs=kwargs)
        if not self.queue.offer(task):          # ONE atomic step, no full()+put()
            with self._lock:
                self._rejected += 1
            self.rejection.rejected(task, self)  # Strategy decides what "full" means
        return task.future

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> bool:
        """Graceful: stop accepting, let the queue DRAIN, retire the workers."""
        self._shutdown.set()
        self.queue.close()          # closed-but-not-empty keeps serving -> it drains
        if not wait:
            return not any(w.is_alive() for w in self._workers)
        return self.await_termination(timeout)

    def shutdown_now(self) -> List[Task]:
        """Abrupt: also abandon what is still QUEUED and return it. The running
        task is NOT stopped — Python has no safe thread kill, so "no NEW work
        starts" is the honest contract."""
        self._shutdown.set()
        self.queue.close()
        abandoned = self.queue.drain()
        for task in abandoned:
            task.future.set_exception(          # settle, or submitters hang for ever
                TaskAbandonedError(f"task {task.task_id} abandoned by shutdown_now()"))
        return abandoned

    def await_termination(self, timeout: Optional[float] = None) -> bool:
        """Budget the timeout ACROSS workers, or `timeout=1` on 8 takes 8s."""
        deadline = None if timeout is None else time.monotonic() + timeout
        for w in self._workers:
            left = None if deadline is None else max(0.0, deadline - time.monotonic())
            w.join(left)
        return not any(w.is_alive() for w in self._workers)

    def _on_start(self) -> None:
        with self._lock:
            self._active += 1

    def _on_finish(self, task: Task) -> None:
        state = task.future.state()             # the future's lock, not ours
        with self._lock:
            self._active -= 1
            if state is TaskState.FAILED:
                self._failed += 1
            elif state is TaskState.SUCCESS:
                self._completed += 1

    def stats(self) -> PoolStats:
        queued = self.queue.size()
        with self._lock:
            return PoolStats(len(self._workers),
                             sum(1 for w in self._workers if w.is_alive()),
                             queued, self._active, self._completed,
                             self._failed, self._rejected)

    def worker_load(self) -> Dict[str, int]:
        """Tasks dequeued per worker — proves the work actually spread."""
        return {w.name: w.completed for w in self._workers}


# ---------------------------------------------------------------------------
# HINT (to rebuild) — sizing:
#   Thread count is a DECISION with a formula: CPU-bound ~ cpu_count(); IO-bound
#   ~ cpu_count() * (1 + wait/service), those threads being asleep in a syscall
#   rather than holding the GIL (which is released around blocking IO).
#   ** Bound it from above by the downstream too — 200 threads against a
#      20-connection DB pool just moves the queue somewhere worse.
# ---------------------------------------------------------------------------
def suggest_pool_size(io_bound: bool, wait_ms: float = 0.0, service_ms: float = 1.0) -> int:
    cores = os.cpu_count() or 1
    if not io_bound:
        return cores
    return max(1, int(cores * (1 + wait_ms / max(service_ms, 0.001))))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    baseline = threading.active_count()

    print("=== 1. workers BLOCK on an empty queue (no busy-wait) ===")
    idle = ThreadPool(3, 8, name="idle")
    time.sleep(0.25)
    print(f"   3 workers idle 250ms -> wakeups={idle.queue.wakeups()}, "
          f"alive={idle.stats().alive}   (a 1ms poll loop would be ~750)")
    idle.shutdown()

    print("\n=== 2. 12 tasks across 4 workers, results in SUBMISSION order ===")
    RATE = Decimal("125.50")                 # money is Decimal, never float

    def invoice(line: int) -> Decimal:
        time.sleep(0.012 * (12 - line))      # later tasks finish FIRST on purpose
        return RATE * line

    pool = ThreadPool(4, 16, name="w")
    results = [f.result() for f in [pool.submit(invoice, i) for i in range(1, 13)]]
    print(f"   results : {[str(r) for r in results[:3]]} ... {results[-1]}")
    print(f"   in order: {results == [RATE * i for i in range(1, 13)]} "
          f"(slowest submitted FIRST)   total {sum(results)}, exact Decimal")
    print(f"   spread  : {pool.worker_load()}")
    print(f"   stats   : {pool.stats()}")
    pool.shutdown()

    print("\n=== 3. an exception SURFACES to its caller, the pool survives ===")

    def flaky(n: int) -> int:
        if n == 7:
            raise ValueError("task 7 is cursed")
        return n * n

    pool = ThreadPool(3, 16, name="bh")
    futures = [pool.submit(flaky, i) for i in range(10)]
    ok, bad = [], []
    for f in futures:
        try:
            ok.append(f.result(timeout=2))
        except ValueError as exc:
            bad.append(f"{type(exc).__name__}: {exc}")
    print(f"   succeeded: {ok}")
    print(f"   raised   : {bad}   <- re-raised in the CALLER's thread")
    print(f"   states   : {[f.state().value for f in futures]}")
    print(f"   alive={pool.stats().alive}/3 (bulkhead held), still works: "
          f"{pool.submit(flaky, 11).result()}   {pool.stats()}")
    pool.shutdown()

    print("\n=== 4. queue FULL (1 worker, capacity 2) — the pluggable decision ===")

    def who(tag: str) -> str:
        return f"{tag}@{threading.current_thread().name}"

    def occupy(pool: ThreadPool, seconds: float = 0.6) -> Future:
        """Pin the worker and WAIT until it really runs, or the demo races
        startup and the queue counting is off by one."""
        started = threading.Event()

        def blocker() -> str:
            started.set()
            time.sleep(seconds)
            return "blocker done"

        fut = pool.submit(blocker)
        started.wait(2.0)
        return fut

    p = ThreadPool(1, 2, AbortPolicy(), name="abort")
    occupy(p); p.submit(who, "A"); p.submit(who, "B")      # queue now 2/2
    s = p.stats()
    print(f"   full? active={s.active} queued={s.queued}/{p.queue_capacity}"
          f"   <- MEASURED, not asserted in a comment")
    try:
        p.submit(who, "C")
    except QueueFullError as exc:
        print(f"   Abort        -> {type(exc).__name__}: {exc}; "
              f"rejected={p.stats().rejected} (counted for /health)")
    p.shutdown()

    p = ThreadPool(1, 2, DiscardOldestPolicy(), name="disc")
    occupy(p)
    fa, fb = p.submit(who, "A"), p.submit(who, "B")
    fc = p.submit(who, "C")                                # evicts A
    try:
        fa.result(timeout=2)
    except TaskDiscardedError as exc:
        print(f"   DiscardOldest-> A's caller got {type(exc).__name__}, not a hang; "
              f"B={fb.result(timeout=2)} C={fc.result(timeout=2)}")
    p.shutdown()

    p = ThreadPool(1, 2, CallerRunsPolicy(), name="cr")
    occupy(p); p.submit(who, "A"); p.submit(who, "B")
    print(f"   CallerRuns   -> C ran on {p.submit(who, 'C').result(timeout=2)}"
          f"   <- the SUBMITTER, so it cannot submit more")
    p.shutdown()

    p = ThreadPool(1, 2, BlockPolicy(timeout=2.0), name="blk")
    occupy(p); p.submit(who, "A"); p.submit(who, "B")
    t0 = time.monotonic()
    fc = p.submit(who, "C")                                # parks until a slot frees
    print(f"   Block        -> submit() parked {time.monotonic() - t0:.2f}s, "
          f"then C={fc.result(timeout=2)}")
    p.shutdown()

    print("\n=== 5. shutdown() DRAINS — nothing lost, no thread left alive ===")
    p = ThreadPool(2, 32, name="drain")
    for _ in range(11):
        p.submit(time.sleep, 0.03)           # most still queued when shutdown lands
    finished = p.shutdown(wait=True, timeout=5)
    print(f"   all 11 completed : {p.stats().completed == 11}   {p.stats()}")
    print(f"   every worker dead: {finished}   threads {baseline} -> "
          f"{threading.active_count()}, back to baseline")
    try:
        p.submit(time.sleep, 0)
    except PoolShutdownError as exc:
        print(f"   submit() after it -> {type(exc).__name__} (503, not a silent "
              f"drop); and calling shutdown() twice is fine (idempotent)")
    p.shutdown()

    print("\n=== 5b. shutdown_now() ABANDONS the backlog and hands it back ===")
    p = ThreadPool(1, 32, name="now")
    running = occupy(p)                      # in flight, cannot be stopped
    queued = [p.submit(who, f"q{i}") for i in range(5)]
    abandoned = p.shutdown_now()
    print(f"   abandoned {[t.task_id for t in abandoned]}")
    try:
        queued[0].result(timeout=2)
    except TaskAbandonedError as exc:
        print(f"   their callers get {type(exc).__name__} (settled, not a hang)")
    print(f"   the IN-FLIGHT task still finished: {running.result(timeout=3)!r}"
          f"   <- 'no NEW work starts' is the honest contract")
    p.await_termination(timeout=3)

    print("\n=== 6. cancel() wins only while PENDING ===")
    ran: List[str] = []
    p = ThreadPool(1, 8, name="cancel")
    occupy(p)
    f = p.submit(lambda: ran.append("x"))
    print(f"   cancel() while queued: {f.cancel()}  state={f.state().value}")
    try:
        f.result(timeout=2)
    except TaskCancelledError as exc:
        print(f"   result() -> {type(exc).__name__} (settled, not a hang)")
    time.sleep(0.7)
    print(f"   worker skipped it? {ran == []}   (at _start(), atomically)")
    p.shutdown()

    print(f"\n=== 7. sizing: cpu_count={os.cpu_count()} -> CPU pool "
          f"{suggest_pool_size(False)}, IO pool (90ms wait/10ms cpu) "
          f"{suggest_pool_size(True, 90, 10)} ===")
    print(f"final thread count: {threading.active_count()} (started at {baseline})"
          f"   <- every worker retired")
