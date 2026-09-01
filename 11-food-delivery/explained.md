# Food Delivery

---

## Problem kya hai

Customer order karta hai, restaurant banata hai, partner pahunchata hai. Beech mein chaar sawaal:
**paisa kitna**, **partner kaun**, **kaun sa transition legal hai**, **kisko batana hai**.

Chaaron ka jawab alag pattern hai. Is capstone ka test "Observer aata hai kya" nahi — test yeh hai:
**kaun sa hissa kaun sa pattern maangta hai, aur unhe ulajhne kaise nahi dena.**

---

## Pehla instinct

```python
class FoodDeliveryService:
    def update_status(self, order, new_status):
        if new_status == "ACCEPTED":
            order.status = "ACCEPTED"
            customer.notify(...); restaurant.notify(...)
        elif new_status == "PREPARING":
            ...

    def assign(self, order):
        for p in self.partners:                  # list scan
            if p.status == "AVAILABLE":
                p.status = "BUSY"                # <- yahin race hai
                return p

    def price(self, order):
        return sum(...) + 50                     # 50 hardcoded
```

**1. "Surge pricing daalo."** → `price` edit. **"Weekend rate."** → phir edit.
**2. "Nearest do, list ka pehla nahi."** → `assign` edit. **"Ab least-busy."** → phir edit.
**3. "PREPARING ke baad cancel ho sakta hai?"** → jawab `if/elif` mein bikhra hai. State machine
**exist karti hai, likhi kahin nahi** — wahi shikayat jo elevator mein thi.
**4. "Slack pe bhi alert."** → `update_status` edit. Jo function order ke baare mein hai, use SMTP ka
pata kyun ho?

Dikkat ek hi hai — **chaar axis of change, chaaron ek hi class mein**:

| Kya badalta hai | Kya alag hai | Jawab |
|---|---|---|
| Price nikaalne ka tareeka | **behaviour** | Strategy |
| Partner chunne ka tareeka | **behaviour** | Strategy |
| Kaun sa transition legal hai | sirf **data** | enum + table |
| Kaun react karta hai | bas *kaun* | Observer |

---

## Pricing — pehli Strategy

`PricingStrategy.calculate(order) -> Decimal`. `StandardPricing` = `OrderItem` subtotals + flat fee;
`SurgePricing` usi ka subclass, sirf fee multiply karta hai. `OrderService` ko fee ka number **pata hi
nahi** — `place_order` bas `self.pricing.calculate(order)` bulata hai. Demo mein **ek class swap** se
amount 710 → 810, matlab swap asli hai. Paisa `Decimal`, `float` nahi — Splitwise wali seekh.

---

## Partner kaun — doosri Strategy

`find_partner(order, partners, radius_km) -> Optional[DeliveryPartner]`. `NearestPartnerStrategy`:
`AVAILABLE` partners mein se jo **restaurant** ke `radius_km` mein sabse paas ho — customer ke paas
wala nahi, **pickup pehle hota hai**. Distance `Location.distance_km()` (haversine).

**Asli line yahan:** *strategy sirf chunti hai, claim service karti hai.* `min(...)` return hota hai,
`status = BUSY` yahan **nahi**. Warna **har nayi strategy ko locking dobara theek se likhni padegi**,
aur ek galti ek partner do orders ko de degi. Concurrency ek jagah rahe — orchestrator mein. Wahi
separation jo parking mein tha.

---

## Lifecycle — aur yahan State pattern **nahi**

Sabse kaam ki baat, kyunki dikhne mein yeh bilkul elevator jaisa lagta hai.

| | Elevator | Food delivery |
|---|---|---|
| Har state pe kaam | IDLE kuch nahi, MOVING floor badalta, DOOR_OPEN utaarta — **teen alag kaam** | har transition ka shape **same**: validate → set → publish |
| Toh alag kya hai | **behaviour** | sirf **kaun sa transition legal hai** |
| Jawab | State pattern | **enum + `ALLOWED_TRANSITIONS`** |

```python
ALLOWED_TRANSITIONS = {
    OrderStatus.PLACED:    {OrderStatus.ACCEPTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED:  {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY},       # CANCELLED nahi - khaana ban raha hai
    OrderStatus.READY:     {OrderStatus.PICKED_UP},
    OrderStatus.PICKED_UP: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(), OrderStatus.CANCELLED: set(),      # terminal
}
```

Yeh table hi **poori state machine hai** — ek jagah padho, ek line badlo. Gate bhi ek hi hai:
`_transition()` `order.can_transition_to(to)` poochta hai (jo table padhta hai), warna
`InvalidTransitionError`. `accept_order`, `reject_order`, `advance`, `cancel_order` sab isi se guzarte
hain — isliye poori service mein kahin `if order.status == ...` nahi. `cancel_order` ko alag
"PREPARING check" likhna hi nahi pada; table khud mana kar deta hai.

> **Caveat zaroor bolna:** *"agar states apna kaam karne lage — PREPARING khud timer start kare, READY
> khud assignment trigger kare — toh data behaviour ban jaayega aur main State pattern pe jaunga."*
> Yeh line batati hai ki shortcut nahi maara, **test lagaya** hai.

- **Ek honest exception:** `advance` mein `if to is OrderStatus.DELIVERED: self._free_partner(order)`
  — yehi ek jagah hai jahan ek transition apna extra kaam karta hai (`cancel_order` bhi). Abhi ek
  line hai isliye chalta hai; do-teen aise branches aa gaye toh **wahi State pattern ka signal** hai.
  Note: yeh branch `to` pe hai, `order.status` pe nahi — status-based `if` service mein sach mein
  kahin nahi.

---

## Kisko batana hai — Observer

```python
customer.notify(...); restaurant.notify(...); partner.notify(...)   # service sabko jaanti hai
self._publish(OrderEventType.STATUS_CHANGED, order)                 # service kisi ko nahi jaanti
```

- `EventBus` = `dict[OrderEventType, list[Subscriber]]`, aur `Subscriber` ka `handle()`
  `@abstractmethod` hai — **yehi bus ko anjaan rehne deta hai.**
- Clarification #3 ("sirf relevant actors") code mein `if` nahi bani, **subscription lines** bani:
  `CustomerNotifier` har event pe, `RestaurantNotifier` sirf `ORDER_PLACED` pe, `PartnerNotifier` sirf
  `PARTNER_ASSIGNED` pe. Routing ab wiring hai, logic nahi. Service khud teen notifiers bulaati toh SMS
  notifier add karne ke liye **chalta hua order flow dobara kholna padta**; ab diff zero hai.
- **Bulkhead:** `publish` har `handle()` ko apne `try/except` mein bulata hai — ek toota listener baaki
  sabko nahi le doobta. (07 ka jaanbujhkar chhoda gap, yahan band.) Aur list ki **copy lock ke andar**
  banti hai, `handle()` lock **chhod ke** chalta hai: slow I/O bus block na kare, aur handler khud
  `subscribe()` kare toh deadlock na ho — `threading.Lock` reentrant nahi hai. Yeh baat wapas aayegi.

---

## Do orders, ek partner

`find_partner()` ne AVAILABLE partner return kiya → **gap** → `partner.status = BUSY`. Us gap mein
doosra thread bhi usi ko AVAILABLE dekh leta hai. Ek partner, do orders.

Yeh track mein **saatvi baar** hai, har baar wahi shape:
`exists+save · find+claim · get+set · balance+= · matchmaking · check+hold · **find_partner+BUSY**`

Fix bhi wahi: **check aur act ek hi critical section mein.**

```python
with self._lock:
    for radius_km in (2, 5, 8):
        partner = self.assignment.find_partner(order, self._partners, radius_km)
        if partner is not None:
            partner.status = PartnerStatus.BUSY      # <- CLAIM, usi lock ke andar
            order.partner = partner
            return partner
```

Demo: 200 threads ek partner pe toot padte hain → **exactly 1 winner, 199 pending**.

HLD mein `Lock` bekaar hai (do machines, do lock). Wahan wahi universal jawab: **atomicity shared store
ke andar push karo** — Redis `SETNX`/Lua, ya `UPDATE partners SET status='BUSY' WHERE id=? AND
status='AVAILABLE'` aur rowcount dekho.

---

## Koi nahi mila — radius badhao, cancel mat karo

- **2 km pehle kyun:** khaana garam pahunchana hai. Ideal se shuru, majboori mein failao.
- **Teeno attempts ek hi lock mein kyun:** find→claim ek unit hai. Beech mein lock chhoda toh 5 km wale
  attempt ke waqt 2 km wala partner kisi aur ne utha liya hoga — tum baasi scan pe claim karoge.
- **Kuch na mila:** order `_pending` mein park, `NO_PARTNER_FOUND` publish, order **zinda**.

Auto-cancel **fail-closed** hota, aur woh galat call hai. Rate limiter fail-open hai, payments
fail-closed. Yahan khaana ban chuka hai aur paisa aa chuka hai — "abhi partner nahi mila" **temporary**
condition hai; usse permanent failure banana kiya hua kaam barbaad karna hai. Toh **fail-open**: park
karo, koi free ho toh de do. Aur `if order not in self._pending` — retry pe wahi order queue mein do
baar na ghuse; at-least-once wala mini **dedup key**.

---

## `_free_partner` ka handoff — aur deadlock ka trap

```python
with self._lock:
    partner.status = PartnerStatus.AVAILABLE
    order.partner = None
    waiting = self._pending.pop(0) if self._pending else None    # FIFO

if waiting is not None:
    self.assign_partner(waiting.order_id)        # <- LOCK KE BAAHAR
```

Aakhri line indent ke ek level se bug ban jaati hai. `assign_partner` **wahi lock** leta hai, aur
`threading.Lock` **reentrant nahi hai** — same thread dobara maange toh apne hi lock ka wait karega.
Koi exception nahi, koi message nahi, bas **thread hamesha ke liye latka**. Rule: **lock ke andar sirf
shared state badlo, kaam bahar karo** — `EventBus` ne bhi yehi kiya.

Ek honest gap bacha hai: `assign_partner` ka `_publish` abhi **lock ke andar** chalta hai. Notifiers
sirf print karte hain isliye chal raha hai, par koi subscriber wapas `OrderService` ko call kare toh
wahi deadlock. Saaf shape: events lock ke andar collect karo, release ke baad publish.

---

## Interview line

> *"Chaar axis of change, chaar jawab. Pricing aur matching mein **behaviour** badalta hai — dono
> Strategy, aur strategy sirf chunti hai; `BUSY` claim service lock ke andar karti hai. Lifecycle mein
> behaviour nahi badalta — har transition ka kaam ek hi shape ka hai (validate → set → publish), sirf
> **kaun sa legal hai** woh alag, aur woh data hai — isliye enum + `ALLOWED_TRANSITIONS`, State pattern
> nahi; states khud kaam karne lage toh State pe jaunga. Notifications ke liye service kisi notifier ko
> call nahi karti, publish karti hai. Race sirf ek jagah hai — `find_partner` aur `BUSY` ke beech — woh
> ek critical section mein hai; aur partner na milne pe order cancel nahi, pending queue mein park
> hota hai."*
