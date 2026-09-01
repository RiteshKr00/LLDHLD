"""
Logging Framework — LLD solution (Decorator + a justified Singleton).

THE THREE IDEAS — keep them separate in your head:
    1. LEVELS are DATA. DEBUG < INFO < WARN < ERROR < FATAL is an ORDER, so all
       of "level filtering" is `record.level >= threshold`. No class per level.
    2. DECORATOR is the composition axis. A sink does ONE thing (write bytes);
       enrich, filter, rate-limit and go-async are each a Handler that HOLDS a
       Handler, so they stack in any order over any sink.
    3. SINGLETON is the *accessor*, not the class. LoggerRegistry is an ordinary
       injectable object; only the module-level default is global. Read the note
       above set_registry() before copying this one.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import IntEnum
from typing import Callable, Iterator, Optional


# Error TYPES become HTTP status codes at the API layer — never return None to
# signal failure.
class LoggingError(Exception):
    """Base for everything this framework raises."""

class UnknownLevelError(LoggingError):
    """Level name outside the five. -> 400 at the config endpoint."""

class InvalidLoggerNameError(LoggingError):
    """Empty name, or an empty dotted segment ('app..db'). -> 400."""

class HandlerClosedError(LoggingError):
    """A record handed to an already-closed handler. -> 409."""

class LogFormatError(LoggingError):
    """template % args blew up. Caught by the dispatch bulkhead, so one bad call
    site degrades one line and not the request."""

class HandlerConfigError(LoggingError):
    """Nonsensical wrapper config (capacity 0, queue size 0). -> 400."""


# HINT (to rebuild) — LogLevel
#   The five severities as an ORDER, so filtering is one comparison.
#   ** IntEnum, not Enum: severity is DATA, not behaviour — a class per level
#      would be ceremony with no differing method.
#   Number in 10s so TRACE/NOTICE can slot in later (syslog's reason).
#   Needs a parse(): config files carry the STRING "WARN".
class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40
    FATAL = 50

    @classmethod
    def parse(cls, name: str) -> "LogLevel":
        try:
            return cls[name.strip().upper()]
        except KeyError as exc:
            raise UnknownLevelError(
                f"unknown level {name!r}; expected one of {[m.name for m in cls]}"
            ) from exc


# HINT (to rebuild) — LogRecord
#   ONE logging event, carried UNFORMATTED: template and args stay SEPARATE and
#   are joined only on demand. That deferral is the whole performance point.
#   ** frozen: one record is shared by every sink in the fan-out, so enrichment
#      must RETURN A COPY rather than mutate.
#   ** rendering must happen at most once even across three sinks.
#   Mutable / call-time defaults need field(default_factory=...).
@dataclass(frozen=True)
class LogRecord:
    logger_name: str
    level: LogLevel
    template: str
    args: tuple = ()
    context: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    thread_name: str = field(
        default_factory=lambda: threading.current_thread().name
    )
    _rendered: Optional[str] = field(default=None, repr=False, compare=False)

    def message(self) -> str:
        """template % args, memoised — the deferral only pays if the fan-out
        renders it ONCE, not once per sink."""
        if self._rendered is not None:
            return self._rendered
        if not self.args:
            text = self.template
        else:
            try:
                text = self.template % self.args
            except (TypeError, ValueError) as exc:
                raise LogFormatError(
                    f"cannot render {self.template!r} with {len(self.args)} arg(s): {exc}"
                ) from exc
        object.__setattr__(self, "_rendered", text)      # cache, not mutation:
        return text                                      # public fields stay frozen

    def with_context(self, extra: dict) -> "LogRecord":
        """A COPY with extra context merged in — the record itself never mutates,
        because the sinks downstream of an enricher share it."""
        return replace(self, context={**self.context, **extra})


# HINT (to rebuild) — Formatter (Strategy)
#   record -> str, and NOTHING else: it neither decides whether to log nor
#   writes. That is what lets one record leave as a human line AND as JSON.
#   Two of them: a readable console line, and machine-parseable JSON.
#   ** JSON must be ONE line — a multi-line record is unsplittable by every
#      log collector on earth.
class Formatter(ABC):
    @abstractmethod
    def format(self, record: LogRecord) -> str:
        """One record -> one line, no trailing newline."""


class PlainFormatter(Formatter):
    def format(self, record: LogRecord) -> str:
        stamp = time.strftime("%H:%M:%S", time.localtime(record.created_at))
        millis = int((record.created_at % 1) * 1000)
        ctx = ""
        if record.context:
            ctx = " {" + " ".join(f"{k}={v}" for k, v in sorted(record.context.items())) + "}"
        return (f"{stamp}.{millis:03d} {record.level.name:<5} "
                f"[{record.logger_name}] {record.message()}{ctx}")


class JsonFormatter(Formatter):
    def format(self, record: LogRecord) -> str:
        payload = {
            "ts": round(record.created_at, 3),
            "level": record.level.name,
            "logger": record.logger_name,
            "thread": record.thread_name,
            "msg": record.message(),
        }
        # `default=str` so a Decimal / UUID / datetime in the context does not
        # explode the logger. Losing precision in a log line beats a crash.
        payload.update(record.context)
        return json.dumps(payload, sort_keys=True, default=str)


# HINT (to rebuild) — Filter (Strategy)
#   A pure predicate over a record, for the cuts severity CANNOT express:
#   "only app.db.*", "only tenant=acme". Level is an order; these are set
#   membership, so they need their own tiny abstraction.
#   ** A filter that mutates or writes is a decorator in disguise — keep it pure.
class Filter(ABC):
    @abstractmethod
    def allows(self, record: LogRecord) -> bool:
        """True if the record continues down the chain."""


class NamePrefixFilter(Filter):
    def __init__(self, prefix: str):
        self.prefix = prefix

    def allows(self, record: LogRecord) -> bool:
        name = record.logger_name
        return name == self.prefix or name.startswith(self.prefix + ".")


class ContextFilter(Filter):
    """The cut severity cannot make: one tenant, one request."""

    def __init__(self, key: str, value: object):
        self.key = key
        self.value = value

    def allows(self, record: LogRecord) -> bool:
        return record.context.get(self.key) == self.value


# HINT (to rebuild) — Handler (ABC) and SinkHandler (ABC)
#   Handler is the ONE narrow type every sink AND every wrapper shares — that
#   sameness is what makes Decorator possible.
#   SinkHandler is the base for things that actually WRITE, and owns its OWN
#   formatter and level so two sinks can disagree about both. Subclasses supply
#   write(line) only.
#   ** One record's bytes must be indivisible under threads — so lock the write,
#      and only the write: formatting is expensive and belongs outside it.
class Handler(ABC):
    @abstractmethod
    def handle(self, record: LogRecord) -> None:
        """Consume one record: filter it, transform it, or write it."""

    @abstractmethod
    def close(self) -> None:
        """Release resources. Must be idempotent."""


class SinkHandler(Handler, ABC):
    def __init__(self, formatter: Formatter, level: LogLevel = LogLevel.DEBUG):
        self.formatter = formatter
        self.level = level
        self._lock = threading.Lock()
        self._closed = False

    def handle(self, record: LogRecord) -> None:
        if self._closed:
            raise HandlerClosedError(f"{type(self).__name__} is closed")
        if record.level < self.level:           # the per-sink threshold
            return
        line = self.formatter.format(record)    # expensive, and lock-free
        with self._lock:                        # one record = one indivisible write
            self.write(line)

    @abstractmethod
    def write(self, line: str) -> None:
        """Put one formatted line wherever this sink puts things."""

    def close(self) -> None:
        self._closed = True


class ConsoleHandler(SinkHandler):
    def write(self, line: str) -> None:
        print(line)


class FileHandler(SinkHandler):
    def __init__(self, path: str, formatter: Formatter, level: LogLevel = LogLevel.DEBUG):
        super().__init__(formatter, level)
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")

    def write(self, line: str) -> None:
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._fh.close()


class MemoryHandler(SinkHandler):
    """Ring buffer of rendered lines — the sink tests assert against. maxlen drops
    the OLDEST on overflow, which is the cap for free."""

    def __init__(self, formatter: Formatter, level: LogLevel = LogLevel.DEBUG,
                 capacity: int = 1000):
        super().__init__(formatter, level)
        self._buffer: deque = deque(maxlen=capacity)

    def write(self, line: str) -> None:
        self._buffer.append(line)

    def lines(self) -> list:
        with self._lock:
            return list(self._buffer)


# HINT (to rebuild) — HandlerDecorator  ** THE PATTERN **
#   IS-A Handler and HAS-A Handler. That double relationship is the whole
#   pattern: a wrapper can stand anywhere a sink stands.
#   ** Why not subclassing: the behaviours (enrich, filter, rate-limit, go async)
#      are independent and any subset may be wanted in any order — subclassing is
#      O(2^behaviours x sinks) classes, wrapping is O(b + s) and composes at
#      runtime, from config, with no new code.
#   Delegate close(); leave handle() abstract so a no-op decorator won't compile.
class HandlerDecorator(Handler, ABC):
    def __init__(self, inner: Handler):
        self.inner = inner

    @abstractmethod
    def handle(self, record: LogRecord) -> None:
        ...

    def close(self) -> None:
        self.inner.close()


class ContextEnricher(HandlerDecorator):
    """Adds fields every downstream sink then sees, without any sink knowing.
    `provider` is a CALLABLE, not a dict, because per-request values change per
    record: a dict would freeze one request's id into every later record."""

    def __init__(self, inner: Handler, static: Optional[dict] = None,
                 provider: Optional[Callable[[], dict]] = None):
        super().__init__(inner)
        self.static = dict(static or {})
        self.provider = provider

    def handle(self, record: LogRecord) -> None:
        extra = dict(self.static)
        if self.provider is not None:
            extra.update(self.provider())
        self.inner.handle(record.with_context(extra) if extra else record)


class FilteringHandler(HandlerDecorator):
    """Applies a Filter in front of whatever it wraps."""

    def __init__(self, inner: Handler, log_filter: Filter):
        super().__init__(inner)
        self.log_filter = log_filter

    def handle(self, record: LogRecord) -> None:
        if self.log_filter.allows(record):
            self.inner.handle(record)


class RateLimitingHandler(HandlerDecorator):
    """Token bucket in front of a sink — the fix for a hot loop flooding the log.

    Problem 04's lazy-refill math without its swappable-store machinery: one
    bucket, one handler (YAGNI). Drops are COUNTED, never silent, and the count
    rides out on the next record through — or at close(), so the last batch of a
    burst is still reported rather than lost.
    """

    def __init__(self, inner: Handler, capacity: int, refill_per_second: float):
        super().__init__(inner)
        if capacity <= 0 or refill_per_second < 0:
            raise HandlerConfigError("need capacity >= 1 and refill >= 0")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._unreported = 0
        self.dropped = 0
        self._lock = threading.Lock()

    def _take_token(self) -> bool:
        with self._lock:                       # refill + take is ONE atomic step
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens
                               + (now - self._last_refill) * self.refill_per_second)
            self._last_refill = now
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            self._unreported += 1
            self.dropped += 1
            return False

    def _notice(self, logger_name: str) -> Optional[LogRecord]:
        with self._lock:
            n, self._unreported = self._unreported, 0
        return None if not n else LogRecord(
            logger_name, LogLevel.WARN, "rate limiter suppressed %d record(s)", (n,))

    def handle(self, record: LogRecord) -> None:
        if not self._take_token():
            return
        notice = self._notice(record.logger_name)
        if notice is not None:
            self.inner.handle(notice)
        self.inner.handle(record)

    def close(self) -> None:
        notice = self._notice("logging.ratelimit")
        if notice is not None:
            # Best-effort: shutdown is where the inner sink may ALREADY be closed.
            # Losing the count is acceptable; throwing out of close() and breaking
            # the host's shutdown is not.
            try:
                self.inner.handle(notice)
            except Exception as exc:
                _internal_error("final suppression notice", exc)
        self.inner.close()


# The fourth wrapper, left as the exercise — AsyncHandler: handle() enqueues and
# returns, ONE worker (not a pool, so per-sink ordering survives) drains into
# inner, a full queue DROPS rather than blocking the caller, close() drains first.
# Its trap: a flush() waiting on `queue.empty()` returns with the write still IN
# FLIGHT, because the worker pops before it writes.


def _internal_error(where: str, exc: Exception) -> None:
    """The framework's own error channel: a logger may NEVER raise into the
    application it instruments, so failures land here instead."""
    print(f"[logging-internal] {where} failed: {type(exc).__name__}: {exc}")


# HINT (to rebuild) — Logger
#   A NODE in a dotted namespace tree: "app.db.query" -> "app.db" -> "app" -> root,
#   fanning each record out to its own handlers and then its ancestors' — until a
#   node says stop propagating.
#   ** The level must be NULLABLE, meaning "inherit"; defaulting it to DEBUG
#      would silently break configuring a whole subtree from its parent.
#   ** Check the level FIRST — building no record is the lazy-formatting payoff.
#   ** Fan-out iterates a SNAPSHOT, and one broken handler must not stop the rest.
class Logger:
    def __init__(self, name: str, parent: Optional["Logger"] = None):
        self.name = name
        self.parent = parent
        self.propagate = True
        self._level: Optional[LogLevel] = None
        self._handlers: list = []
        self._lock = threading.Lock()

    def set_level(self, level: LogLevel) -> None:
        if not isinstance(level, LogLevel):
            raise UnknownLevelError(f"expected LogLevel, got {type(level).__name__}")
        self._level = level

    def effective_level(self) -> LogLevel:
        """Walk UP until a node has one — None means INHERIT."""
        node: Optional[Logger] = self
        while node._level is None and node.parent is not None:
            node = node.parent
        return node._level or LogLevel.DEBUG

    def is_enabled_for(self, level: LogLevel) -> bool:
        return level >= self.effective_level()

    def add_handler(self, handler: Handler) -> None:
        with self._lock:
            self._handlers.append(handler)

    def handlers(self) -> tuple:
        with self._lock:
            return tuple(self._handlers)

    def set_propagate(self, propagate: bool) -> None:
        self.propagate = propagate

    def log(self, level: LogLevel, template: str, *args: object, **context: object) -> None:
        if not self.is_enabled_for(level):
            return                                    # <- nothing is formatted
        self._dispatch(LogRecord(logger_name=self.name, level=level,
                                 template=template, args=tuple(args),
                                 context=dict(context)))

    def debug(self, template: str, *args: object, **context: object) -> None:
        self.log(LogLevel.DEBUG, template, *args, **context)

    def info(self, template: str, *args: object, **context: object) -> None:
        self.log(LogLevel.INFO, template, *args, **context)

    def warn(self, template: str, *args: object, **context: object) -> None:
        self.log(LogLevel.WARN, template, *args, **context)

    def error(self, template: str, *args: object, **context: object) -> None:
        self.log(LogLevel.ERROR, template, *args, **context)

    def fatal(self, template: str, *args: object, **context: object) -> None:
        self.log(LogLevel.FATAL, template, *args, **context)

    def _dispatch(self, record: LogRecord) -> None:
        node: Optional[Logger] = self
        while node is not None:
            for handler in node.handlers():
                try:
                    handler.handle(record)
                except Exception as exc:              # BULKHEAD, per handler
                    _internal_error(f"{node.name}/{type(handler).__name__}", exc)
            if not node.propagate:
                break
            node = node.parent


# HINT (to rebuild) — LoggerRegistry
#   Owns the namespace tree; hands out loggers by name, auto-creating missing
#   ancestors ("app.db.query" creates "app.db" and "app").
#   ** THE RACE: look-up-or-create is a textbook check-then-act — two threads
#      both miss, both build, one overwrites, and handlers on the loser are
#      SILENTLY invisible. Push atomicity into the store. (RLock: it recurses.)
#   ** A PLAIN object: constructible, injectable, throwaway.
ROOT_NAME = "root"
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$")


class LoggerRegistry:
    def __init__(self, root_level: LogLevel = LogLevel.INFO):
        self._root = Logger(ROOT_NAME, parent=None)
        self._root.set_level(root_level)
        self._loggers: dict = {ROOT_NAME: self._root}
        self._lock = threading.RLock()

    def root(self) -> Logger:
        return self._root

    def get_logger(self, name: str) -> Logger:
        if name == ROOT_NAME:
            return self._root
        if not _NAME_RE.match(name or ""):
            raise InvalidLoggerNameError(
                f"bad logger name {name!r}: expected dotted segments like 'app.db.query'"
            )
        with self._lock:                       # <- the atomic look-up-or-create
            return self._get_or_create(name)

    def _get_or_create(self, name: str) -> Logger:
        existing = self._loggers.get(name)
        if existing is not None:
            return existing
        parent_name = name.rpartition(".")[0]
        parent = self._get_or_create(parent_name) if parent_name else self._root
        logger = Logger(name, parent)
        self._loggers[name] = logger
        return logger

    def names(self) -> list:
        with self._lock:
            return sorted(self._loggers)

    def close(self) -> None:
        """Close every handler in the tree, ONCE each — one handler is commonly
        attached to several nodes."""
        with self._lock:
            seen: set = set()
            for logger in self._loggers.values():
                for h in logger.handlers():
                    if id(h) not in seen:
                        seen.add(id(h))
                        try:
                            h.close()
                        except Exception as exc:
                            _internal_error(f"close {type(h).__name__}", exc)


# HINT (to rebuild) — the module-level default registry, and the test seam
#   A default LoggerRegistry at module scope, an accessor, a SETTER that returns
#   the previous one, and a context manager built on that setter.
#   ** The setter is not a convenience: it IS the answer to "how do you test a
#      Singleton", so it must hand the old registry back to be restored.
#
# THE ARGUMENT, this being the one place in eleven problems where the repo does
# not inject. A global is right for logging SPECIFICALLY: a logger is needed at
# every depth, leaf helpers and import-time code included, so threading it through
# would poison every signature for one cross-cutting concern.
# IT STILL COSTS, and say so unprompted: a class calling get_logger() has a HIDDEN
# dependency its signature never declares, and global mutable state leaks across
# tests in one process — test A's handler catches test B's records, and parallel
# tests fight over it. The classic __new__/getInstance Singleton makes all of that
# WORSE by making the instance unreplaceable; do not write that one.
# THE COMPROMISE REAL LIBRARIES SHIP, copied here: the registry is an ordinary
# injectable class, only the module-level DEFAULT is global, and set_registry /
# use_registry are a documented seam for swapping in a private tree. Convenience
# for the 99% of call sites, injectability for the 1% that need it.
_registry_lock = threading.Lock()
_registry = LoggerRegistry()


def current_registry() -> LoggerRegistry:
    with _registry_lock:
        return _registry


def set_registry(registry: LoggerRegistry) -> LoggerRegistry:
    """Swap the process-wide registry, returning the previous one so the caller
    can put it back. THIS is the answer to 'how do you test a Singleton'."""
    global _registry
    with _registry_lock:
        previous, _registry = _registry, registry
        return previous


@contextmanager
def use_registry(registry: LoggerRegistry) -> Iterator[LoggerRegistry]:
    """An isolated tree for one test, restored even if the test raises."""
    previous = set_registry(registry)
    try:
        yield registry
    finally:
        set_registry(previous)


def get_logger(name: str) -> Logger:
    """The one function application code calls. `log = get_logger(__name__)`."""
    return current_registry().get_logger(name)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tmpdir = tempfile.mkdtemp(prefix="lld-logging-")
    log_path = f"{tmpdir}/app.log"

    print("=== 1. ONE record -> TWO sinks -> TWO formats ===")
    console = ConsoleHandler(PlainFormatter(), level=LogLevel.INFO)
    audit = MemoryHandler(JsonFormatter(), level=LogLevel.INFO)
    registry = LoggerRegistry(root_level=LogLevel.INFO)
    set_registry(registry)
    app = get_logger("app")
    app.add_handler(console)
    app.add_handler(audit)

    app.info("order %s captured %s", "ORD-9", Decimal("1299.50"), tenant="acme")
    print("  ", audit.lines()[-1])
    print("   -> the sinks share the RECORD, not the rendering; formatter is per-sink.")

    print("\n=== 2. LEVEL FILTERING suppresses, and formats nothing ===")

    class Expensive:
        renders = 0

        def __str__(self) -> str:
            Expensive.renders += 1
            return "<a 4kB cart dump>"

    cart = Expensive()
    before = len(audit.lines())
    for _ in range(1000):
        app.debug("cart contents: %s", cart)       # DEBUG < INFO -> suppressed
    print(f"   1000 debug calls -> {len(audit.lines()) - before} logged, str(cart) ran "
          f"{Expensive.renders}x")
    app.info("cart contents: %s", cart)            # this one passes
    print(f"   one info call    -> {len(audit.lines()) - before} logged, 2 sinks, "
          f"str(cart) ran {Expensive.renders}x (memoised, not once per sink)")
    print('   -> f"cart {cart}" would have paid that cost 1000 times for nothing.')

    print("\n=== 3. HIERARCHY: configure the parent, the children inherit ===")
    db = get_logger("app.db")
    query = get_logger("app.db.query")
    db.set_level(LogLevel.DEBUG)                   # configure the PARENT only
    print(f"   app.db.query level = {query.effective_level().name}, inherited from a "
          f"parent it never names; tree = {registry.names()}")

    def reached(fn) -> bool:
        before = len(audit.lines())
        fn()
        return len(audit.lines()) > before

    print(f"   INFO   propagated up two levels to app's sinks? "
          f"{reached(lambda: query.info('SELECT %d rows', 3))}")
    print(f"   DEBUG  too? {reached(lambda: query.debug('cache miss'))}  <- the logger "
          f"said yes, the SINK's own INFO threshold said no")
    db.set_propagate(False)                        # a firewall at app.db
    print(f"   INFO   with app.db propagate=False? "
          f"{reached(lambda: query.info('SELECT %d rows', 7))}")
    db.set_propagate(True)

    print("\n=== 4. DECORATOR: wrappers stack over ONE plain sink ===")
    request_ctx = threading.local()
    file_sink = FileHandler(log_path, JsonFormatter())
    stack = ContextEnricher(
        FilteringHandler(file_sink, NamePrefixFilter("app.db")),
        static={"service": "checkout"},
        provider=lambda: {"request_id": getattr(request_ctx, "rid", "-")},
    )
    for name in ("app.db.query", "app.web.route"):
        node = get_logger(name)
        node.set_propagate(False)
        node.add_handler(stack)

    request_ctx.rid = "req-77"
    get_logger("app.db.query").info("wrote %d row(s)", 2)
    get_logger("app.web.route").info("GET /health")    # wrong prefix -> filtered
    with open(log_path, encoding="utf-8") as fh:
        on_disk = [ln.strip() for ln in fh if ln.strip()]
    print(f"   ContextEnricher( Filtering( FileHandler )): 2 records in, "
          f"{len(on_disk)} on disk:")
    print("  ", on_disk[-1])
    print("   -> the FileHandler never learned about context or filtering. Subclassing")
    print("      would need an EnrichedFilteredFileHandler; wrapping needed 0 classes.")

    print("\n=== 5. RATE LIMITING: a hot loop floods the log ===")
    flood = MemoryHandler(PlainFormatter())
    limited = RateLimitingHandler(flood, capacity=5, refill_per_second=0.0)
    hot = get_logger("app.hotloop")
    hot.set_propagate(False)
    hot.set_level(LogLevel.DEBUG)
    hot.add_handler(limited)

    for i in range(500):
        hot.error("retry storm, attempt %d", i)
    print(f"   500 ERROR records -> {len(flood.lines())} written, {limited.dropped} dropped")
    limited.close()
    print("   the drops are ACCOUNTED for, never silent:")
    print("  ", flood.lines()[-1])

    print("\n=== 6. THREAD SAFETY: one record must not be torn in half ===")

    class ChunkedSink(SinkHandler):
        """Writes each line as TWO appends with a yield between them — the cheapest
        way to make a torn write visible. locked=False skips SinkHandler's lock."""

        def __init__(self, locked: bool = True):
            super().__init__(PlainFormatter())
            self.chunks: list = []
            self.locked = locked

        def handle(self, record: LogRecord) -> None:
            if self.locked:
                super().handle(record)
            else:
                self.write(self.formatter.format(record))

        def write(self, line: str) -> None:
            self.chunks.append("HEAD:" + line)
            time.sleep(0.0005)                 # a real yield: the GIL is released
            self.chunks.append("TAIL:" + line)

    def hammer(name: str, locked: bool, threads: int = 6, each: int = 40) -> str:
        """Six threads log at one sink; count the records whose chunks split up."""
        sink = ChunkedSink(locked)
        writer = get_logger(name)
        writer.set_propagate(False)
        writer.set_level(LogLevel.DEBUG)
        writer.add_handler(sink)

        def worker(n: int) -> None:
            for j in range(each):
                writer.info("worker %d record %d", n, j)

        ts = [threading.Thread(target=worker, args=(n,)) for n in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        torn = sum(1 for i, c in enumerate(sink.chunks) if c.startswith("HEAD:")
                   and sink.chunks[i + 1:i + 2] != ["TAIL:" + c[5:]])
        return f"{len(sink.chunks) // 2} records, {torn} torn in half"

    print(f"   NO lock  : {hammer('app.threads.naive', locked=False)}")
    print(f"   WITH lock: {hammer('app.threads.safe', locked=True)}")
    print("   -> the lock wraps write() only; formatting stays outside it.")

    print("\n=== 7. The global registry, and the seam that pays for it ===")
    outer = get_logger("app")
    print(f"   get_logger('app') is get_logger('app') -> {get_logger('app') is outer}")
    audit_before = len(audit.lines())
    with use_registry(LoggerRegistry(root_level=LogLevel.DEBUG)) as test_reg:
        probe = MemoryHandler(PlainFormatter())
        test_reg.root().add_handler(probe)
        get_logger("app").info("this record belongs to the TEST tree only")
        print(f"   inside use_registry, same 'app' object as outside? "
              f"{get_logger('app') is outer}")
        print(f"   test tree caught {len(probe.lines())}, production sink "
              f"{len(audit.lines()) - audit_before}")
    print(f"   afterwards, the original is back: {get_logger('app') is outer}")
    print("   -> global by DEFAULT, injectable when it matters. The hidden dependency")
    print("      and the test pollution are real, and this seam is the price paid for")
    print("      them — which is why the registry is a plain class, not a Singleton.")

    print("\n=== 8. TYPED FAILURES, and the per-handler bulkhead ===")
    for label, thunk in [
        ("LogLevel.parse('LOUD')", lambda: LogLevel.parse("LOUD")),
        ("get_logger('app..db')", lambda: get_logger("app..db")),
        ("RateLimitingHandler(capacity=0)", lambda: RateLimitingHandler(console, 0, 1.0)),
        ("closed_sink.handle(record)", lambda: limited.inner.handle(
            LogRecord("app", LogLevel.ERROR, "after close"))),
    ]:
        try:
            thunk()
            print(f"   {label:32s} -> no error (unexpected)")
        except LoggingError as exc:
            print(f"   {label:32s} -> {type(exc).__name__}")

    class BrokenHandler(Handler):
        def handle(self, record: LogRecord) -> None:
            raise RuntimeError("disk on fire")

        def close(self) -> None:
            pass

    survivor = MemoryHandler(PlainFormatter())
    bulk = get_logger("app.bulkhead")
    bulk.set_propagate(False)
    bulk.add_handler(BrokenHandler())
    bulk.add_handler(survivor)
    bulk.error("payment %s failed", "PAY-1")
    print(f"   a handler that raised did not stop the next one: {len(survivor.lines())} "
          f"record at the healthy sink, and the caller saw nothing")

    stack.close()
    registry.close()
    shutil.rmtree(tmpdir, ignore_errors=True)
