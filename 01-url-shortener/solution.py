"""
URL Shortener — LLD solution (built step by step).

Locked entities (Step 2):
    1. ShortLink            - the data model (this noun holds one link's state)
    2. ShortCodeGenerator   - makes short codes  (algorithm lives here)
    3. URLRepository        - stores & fetches links (hides storage)
    4. URLShortenerService  - orchestrator; delegates to the three above
"""

# ===========================================================================
# HOW TO PRESENT THIS (interview walkthrough — talk in this order):
#   1. Scope    : restate reqs + say what's OUT of scope (auth, distributed). Senior move.
#   2. Entities : 4 nouns, one responsibility each (SRP) -> the 4 classes below.
#   3. Flow     : shorten = generate(Strategy) -> claim(save_if_absent) -> return;
#                 resolve = find -> is_active? -> count.
#   4. Decisions: WHY each pattern earns its place -
#                 Strategy   -> swap code algorithms without touching the service
#                 Repository -> swap storage (dict -> DB) with no logic rewrite
#                 DI         -> inject both -> trivially testable / mockable
#                 save_if_absent -> atomic claim; thread-safe AND distributed-ready
#   5. Edge cases: collision (retry vs raise), expiry/disable (is_active), where locks live.
#   6. "If I had more time": resolve error semantics (404 vs 410), alias format
#                 validation, async click analytics, unit tests.
# ===========================================================================
import random
import string
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import threading


# ---------------------------------------------------------------------------
# Step 4a: ShortLink — the data model
#
# HINT (to rebuild from scratch): a pure data holder, one field per requirement:
#   "long -> short"      => long_url, short_code
#   "when was it made"   => created_at
#   "expiry / TTL"       => expiry_date (Optional — most links never expire)
#   "track clicks"       => click_count (starts 0)
#   "disable"            => is_disabled (starts False)
# Then TWO tiny behaviours, so the object answers questions about itself
# ("Tell, Don't Ask") instead of callers poking at its fields:
#   is_expired() -> has expiry_date passed? (use datetime.now(timezone.utc) —
#                   tz-AWARE, or comparing to a naive datetime raises TypeError)
#   is_active()  -> not disabled AND not expired   <- both, not just one
# ---------------------------------------------------------------------------
@dataclass
class ShortLink:
    long_url: str
    short_code: str
    created_at: datetime
    expiry_date: Optional[datetime] = None
    click_count: int = 0
    is_disabled: bool = False

    def is_expired(self) -> bool:
        if self.expiry_date and datetime.now(timezone.utc) > self.expiry_date:
            return True
        return False

    def is_active(self) -> bool:
        return not self.is_disabled and not self.is_expired()

# ---------------------------------------------------------------------------
# Step 4b: ShortCodeGenerator  (Strategy pattern) — DONE
#
# HINT (to rebuild): the requirement said "extensible — easy to add new
# shortening algorithms". That word IS the Strategy signal:
#   1. an ABC with ONE method: generate_short_code(long_url) -> str
#   2. Base62CodeGenerator  -> counter += 1, encode to base62. Collision-free,
#      but sequential => codes are guessable/enumerable. The `+= 1` is a
#      read-modify-write -> needs a lock.
#   3. RandomCodeGenerator  -> N random base62 chars. Unguessable, but CAN
#      collide => caller must retry.
# Base62 = a-zA-Z0-9 (62 chars) because base64's + / = are URL-unsafe.
# Encode loop: repeatedly take num % 62 as a char, num //= 62, then REVERSE.
# YAGNI check: don't build 6 strategies — build one, name the others out loud.
# ---------------------------------------------------------------------------
BASE62_ALPHABET = string.ascii_letters + string.digits  # a-zA-Z0-9  -> 62 chars


class ShortCodeGenerator(ABC):
    """Strategy interface: every code-generation algorithm implements this
    one method, so the service can swap algorithms without changing."""

    @abstractmethod
    def generate_short_code(self, long_url: str) -> str:
        ...


class Base62CodeGenerator(ShortCodeGenerator):
    """Primary strategy: encode an incrementing counter to base62.
    Short + collision-free. Downside: sequential -> codes are enumerable/guessable.

    NOTE: `self.counter += 1` is NOT atomic -> race condition under threads.
          We'll wrap it in a lock when we handle the concurrency requirement.
    """

    def __init__(self) -> None:
        self.counter = 0
        self.counter_lock = threading.Lock()  # Lock to ensure thread-safe incrementing of the counter

    def generate_short_code(self, long_url: str) -> str:  # long_url ignored by design
        with self.counter_lock:
            self.counter += 1
            return self._encode_base62(self.counter)

    def _encode_base62(self, num: int) -> str:
        if num == 0:
            return BASE62_ALPHABET[0]
        chars = []
        while num > 0:
            chars.append(BASE62_ALPHABET[num % 62])
            num //= 62
        return "".join(reversed(chars))


class RandomCodeGenerator(ShortCodeGenerator):
    """Alternate strategy: N random base62 chars. Unguessable, but CAN collide
    -> the repository/service must verify uniqueness and retry on collision."""

    CODE_LENGTH = 7

    def generate_short_code(self, long_url: str) -> str:  # long_url ignored by design
        return "".join(random.choices(BASE62_ALPHABET, k=self.CODE_LENGTH))

# ---------------------------------------------------------------------------
# Step 4c: URLRepository (Repository pattern)
#
# HINT (to rebuild): the requirement "in-memory now, swappable to a DB with no
# logic rewrite" IS the Repository signal. Rules for what goes on it:
#   - THE VERB TEST: storage verbs (save/find/exists) belong to the repository;
#     domain verbs (shorten/resolve) belong to the SERVICE. Don't mix.
#   - Every method the service calls through this interface MUST be declared
#     here as @abstractmethod — an abstraction missing a method the caller
#     needs is a trap (a new repo could forget it -> AttributeError in prod).
#   - @abstractmethod only has teeth if the class inherits from ABC.
# The three methods, and WHY each exists:
#   save()           -> unconditional write; the UPDATE primitive (used by disable())
#   find_by_short_code() -> lookup
#   save_if_absent() -> the ATOMIC CLAIM. Check-and-set under ONE lock
#                       acquisition. Separate exists()+save() can NEVER be
#                       atomic (the lock drops between them = TOCTOU race).
#                       Maps to SQL INSERT..ON CONFLICT DO NOTHING / Redis SET NX.
# ---------------------------------------------------------------------------
class URLRepository(ABC):
    """Repository pattern: hides storage details from the service. The service
    doesn't care if we store links in memory, on disk, or in a DB. It just calls
    these methods and gets back ShortLink objects."""
    
    @abstractmethod
    def save(self, short_link: ShortLink) -> None:
        """Persist a link unconditionally — the update/upsert primitive."""
        pass

    @abstractmethod
    def find_by_short_code(self, short_code: str) -> Optional[ShortLink]:
        pass

    @abstractmethod
    def save_if_absent(self, short_link: ShortLink) -> bool:
        """Atomic claim: save IFF the code is free. True=saved, False=taken.
        Backed store => INSERT ON CONFLICT DO NOTHING (SQL) / SET NX (Redis)."""
        pass


class InMemoryURLRepository(URLRepository):
    """In-memory implementation of URLRepository. For testing and demo purposes.
    Not thread-safe; we'll wrap it in a lock when we handle the concurrency requirement.
    """

    def __init__(self) -> None:
        self.storage: dict[str, ShortLink] = {}
        self.storage_lock = threading.Lock()  # Lock to ensure thread-safe access to the storage

    def save(self, short_link: ShortLink) -> None:
        with self.storage_lock:
            self.storage[short_link.short_code] = short_link

    def find_by_short_code(self, short_code: str) -> Optional[ShortLink]:
        with self.storage_lock:
            return self.storage.get(short_code)

    def save_if_absent(self, short_link: ShortLink) -> bool:
        # Atomicity = check AND set under ONE lock acquisition (no gap to race).
        with self.storage_lock:
            if short_link.short_code in self.storage:
                return False
            self.storage[short_link.short_code] = short_link
            return True



# ---------------------------------------------------------------------------
# Step 4d: URLShortenerService (orchestrator)
#
# HINT (to rebuild):
#   __init__  -> take BOTH collaborators as arguments (Dependency Injection).
#                Never `self.repo = InMemoryURLRepository()` inside — that welds
#                the service to one impl and kills testability.
#                NOTE: this class is CONCRETE, not an ABC. Only one impl exists
#                -> making it abstract is YAGNI (and instantiating it crashes).
#
#   shorten() -> the fork that carries the whole lesson. Same clash, opposite
#                reaction, decided by WHO OWNS THE INPUT:
#                  custom alias taken  -> RAISE  (user chose it; can't overrule)
#                  generated code taken -> RETRY (machine chose it; just re-roll)
#                Both use save_if_absent, so the claim is atomic either way.
#                Don't forget to actually SAVE — building the ShortLink and
#                returning it without storing is the classic bug.
#
#   disable() -> find, flip is_disabled, then save() to persist the mutation.
#                This is the only caller that justifies keeping save().
#
#   resolve() -> find -> is_active()? -> count the click -> return.
#                click_count += 1 is a read-modify-write => guard it with a lock.
#                Design note: returning None collapses not-found/expired/disabled
#                into one answer; a real API would raise distinct errors (404 vs 410).
#                Senior nuance: real systems make click-counting ASYNC/approximate
#                (fire an event) rather than block every redirect on a lock.
# ---------------------------------------------------------------------------
class URLShortenerService:

    def __init__(self, code_generator: ShortCodeGenerator, repository: URLRepository) -> None:
        self.code_generator = code_generator
        self.repository = repository
        # Uniqueness/atomicity now lives in the repo (save_if_absent), so shorten needs no lock.
        # This guards ONLY resolve's click_count increment.
        self.click_lock = threading.Lock()



    def shorten(self, long_url: str, custom_code: Optional[str] = None,
                expiry_date: Optional[datetime] = None) -> ShortLink:
        # Custom alias: user owns the code -> a clash is a hard error (can't overrule them).
        if custom_code:
            short_link = ShortLink(long_url=long_url, short_code=custom_code,
                                   created_at=datetime.now(timezone.utc), expiry_date=expiry_date)
            if not self.repository.save_if_absent(short_link):
                raise ValueError(f"Custom code '{custom_code}' already exists.")
            return short_link

        # Generated code: machine owns the code -> a clash just means "roll again".
        while True:
            short_code = self.code_generator.generate_short_code(long_url)
            short_link = ShortLink(long_url=long_url, short_code=short_code,
                                   created_at=datetime.now(timezone.utc), expiry_date=expiry_date)
            if self.repository.save_if_absent(short_link):
                return short_link

    def disable(self, short_code: str) -> None:
        # Soft-delete: flip the flag and persist. This is the caller that justifies save().
        short_link = self.repository.find_by_short_code(short_code)
        if short_link is None:
            raise ValueError(f"No link found for code '{short_code}'.")
        short_link.is_disabled = True
        self.repository.save(short_link)  # persist the mutation (the 'update' primitive)

    def resolve(self, short_code: str) -> Optional[ShortLink]:
        short_link = self.repository.find_by_short_code(short_code)
        if short_link and short_link.is_active():
            with self.click_lock:  # guard ONLY the read-modify-write
                short_link.click_count += 1
            return short_link
        return None


url_shortener_service = URLShortenerService(code_generator=Base62CodeGenerator(), repository=InMemoryURLRepository())   

short_link = url_shortener_service.shorten("https://www.example.com")
print(short_link)  # Should print the ShortLink object with long_url, short_code, created_at, etc.
print(url_shortener_service.resolve(short_link.short_code))  # Should print the ShortLink object with click_count incremented     
