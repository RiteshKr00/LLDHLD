# Chess

> **Is problem ka core:** har piece ka move-logic alag hai → polymorphism. Aur "simulate karke check karo".

---

## Problem kya hai

8×8 board, 6 tarah ke pieces, har ek ke apne rules. Move valid hai ya nahi batao, turn enforce karo,
aur check / checkmate / stalemate detect karo.

---

## Pehla instinct

```python
def can_move(piece, from_cell, to_cell, board):
    if piece.type == "rook":
        # ...25 lines, seedhi line mein slide...
    elif piece.type == "bishop":
        # ...25 lines, diagonal slide...
    elif piece.type == "knight":
        # ...15 lines, L-shape...
    elif piece.type == "queen":
        # ...40 lines (rook + bishop ka copy-paste)...
    elif piece.type == "pawn":
        # ...30 lines, aur yeh sabse weird hai...
```

Dikkat:

**1. 150-line ka function.** Koi bhi ise dimaag mein nahi rakh sakta.

**2. Queen ka code copy-paste hai** rook + bishop se. Kal sliding mein bug mila, toh **do jagah** fix
karna padega. Tum ek jagah bhool jaoge. Pakka.

**3. "Knight ka test likho."** → Poore giant function ko call karo aur umeed karo ki sahi branch hit
ho jaye.

**4. "Ek naya custom piece add karo."** → Us 150-line function ko edit karo jo abhi theek chal raha
hai. Har edit mein rook ke tootne ka risk.

---

## Test wahi: data ya behaviour?

Ab tak yeh test do baar aa chuka hai. Yahan phir:

- **Parking (VehicleType):** Truck aur Car dono bas ek spot ghere hain. Sirf *kaunsa spot fit hai*
  alag — ek **lookup table**. → **Data** → enum. ✅
- **Chess (Piece type):** Rook ka legal-move nikalne ka **algorithm** knight se bilkul alag hai.
  Yeh koi table nahi hai — yeh alag-alag **code** hai. → **Behaviour** → polymorphism. ✅

Toh piece types ko enum banana galat hoga.

---

## Do tarike, humne (b) chuna

**(a) Classic subclassing:**
```python
class Piece(ABC): ...
class Rook(Piece): def get_legal_moves(...)
class Knight(Piece): def get_legal_moves(...)
```

**(b) Composition — movement rule inject karo:** ← humne yeh liya
```python
@dataclass
class Piece:
    color, position, has_moved
    movement_rule: MovementStrategy      # <- behaviour bahar se aata hai

rook   = Piece(WHITE, cell, RookMovementStrategy())
knight = Piece(WHITE, cell, KnightMovementStrategy())
```

**Kyun (b)?** Kyunki yeh **wahi Strategy pattern hai** jo `ShortCodeGenerator`, `SpotAssignmentStrategy`,
`RateLimitAlgorithm` mein tha. Ek hi soch, chhathi baar. Piece ek hi concrete class rehti hai, uske
andar behaviour ka object baithta hai.

Dono defensible hain — par consistency achhi cheez hai.

---

## Sliding pieces — DRY

Rook, Bishop, Queen ka loop bilkul same hai, sirf **directions** alag:

```python
class SlidingMovement:                       # mixin — sirf shared loop
    def _slide(self, piece, board, directions):
        for dx, dy in directions:
            x, y = piece.position.x, piece.position.y
            while True:
                x += dx; y += dy
                cell = Cell(x, y)
                if not cell.is_on_board(): break
                other = board.get_piece_at(cell)
                if other:
                    if other.color != piece.color:
                        moves.append(cell)   # dushman -> kaat sakte ho
                    break                    # par aage nahi jaa sakte (dono case mein)
                moves.append(cell)           # khali -> chalte raho
```

Ab teeno classes 3-line ki ho gayin:
```python
class RookMovementStrategy(SlidingMovement, MovementStrategy):
    def get_legal_moves(self, piece, board):
        return self._slide(piece, board, [(1,0), (-1,0), (0,1), (0,-1)])
```
Queen = rook ke 4 + bishop ke 4 = 8 directions. **Copy-paste khatam.**

Knight aur King slide nahi karte — unke **fixed offsets** hain (8-8), bas "board pe hai kya" aur
"apna piece toh nahi hai" check karo.

---

## Pawn — akela weirdo

Har piece ke liye "jahan ja sakta hoon" = "jahan attack karta hoon". **Pawn ke liye nahi.**

- **Chalta hai:** seedha aage (sirf **khali** khaane pe)
- **Maarta hai:** **diagonal** aage (sirf agar wahan dushman ho)

Do bilkul alag sets! Isliye:

```python
def get_legal_moves(...):     # kahan JA sakta hoon
    # 1. ek aage — sirf agar KHALI hai
    #    (dushman saamne ho toh woh BLOCK hai, kill nahi — yeh pawn ki khaas baat hai)
    # 2. do aage — sirf agar has_moved=False AUR pehla khaana bhi khali tha
    # 3&4. diagonal — sirf agar wahan DUSHMAN khada hai

def get_attacked_squares(...):   # kahan CONTROL karta hoon
    # bas dono diagonals — chahe wahan koi ho ya na ho!
```

### Yeh alag kyun karna pada — asli bug

Agar `is_square_attacked` ke liye `get_legal_moves` use karo, toh **do galtiyan** hoti hain:

**Galti 1 — khatarnaak wali (false negative):**
Kaala pawn `(3,4)` pe. Safed raja `(4,3)` pe jaana chahta hai — woh khaana **khali** hai.
- Pawn ke `get_legal_moves` mein `(4,3)` nahi aayega (khali hai, kaatne ko kuch nahi)
- → `is_square_attacked` bolega **"safe hai"**
- → Raja wahan chala gaya → **agli chaal mein mar gaya**. Tumne illegal move allow kar diya.

Pawn us khaane ko **control** karta hai, chahe abhi wahan kuch na ho.

**Galti 2 — chidhane wali (false positive):**
Raja `(3,3)` jaana chahta hai — pawn ke **bilkul saamne**.
- Pawn ke legal moves mein `(3,3)` hai (khali hai, aage badh sakta hai)
- → `is_square_attacked` bolega **"attacked hai"** → raja ko roka
- Par pawn **seedha maar hi nahi sakta**! Woh khaana bilkul safe tha.

**Fix:** ABC mein ek **default method** daal do jo baaki sab ke liye theek hai, aur sirf Pawn use
override kare:
```python
class MovementStrategy(ABC):
    def get_attacked_squares(self, piece, board):
        return self.get_legal_moves(piece, board)   # 5 pieces ke liye same hai
```
Sirf `PawnMovement` ise override karta hai. **Ek exception, ek override.** Clean.

---

## King — aur infinite recursion ka trap

King ke 8 padosi khaane. Bas "board pe hai" + "apna piece nahi hai".

**Par ruko — asli king toh check mein nahi ja sakta! Woh check kahan hai?**

Yahan **jaanbujh ke nahi** daala. Kyun? Socho agar `KingMovementStrategy` andar
`board.is_square_attacked(...)` call kare:

```
Safed raja: "kya (4,5) attacked hai?"
  → Board saare kaale pieces ghoomta hai, kaale raja samet
    → Kaala raja: "kya (3,2) attacked hai?"
      → Board saare safed pieces ghoomta hai, safed raja samet
        → Safed raja: "kya (4,5) attacked hai?" → 💥 infinite recursion
```

Dono raje ek dusre se hamesha poochte rahenge.

**Isliye:** `get_legal_moves` sirf **geometry** batata hai — "yeh piece physically kahan jaa sakta
hai". "Check mein mat jao" wala rule **ek level upar** `make_move` mein lagta hai.

**Aur yeh sirf workaround nahi, behtar design hai** — kyunki wahi ek rule ek aur case pakad leta hai
jo tumne likha hi nahi:

> **Pinned piece.** Tumhara bishop raja aur dushman ke rook ke beech mein khada hai. Bishop ka apna
> move bilkul legal hai — par usko hilaoge toh raja expose ho jayega. **Illegal.**
> King-only check ise kabhi nahi pakad pata. "Simulate karo, phir apne raja ko dekho" pakad leta hai.

---

## `make_move` — 5 steps

```python
def make_move(self, from_cell, to_cell):
    1. piece = board.get_piece_at(from_cell)
       - None? -> raise
       - piece.color != current_turn? -> raise ("teri baari nahi")
    2. legal = piece.movement_rule.get_legal_moves(piece, board)
    3. to_cell legal mein nahi? -> raise
    4. is_move_safe(...)? nahi -> raise ("tera raja check mein aa jayega")
    5. Commit: move karo, has_moved=True, promotion dekho, turn palto, status update karo
```

Step 4 ka test **"apna raja check mein aayega kya"** hai — **checkmate nahi**. Checkmate ek terminal
state hai, aur woh step 5 mein **dushman** ke liye check hota hai.

### Simulate karne ka tarika
```python
def is_move_safe(board, from_cell, to_cell, color):
    moving, captured = try_move(board, from_cell, to_cell)   # kar ke dekho
    safe = not is_in_check(board, color)                      # ab dekho
    undo_move(board, from_cell, to_cell, moving, captured)    # waapas kar do
    return safe                                               # ORDER important hai
```
**Trap:** `safe` **undo se pehle** nikaalo, `return` **undo ke baad** karo. Beech mein `return` kar
diya toh board **kharab reh jayega**.

Aur `try_move`/`undo_move` mein `moving.position = to_cell` **mat bhoolna** — piece apni position
khud rakhta hai, sirf grid badalna kaafi nahi.

---

## Checkmate vs Stalemate — ek hi calculation!

Yeh sabse pyaari cheez hai is problem mein:

```python
in_check = is_in_check(board, current_turn)
can_move = has_any_legal_move(board, current_turn)

if not can_move:
    status = CHECKMATE if in_check else STALEMATE     # bas itna hi farak
else:
    status = IN_PROGRESS
```

**Dono ka matlab same hai: "koi legal move bachi hi nahi".** Farak sirf itna ki **abhi check mein ho
ya nahi**. Do alag lagne wale rules, **ek calculation + ek boolean**.

Aur `has_any_legal_move` har piece ke har move pe `is_move_safe` chalata hai — isliye "check se
bachne ke 3 tarike" (raja hilao / attacker ko maaro / raasta block karo) **apne aap** cover ho jaate
hain. Tumne teenon ko alag se code nahi kiya.

---

## Grid ka chakkar: `cells[y][x]`

```python
self.cells = [[None]*8 for _ in range(8)]     # list of lists
```
Pehla index **row** (y), doosra **column** (x). Toh `cells[y][x]`.

**Confusing part:**
```python
Cell(3, 5)      # x=3, y=5   <- x pehle
cells[5][3]     # y=5, x=3   <- y pehle  (ULTA!)
```

Isliye yeh flip **sirf ek jagah** hota hai:
```python
def get_piece_at(self, cell):
    return self.cells[cell.y][cell.x]
```
Baaki poore code mein sirf `Cell` pass karo, kabhi socho mat.

> **Aur ek trap:** Python mein negative index **wrap** ho jaata hai — `cells[-1][3]` error nahi
> deta, aakhri row de deta hai. Isliye `is_on_board()` **pehle** check karna zaroori hai.

---

## Interview line

> *"Piece types ka behaviour genuinely alag hai — rook ka algorithm knight se alag hai, koi lookup
> table nahi — isliye polymorphism, injected `MovementStrategy` ke through. Aur king-safety maine
> per-piece nahi, `make_move` mein ek jagah rakha (simulate → test → undo) — usse pinned pieces bhi
> apne aap handle ho jaate hain, aur do raje ek dusre ko infinitely poochne se bach jaate hain."*
