# Problem 1: URL Shortener (LLD)

## The prompt (as an interviewer would give it)

> "Design a URL shortener, like TinyURL or bit.ly. A user gives a long URL and gets back a
> short one; hitting the short URL redirects to the original."

That's it. Deliberately vague. **Your job is to make it concrete** — that's Step 1.

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **Custom aliases** — can a user pick their own short code (`bit.ly/my-brand`)? *(Forces the raise-vs-retry fork in `shorten`.)*
2. **Expiry** — do links have a TTL? Can they be disabled/soft-deleted?
3. **Analytics** — track click counts? How detailed — just a count, or per-click metadata?
4. **Deployment** — single process, or many servers? *(Decides whether an in-process counter/lock is even valid.)*
5. **Storage** — in-memory for now, but must it swap to a real DB later? *(The Repository signal.)*
6. **Code format** — any length limit? Do codes need to be unguessable, or is sequential fine? *(Picks the generation strategy.)*
7. **Scale** — rough read:write ratio? *(Read-heavy changes everything at HLD.)*

## Clarifications (locked scope from Q&A)
1. **Custom alias:** yes, optional — user may supply their own code.
2. **Expiry:** yes, optional TTL; links can also be **disabled** (soft-delete, kept for records).
3. **Analytics:** a simple **click count** only — no per-click metadata.
4. **Deployment:** single process for the LLD, but the design must survive going distributed.
5. **Storage:** in-memory now, **swappable to a real DB with no logic rewrite**. ← *Repository signal*
6. **Code format:** short (~7 chars), URL-safe. Guessability isn't critical, but note the tradeoff.
7. **Scale:** heavily **read-dominated** (~100:1 resolve:shorten).

---

## Step 1 — Requirements  ✅ LOCKED

### Functional (what it DOES — the verbs)
- [x] Shorten: long URL → short code
- [x] Resolve: short code → long URL (redirect)
- [x] Track click / redirect count per link
- [x] Expiry: a link can have a TTL and become invalid
- [x] Disable: a link can be turned off (soft-delete, kept for records)
- [x] Custom alias (optional): user picks their own short code

### Non-functional (constraints — the "-ilities")
- [x] **Thread-safe** — concurrent shorten/resolve must not corrupt state  ← changes the code
- [x] Persistence: in-memory now, but swappable to a real DB with no logic rewrite
- [x] Extensible — easy to add new shortening algorithms
- [x] Testable, low coupling / high cohesion

### Explicitly out of scope (say this out loud — it's a senior move)
- [x] Authentication
- [x] Full analytics (only a simple click count is in scope)
- [x] User management
- [x] Real HTTP server, distributed / multi-machine scaling

---

## Step 2 — Entities  ✅ LOCKED
_Format: `Name — single responsibility — key attributes/methods`_

1. **ShortLink** — holds one link's state (the core noun) — `long_url, short_code, created_at, expires_at?, click_count, is_active`
2. **ShortCodeGenerator** — produces a short code (the algorithm lives here) — `generate() -> str`
3. **URLRepository** — stores & fetches links (hides storage) — `save(link), find_by_code(code)`
4. **URLShortenerService** — orchestrator; delegates to the three above — `shorten(url), resolve(code)`

> Note: originally I had one `URLShortener` doing shorten + retrieve + validate. That's 3 jobs →
> split by Single Responsibility Principle into the generator, repository, and orchestrator.

---

## Step 3 — Relationships & APIs  (in progress)
_Label each arrow with the relationship type._

```
URLShortenerService
    ├── uses ──▶ ShortCodeGenerator   (asks it for a code)
    ├── uses ──▶ URLRepository        (asks it to save / fetch)
    └── creates ─▶ ShortLink          (wraps the code+url into a link, then stores it)
```

Public API (signatures = the design; write these before bodies):
- `shorten(long_url: str, custom_alias: str | None = None) -> str`   # returns short_code
- `resolve(short_code: str) -> str`                                  # returns long_url, raises if expired/disabled

---

## REST API mapping  (LLD method -> HLD endpoint)

> In an **LLD round** "the API" = the **method signatures** above. This block is the **HLD view** of
> the same thing — keep them separate in your head, but be able to map one to the other on demand.

| LLD method | HTTP |
|---|---|
| `shorten(long_url, custom_code?, expiry?)` | `POST /api/v1/urls` -> **201** `{short_code}` · **409** alias taken *(the RAISE branch; generated-code collisions retry internally and never reach the caller)* |
| `resolve(short_code)` | `GET /{code}` -> **302** `Location: <long_url>` *(302 not 301, so clicks are counted)* · **404** unknown · **410** Gone (expired/disabled) |
| `disable(short_code)` | `DELETE /api/v1/urls/{code}` -> **204** |

`save_if_absent` never becomes an endpoint — it is the storage primitive under `POST /urls`
(`INSERT ... ON CONFLICT DO NOTHING` at scale).

## Notes / decisions (log the "why" here)
- Repository pattern chosen so storage (dict today, DB tomorrow) is swappable — supports the
  "no logic rewrite" requirement via Dependency Inversion.
- Generator kept separate so the algorithm is replaceable → sets up the Strategy pattern.
