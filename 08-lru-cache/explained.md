# LRU Cache

> **Yeh problem baaki sabse alag hai** — koi pattern nahi dhoondhna, **data structures** chunni hain.

---

## Problem kya hai

Ek cache banao jisme **fixed** number of items rahein — maan lo 100. Jab 101st item aaye, toh
**sabse purana istemal kiya hua** (Least Recently **Used**) item nikal do.

Aur ek hard requirement: **`get` aur `put` dono O(1)** hone chahiye.

Bas yehi ek requirement poora design decide kar deti hai.

---

## Pehla instinct

**Try 1 — sirf dict:**
```python
cache = {}
def get(key):    return cache.get(key)
def put(key, v): cache[key] = v
```
Lookup O(1) ✅. Par... **"sabse purana kaunsa hai"** yeh kaise pata karoge? Dict mein koi **order**
hi nahi hai. Evict karne ke liye order chahiye.

**Try 2 — dict + list (order ke liye):**
```python
order = []          # sabse aage = sabse recent
def get(key):
    order.remove(key)          # <- yahan dikkat hai
    order.insert(0, key)
    return cache[key]
```
Ab order toh hai, par `order.remove(key)` **O(n)** hai! Python ko pehle list mein `key` **dhoondhna**
padta hai (poori list scan), phir uske baad wale saare elements **shift** karne padte hain.

100 items ka cache hai toh chalega. 1 lakh ka cache? Har `get` pe 1 lakh steps. 💀

**Try 3 — sirf linked list:**
Linked list mein delete O(1) hai (agar node haath mein ho). Par **key se node dhoondhna** O(n) hai —
poori list chalni padegi.

---

## Asli jugaad: dono ko mila do

Dekho har structure mein kya kami hai:

| | Key se dhoondhna | Beech se delete | Order rakhna |
|---|---|---|---|
| **dict** akela | ✅ O(1) | ✅ O(1) | ❌ order hai hi nahi |
| **DLL** akeli | ❌ O(n) (dhoondhna padega) | ✅ O(1) *(node ho toh)* | ✅ |
| **Dono saath** | ✅ O(1) | ✅ O(1) | ✅ |

**Ek dusre ki kami puri kar rahe hain.** Dict ko order nahi pata, list ko dhoondhna nahi aata.

### Asli trick: dict mein **value nahi, NODE** rakho

```python
self._map: dict[key, Node] = {}      # <- key se seedha NODE milta hai
```

Yeh ek line hi poora khel hai:
```
get(key):
  node = self._map[key]         # O(1) — dict ne node de diya
  dll.remove(node)              # O(1) — node haath mein hai, dhoondhna nahi pada!
  dll.add_to_front(node)        # O(1)
  return node.value
```

Agar dict mein **value** rakhte, toh node dhoondhne ke liye **list chalni padti** = O(n). Bas woh
ek indirection — key→node instead of key→value — hi O(1) banata hai.

---

## **Doubly** linked kyun, singly kyun nahi?

Node `X` ko nikalna hai. Uske aage-peeche wale ko jodna padega:

```
... ⇄ [A] ⇄ [X] ⇄ [B] ⇄ ...

X hatane ke liye:  A.next = B   aur   B.prev = A
```

Matlab tumhe **`A` chahiye** — X ka **pichla** node.

- **Singly** list mein sirf `next` hota hai → `A` dhoondhne ke liye **shuru se chalna** padega → **O(n)** 💀
- **Doubly** mein `prev` bhi hai → `X.prev` seedha `A` de deta hai → **O(1)** ✅

**`prev` pointer hi woh cheez hai jo O(1) deletion kharidta hai.**

---

## Node apni `key` kyun rakhta hai? (classic bug)

Eviction aisa hota hai:
```python
victim = dll.remove_last()      # tail node mil gaya
del self._map[victim.key]       # <- iske liye victim.key CHAHIYE
```

Tumhare paas **node** hai (tail se aaya), par dict se hatane ke liye **key** chahiye.

Agar node mein key nahi rakhi, toh dict wali entry **hamesha padi rahegi**:
```
DLL:  chhoti hoti jayegi     ✓ (evict ho rahe hain)
dict: badhta jayega          ✗ (kabhi delete hi nahi hua)
```
Result: **memory leak**, aur `len(map)` galat hone se **capacity check bhi toot jaata hai** (cache
sochega woh full hai jabki list mein jagah hai).

**Rule: dono structures hamesha sync mein rehni chahiye.**

---

## Sentinel nodes — chhota trick, bada fayda

Head aur tail pe do **dummy nodes** rakho jo kabhi data nahi rakhte:

```
Bina sentinels:                    Sentinels ke saath:
  [A] ⇄ [B] ⇄ [C]                  head ⇄ [A] ⇄ [B] ⇄ [C] ⇄ tail
                                    ↑dummy                dummy↑

A hatana hai? Sochna padega:        A hatana hai?
  "A pehla hai? head badalna hai?     node.prev.next = node.next
   ya beech mein hai?                 node.next.prev = node.prev
   ya list khali hai?"                Bas. HAR case mein wahi 2 lines.
  → 4-5 if conditions 😩             → koi if nahi ✅
```

Sentinels ka **poora kaam** yeh hai ki **har real node ke hamesha `prev` aur `next` ho** — chahe woh
pehla ho, aakhri ho, ya akela. Isliye `if node is None` kahin likhna hi nahi padta.

---

## `get` ek WRITE hai (yeh counter-intuitive hai)

Normally `get` matlab "sirf padho". **LRU cache mein nahi.**

`get(key)` key ko **most-recently-used** bana deta hai — matlab **order badal raha hai** — matlab
yeh ek **write** hai.

Do nateeje:
1. **Reads pe bhi lock lagega.** "Read-only fast path" jaisi koi cheez yahan nahi hai.
2. Do threads ek saath `get` karein toh bhi race ho sakti hai.

---

## Do ordering traps (interview mein poochte hain)

### Trap 1: "key pehle se hai kya" — yeh check **pehle** karo

```python
put(key, value):
    if key in map:            # <- YEH PEHLE
        update kar do; return  # cache BADA nahi ho raha!
    if full:
        evict()
    insert()
```

Agar key already hai, toh tum sirf **value update** kar rahe ho — cache mein item count **wahi** rahega.
Toh evict karna bilkul galat hoga (bina wajah ek achhi entry phenk doge).

### Trap 2: **evict pehle, insert baad mein**

`capacity = 1` socho:
```
Galat (insert-then-evict):
  naya node head pe daala      → list: [naya]
  ab tail evict kiya           → head aur tail WAHI node hai!
  → jo abhi daala wahi nikal gaya → cache hamesha khali 💀

Sahi (evict-then-insert):
  pehle purana nikala          → list: []
  phir naya daala              → list: [naya] ✓
```

---

## Policy ko swappable banana (Strategy)

Requirement thi "LFU/FIFO baad mein aa sakte hain". Toh socho — **actually kya alag hai** teeno mein?

| Policy | `on_access` — key touch hui | `evict` — kisko nikaalein |
|---|---|---|
| **LRU** | front pe le aao | tail |
| **FIFO** | **kuch mat karo** | tail |
| **LFU** | frequency +1 | sabse kam frequency wala |

FIFO aur LRU mein **sirf ek line ka farak** hai — FIFO mein `on_access` khali hai. Bas.

---

## LFU ne ek design galti pakdi (yeh sabse achhi seekh hai)

Maine pehle interface aisa banaya tha:
```python
def on_access(self, dll, node)      # cache ne DLL pass kiya
def evict(self, dll)
```

LRU ✅ FIFO ✅ ... phir **LFU aaya aur bilkul fit nahi hua.**

**Kyun?** LFU ko "sabse kam frequency wala" O(1) mein chahiye. **Ek list se yeh possible hi nahi.**
LFU ko chahiye:
```
freq 1: [ D ] ⇄ [ C ]      <- min_freq = 1, yahin se evict
freq 2: [ A ]
freq 5: [ B ]
```
Matlab **har frequency ki apni list**, aur ek `min_freq` pointer.

Toh interface mein ek **chhupi hui assumption** thi: *"har policy ek hi linked list use karegi."*
Woh assumption **dikhi hi nahi** jab tak sirf LRU aur FIFO the — kyunki dono ek jaise the!

**Fix:** policy ko structure **do mat** — policy **apni structure khud rakhe**. Cache sirf dict
rakhta hai, aur policy se ek hi sawal poochta hai: *"ab kaun marega?"*

```python
def on_insert(node)      # naya node aaya
def on_access(node)      # purana node touch hua
def evict() -> Node      # tu bata kaun marega
```

> **Seekh (yeh interview mein bolne layak hai):** *"ek abstraction tab tak prove nahi hoti jab tak
> ek **doosri, genuinely alag** implementation na aa jaye. Do milti-julti implementations (LRU/FIFO)
> ek galat interface pe bhi aaram se raazi ho jaati hain."*

### LFU ka O(1) jugaad
- `freq → list` ka dict, aur ek `min_freq` pointer
- `on_access`: node ko `freq` wali list se nikaalo, `freq+1` wali mein daalo. Agar purani list khali
  ho gayi aur wahi `min_freq` thi → `min_freq += 1`
- `evict`: `min_freq` wali list ka **tail** (same frequency mein tie ho toh LRU se todo)
- Naya item hamesha `freq = 1` → `min_freq = 1`

---

## Interview line

> *"O(1) dono operations mein chahiye tha, aur akela koi structure yeh de nahi sakta — dict ko order
> nahi pata, linked list ko dhoondhna nahi aata. Toh dict mein **value nahi, node** rakha: dict node
> O(1) mein deta hai, DLL usko `prev` pointer se O(1) mein unlink karta hai. Node apni key rakhta hai
> taaki eviction ke waqt dict se bhi hata sakein — warna dict leak karega. Aur eviction policy ko
> Strategy banaya; LFU ne pakda ki mera pehla interface leaky tha, toh policy ko apni structure khud
> own karne di."*
