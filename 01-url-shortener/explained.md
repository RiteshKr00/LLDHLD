# URL Shortener

> Yeh file `solution.py` ko line-by-line nahi, **soch ke level pe** samjhati hai.

---

## Problem kya hai

Bahut simple: koi tumhe ek lamba URL deta hai —
`https://www.amazon.in/some-product?ref=xyz&tracking=abc123...`

Tum usko chhota bana ke wapas do — `bit.ly/b`. Aur jab koi us chhote wale pe click kare, toh usko
original wale pe bhej do.

Bas do kaam: **chhota banao** (`shorten`) aur **wapas kholo** (`resolve`).

---

## Pehla instinct (jo galat nahi hai, bas kaafi nahi hai)

Tum shayad yeh likhoge — aur honestly, yeh **chalta hai**:

```python
class URLShortener:
    def __init__(self):
        self.urls = {}       # code -> long_url
        self.counter = 0

    def shorten(self, long_url):
        self.counter += 1
        code = str(self.counter)
        self.urls[code] = long_url
        return code

    def resolve(self, code):
        return self.urls[code]
```

Ab interviewer 4 sawaal poochega, aur har sawaal pe yeh code toot jayega:

**1. "Codes guess na ho paayein, aisa kar sakte ho?"**
→ `1, 2, 3...` toh koi bhi guess kar lega. Change karne ke liye tumhe `shorten` **edit** karna padega.

**2. "Hum Postgres pe shift kar rahe hain."**
→ `self.urls = {}` poori class mein ghusa hua hai. `shorten` bhi edit, `resolve` bhi edit.

**3. "User ko apna custom code chahiye — `bit.ly/ritesh`."**
→ Pass karne ki jagah hi nahi hai. Aur agar zabardasti daal bhi do, toh agar woh code pehle se kisi
ka hai, tumhara code **chupchaap uske upar likh dega**. Uska link mar gaya, aur kisi ko pata bhi nahi
chalega.

**4. "Do requests ek saath aa gaye toh?"** ← yeh wala sabse important hai
→ Thread A ne padha `counter = 5`. Thread B ne bhi padha `5` (A ne abhi likha nahi tha).
Dono ne `6` likh diya. **Do alag URLs, ek hi code.** Ek link silently gayab.

---

## Asli problem: teen kaam ek jagah phase hue hain

Us chhoti si class ke andar teen bilkul alag kaam hain:

1. **Code banana** (algorithm)
2. **Store karna** (storage)
3. **Dono ko coordinate karna** (orchestration)

Isliye koi bhi cheez change karo, poori class hilti hai. Solution seedha hai — **teeno ko alag karo**.

---

## Ab entities dekho

### 1. `ShortLink` — sirf data
```python
@dataclass
class ShortLink:
    long_url, short_code, created_at
    expiry_date, click_count, is_disabled
```
Yeh koi kaam nahi karta, bas ek link ki information rakhta hai. Sirf do chhote methods:
`is_expired()` aur `is_active()`.

**Kyun methods rakhe?** Kyunki bahar wale code ko yeh na poochna pade "expiry date kya hai, aaj ki
date kya hai, compare karo..." — object khud batayega ki main zinda hoon ya nahi. Isko
**"Tell, Don't Ask"** kehte hain.

> **Chhota trap:** `datetime.now()` mat likhna, `datetime.now(timezone.utc)` likhna. Warna
> timezone-aware aur naive date compare karne pe Python `TypeError` de dega.

### 2. `ShortCodeGenerator` — Strategy pattern
Requirement thi: *"naye algorithms aasani se add ho sakein."* Yeh line hi **Strategy ka signal** hai.

```python
class ShortCodeGenerator(ABC):
    def generate_short_code(self, long_url) -> str: ...

class Base62CodeGenerator(...):   # counter -> base62. Chhota, collision nahi. Par guessable.
class RandomCodeGenerator(...):   # random 7 chars. Guess nahi kar sakte. Par collide ho sakta hai.
```

**Base62 kyun, base64 kyun nahi?** Base64 mein `+ /  =` hote hain — URL mein yeh characters problem
karte hain. Base62 = sirf `A-Z a-z 0-9`. Safe.

> **Yahan maine over-engineering ki thi** — 6 strategies bana diye the. Interview mein **ek banao,
> baaki naam le lo**. Aur `CustomCodeGenerator` toh galat hi tha — custom alias user **deta** hai,
> generate nahi hota. Isko **YAGNI** kehte hain: jo abhi chahiye nahi, mat banao.

### 3. `URLRepository` — Repository pattern
Requirement thi: *"abhi memory, baad mein DB, bina logic badle."* Yeh **Repository ka signal** hai.

```python
class URLRepository(ABC):
    def save(...)                  # update karne ke liye
    def find_by_short_code(...)    # dhoondhne ke liye
    def save_if_absent(...) -> bool  # <- yeh wala magic hai, neeche padho
```

> **Verb test yaad rakhna:** `save/find/exists` — yeh **storage ke verbs** hain, repository mein
> jaayenge. `shorten/resolve` — yeh **domain ke verbs** hain, service mein jaayenge. Maine pehle
> repository mein `shorten` likh diya tha — galat.

### 4. `URLShortenerService` — orchestrator
Yeh dono ko inject karke leta hai (**Dependency Injection**):

```python
def __init__(self, code_generator, repository):   # bahar se aa rahe hain
```

Andar `InMemoryURLRepository()` **mat banao** — tab woh class us ek implementation se chipak jayegi,
aur test karna namumkin ho jayega.

---

## Sabse important cheez: `save_if_absent`

Yeh samajh liya toh aadhi LLD samajh gaye.

**Problem:** code dena hai, par pehle check karna hai ki free hai ya nahi.

```python
if not repo.exists(code):      # <- check
    repo.save(link)            # <- act
```

Yeh galat hai. Kyun? Do threads dono `exists()` chalayenge, dono ko "free hai" milega, dono `save`
kar denge. Beech mein **gap** hai. Isko **TOCTOU** kehte hain — *Time Of Check To Time Of Use*.

**Fix:** check aur save ko **ek hi operation** bana do:

```python
def save_if_absent(self, short_link) -> bool:
    with self.storage_lock:              # ek hi lock, dono steps ke liye
        if short_link.short_code in self.storage:
            return False                 # code busy hai
        self.storage[short_link.short_code] = short_link
        return True                      # mil gaya
```

Ab beech mein gap hi nahi hai. Aur sabse badhiya baat — **yeh scale pe bhi kaam karta hai**:

| Kahan | `save_if_absent` banta hai |
|---|---|
| Memory (abhi) | lock + check-and-set |
| Postgres | `UNIQUE(code)` + `INSERT ... ON CONFLICT DO NOTHING` |
| Redis | `SET code url NX` |
| DynamoDB | `PutItem(attribute_not_exists)` |

Service ka code **kabhi nahi badalta**. Sirf repository badalta hai.

---

## `shorten` ka asli logic (yeh line interview jitwa degi)

```python
def shorten(self, long_url, custom_code=None):
    if custom_code:                                    # user ne apna code diya
        link = ShortLink(long_url, custom_code, now())
        if not self.repository.save_if_absent(link):
            raise ValueError("code already taken")     # RAISE
        return link

    while True:                                        # machine khud bana raha hai
        code = self.code_generator.generate_short_code(long_url)
        link = ShortLink(long_url, code, now())
        if self.repository.save_if_absent(link):
            return link                                # RETRY jab tak na mile
```

Dhyan do — **same problem, ulta reaction**:

| Case | Code kiska? | Clash hone pe |
|---|---|---|
| Custom alias | **User ka** | **Raise** — user ki choice badal nahi sakte |
| Generated | **Machine ka** | **Retry** — dobara bana lo, kisi ko farak nahi padta |

Interview mein bolna: *"reaction is decided by **who owns the input**."* Yeh senior-level line hai.

---

## Interview mein kaise present karna

1. **Scope** — requirements bolo, aur **out of scope** bhi bolo (auth nahi, distributed nahi). Yeh
   senior move hai.
2. **Entities** — 4 nouns, har ek ka ek kaam (SRP).
3. **Flow** — `shorten` = generate → claim → return. `resolve` = find → active? → count.
4. **Decisions** — har pattern ka **kyun** batao:
   - Strategy → algorithm badalna ho toh service ko haath na lagana pade
   - Repository → storage badalna ho toh logic na badle
   - DI → test kar sako
   - `save_if_absent` → atomic, aur distributed pe bhi chalega
5. **Edge cases** — collision, expiry, disable, lock kahan hai.
6. **"Aur time hota toh"** — 404 vs 410 error semantics, alias validation, async click analytics, tests.

**Final line jo dono rounds jeet legi:**
> *"`Repository` interface aur `save_if_absent` isliye chune, taaki yahi code dict se DynamoDB pe jaa
> sake — service badalta hi nahi, sirf repository implementation badalti hai."*
