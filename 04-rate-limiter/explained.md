# Rate Limiter

> **Is problem ka core:** algorithm alag, storage alag — aur atomicity kahan rehti hai.

---

## Problem kya hai

Ek user API ko bar-bar hit na kar sake. Maan lo limit hai: **50 requests per minute, per endpoint**.
51st request pe → **429 Too Many Requests**.

---

## Pehla instinct

```python
counts = {}

def allow(user):
    counts[user] = counts.get(user, 0) + 1
    return counts[user] <= 50
```

Chalta hai... 30 second ke liye. Phir:

**1. Window kabhi reset hi nahi hota.**
User ki 51st request block hui. Ab agla din bhi block. Yeh **rate** limiter nahi hai, yeh **lifetime
quota** hai. Requirement mein "per minute" tha — us shabd ke peeche **koi code hi nahi** hai.

**2. Tum 3 servers pe deploy karte ho.**
Har server ka apna `counts` dict hai. User ko har server pe 50 milte hain = **150 requests**.
Tumhari limit chupchaap **3 guna** ho gayi, aur monitoring mein kuch nahi dikhega.

**3. "Thoda burst allow karo, phir throttle."**
→ Bilkul alag algorithm chahiye. Poora rewrite.

**4. Do requests ek saath.**
Dono ne `49` padha, dono ne `50` likha, dono allow. **51 nikal gaye.**

---

## Asli seekh: do cheezein alag hain

Us 3-line function mein **do bilkul alag cheezein** ghusi hui hain:

1. **Ginne ka rule** (algorithm) — fixed window? sliding? token bucket?
2. **Ginti kahan rakhi hai** (storage) — memory? Redis?

Inko alag karna hi is poore design ka point hai. Kyun? Kyunki:

> Algorithm **same rehta hai** chahe woh ek process pe chale ya 10 servers pe.
> Sirf **storage** badalta hai.

```python
class RateLimitAlgorithm(ABC):        # ginne ka rule
    def allow_request(self, key, rule) -> bool: ...

class StateStore(ABC):                 # ginti kahan hai
    def increment(self, key, window_seconds) -> int: ...
```

Algorithm ko store **inject** hota hai (DI). Algorithm ke paas **apna koi dict ya lock nahi hota** —
saara state store mein hai. Isliye:

```
InMemoryStore  -> ek process, dev/test
RedisStore     -> saare servers ek hi counter share karte hain
```
...aur algorithm class **ek line bhi nahi badalti**.

---

## Teen algorithms — kaunsa kab

### 1. Fixed Window Counter (sabse sasta)
Har clock-minute ka ek counter, minute badalte hi reset.

**Dikkat — boundary burst:**
```
11:00:59 pe 50 requests   -> allowed (us minute ka counter 50)
11:01:00 pe 50 requests   -> allowed (naya minute, counter 0 se shuru)
```
Matlab **~1 second mein 100 requests** nikal gaye, aur dono windows "legal" hain. Limit 50/min thi.

### 2. Sliding Window Counter (best default)
Pichhli window ko **weight** deta hai — kitna hissa abhi bhi "current" hai.
```python
estimated = curr_count + prev_count * (1 - elapsed_fraction)
```
Boundary burst khatam, aur memory sirf 2-3 numbers. **Yeh usually sahi choice hai.**

### 3. Token Bucket (alag maqsad)
Ek balti mein tokens hain (shuru mein full). Har request ek token uthati hai. Tokens **dheere-dheere
bharte** rehte hain.

**Yeh strictness ke liye nahi, burst ke liye hai.** Matlab: *"agar tum shaant baithe the toh ek saath
50 kar lo, uske baad steady rate pe aa jao."* Photo upload jaisi cheezon ke liye perfect.

> **Interview mein asli sawal yeh nahi hai "kaunsa accurate hai"** — sawal yeh hai:
> **"tumhe kaisa traffic chahiye?"** Hard cap? → sliding window. Burst allow karke phir throttle?
> → token bucket. Yeh bolna hi senior answer hai.

---

## ISP — har algorithm ka apna store

Yeh chhoti si baat hai par acchi hai. Teeno algorithms ko **alag-alag data** chahiye:

| Algorithm | State kya chahiye |
|---|---|
| Fixed Window | ek counter |
| Token Bucket | tokens + last-refill-time |
| Sliding Window | current count + previous count + window start |

Toh ek **fat interface** banane ki jagah (jismein sab kuch ho aur har store aadhe methods fake kare),
**har algorithm ka apna chhota store interface** banaya:

```python
class StateStore(ABC):          def increment(...)
class TokenBucketStore(ABC):    def consume(...)
class SlidingWindowStore(ABC):  def record(...)
```

Isko **Interface Segregation (ISP)** kehte hain — *"bahut chhote interfaces > ek mota interface."*
Wahi seekh jo URL shortener mein `exists()` hatane pe mili thi.

---

## Sabse zaroori part: atomicity kaun deta hai

### Ek process mein — lock
```python
def increment(self, key, window_seconds):
    now = time.time()
    with self.lock:                                    # <- yeh poora block ek unit hai
        count, expiry = self.state.get(key, (0, 0))
        if now >= expiry:
            count, expiry = 0, now + window_seconds
        count += 1
        self.state[key] = (count, expiry)
        return count
```

Bina lock ke: Thread A padhta hai `49`, B bhi `49` padh leta hai (A ne abhi likha nahi), dono `50`
likhte hain. **Ek increment gum ho gaya.**

Lock ka matlab: **A jab tak `with` block ke andar hai, B `with` line pe hi ruk jayega.** Toh B ka
read A ke write ke **baad hi** hoga.

### Kayi servers pe — lock bekaar hai
`threading.Lock` sirf **ek process ke andar** kaam karta hai. Do servers = do alag locks, do alag
dicts. Ek dusre ko jaante hi nahi. **Lock kuch bhi protect nahi kar raha.**

Toh atomicity kaun dega? **Jo cheez sab servers share karte hain — Redis.**

---

## Redis + Lua (yeh naya tha, dhyan se)

**Redis single-threaded hai.** Matlab ek command poori chalti hai, tab agli shuru hoti hai. Isliye
**ek single command apne aap atomic hai** — `INCR key` kabhi race nahi kar sakta. Redis khud hi lock
hai.

**Par dikkat:** hume do kaam karne hain — increment **aur** TTL set karna (pehli baar). Do alag
commands ke **beech mein** koi aur client ghus sakta hai:

```
INCR count        ✓ atomic
   <- yahan koi aur command aa sakti hai
EXPIRE count 60   ✓ atomic
```
Agar beech mein crash ho jaye toh key **bina TTL ke** reh jayegi — hamesha ke liye.

**Solution: Lua script.** Redis ke andar Lua ka interpreter hai. Poori script **ek single command
ki tarah** chalti hai — beech mein kuch nahi ghus sakta:

```lua
local count = redis.call('INCR', KEYS[1])
if count == 1 then                                -- pehli baar? matlab nayi window
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
```

- `KEYS[1]` = key ka naam (parameter)
- `ARGV[1]` = window seconds (parameter)
- `count == 1` = trick hai — `INCR` sirf **pehli baar** `1` return karta hai (0 se 1), matlab window
  abhi shuru hui

> **Pipeline ≠ atomic!** Pipeline sirf network round-trips bachata hai, commands phir bhi alag-alag
> chalti hain. Atomic chahiye toh **Lua**.

**Ek line mein:** *ek command Redis mein free mein atomic hai (single-threaded); jab do kaam **saath
mein** atomic chahiye, tab Lua script.*

---

## Wahi seekh, paanchvi baar

| Problem | Racy jodi | Store mein push kiya |
|---|---|---|
| URL shortener | `exists()` + `save()` | `save_if_absent` / `INSERT ON CONFLICT` |
| Parking | spot dhoondho + mark karo | ek critical section |
| **Rate limiter** | `get` + `set` | **Redis `INCR` / Lua** |
| Splitwise | `balance += x` | `UPDATE SET x = x + n` transaction mein |

**Har baar same jawab: atomicity ko neeche shared store mein push karo.**

---

## HLD mein kya badalta hai

Bahut kam! Bas store badalta hai:
- Rate limiter **API gateway mein middleware** ban jaata hai (har request se pehle check)
- `InMemoryStore` → `RedisStore` — ek line
- **Naya sawal: Redis hi mar gaya toh?**
  - **Fail-closed** (sab reject) → tumhara **poora API down**, jabki kisi ne limit todi bhi nahi
  - **Fail-open** (sab allow) → API zinda, bas kuch der unprotected
  - **Standard jawab: fail-open** — rate limiter ka kaam backend ko **bachana** hai, usko girane ka
    naya tareeka banna nahi

---

## Interview line

> *"Algorithm aur storage ko alag rakha — algorithm stateless logic hai, store mein state hai.
> Isliye single-process se distributed jaana sirf store badalne ka kaam hai, `RateLimiter` aur
> algorithm classes ek line bhi nahi badaltin. Atomicity in-process lock deta hai, distributed mein
> Redis Lua script."*
