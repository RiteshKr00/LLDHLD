"""
01 - def vs async def vs a task queue, MEASURED.

    python3 solution.py

The whole topic in one number: identical work, one keyword different.
No web framework needed - this models the three execution shapes directly.
"""
import asyncio, time, threading
from concurrent.futures import ThreadPoolExecutor

WORK = 0.30          # stands in for a 300ms provider call
N = 3                # concurrent requests


def blocking_call():
    """A sync SDK call: requests, psycopg2, the Django ORM."""
    time.sleep(WORK)
    return "ok"


async def awaitable_call():
    """An async client: httpx, asyncpg, a streaming LLM client."""
    await asyncio.sleep(WORK)
    return "ok"


# --------------------------------------------------------------------------- #
# shape 1 - plain `def`: FastAPI runs it in a threadpool. Blocking is SAFE.
# --------------------------------------------------------------------------- #
def shape_def():
    with ThreadPoolExecutor(max_workers=40) as ex:     # anyio's default is 40
        list(ex.map(lambda _: blocking_call(), range(N)))


# --------------------------------------------------------------------------- #
# shape 2 - `async def` + a BLOCKING call: freezes the event loop. THE BUG.
# --------------------------------------------------------------------------- #
async def _async_blocking():
    blocking_call()            # never do this inside async def


async def shape_async_blocking():
    await asyncio.gather(*(_async_blocking() for _ in range(N)))


# --------------------------------------------------------------------------- #
# shape 3 - `async def` + await: correct, and the cheapest concurrency
# --------------------------------------------------------------------------- #
async def shape_async_await():
    await asyncio.gather(*(awaitable_call() for _ in range(N)))


# --------------------------------------------------------------------------- #
# shape 4 - the escape hatch when you are already inside async def
# --------------------------------------------------------------------------- #
async def shape_offloaded():
    await asyncio.gather(*(asyncio.to_thread(blocking_call) for _ in range(N)))


# --------------------------------------------------------------------------- #
# shape 5 - a TASK QUEUE: a different axis entirely. The caller stops waiting.
# --------------------------------------------------------------------------- #
class Broker:
    """A 20-line Celery: durable-ish queue + a dedicated pool per queue.

    The point is the BULKHEAD - 'llm' work cannot occupy 'default' workers.
    """

    def __init__(self):
        self.queues, self.done = {}, []

    def send(self, queue, fn):
        self.queues.setdefault(queue, []).append(fn)

    def work(self, queue, workers):
        tasks = self.queues.get(queue, [])
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(lambda f: f(), tasks))
        self.done += tasks
        self.queues[queue] = []


def timed(label, fn, is_async=False):
    t0 = time.perf_counter()
    asyncio.run(fn()) if is_async else fn()
    return time.perf_counter() - t0


if __name__ == "__main__":
    serial = WORK * N
    print(f"{N} concurrent requests, {WORK}s of work each")
    print(f"  ideal (concurrent): ~{WORK:.2f}s     serialised: ~{serial:.2f}s\n")

    r = {}
    r["def + blocking"] = timed("", shape_def)
    r["async def + blocking"] = timed("", shape_async_blocking, True)
    r["async def + await"] = timed("", shape_async_await, True)
    r["async def + to_thread"] = timed("", shape_offloaded, True)

    for k, v in r.items():
        flag = "  <-- THE BUG" if v > serial * 0.9 else ""
        print(f"  {k:<24} {v:.2f}s{flag}")

    assert r["async def + blocking"] > serial * 0.9
    assert r["def + blocking"] < serial * 0.7
    ratio = r["async def + blocking"] / r["def + blocking"]
    print(f"\n  async def + blocking is {ratio:.1f}x slower than plain def.")
    print("  Same work. One keyword.\n")

    # ---- the queue: a different axis ----
    b = Broker()
    for _ in range(20):
        b.send("llm", blocking_call)       # 20 slow LLM tasks
    for _ in range(3):
        b.send("default", lambda: None)    # 3 quick jobs

    t0 = time.perf_counter()
    b.work("default", workers=4)           # NOT blocked by the 20 LLM tasks
    fast = time.perf_counter() - t0
    print(f"  bulkhead: 'default' drained in {fast:.3f}s while 20 LLM tasks")
    print(f"            sat in their own queue. One shared pool would have")
    print(f"            made those 3 quick jobs wait ~{20 * WORK / 4:.1f}s.\n")
    assert fast < 0.1

    print("  the rule")
    print("  --------")
    print("  caller waiting?  no  -> queue (durable, retried, returns instantly)")
    print("                   yes -> does EVERY call inside await?")
    print("                          yes -> async def")
    print("                          no  -> def   (threadpool absorbs blocking)")
    print("\nOK - topic 01")
