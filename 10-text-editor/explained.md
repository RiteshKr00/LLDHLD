# Text Editor with Undo/Redo

> **Is problem ka core:** ek operation ko **object** bana do, taaki woh khud ko ulta kar sake.

---

## Problem kya hai

Text editor. User type karta hai, delete karta hai, replace karta hai. **Ctrl+Z** peeche le jaata
hai, **Ctrl+Y** aage.

---

## Pehla instinct

```python
class Editor:
    def __init__(self):
        self.text = ""

    def insert(self, s, pos):
        self.text = self.text[:pos] + s + self.text[pos:]

    def delete(self, start, end):
        self.text = self.text[:start] + self.text[end:]
```

Chalta hai. Ab **undo** add karo... aur ruk jao. **Kaise?**

Text badal chuka hai. Purana text **kahin save hi nahi kiya**. Jo delete kiya woh **gayab** ho gaya.
Undo karne ke liye information hai hi nahi.

---

## Do raaste hain (aur yehi do patterns hain)

### Raasta (a): "har operation apna ulta jaanta ho" → **COMMAND**

Har operation ko ek **object** bana do, jisme do method hon:

```python
class InsertCommand:
    def __init__(self, text, pos):
        self.text, self.pos = text, pos

    def execute(self, doc):
        doc.insert(self.text, self.pos)

    def undo(self, doc):
        doc.delete(self.pos, self.pos + len(self.text))   # ulta kaam
```

Insert ka ulta = delete. Delete ka ulta = insert. Har command ko pata hai apna ulta kya hai.

**Memory:** sirf **jo badla** utna. Ek letter type kiya → undo entry ek letter ki.

### Raasta (b): "pehle ka poora document save kar lo" → **MEMENTO**

```python
class Memento:
    def __init__(self, content):
        self._content = content        # poora document ka snapshot

# har operation se pehle:
history.append(Memento(doc.text))
# undo pe: doc.text = history.pop()._content
```

Simple hai. Par **memory:** har baar **poora document**.

### Kaunsa kab? (yeh tumne khud sahi bola tha)

| | Command | Memento |
|---|---|---|
| Store karta hai | sirf **delta** | **poora state** |
| 10 MB doc, 50 undo | ~KB | **500 MB** 💀 |
| Chahiye | har op ka ulta pata ho | kuch nahi — kisi bhi cheez pe chalta hai |
| Bonus | commands **objects** hain → log, replay, macro, queue | — |

**→ Text editor mein Command.** Kyunki text edits ka ulta hamesha nikala ja sakta hai.

**Memento tab** jab operation ka ulta nikalna **possible hi na ho** — koi complex transform, game
save, ya risky batch job se pehle ka checkpoint.

---

## Par asli mein dono milte hain

Socho `DeleteCommand` ka undo:

```python
class DeleteCommand:
    def undo(self, doc):
        doc.insert(???, self.start)      # kya insert karein?
```

**Jo delete kiya tha wahi text** — par woh toh gayab ho chuka! Toh delete karte waqt **yaad rakhna**
padega:

```python
def execute(self, doc):
    self._removed = doc.delete(self.start, self.end)   # PEHLE capture, phir delete
```

**Woh saved fragment ek chhota Memento hai** — poore document ka nahi, sirf **jo hissa badla** uska.

Asli editors yahi karte hain: **Command-driven, par har command ke andar ek mini-memento.**

### Ek zaroori detail

`DeleteCommand` ko purana text **banate waqt pata nahi hota** — usne document dekha hi nahi abhi tak!

```python
DeleteCommand(3, 8)          # abhi kuch pata nahi
    ↓
cmd.execute(doc)             # AB document mila -> ab capture kar sakte hain
```

Isliye capture **`execute()` ke andar** hota hai, `__init__` mein nahi.

---

## Do stacks, ek nahi

```
   undo_stack                      redo_stack
   ┌──────────┐                    ┌──────────┐
   │ cmd3     │ <- last            │          │
   │ cmd2     │                    │          │
   │ cmd1     │                    │          │
   └──────────┘                    └──────────┘
```

**Teen flows:**

```
naya edit:   cmd.execute(doc)
             undo_stack.push(cmd)
             redo_stack.CLEAR()      <- yeh line important hai, neeche padho

undo():      cmd = undo_stack.pop()
             cmd.undo(doc)
             redo_stack.push(cmd)    <- command MARTA nahi, doosre stack mein chala jaata hai

redo():      cmd = redo_stack.pop()
             cmd.execute(doc)        <- wahi execute, dobara
             undo_stack.push(cmd)
```

**Commands undo se marte nahi** — bas ek stack se doosre mein move karte hain. Isliye redo ke liye
kuch naya nahi likhna padta, wahi `execute()` phir se chal jaata hai.

---

## Naya edit redo ko kyun clear karta hai?

```
   ABC type kiya:       A ──▶ AB ──▶ ABC
                                      ▲ yahan ho

   do baar undo:        A             redo mein: [C, B]
                        ▲ yahan ho

   ab "X" type kiya:    A ──▶ AX
                                ▲ tum DOOSRE raste chale gaye

   AB aur ABC is timeline mein hue hi nahi.
   Redo karke unme jaana matlab aisi state mein jaana jo exist hi nahi karti.
   -> redo_stack.clear()
```

Yeh baat users actually notice karte hain — undo karke kuch naya type karo, toh redo **band** ho
jaata hai. Har editor mein aisa hi hota hai.

---

## 50 ki limit — free mein

```python
from collections import deque
self._undo = deque(maxlen=50)
```

51st push pe **sabse purana apne aap gir jaata hai**. Bilkul wahi jo chahiye tha, aur ek line mein.

---

## Command ka chhupa hua fayda

Kyunki operation ab ek **object** hai (na ki ek function call jo ho ke khatam ho gaya), yeh sab
**free** mil jaata hai:

| Cheez | Kaise |
|---|---|
| **Log** | `undo_stack` khud hi history hai — padh lo |
| **Macro** | `[cmd1, cmd2, cmd3]` — list bana ke replay kar do |
| **Queue** | commands ko network pe bhej do, kahin aur execute karo |
| **Replay** | saved command list se poora session dobara chala do |

Agar operation sirf ek function call hota, toh in mein se **kuch bhi possible nahi** tha.

---

## Interview line

> *"Undo ke do tareeke hain — operation khud apna ulta jaane (**Command**), ya har baar poora state
> save karo (**Memento**). Maine Command chuna kyunki woh sirf **delta** store karta hai — 10 MB
> document pe 50 undo matlab KBs, Memento mein 500 MB hota. Par dono milte hain: `DeleteCommand` ko
> hataya hua text yaad rakhna padta hai, aur woh fragment ek **mini-memento** hai — sirf badle hue
> hisse ka. Aur command ko object banane se log, macro aur replay free mein mil jaate hain."*
