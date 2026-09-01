# Entity-Finding Playbook

The technique for Step 2 (nouns → classes) — what to actually *do* when a blank prompt gives you no
scaffolding. Run this checklist, in order, on the locked Step 1 requirements. Verified against all 4
solved problems below.

## Step 1 first: the clarifying-question checklist

Before entities, you have to *scope*. A good clarifying question is one where **different answers
produce different code** — anything else is small talk. Six categories, verified across all solved
problems (each problem's own list is at the top of its `problem.md`):

| # | Category | The question | Why it changes the code |
|---|---|---|---|
| 1 | **Deployment / scale** | one process or many servers? | decides whether an in-process lock is even valid (rate limiter: N servers = N× the limit) |
| 2 | **The core domain rule** | the fit rule? the split types? validation depth? | this IS the problem — get it wrong and everything downstream is wrong |
| 3 | **What varies** | "should X be swappable/configurable later?" | **every "yes" here is a Strategy interface.** Highest-yield question you can ask |
| 4 | **Boundaries** | special cases in or out? (castling, multi-currency, fire mode) | scope-cutting; sometimes you should actively push to CUT |
| 5 | **Concurrency** | who touches shared state at the same time? | parking: two cars one spot ✓ · chess: turn-based ✗ · splitwise: *depends on your model* |
| 6 | **Failure / edge behaviour** | what happens when it's full / over limit / not found? | decides raise-vs-return-None, retry-vs-reject |

**Two habits worth drilling:**
- **Ask #3 explicitly, every time.** "Will the pricing rule change?" → `CostCalculator`. "New algorithms later?" → `RateLimitAlgorithm`. The interviewer is often *waiting* to say yes.
- **Don't assume #5 either way.** It's not a template — reason about it. And note a "yes" can sometimes be designed *away* (Splitwise: deriving balances made the race structurally impossible).

---

## The checklist

**1. List the nouns.** Underline every physical/conceptual thing named in the requirements.
**2. List the verbs.** Every verb needs a *home* — some class whose responsibility it is.
**3. Find THE orchestrator.** There is always exactly one: the object the client actually calls.
It's usually named `...Service` / `...System` / `...Lot` / `...Limiter`. If two verbs feel homeless,
they probably both belong to this one object.
**4. Find the state/record holder.** The object that represents "one instance of the core scenario in
progress" — created fresh per request, holds the data that gets read back later.
**5. Scan the NFRs for "-ility" words** — extensible / swappable / configurable / pluggable. **Each one
is a Strategy interface**, not a feature of the orchestrator. This is the single highest-yield step —
it's flagged directly in the requirements text, don't skip it.
**6. Find the identifier/key.** How do you look one thing up? Often a composite (`user+endpoint`,
`code`), sometimes an entity's own id.
**7. For anything with sub-"types" (vehicle types, states, algorithms) — data or behavior?** If the
types only ever differ by *data* → enum + a rule-map. If they differ by *behavior* (different methods
do genuinely different things) → subclasses (State pattern / Factory).

## Verified against the 4 solved problems

| Checklist step | URL shortener | Parking lot | Elevator | Rate limiter |
|---|---|---|---|---|
| **Orchestrator** | `URLShortenerService` | `ParkingLot` | `ElevatorSystem` | `RateLimiter` |
| **State/record holder** | `ShortLink` | `Ticket` | `Elevator` (its own state) | *(none — pure counter, no per-request record)* |
| **"-ility" → Strategy** | extensible → `ShortCodeGenerator` | extensible → `SpotAssignmentStrategy` + `CostCalculator` | extensible → `SchedulingStrategy` | extensible → `RateLimitAlgorithm` |
| **Storage abstraction** | `URLRepository` | *(in-memory objects, no repo needed)* | *(in-memory)* | `StateStore` (+ narrower ones per algorithm — ISP) |
| **Identifier/key** | `short_code` | license plate | car `id` | `(user, endpoint)` |
| **Data vs behavior** | n/a (no subtypes) | vehicle/spot types = **data** → enum | elevator states = **behavior** → **State pattern** | n/a |

Notice: **every single problem has an orchestrator + at least one Strategy.** If you take nothing else
from this table, take that — when you see a vague prompt, immediately ask *"what's the one object the
client calls?"* and *"which NFR word ('extensible'/'configurable') is hiding a Strategy?"* Those two
questions alone will surface most of the entity list.

## The drill (do this instead of re-reading)

Don't re-read old solutions passively — that builds recognition, not recall. Instead, for each solved
problem: close `solution.py`, look only at the original vague one-line prompt, and re-run this checklist
cold (~5 min), writing your own Step 1/Step 2 from scratch. Then diff against the locked `problem.md`.
The gaps are the real signal — that's what didn't stick yet.

## How to grow this file

When a new problem's entity-finding reveals a checklist step not covered here (e.g. a graph-shaped
domain, a many-to-many relationship), add it as a new row/step with the same "verified against solved
problems" discipline.
