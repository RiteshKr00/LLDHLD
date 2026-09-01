# Problem 5: Chess (LLD)

## The prompt (as an interviewer would give it)

> "Design a chess game — two players, a board, standard pieces and rules."

Deliberately vague. **Your job is to make it concrete** — that's Step 1.

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **Validation depth** — just legal piece movement, or full **check / checkmate / stalemate** detection? *(Check-detection means simulating a move and asking "does this leave my own king attacked" — a far bigger rule engine.)*
2. **Special moves** — castling, en passant, pawn promotion? *(Each is a separate rule; promotion is cheap, the other two are not.)*
3. **Turn enforcement** — strict alternating turns, rejecting out-of-turn moves?
4. **Mode** — two local players, or networked? Clocks/timers? AI opponent? *(Decides whether concurrency exists at all.)*
5. **History** — undo/redo, move log, replay?

---

## Clarifications (locked scope from Q&A)
- **Checkmate:** full check / checkmate / stalemate detection required — not just legal-move validation.
- **Special moves:** castling and en passant → **out of scope**. Pawn promotion → **in scope**.
- **Turn handling:** strict alternating turns between two players.
- **Mode:** two local players, same machine — no networking, no clocks/timers.

---

## Step 1 — Requirements  ← YOUR TURN
_Ask clarifying questions first, then state these back._

### Functional (what it DOES — the verbs)
- Validate a proposed move against that piece's legal-move rules
- Enforce strict alternating turns — reject a move made out of turn
- Detect check; if the current player is in check, only moves that resolve it (move king / capture attacker / block) are legal
- Detect checkmate and stalemate → determine game outcome (win / draw)
- Pawn promotion on reaching the last rank

### Non-functional (constraints — the "-ilities")
- **Extensible** — new piece types / board variants pluggable without rewriting the move engine
- **Testable**

### Explicitly out of scope (say this out loud — senior move)
- Castling, en passant, timers/clocks
- AI opponent (two local human players only)

> 📝 **Review note (Step 1):** strong — out-of-scope written **unprompted**, plus a genuinely new item ("no AI") beyond what was locked; that's the habit forming. Fixes: added explicit **turn enforcement** and **game-outcome** (win/draw), sharpened "checkmate can be prevented" into the real constraint (only check-resolving moves are legal while in check). NF: dropped vague "should be fast" (not the actual crux for a turn-based game) for **extensible** (the real swap point — new piece/board variants); flagged that **thread-safety is correctly ABSENT** here — first problem where it doesn't apply, since chess is strictly turn-based with no concurrent access to shared state. Lesson: NFRs come from the system's actual concurrency profile, not a template copied onto every problem.

---

## Step 2 — Entities  (nouns → classes)  ✅ LOCKED
_Format: `Name — single responsibility — key attributes/methods`_

1. **Cell** — a board coordinate (value object) — `x: int, y: int`
2. **Piece** — one piece on the board; behavior is injected, not hard-coded — `color, position: Cell, has_moved: bool, movement_rule: MovementStrategy`
3. **MovementStrategy** *(Strategy, ABC)* — computes legal destinations for one piece type — concrete: `RookMovement, KnightMovement, BishopMovement, QueenMovement, KingMovement, PawnMovement` — `get_legal_moves(piece, board) -> list[Cell]`
4. **Board** — the 8×8 grid; owns lookups that need to see everything at once — `cells / pieces_by_position; is_square_attacked(cell, by_color) -> bool`
5. **Player** — a side in the game — `color` *(no `turn`/`count_moved` — see note)*
6. **Match** — state/record of one game in progress (like `Ticket`/`ShortLink`) — `match_id, board, players, current_turn, status`
7. **ChessOrchestrator** — entry point; the object a client calls — `make_move(from_cell, to_cell) -> None`

> 📝 **Review note (Step 2):** the `Piece` decision was the third time in a row this exact signal appeared (behavior-differs-by-type) — parking correctly used enum (types differed only by *data*), elevator's State pattern didn't fire proactively on cold recall, and here `Piece: type` was again modeled as data even though each piece type needs a genuinely *different move-computing algorithm* (not a lookup table like `FIT_RULE`) — that's behavior, calling for polymorphism. Chose **(b) composition via injected `MovementStrategy`** over classic subclassing — consistent with every other Strategy built so far (`ShortCodeGenerator`, `SchedulingStrategy`, `RateLimitAlgorithm`), same "behavior differs → needs its own abstraction" lesson, expressed via DI instead of inheritance this time.
>
> Smaller fixes: `Player.turn` was game-level state → moved to `Match.current_turn`; `count_moved` → replaced by `has_moved: bool` **on `Piece`** (needed for pawn's first-move-2-squares rule, not a player-level concept). `move(cell, direction)` → corrected to `make_move(from_cell, to_cell)` (chess moves are cell-to-cell, not directional). Added **`Board.is_square_attacked`** — check/checkmate detection needs to ask *every* opposing piece "could you reach this square," so that coordination got a home instead of living nowhere. `Match` separated from `ChessOrchestrator` — Match is the **state holder** (mirrors `Ticket`/`ShortLink`), the orchestrator is the **entry point**.

---

## Step 3 — Relationships & APIs  ✅ LOCKED
_Signatures before bodies._

**Relationships:**
```
ChessOrchestrator ──composition──▶ Match
Match ──has──▶ Board, Player[]
Board ──composed of──▶ Cell[8x8]
Piece ──uses (DI)──▶ MovementStrategy
```

**Signatures:**
```python
# ChessOrchestrator (entry point)
def make_move(self, from_cell: Cell, to_cell: Cell) -> None

# MovementStrategy (Strategy)
def get_legal_moves(self, piece: Piece, board: Board) -> list[Cell]

# Board
def is_square_attacked(self, cell: Cell, by_color: Color) -> bool
def get_piece_at(self, cell: Cell) -> Optional[Piece]

# Match
current_turn: Color
status: GameStatus   # enum: IN_PROGRESS / CHECKMATE / STALEMATE — data, not behavior
```

**`make_move` sequence:**
1. Check `from_cell` holds a piece belonging to the current player.
2. Get that piece's legal moves via its `MovementStrategy`.
3. Check `to_cell` is among them.
4. Simulate the move — if it would leave the **mover's own king** in check, reject (illegal, regardless of checkmate).
5. Commit the move → check whether the **opponent** is now in check / checkmate / stalemate → update `Match.status`.

> 📝 **Review note (Step 3):** relationships + signatures correct. Notably, **`status` was correctly identified as an enum** (`IN_PROGRESS/CHECKMATE/STALEMATE` are labels, no differing behavior) in the same message where `Piece.type` was correctly rejected as an enum (needs behavior) — good evidence the data-vs-behavior lens *does* fire when actively invoked; the gap is making the pause automatic on sight, not the reasoning itself. Sequence fix: step 4 tests "does this move put **my own king in check**" — not checkmate; checkmate is a terminal state only evaluated for the opponent in step 5.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

| LLD method | HTTP / WS |
|---|---|
| `make_move(from, to)` | `POST /api/v1/matches/{id}/moves` `{from, to}` -> **200** `{status, board}` · **400** illegal move · **409** not your turn |
| *(read model)* | `GET /api/v1/matches/{id}` -> **200** `{board, current_turn, status}` |
| *(opponent's move)* | **WebSocket** push — you cannot poll for a live game |
| `is_move_safe` / rule engine | **no endpoint** — it runs *inside* `POST /moves`, server-side. That is the **anti-cheat boundary**: never trust the client's idea of legality |

## Notes / decisions (log the "why" here)
- **Piece movement rules (domain reference, corrected):**
  - **Rook:** straight (horizontal/vertical), any distance, blocked by pieces in its path.
  - **Bishop:** diagonal, any distance, blocked by pieces in its path.
  - **Queen:** Rook + Bishop combined.
  - **King:** one step, any direction; **cannot move into a square under attack** (can't walk into check).
  - **Knight:** L-shape — 2 squares straight then 1 perpendicular (8 possible landing squares). **The only piece that can jump over others** — its path is never blocked.
  - **Pawn:** forward-only movement (1 square, or 2 on its first move); **captures diagonally forward only** (movement ≠ capture — unique to this piece); promotes on reaching the last rank.
- **Checkmate = king in check AND no legal move by any piece resolves it**, via any of 3 escapes: (1) move the king to a safe square, (2) capture the attacking piece, (3) block the line of attack (only works vs. Rook/Bishop/Queen — doesn't work vs. Knight, which jumps).

> 📝 **Review note (Step 4 build — COMPLETE):** working engine; **Fool's Mate plays end-to-end** to a correctly-detected checkmate, all 4 error paths reject, promotion works.
>
> Design payoffs that showed up while building:
> - **`get_attacked_squares` as a default method on the ABC**, overridden only by `PawnMovement`. Needed because the pawn is the *sole* piece where "squares I can move to" ≠ "squares I attack" — using `get_legal_moves` for attack detection gives a **false negative** (empty diagonal reads as unguarded → king walks into capture) *and* a **false positive** (square directly ahead reads as attacked → legal king move wrongly blocked). Five strategies get correct behaviour free; the one exception declares itself.
> - **King-safety enforced in `make_move`, NOT in `KingMovementStrategy`.** Filtering attacked squares inside the king's own movement would infinitely recurse (king A asks "is X attacked?" → loops enemy pieces incl. king B → king B asks the same → …). Enforcing it once via simulate-then-test is *also strictly better*: it catches **pins** (a shielding bishop can't legally move either) with zero extra code — verified by test.
> - **Checkmate and stalemate are ONE computation**: both mean `has_any_legal_move == False`; only the `is_in_check` flag distinguishes them.
> - **Composition beat inheritance for promotion**: because behaviour is *injected*, promoting a pawn is `piece.movement_rule = QueenMovementStrategy()` — swapping one object. With per-type subclasses you'd have to replace the whole `Piece`.
> - Bugs hit en route: `@dataclass(frozenset=True)` (→ `frozen=True`), 4-space indent nesting all strategies inside `SlidingMovement`, `Cell(x+1)` missing its `y`, and `is_square_attacked(king)` passed a Piece where a Cell was expected. Rook/Bishop/Queen deduped into a `SlidingMovement._slide` mixin.
