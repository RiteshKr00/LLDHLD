# Movie Booking

> **Is problem ka core:** seat ki teesri state — **HELD**.

---

## Problem kya hai

BookMyShow. User show chunta hai → seat map dekhta hai → seats chunta hai → payment karta hai →
ticket mil jaata hai. Cancel bhi kar sakta hai.

Sunne mein simple CRUD lagta hai. Par ek gap hai jo sab kuch mushkil bana deta hai.

---

## Pehla instinct

```python
def book(user, show, seat_ids):
    for sid in seat_ids:
        seat = show.seats[sid]
        if seat.is_booked:
            raise Exception("seat taken")
        seat.is_booked = True
    return Ticket(user, seat_ids)
```

Chalta hai... jab tak asli duniya na aa jaye:

**1. Payment mein time lagta hai.**
User ne seat chuni. Ab woh card details daal raha hai, OTP aa raha hai, bank redirect ho raha hai —
**30 second se 2 minute**. Us poore time mein seat kya hai?
- `is_booked = True` kar do? → payment fail ho gaya toh **seat hamesha ke liye blocked**
- `is_booked = False` rakho? → koi aur woh seat le lega, aur payment ke baad user ko **"sorry"** bolna padega

**Dono galat hain.** Isliye ek **teesri state** chahiye: **HELD**.

**2. Popular show pe hazaaron log ek saath.**
Naya movie release. 10,000 log ek saath **wahi seat A1** pe click kar rahe hain. Upar wala code:
```
Thread A: seat.is_booked? -> False ✓
Thread B: seat.is_booked? -> False ✓   (A ne abhi likha nahi)
Thread A: is_booked = True
Thread B: is_booked = True
→ Do logon ko same seat 💥
```

**3. Seat kis show ki hai?**
`show.seats[sid]` — matlab seat show ke andar hai. Par asli duniya mein **seat physical hai**, screen
mein lagi hui hai. Wahi A1 seat 3pm ke liye free ho sakti hai aur 6pm ke liye booked.

---

## Fix #1: Seat aur ShowSeat alag karo

```
   Seat("A1")           <- PHYSICAL. Screen ka part. Koi status NAHI.
        │
        ├── ShowSeat(3pm show) : AVAILABLE
        ├── ShowSeat(6pm show) : BOOKED
        └── ShowSeat(9pm show) : HELD by Bob, 20:47 tak
```

Agar `status` ko `Seat` pe rakh doge, toh 6pm ke liye book karne se woh seat **poore din ke liye**
book ho jayegi. Yeh classic modeling mistake hai is problem ki.

---

## Fix #2: Teesri state — HELD

```
                  hold_seats()            confirm()
   AVAILABLE  ─────────────────▶  HELD  ─────────────▶  BOOKED
       ▲                            │                      │
       │      5 min timeout         │                      │
       └────────────────────────────┘                      │
       │                    cancel()                       │
       └───────────────────────────────────────────────────┘
```

`HELD` matlab: *"yeh seat abhi kisi aur ki nahi hai, par pakki bhi nahi hui. 5 minute ka time hai."*

**Aur yehi teesri state dono hard problems paida karti hai:**
1. **Race** — do log ek saath hold karne ki koshish
2. **Leak** — hold kabhi expire hi na ho toh seat **hamesha ke liye** phansi rahegi

---

## Fix #3: Race — lock (6th time!)

Ab tak yeh pattern 6 baar aa chuka hai:

| Problem | Racy jodi |
|---|---|
| URL shortener | `exists()` + `save()` |
| Parking | spot dhoondho + mark karo |
| Rate limiter | `get` + `set` |
| Splitwise | `balance += x` |
| Chess | matchmaking |
| **Movie** | **check available + mark HELD** |

Hamesha wahi shape: **check karo, phir act karo — aur beech mein gap hai.**

```python
with self._lock_for(show.show_id):     # <- poora check+claim ek unit
    ...check all seats...
    ...mark all HELD...
```

**Ek baat dhyan do — lock PER SHOW hai, global nahi.** Agar ek hi lock hota, toh 3pm show ki bheed
9pm ke buyers ko bhi rok deti. Alag shows ka koi lena-dena nahi hai.

---

## Fix #4: All-or-nothing

User ne 3 seats maange: A1, A2, A3. A2 kisi aur ne le li.

**Galat:** A1 aur A3 hold kar lo, A2 ke liye sorry bolo.
→ User ko 3 chahiye the, 2 se kaam nahi chalega. Woh chala jayega.
→ **A1 aur A3 ab 5 minute ke liye phanse hue hain** — koi aur bhi nahi le sakta.

**Sahi:** pehle **saare** check karo. Ek bhi busy hai toh **kisi ko haath mat lagao**.

```python
targets = []
for sid in seat_ids:
    if ss.status is not AVAILABLE:
        raise SeatUnavailableError(...)     # kuch bhi mutate nahi kiya abhi tak
    targets.append(ss)

for ss in targets:                          # ab jaake sabko ek saath hold karo
    ss.hold(user)
```

---

## Fix #5: Leak — dono mechanism (defence in depth)

Hold expire kaise ho? Do tarike, **dono chahiye**:

**(a) Lazy** — jab bhi koi seat map dekhe ya hold kare, tab check karo "koi hold expire toh nahi hua?"
```python
def hold_seats(...):
    with lock:
        self._expire_holds(show_id)     # <- pehle safai
        ...
```

**(b) Sweeper job** — background mein har minute chal ke expired holds release kare

**Dono kyun?**

| | Akela kyun kaafi nahi |
|---|---|
| **Lazy** | Jis seat ko koi **poochta hi nahi**, woh data mein `HELD` padi rahegi → **seat map jhooth bolega**, kam seats dikhayega |
| **Sweeper** | Job mar gayi ya lag ho gayi → seats leak → **correctness ek cron pe depend** kar rahi hai |

**Saath mein:** sweeper data ko fresh rakhta hai (display ke liye), lazy check **decision ke waqt
correctness** guarantee karta hai — chahe sweeper mara hua ho.

> Yehi shape URL shortener mein tha (lazy `is_expired()` + purge job) aur parking ke no-show reaper mein.

---

## Ek chhoti par zaroori baat: `confirm` dobara check karta hai

```python
def confirm(self, booking_id):
    ...
    if any(ss.is_hold_expired() or ss.held_by is not booking.user for ss in booking.show_seats):
        raise InvalidBookingStateError("hold expired before payment completed")
```

**Kyun?** Kyunki payment mein time lagta hai. User ne hold liya 20:42 pe, payment 20:48 pe complete
hua — hold **20:47 pe expire** ho chuka. Us beech kisi aur ne woh seat le li hogi.

Bina is check ke, tum **double-book** kar doge. Yeh bug production mein bahut milta hai.

---

## Interview line

> *"Is problem ka core yeh hai ki seat ki ek teesri state hai — **HELD** — kyunki seat chunne aur
> payment complete hone ke beech gap hota hai. Woh gap do problem deta hai: race (do log same seat)
> aur leak (hold kabhi khatam na ho). Race ke liye **per-show lock** ke andar check+claim, aur
> all-or-nothing taaki partial hold seats na phansaye. Leak ke liye **dono** — lazy expiry
> correctness ke liye, sweeper job seat map honest rakhne ke liye. Aur `confirm` hold dobara verify
> karta hai, kyunki payment ke beech mein hold expire ho sakta hai."*
