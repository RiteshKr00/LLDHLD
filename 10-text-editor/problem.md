# Problem 10: Text Editor with Undo/Redo (LLD)

## The prompt (as an interviewer would give it)

> "Design a text editor that supports undo and redo. The user types, deletes, replaces —
> and can Ctrl+Z back, Ctrl+Y forward."

---

## Clarifying questions to ask
1. **Which operations** — insert, delete, replace? Anything else (formatting, cut/paste)?
2. **Undo depth** — unlimited, or capped?
3. **Redo** — supported? What happens to the redo stack when the user makes a *new* edit after undoing?
4. **Document representation** — plain string, or something fancier (rope / gap buffer)?
5. **Extensibility** — will new operation types be added later?
6. **Multi-user / collaborative?** (scope-cutter)

## Clarifications (locked scope from Q&A)
1. Operations: **insert(text, pos)**, **delete(start, end)**, **replace(start, end, text)**.
2. Undo depth: last **50** operations.
3. Redo: yes. **A new edit after an undo CLEARS the redo stack.**
4. Document: a simple string. Rope/gap-buffer out of scope.
5. **New operation types must be addable without touching existing code.**
6. Single user. No collaboration, no persistence.

---

## Step 1 — Requirements  ← YOUR TURN

### Functional (what it DOES — the verbs)
- **insert(text, pos)** · **delete(start, end)** · **replace(start, end, text)**
- **undo** — reverse the last operation (up to 50 deep)
- **redo** — re-apply an undone operation
- **A new edit after an undo CLEARS the redo stack** ← easy to forget, and users notice
- Read the current document

### Non-functional (constraints — the "-ilities")
- **Extensible** — new operation types addable without touching existing code
- **Memory-efficient undo** — 50 levels must not mean 50 copies of the document
- Testable

### Explicitly out of scope (say this out loud — senior move)
- Collaboration · persistence · rich formatting · find/replace-all · cursor & selection state

> 📝 **Review note (Step 1):** operations + the 50-deep cap were right, extensible caught. Added: (a) **redo stack clears on a new edit** — a real behaviour users depend on (undo 5 times, type one letter, and the "future" is gone); (b) **memory efficiency as an explicit NFR**, because that's what actually decides Command vs Memento.

---

## Step 2 — Entities  (nouns → classes)
_The key question: **what does it take to undo an operation?** There are two completely different
answers, and that difference IS Command vs Memento._

### The two answers — and they are the two patterns

**(a) The operation knows how to reverse itself → COMMAND**
```python
class Command(ABC):
    def execute(self, doc): ...
    def undo(self, doc): ...          # <- the operation owns its own inverse

InsertCommand("hello", pos=5)   ->  undo = delete 5 chars at pos 5
DeleteCommand(start=3, end=8)   ->  undo = re-insert the text it removed
                                           (so it must REMEMBER that text)
```
Memory cost = **size of the change**. Insert one letter → the undo entry is one letter.

**(b) Snapshot the state before, restore it after → MEMENTO**
```python
class Memento:                        # an opaque saved state
    def __init__(self, content): self._content = content

editor.save()   -> Memento(whole document)
editor.restore(memento)
```
Memory cost = **size of the whole document**, every single time.

### The verdict (correctly identified)

| | Command | Memento |
|---|---|---|
| Stores | just the delta | the whole state |
| 50 undos on a 10 MB doc | ~KBs | **500 MB** 💀 |
| Needs | every op to be cleanly invertible | nothing — works for anything |
| Extra power | commands are objects → queue, log, replay, macro them | — |

**→ Command for a text editor.** Memento is right when an operation *can't* be cleanly inverted
(a complex transform, a game save, a checkpoint before a risky batch job).

> **In practice they combine:** a `DeleteCommand` has to remember the text it deleted — that
> remembered fragment **is a tiny memento**, of only the affected slice rather than the whole document.
> Real editors are Command-driven with per-command mini-mementos.

### Entities

1. **Document** — holds the text, exposes primitive edits — `content: str`, `insert()`, `delete()`, `get_text()`
2. **Command** *(ABC)* — `execute(doc)`, `undo(doc)`
3. **InsertCommand / DeleteCommand / ReplaceCommand** — each stores what it needs to reverse itself
4. **CommandHistory** — the two stacks + the 50 cap — `push()`, `undo()`, `redo()`
5. **TextEditor** — the entry point users call — `insert()`, `delete()`, `replace()`, `undo()`, `redo()`

> 📝 **Review note (Step 2):** **the core question was answered correctly and for the right reason** — "if the text is large use the first one, otherwise you'd store multiple large states." That's exactly the Command-vs-Memento tradeoff: Command stores the **delta**, Memento stores the **whole state**, so 50 undos on a 10 MB document is KBs vs 500 MB. Named the patterns and added the nuance that real editors **combine** them: a `DeleteCommand` must remember the deleted text, and that fragment is a mini-memento of just the affected slice. Also noted Command's bonus — because operations become *objects*, you get logging, replay and macros for free.

---

## Step 3 — Relationships & APIs

**TWO stacks, not one:**
```
   undo_stack  (deque, maxlen=50)        redo_stack
   ┌──────────┐                          ┌──────────┐
   │ cmd3     │ <- most recent           │          │
   │ cmd2     │                          │          │
   │ cmd1     │                          │          │
   └──────────┘                          └──────────┘
```

**The three flows:**
```
new edit(cmd):     cmd.execute(doc)
                   undo_stack.push(cmd)
                   redo_stack.CLEAR()      <- the branch you undid is now unreachable

undo():            cmd = undo_stack.pop()
                   cmd.undo(doc)
                   redo_stack.push(cmd)    <- moves ACROSS, not deleted

redo():            cmd = redo_stack.pop()
                   cmd.execute(doc)        <- same execute(), replayed
                   undo_stack.push(cmd)
```

**Why redo clears on a new edit:** you undid to a past point and then went a *different* way. The
old future never happened. Keeping it would let you "redo" into a document state that no longer
makes sense.
```
   A -> B -> C          undo twice -> back at A
   A -> D               type something new
        ^ B and C are now unreachable. Clear them.
```

**The 50 cap:** `deque(maxlen=50)` — pushing #51 silently drops the oldest. Exactly the desired
behaviour, and free.

**Signatures:**
```python
class Command(ABC):
    def execute(self, doc: Document) -> None: ...
    def undo(self, doc: Document) -> None: ...

class CommandHistory:
    def push(self, cmd) -> None      # also clears redo
    def undo(self, doc) -> bool
    def redo(self, doc) -> bool

class TextEditor:
    def insert(self, text, pos) -> None
    def delete(self, start, end) -> None
    def replace(self, start, end, text) -> None
    def undo(self) -> bool
    def redo(self) -> bool
    def get_text(self) -> str
```

### ⚠️ The trap: what must each command REMEMBER?

| Command | To undo it you need |
|---|---|
| `InsertCommand(text, pos)` | just `pos` + `len(text)` → delete that range |
| `DeleteCommand(start, end)` | **the text that was deleted** — otherwise you can't put it back |
| `ReplaceCommand(start, end, new)` | **the old text** (to restore) **and** `len(new)` (to know what to remove) |

**And the subtle part:** `DeleteCommand` and `ReplaceCommand` don't know the old text at
**construction** time — they only learn it when they actually run against the document. So:

```python
def execute(self, doc):
    self._removed = doc.get_text()[self.start:self.end]   # CAPTURE during execute
    doc.delete(self.start, self.end)
```

> That captured fragment **is the mini-memento** — a snapshot of just the slice that changed, not
> the whole document. Command and Memento combining, exactly as noted in Step 2.

> 📝 **Review note (Step 3):** stack was right. Completed: (1) it's **two** stacks and undo/redo
> **move commands across** rather than discarding them; (2) a new edit must **clear the redo stack** —
> you branched away, so the old future is unreachable; (3) `deque(maxlen=50)` gives the depth cap for
> free. **The trap:** `Delete` and `Replace` must capture the old text **inside `execute()`**, not in
> `__init__` — at construction they haven't seen the document yet. That captured slice is the
> mini-memento.

---

---

## REST API mapping  (LLD method -> HLD endpoint)

**Also a library, not a service** — a single-user editor runs in-process; there is nothing to call.

It only becomes an API if the document goes **collaborative**:

| LLD method | HTTP / WS |
|---|---|
| `insert / delete / replace` | `POST /api/v1/docs/{id}/operations` `{type, pos, text}` -> **200** `{version}` |
| `undo()` / `redo()` | `POST /api/v1/docs/{id}/undo` · `/redo` -> **200** |
| *(other people's edits)* | **WebSocket** push |

> Note what breaks the moment it is shared: **undo stops being global.** Ctrl+Z must undo *your* last
> operation, not whatever the other person just typed — which needs per-user command stacks and
> operational transforms. That is why collaboration was scoped out.

## Notes / decisions (log the "why" here)
- **Command over Memento** — decided by memory: Command stores the *delta*, Memento the *whole state*. 50 undos on a 10 MB doc = KBs vs 500 MB.
- **But they combine** — `Delete`/`Replace` capture the old text **inside `execute()`** (they haven't seen the document at construction time). That captured slice **is** a mini-memento of just what changed.
- **`Document` knows nothing about undo** — it only does primitive edits. All history logic lives in `CommandHistory`. Separating them means undo/redo can change without touching the document.
- **Two stacks; commands MOVE across** — undo pops from one and pushes to the other, so the object survives and `redo` just calls the same `execute()` again.
- **New edit clears redo** — you branched away from that future, so it's unreachable. Keeping it would let redo jump into a document state that no longer exists.
- **`deque(maxlen=50)`** gives the depth cap for free — pushing #51 silently drops the oldest.
- **Adding a new operation = a new `Command` subclass.** Nothing else changes (Open/Closed) — that was the extensibility NFR.

> 📝 **Review note (Step 4 build):** demo verified the full undo→redo round trip, the **redo-clearing rule** (redo stack visibly went from 2 entries to `[]` after one new edit), and the depth cap (with `max_history=3`, `'ab'` became un-undoable because those commands were dropped). Also demonstrated Command's freebie: because operations are **objects**, a macro is just a list of commands replayed, and the undo stack doubles as a readable **operation log**.
