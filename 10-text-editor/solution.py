"""
Text Editor with Undo/Redo — LLD solution.

THE PATTERN: Command. Each operation is an OBJECT that knows how to do itself
AND undo itself. Contrast with Memento (snapshot the whole state):

    Command : stores the DELTA        -> 50 undos on a 10MB doc = KBs
    Memento : stores the WHOLE STATE  -> 50 undos on a 10MB doc = 500MB

They combine: DeleteCommand must remember the text it removed — that fragment is
a MINI-MEMENTO of just the changed slice, not the whole document.

Bonus of making operations into objects: you get logging, replay and macros free.
"""

from abc import ABC, abstractmethod
from collections import deque
from typing import Optional


MAX_HISTORY = 50


# ---------------------------------------------------------------------------
# HINT (to rebuild) — Document is the RECEIVER: it only does primitive edits.
#   content: str, get_text(), insert(text, pos), delete(start, end) -> returns
#   the removed text (the commands need that return value to undo themselves).
#   ** Document must know NOTHING about undo. Keep all history logic out of it,
#      so the undo strategy can change without touching the document.
# ---------------------------------------------------------------------------
class Document:
    """The receiver. Knows only primitive edits — no undo logic here."""

    def __init__(self, content: str = ""):
        self._content = content

    def get_text(self) -> str:
        return self._content

    def insert(self, text: str, pos: int) -> None:
        if not 0 <= pos <= len(self._content):
            raise IndexError(f"pos {pos} out of range")
        self._content = self._content[:pos] + text + self._content[pos:]

    def delete(self, start: int, end: int) -> str:
        if not 0 <= start <= end <= len(self._content):
            raise IndexError(f"range {start}:{end} out of range")
        removed = self._content[start:end]
        self._content = self._content[:start] + self._content[end:]
        return removed


# ---------------------------------------------------------------------------
# Command — the pattern
#
# HINT (to rebuild) — the Command pattern:
#   Command(ABC) -> execute(doc), undo(doc)     <- @abstractmethod on BOTH
#
#   InsertCommand(text, pos)   easy: undo = delete what we inserted. Knows
#                              everything at construction time.
#   DeleteCommand(start, end)  ** must remember WHAT IT DELETED — but it hasn't
#                              seen the document at __init__! So capture inside
#                              execute():  self._removed = doc.delete(...)
#   ReplaceCommand(start,end,new)  the trickiest: undo needs the OLD text (to put
#                              back) AND len(new_text) (to know what to remove).
#
#   ** Those captured fragments ARE mini-Mementos — a snapshot of only the slice
#      that changed, not the whole document. Command + Memento combined.
# ---------------------------------------------------------------------------
class Command(ABC):
    """An operation as an OBJECT: it can do itself and undo itself.

    Adding a new operation type = a new class. Nothing else changes (Open/Closed).
    """

    @abstractmethod
    def execute(self, doc: Document) -> None: ...

    @abstractmethod
    def undo(self, doc: Document) -> None: ...


class InsertCommand(Command):
    """Simplest case: to undo an insert, delete what we inserted.
    Nothing needs capturing — we already know the text and where it went."""

    def __init__(self, text: str, pos: int):
        self.text = text
        self.pos = pos

    def execute(self, doc: Document) -> None:
        doc.insert(self.text, self.pos)

    def undo(self, doc: Document) -> None:
        doc.delete(self.pos, self.pos + len(self.text))

    def __repr__(self):
        return f"Insert({self.text!r} @{self.pos})"


class DeleteCommand(Command):
    """To undo a delete you must put back WHAT WAS THERE — but you don't know
    that at construction time. Capture it during execute()."""

    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end
        self._removed: str = ""          # <- the mini-memento

    def execute(self, doc: Document) -> None:
        self._removed = doc.delete(self.start, self.end)    # CAPTURE, then act

    def undo(self, doc: Document) -> None:
        doc.insert(self._removed, self.start)

    def __repr__(self):
        return f"Delete({self.start}:{self.end} -> {self._removed!r})"


class ReplaceCommand(Command):
    """The trickiest: undo needs the OLD text (to restore) AND the length of the
    NEW text (to know how much to remove)."""

    def __init__(self, start: int, end: int, new_text: str):
        self.start = start
        self.end = end
        self.new_text = new_text
        self._old_text: str = ""         # <- the mini-memento

    def execute(self, doc: Document) -> None:
        self._old_text = doc.delete(self.start, self.end)   # capture what we're overwriting
        doc.insert(self.new_text, self.start)

    def undo(self, doc: Document) -> None:
        doc.delete(self.start, self.start + len(self.new_text))   # remove the new
        doc.insert(self._old_text, self.start)                    # restore the old

    def __repr__(self):
        return f"Replace({self.start}:{self.end} {self._old_text!r} -> {self.new_text!r})"


# ---------------------------------------------------------------------------
# History — two stacks
#
# HINT (to rebuild) — TWO stacks, and commands MOVE between them:
#     new edit -> execute, push to undo, and CLEAR REDO
#     undo()   -> pop undo  -> cmd.undo(doc)    -> push redo
#     redo()   -> pop redo  -> cmd.execute(doc) -> push undo   (same execute!)
#
#   ** Why clear redo on a new edit: you branched away from that future, so it can
#      never be reached again. Keeping it would let redo jump into a document
#      state that no longer exists.
#   ** deque(maxlen=50) gives the depth cap for free — pushing #51 silently drops
#      the oldest, which is exactly the desired behaviour.
# ---------------------------------------------------------------------------
class CommandHistory:
    """undo_stack and redo_stack. Commands MOVE between them; they aren't discarded.

        new edit -> push to undo, CLEAR redo
        undo     -> pop undo  -> cmd.undo()    -> push redo
        redo     -> pop redo  -> cmd.execute() -> push undo
    """

    def __init__(self, max_history: int = MAX_HISTORY):
        # deque(maxlen=N) silently drops the OLDEST on overflow — exactly the cap we want
        self._undo: deque[Command] = deque(maxlen=max_history)
        self._redo: list[Command] = []

    def push(self, cmd: Command) -> None:
        self._undo.append(cmd)
        # A new edit means we branched away from the undone future. It can never
        # be reached again, so it must go — otherwise redo would jump into a
        # document state that no longer exists.
        self._redo.clear()

    def undo(self, doc: Document) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        cmd.undo(doc)
        self._redo.append(cmd)          # moves ACROSS
        return True

    def redo(self, doc: Document) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        cmd.execute(doc)                # the SAME execute, replayed
        self._undo.append(cmd)
        return True

    def undo_stack(self) -> list:
        return list(self._undo)

    def redo_stack(self) -> list:
        return list(self._redo)


# ---------------------------------------------------------------------------
# TextEditor — entry point
#
# HINT (to rebuild) — thin entry point. Every edit method is the same 2 lines:
#     build the right Command, then self._run(cmd)
#   where _run does: cmd.execute(self._doc); self._history.push(cmd)
#   ** Adding a new operation type = a NEW Command subclass + one thin method.
#      Nothing existing changes (Open/Closed) — that was the extensibility NFR.
# ---------------------------------------------------------------------------
class TextEditor:
    def __init__(self, content: str = "", max_history: int = MAX_HISTORY):
        self._doc = Document(content)
        self._history = CommandHistory(max_history)

    def _run(self, cmd: Command) -> None:
        cmd.execute(self._doc)
        self._history.push(cmd)

    def insert(self, text: str, pos: int) -> None:
        self._run(InsertCommand(text, pos))

    def delete(self, start: int, end: int) -> None:
        self._run(DeleteCommand(start, end))

    def replace(self, start: int, end: int, text: str) -> None:
        self._run(ReplaceCommand(start, end, text))

    def undo(self) -> bool:
        return self._history.undo(self._doc)

    def redo(self) -> bool:
        return self._history.redo(self._doc)

    def get_text(self) -> str:
        return self._doc.get_text()

    def history(self) -> tuple[list, list]:
        return self._history.undo_stack(), self._history.redo_stack()


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ed = TextEditor()

    print("=== typing ===")
    ed.insert("Hello", 0)
    print(f"  insert 'Hello'      -> {ed.get_text()!r}")
    ed.insert(" World", 5)
    print(f"  insert ' World'     -> {ed.get_text()!r}")
    ed.replace(0, 5, "Goodbye")
    print(f"  replace 0:5 'Goodbye' -> {ed.get_text()!r}")
    ed.delete(7, 13)
    print(f"  delete 7:13         -> {ed.get_text()!r}")

    print("\n=== undo all the way back ===")
    while ed.undo():
        print(f"  undo -> {ed.get_text()!r}")

    print("\n=== redo all the way forward ===")
    while ed.redo():
        print(f"  redo -> {ed.get_text()!r}")

    print("\n=== the redo-clearing rule ===")
    ed2 = TextEditor()
    ed2.insert("A", 0); ed2.insert("B", 1); ed2.insert("C", 2)
    print(f"  typed ABC           -> {ed2.get_text()!r}")
    ed2.undo(); ed2.undo()
    u, r = ed2.history()
    print(f"  undo twice          -> {ed2.get_text()!r}   redo stack: {r}")
    ed2.insert("X", 1)                       # a NEW edit -> the old future dies
    u, r = ed2.history()
    print(f"  type 'X' (new edit) -> {ed2.get_text()!r}   redo stack: {r}  <- CLEARED")
    print(f"  redo now returns    -> {ed2.redo()}")

    print("\n=== the 50-deep cap ===")
    ed3 = TextEditor(max_history=3)
    for ch in "abcde":
        ed3.insert(ch, len(ed3.get_text()))
    print(f"  typed 'abcde' with max_history=3 -> {ed3.get_text()!r}")
    print(f"  undo stack holds only: {ed3.history()[0]}")
    while ed3.undo():
        pass
    print(f"  undo everything possible -> {ed3.get_text()!r}  <- 'ab' can't be undone, dropped")

    print("\n=== Command's bonus: operations are OBJECTS ===")
    ed4 = TextEditor("data")
    macro = [InsertCommand("[", 0), InsertCommand("]", 5)]
    for c in macro:                          # a replayable MACRO, for free
        ed4._run(c)
    print(f"  applied a macro -> {ed4.get_text()!r}")
    print(f"  the log reads   -> {ed4.history()[0]}")
