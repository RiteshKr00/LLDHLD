# Parking Lot

---

## Problem kya hai

Multi-floor parking. Gaadi aati hai → usko **fit hone wali** khali jagah do → ticket do.
Nikalte waqt → time dekho → paisa lo → spot free karo.

Sunne mein simple lagta hai. Asli twist **"fit hone wali"** mein hai.

---

## Pehla instinct

```python
def park(vehicle):
    for spot in all_spots:
        if not spot.free:
            continue
        if vehicle.type == "motorcycle":
            return assign(spot)                                    # kahin bhi ghus jaayegi
        elif vehicle.type == "car" and spot.type in ("medium", "large"):
            return assign(spot)
        elif vehicle.type == "truck" and spot.type == "large":
            return assign(spot)

def fee(hours, spot_type):
    if spot_type == "small":    return hours * 1
    elif spot_type == "medium": return hours * 2
    elif spot_type == "large":  return hours * 3
```

Chalta hai. Par ab dekho kya hota hai:

**1. "Electric scooter add karo."** → `park` edit karo.
**"Aur EV charging spots bhi."** → `park` bhi edit, `fee` bhi edit.

**2. "Bhai fit rules kya hain exactly?"**
→ Tumhe **code padhna padega** unko jaanne ke liye. Rules kahin likhe hi nahi hain — woh `if`
statements ke **shape** mein chhupe hue hain. Isliye agar koi rule galat ho, toh kisi ko dikhega hi
nahi.

**3. "Weekend pe rate badhega."** → `fee` edit → deploy. Ek pricing change ke liye parking ka code
chhedna pad raha hai. Galat hai yeh.

**4. "Do gaadiyan ek saath aa gayin."** → Dono ka loop spot #12 ko free dekhega. Dono wahin park
ho jayengi. 💥

---

## Asli seekh: rules ko **data** banao, `if` mat banao

Yeh is problem ka sabse bada takeaway hai.

```python
FIT_RULE = {
    VehicleType.MOTORCYCLE: {SMALL, MEDIUM, LARGE},
    VehicleType.CAR:        {MEDIUM, LARGE},
    VehicleType.TRUCK:      {LARGE},
}
```

Ab:
- Rules **ek jagah, table ki tarah** dikhte hain. Koi bhi 5 second mein padh ke verify kar sakta hai.
- Scooter add karna = **ek line data**, code change nahi. Isko **Open/Closed** kehte hain — extend
  karo, modify mat karo.
- `can_fit` ek line ban jaata hai: `return self.type in FIT_RULE[vehicle.type]`

---

## Yahan enum, par elevator mein State pattern — kyun?

Yeh confusion sabko hoti hai, isliye seedha samjho:

**Sawal poochho: types ka behaviour alag hai, ya sirf data alag hai?**

| | Parking `VehicleType` | Elevator `status` |
|---|---|---|
| Kya alag hai? | sirf **kaunsa spot fit hota hai** (ek lookup) | `step()` **poora alag kaam** karta hai |
| Kya Truck alag tarike se park hota hai? | Nahi — sab bas ek spot lete hain | — |
| Answer | **enum + map** (data) | **State pattern** (behaviour) |

Motorcycle, Car, Truck — teeno ka kaam same hai: ek spot ghero. Sirf *kaunsa* spot, woh alag hai.
Woh **data** hai. Isliye subclasses banana **YAGNI** hota (bekaar ka kaam).

---

## Entities

### `Vehicle` aur `ParkingSpot`
```python
@dataclass
class ParkingSpot:
    id, spot_type, floor, is_available = True

    def can_fit(self, vehicle) -> bool:
        return self.type in FIT_RULE[vehicle.vehicle_type]
```

> **Yahan maine galti ki thi** — `can_fit` mein `is_available` bhi check kar diya tha:
> ```python
> return self.is_available and self.type in FIT_RULE[...]   # ❌
> ```
> **Yeh galat kyun hai?** Kyunki `can_fit` ka matlab hai *"kya yeh gaadi kabhi is spot mein aa
> sakti hai?"* — yeh **types ka sawal** hai. `is_available` matlab *"abhi khali hai kya?"* — yeh
> **state ka sawal** hai. Dono alag hain.
>
> Merge karoge toh naam jhoot bolne lagega, aur ek chhupa hua doosra kaam aa jayega (SRP violation).
> Practical dikkat: baad mein agar poochna ho *"total kitne car-compatible spots hain?"* (bhare hue
> milake), toh merged `can_fit` jawab hi nahi de payega.

Strategy dono ko milata hai: `spot.is_available and spot.can_fit(vehicle)`.

### Do Strategies (dono breadcrumbs pakadne the)
Requirement mein do jagah "swappable" tha — **pricing** aur **spot assignment**. Dono ke liye alag
Strategy:

```python
class SpotAssignmentStrategy(ABC):   # kaunsa spot doon
class CostCalculator(ABC):            # kitna paisa loon
```

> Maine pricing wala pakad liya tha, **assignment wala miss kar diya**. Dono "swappable" the — dono
> Strategy bante hain.

### `CostCalculator` — pure rakhna
```python
def calculate_fee(self, ticket) -> float:
    end = ticket.exit_time or datetime.now(timezone.utc)     # local variable
    hours = ceil((end - ticket.entry_time).total_seconds() / 3600)
    return hours * self.RATES[ticket.spot.type]
```

> **Yahan bhi maine galti ki thi** — andar `ticket.exit_time = now()` set kar diya tha.
> **Kyun galat?** Kyunki "calculate" ka matlab hai *padho aur number wapas do* — kuch **badlo mat**.
> `exit_time` set karna ek **state change** hai, aur woh `unpark()` ka kaam hai.
>
> Practical dikkat: agar koi sirf **quote** poochhna chahe ("abhi nikloon toh kitna lagega?"), toh
> yeh function chupchaap gaadi ko **checkout kar dega**. Ek "read" jo chupke se "write" kare — yeh
> bahut khatarnaak bug hai.

`ceil` isliye — parking mein shuru hua ghanta poora ghanta ginta hai.

---

## Thread-safety: do gaadi, ek spot

Yeh URL shortener wala **wahi TOCTOU** hai, bas naye kapdon mein:

```
Thread A: strategy ne spot #12 diya (free hai)
Thread B: strategy ne bhi spot #12 diya (A ne abhi mark nahi kiya tha)
Thread A: spot.is_available = False
Thread B: spot.is_available = False
→ Do gaadi, ek jagah 💥
```

**Fix:** `find` aur `claim` ko **ek hi critical section** mein rakho:

```python
def park(self, vehicle):
    with self.lock:                                    # <- yahin se
        if vehicle.license_plate in self.active_tickets:
            raise VehicleAlreadyParkedError(...)
        spot = self.spot_strategy.assign_spot(self.floors, vehicle)
        if spot is None:
            raise LotFullError(...)
        spot.is_available = False                      # claim
        ticket = Ticket(vehicle=vehicle, spot=spot)
        self.active_tickets[vehicle.license_plate] = ticket
        return ticket                                  # <- yahan tak lock chahiye
```

> **Trap:** lock ko `spot = strategy...` ke baad chhod dena. Maine yahi kiya tha — lock jaldi
> release ho gaya aur claim lock ke bahar chala gaya. Gap wapas khul gaya. **Check se claim tak lock
> pakde rehna hai.**

---

## Double-park leak (chhota par asli bug)

Agar wahi gaadi dobara park kare, toh `active_tickets[plate]` overwrite ho jaata hai — purana ticket
gum, aur uska spot **hamesha ke liye blocked**. Isliye shuru mein hi check:

```python
if vehicle.license_plate in self.active_tickets:
    raise VehicleAlreadyParkedError(...)
```

---

## Errors: raise karo, `None` mat lautao

```python
def park(...) -> Ticket:              # None nahi
    raise LotFullError(...)           # lot bhara hai
    raise VehicleAlreadyParkedError(...)
    raise VehicleNotFoundError(...)   # unpark mein
```

`None` lautaoge toh caller ko **yaad rakhna padega** check karna — aur woh bhool jayega. Exception
ignore karna mushkil hai. Aur baad mein yeh seedha HTTP codes pe map ho jaate hain (409, 404).

---

## Factory kahan gaya?

Maine bola tha ki Factory aayega. **Nahi aaya** — kyunki enum wale decision ne uski zaroorat hi khatam
kar di (koi subclass hi nahi hai toh banana kya hai). **Yeh YAGNI ka kaam karna hai, miss karna nahi.**

Factory ki asli jagah nikli: **lot banane mein** —
```python
def build_lot(floors, per_floor):     # config se poora lot bana do
```

---

## Interview line

> *"Fit rules ko maine **data** rakha, `if/elif` nahi — isliye naya vehicle type add karna ek line ka
> data change hai, code change nahi. Aur `find→claim` ko ek hi lock ke andar rakha, kyunki beech mein
> gap chhodne se do gaadi ek spot le sakti hain — wahi TOCTOU jo URL shortener mein tha."*
