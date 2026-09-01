# URL Shortener — Diagrams

## 1. Class diagram

```mermaid
classDiagram
    class ShortLink {
        +str long_url
        +str short_code
        +datetime created_at
        +datetime expiry_date
        +int click_count
        +bool is_disabled
        +is_expired() bool
        +is_active() bool
    }
    class ShortCodeGenerator {
        <<abstract>>
        +generate_short_code(long_url) str
    }
    class Base62CodeGenerator {
        -int counter
        -Lock counter_lock
    }
    class RandomCodeGenerator {
        +CODE_LENGTH = 7
    }
    class URLRepository {
        <<abstract>>
        +save(link)
        +find_by_short_code(code) ShortLink
        +save_if_absent(link) bool
    }
    class InMemoryURLRepository {
        -dict storage
        -Lock storage_lock
    }
    class URLShortenerService {
        -Lock click_lock
        +shorten(url, custom?, expiry?) ShortLink
        +resolve(code) ShortLink
        +disable(code)
    }

    ShortCodeGenerator <|-- Base62CodeGenerator
    ShortCodeGenerator <|-- RandomCodeGenerator
    URLRepository <|-- InMemoryURLRepository
    URLShortenerService --> ShortCodeGenerator : uses (DI)
    URLShortenerService --> URLRepository : uses (DI)
    URLShortenerService ..> ShortLink : creates
```

## 2. ShortLink states

```mermaid
stateDiagram-v2
    [*] --> ACTIVE : shorten()
    ACTIVE --> EXPIRED : expiry_date passed<br/>(lazy check, no job needed)
    ACTIVE --> DISABLED : disable()
    EXPIRED --> [*] : resolve returns None
    DISABLED --> [*] : resolve returns None
```

> These aren't stored as a status field — they're **computed** from `expiry_date` and `is_disabled`
> via `is_active()`. Cheap, and never goes stale.

## 3. `shorten()` — same clash, opposite reaction

```mermaid
flowchart TD
    A[shorten long_url, custom_code?] --> B{custom_code given?}
    B -->|YES - user owns it| C[build ShortLink]
    C --> D{save_if_absent?}
    D -->|taken| E[RAISE ValueError<br/>can't overrule the user]
    D -->|ok| F[return link]
    B -->|no - machine owns it| G[generate code]
    G --> H[build ShortLink]
    H --> I{save_if_absent?}
    I -->|taken| G
    I -->|ok| F

    style E fill:#5c1a1a,color:#fff
    style G fill:#2d5016,color:#fff
```

**The rule: who owns the input decides the reaction.**
User picked it → **raise**. Machine picked it → **retry**.

## 4. Why `save_if_absent` and not `exists()` + `save()`

```
   exists() + save()  =  TWO operations, a GAP between them

   Thread A: exists("abc")? -> free ✓
                                        <- Thread B: exists("abc")? -> free ✓
   Thread A: save(...)                  <- Thread B: save(...)   💥 one link lost

   save_if_absent()   =  ONE operation, no gap
   ┌────────────────────────────┐
   │ with lock:                 │   Thread B waits at the door
   │   if code in storage: NO   │   until A is completely done
   │   storage[code] = link     │
   │   return YES               │
   └────────────────────────────┘
```

Same shape at every scale: `INSERT ... ON CONFLICT DO NOTHING` (SQL), `SET key val NX` (Redis),
`PutItem(attribute_not_exists)` (DynamoDB).
