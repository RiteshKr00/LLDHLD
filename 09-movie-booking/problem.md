# Problem 9: Movie Ticket Booking (LLD)

## The prompt (as an interviewer would give it)

> "Design a movie ticket booking system — like BookMyShow. Users pick a show, pick seats, and book."

---

## Clarifying questions to ask
1. **Scope of the catalogue** — one cinema or many? Multiple screens, multiple shows per screen?
2. **Seat selection** — user picks specific seats, or system auto-assigns?
3. **The hold** — between "I picked seats" and "I paid", are those seats **locked** for me? For how long?
4. **Payment** — in scope, or assume a payment result arrives?
5. **Seat types / pricing** — recliner vs regular? Weekend pricing? Should pricing be swappable?
6. **Cancellation** — can a booking be cancelled and the seats released?
7. **Concurrency** — how many users can hit the same show at once? *(popular show = thousands)*

## Clarifications (locked scope from Q&A)
1. One cinema, **multiple screens**, multiple **shows** per screen.
2. User **picks specific seats** from a seat map.
3. **HOLD: seats lock for 5 minutes** while payment happens; on timeout they auto-release. ← the crux
4. Payment gateway out of scope — assume a `confirm()` / `fail()` result arrives.
5. Pricing by **seat type** (regular/premium/recliner), and **swappable** (weekend pricing later).
6. **Cancellation** supported — seats go back to available.
7. **Thousands of users click the same seat** on a popular show.

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- Browse shows (movie → screen → show) and see the **seat map** with availability
- **HOLD** selected seats for 5 minutes while paying ← the crux
- **Confirm** the booking on payment success → hold becomes a booking
- **Auto-release** the hold if payment doesn't complete in time
- **Cancel** a confirmed booking → seats become available
- Price the booking by seat type

### Non-functional (constraints — the "-ilities")
- **Thread-safe under heavy contention** — thousands of users clicking the same seat
- **Extensible** — pricing strategy swappable
- **No double-booking, and no seat stuck forever** (a held seat must always come back)
- Testable

### Explicitly out of scope (say this out loud — senior move)
- Payment gateway integration · notifications · seat recommendations · multi-cinema/city · refunds policy

> 📝 **Review note (Step 1):** book / cancel / multi-show were right, and both NFRs caught (concurrency + swappable pricing). **Big miss: the HOLD.** Everything else here is ordinary CRUD — the *only* interesting part of this problem is that a seat has a third state between free and booked: **held, with an expiry**. That single requirement creates both hard problems: the race (two users holding the same seat) and the leak (a hold that never expires blocks the seat forever).

---

## Step 2 — Entities  (nouns → classes)

**Catalogue (static):**
1. **Movie** — `movie_id, title, duration`
2. **Screen** — a physical hall — `screen_id, name, seats: list[Seat]`
3. **Seat** — a **physical** seat, belongs to a Screen — `seat_id ("A5"), row, number, seat_type`
4. **Show** — a movie on a screen at a time — `show_id, movie, screen, start_time`

**Per-show state (the important split):**
5. **ShowSeat** — one seat **for one show**; this is what actually gets held/booked —
   `show, seat, status: SeatStatus, held_by: Optional[user], hold_expires_at: Optional[datetime]`
6. **SeatStatus** *(enum)* — `AVAILABLE / HELD / BOOKED` — pure labels, no differing behaviour → enum is right
7. **SeatType** *(enum)* — `REGULAR / PREMIUM / RECLINER` — drives pricing

**Transaction:**
8. **Booking** — `booking_id, user, show, show_seats[], status, amount, created_at`
9. **BookingStatus** *(enum)* — `PENDING / CONFIRMED / CANCELLED / EXPIRED`

**Swappable + orchestration:**
10. **PricingStrategy** *(Strategy)* — `calculate(show, seats) -> Decimal`
11. **BookingService** — orchestrator: `hold_seats`, `confirm`, `cancel`, `release_expired`

> 📝 **Review note (Step 2):** Movie / Screen / Show / status-enum were right. **The key miss: `Seat` vs `ShowSeat`.** A seat like "A5" is *physical* and belongs to the Screen — but whether it's free is **per show** (A5 free at 3pm, booked at 6pm). Putting `status` on `Seat` means booking a seat for one show books it for every show. So the per-show state gets its own entity, `ShowSeat`, which is what actually carries `status`, `held_by`, and `hold_expires_at`. Also added `Booking` (the transaction record — the thing the user actually owns), `PricingStrategy` (the swappable NFR), and the orchestrator. `SeatStatus` correctly stays an **enum** — the three values are labels, nothing behaves differently per value.

---

## Step 3 — Relationships & APIs

**APIs:**
```
GET  /shows/{show_id}/seats          -> seat map with live availability
POST /holds        {show_id, seat_ids, user}   -> Booking (PENDING) + expires_at
POST /bookings/{id}/confirm                    -> CONFIRMED   (payment succeeded)
POST /bookings/{id}/cancel                     -> CANCELLED, seats released
```
```python
# BookingService
def hold_seats(self, user, show, seat_ids) -> Booking      # PENDING + 5-min expiry
def confirm(self, booking_id) -> Booking                   # PENDING -> CONFIRMED
def cancel(self, booking_id) -> None                       # release seats
def release_expired(self) -> int                           # the sweeper job
```

**`hold_seats` — the atomic claim, 6th appearance:**
```
with lock(show):                       # per-SHOW lock, not one global lock
    1. lazily expire: any seat whose hold_expires_at has passed -> AVAILABLE
    2. check ALL requested seats are AVAILABLE
       - any one taken -> raise, hold NOTHING (all-or-nothing)
    3. mark all -> HELD, held_by=user, hold_expires_at=now+5min
    4. create Booking(PENDING)
```
- Check-then-claim must be **one critical section** — else two users both see A5 free and both hold it.
- **All-or-nothing:** if a user asks for 3 seats and only 2 are free, hold none. Partial holds strand seats.
- **Per-show lock**, not global — different shows shouldn't block each other.

**Hold expiry — BOTH mechanisms (defence in depth):**

| | What it does | Why it alone isn't enough |
|---|---|---|
| **Lazy** (check on read/hold) | expire seats the moment someone looks at them | seats nobody asks about stay `HELD` in the data → **seat map lies**, shows fewer seats than really exist |
| **Background sweeper** | periodically release all expired holds | if the job dies or lags, seats leak → **correctness depends on a cron** |

Together: the **sweeper keeps the displayed data honest**, the **lazy check guarantees correctness at the
moment of decision** (even if the sweeper is dead). Same shape as the URL shortener's expiry
(lazy `is_expired()` + purge job) and the parking-lot no-show reaper.

> 📝 **Review note (Step 3):** both hard parts answered correctly — **lock** for the race (6th appearance of check-then-claim: `exists+save`, `find+claim`, `get+set`, `balance+=`, matchmaking, now `check+hold`) and **both** expiry mechanisms as defence in depth, with the right instinct that they cover different failure modes. Added the details: the lock should be **per-show** (a global lock serialises unrelated shows), and the hold must be **all-or-nothing** across the requested seats — partial holds leave stranded seats nobody can use.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

| LLD method | HTTP |
|---|---|
| `seat_map(show_id)` | `GET /api/v1/shows/{id}/seats` -> **200** `{seat_id: status}` *(cacheable; stale-by-seconds is fine)* |
| `hold_seats(user, show, ids)` | `POST /api/v1/holds` `{show_id, seat_ids}` -> **201** `{booking_id, expires_at}` · **409** `SeatUnavailableError` |
| `confirm(booking_id)` | `POST /api/v1/bookings/{id}/confirm` -> **200** · **410 Gone** hold expired |
| `cancel(booking_id)` | `POST /api/v1/bookings/{id}/cancel` -> **204** |
| `release_expired()` | **not an endpoint** — a background sweeper job |

> `expires_at` **must** be in the 201 response — the client needs to show a countdown, and that
> countdown is the entire UX of the hold.

## Notes / decisions (log the "why" here)
- **`Seat` vs `ShowSeat`** — physical seat has no status; availability is per-show. Putting `status` on `Seat` would book A5 for *every* show at once.
- **Per-show lock**, not a global one — different shows are independent; a global lock would serialise the whole cinema.
- **All-or-nothing hold** — check every requested seat *before* mutating any. A partial hold strands seats nobody can use.
- **Both expiry mechanisms:** lazy check = correctness (works even if the job is dead); sweeper = honest seat map (releases seats nobody happened to look at). Same shape as URL-shortener expiry and the parking no-show reaper.
- **`confirm` re-checks the hold** — payment takes time, and the hold can expire mid-flight. Confirming blindly would double-book a seat someone else has since taken.
- Booked seats get `hold_expires_at = None` — a confirmed seat must never be swept.

> 📝 **Review note (Step 4 build):** demo verified all-or-nothing (A2 stayed available after a partial request failed), expiry (sweeper released, then `confirm` correctly refused), cancel returning seats, and the pricing swap (700 → 875 by changing one class). **Concurrency test: 200 threads all rushing seat A1 → exactly 1 winner, 199 clean rejections.** That single assertion is what the whole problem exists to test.
