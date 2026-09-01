# Elevator System

> **Is problem ka star pattern: State pattern.** Isi ke liye yeh problem interviews mein poocha jaata hai.

---

## Problem kya hai

Building mein 3 lifts hain. Log button dabate hain, lift aati hai, log andar jaate hain, lift chalti
hai, darwaza khulta hai. Bas.

Par ismein do cheezein chhupi hui hain jo poora design decide karti hain.

---

## Chhupi hui cheez #1: do tarah ke button hote hain

Yeh sabse important insight hai, aur zyadatar log yahin phisal jaate hain.

**Hallway ka button (bahar):**
Tum 3rd floor pe khade ho, ⬆ dabaya. Tumne kya bataya? Sirf **"main 3rd floor pe hoon aur upar
jaana hai"**. Tumne yeh nahi bataya ki **kaunse floor pe** jaana hai — abhi tak toh tumne socha bhi
nahi hoga!

**Car ka button (andar):**
Lift ke andar ghus ke tumne `7` dabaya. Ab tumne **destination** bataya. Aur yeh request **usi lift
ki** hai — koi doosri lift ise handle nahi kar sakti.

Toh:

| | Hall request (bahar) | Car request (andar) |
|---|---|---|
| Kya pata hai | `source_floor` + `direction` | `destination_floor` |
| Destination? | ❌ pata hi nahi | ✅ yahi toh hai |
| Direction? | ✅ diya hai | ❌ khud pata chal jaata hai |
| Kaunsi lift? | **Dispatcher decide karega** | Pehle se fix hai |

**Isliye yeh do alag classes hain**, ek class with a "type" flag nahi. Fields hi alag hain, aur
handle bhi alag tarike se hote hain.

```python
class HallRequest:  source_floor, direction     # dispatcher ko chahiye
class CarRequest:   destination_floor           # seedha us lift ko
```

---

## Chhupi hui cheez #2: `status` ek normal field nahi hai

Pehla instinct yeh hota hai:

```python
def step(self):
    if self.status == "idle":
        if self.targets:
            self.status = "moving"
    elif self.status == "moving":
        self.current_floor += 1 if self.direction == "up" else -1
        if self.current_floor in self.targets:
            self.status = "door_open"
    elif self.status == "door_open":
        self.targets.remove(self.current_floor)
        self.status = "moving" if self.targets else "idle"
```

Chalta hai. Ab dikkat dekho:

**1. "Maintenance mode add karo."** → `step` edit karo, ek `elif` aur.
**"Emergency stop bhi."** → phir edit.
**"Express mode."** → phir edit.
Yeh ek method har feature ka **kabaad-khana** ban jaata hai.

**2. "DOOR_OPEN ke baad kya ho sakta hai?"**
→ Tumhe branches mein dhoondhna padega ki `self.status = ...` kahan-kahan likha hai. State machine
**exist toh karti hai**, par kahin **likhi hui nahi hai** — poore method mein bikhri padi hai.

**3. "Door-open wala logic akela test karo."**
→ Nahi kar sakte. Pehle lift ko us state tak drive karna padega.

**4.** `self.status == "movng"` — ek typo, aur woh branch **kabhi chalega hi nahi**. Koi error nahi,
koi warning nahi. Bas chupchaap kaam nahi karega.

---

## Toh enum kab, State pattern kab?

Yeh **wahi sawal** hai jo parking lot mein tha, par **jawab ulta** hai. Test yeh hai:

> **Types ka behaviour alag hai, ya sirf data alag hai?**

**Parking:** Motorcycle, Car, Truck — teeno ka kaam same (ek spot ghero). Sirf *kaunsa spot fit hota
hai* woh alag — matlab ek **lookup table**. → **Data** → enum.

**Elevator:** IDLE mein `step()` kuch nahi karta. MOVING mein floor badalta hai. DOOR_OPEN mein
passengers ko utaarta hai. Yeh **teen bilkul alag kaam** hain. → **Behaviour** → State pattern.

---

## State pattern kaise dikhta hai

Har state ek **class** ban jaati hai, aur har class apna kaam + apna next state khud sambhalti hai:

```python
class State(ABC):
    def step(self, elevator): ...

class IdleState(State):
    def step(self, elevator):
        if elevator.targets:
            elevator.state = MovingState()          # khud decide kiya

class MovingState(State):
    def step(self, elevator):
        if elevator.current_floor in elevator.targets:
            elevator.state = DoorOpenState()        # pahunch gaye
            return
        # ek floor aage badho (nearest target ki taraf)

class DoorOpenState(State):
    def step(self, elevator):
        elevator.targets.discard(elevator.current_floor)   # is floor ko serve kar diya
        elevator.state = MovingState() if elevator.targets else IdleState()
```

Aur Elevator ka `step()`? **Ek line:**

```python
def step(self):
    self.state.step(self)        # bas. Koi if nahi. Kabhi nahi.
```

**Fayda:**
- Har state ka kaam **aur** uske transitions ek hi class mein — padhna aasan (SRP)
- Naya state add karna = **nayi class**. Purani classes ko chhedna hi nahi padta (**Open/Closed**)
- Har state alag se test ho sakta hai
- `if/elif` ki chain gayab

**Nuksan (honest raho):** zyada classes ban jaati hain. Sirf 3 stable states ke liye enum + `if` bhi
defensible hai. Interview mein yeh bolna:

> *"3 fixed states ke liye enum+if bhi chal jaata, par behaviour genuinely alag hai aur State pattern
> machine ko Open/Closed rakhta hai — kal maintenance/emergency add karna nayi class hai, bada `if`
> nahi."*

**Responsibility saaf rakhna:** Moving **chalti** hai, DoorOpen **serve** karta hai (`targets.discard`
DoorOpen mein hona chahiye, Moving mein nahi — kyunki passengers tab utarte hain jab darwaza khulta hai).

---

## Ek chhota trap: `targets` ek `set` hai

**Set ko index nahi kar sakte.**

```python
target = elevator.targets[0]        # ❌ TypeError — set indexable nahi hota
```

Sahi tarika — **nearest target** chuno:
```python
target = min(elevator.targets, key=lambda f: abs(f - elevator.current_floor))
```

`set` isliye use kiya kyunki agar koi 5 do baar dabaye, toh dedup apne aap ho jaata hai.

> *(Asli SCAN algorithm — "ek direction mein chalte raho, raaste mein sab serve karo, phir palto" —
> nearest se behtar hai. Woh scheduling ka upgrade hai; interview mein mention kar dena.)*

---

## Mutable default ka chakkar (yeh yaad rakhna)

```python
@dataclass
class Elevator:
    targets: set[int] = set()                    # ❌ dataclass ValueError dega
    state: State = IdleState()                   # ❌ chup-chaap shared object
```

**Rule kya hai?** Sawal yeh nahi ki dataclass hai ya normal class — sawal yeh hai ki **default kab
evaluate hota hai**:

| Kahan | Kab chalta hai | Result |
|---|---|---|
| dataclass field `= set()` | **ek baar**, class banate waqt | 🐛 dataclass **error deta hai** |
| default param `def __init__(self, x=set())` | **ek baar**, function define hote waqt | 🐛 chupchaap **shared** |
| `__init__` ke andar `self.x = set()` | **har baar** | ✅ safe |

Fix: `field(default_factory=set)` — matlab "har baar naya `set()` banao".

> Normal class mein bhi `self.targets = set()` `__init__` ke andar likhoge toh bilkul safe hai.
> Dataclass bas tumhe **explicit** hone pe majboor karta hai.

---

## Baaki cheezein

**`SchedulingStrategy`** — "kaunsi lift jaayegi" ka rule swappable hona chahiye tha → Strategy.
`NearestCarStrategy` bhari hui lifts ko skip karta hai (capacity requirement).

**`ElevatorSystem`** — orchestrator. Yahan Step-2 wali asymmetry ka fayda dikhta hai:
```python
def request_hall(self, req):     # koi lift assign nahi hai -> STRATEGY se pucho
    car = self.strategy.choose_elevator(self.elevators, req)
    car.add_target(req.source_floor)

def request_car(self, car_id, req):   # lift pehle se pata hai -> seedha usko do
    self._by_id[car_id].add_target(req.destination_floor)
```

**`step()` tick** — asli time use nahi kiya. Ek `step()` = ek "tick". Isse simulation deterministic
aur testable ho jaata hai (chhota game-loop).

**Thread-safety** — button presses `targets` badalte hain, aur `step()` usi ko padhta/badalta hai →
teeno methods `with self.lock:` mein.

---

## Interview line

> *"Elevator ka `status` dekhke laga ki enum hoga, par test kiya — states ka **behaviour alag hai**,
> sirf data nahi. Isliye State pattern. Result: `Elevator.step()` ek line hai, poore codebase mein
> ek bhi `if state ==` nahi hai, aur maintenance mode add karna nayi class hai — purana code chhune
> ki zaroorat hi nahi."*
