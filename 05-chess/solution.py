"""
Chess — LLD solution (built step by step).

Entities (Step 2):
    1. Cell               - board coordinate (value object)
    2. Piece               - one piece; behavior injected via MovementStrategy
    3. MovementStrategy     - Strategy: computes legal destinations per piece type
    4. Board                - 8x8 grid; owns is_square_attacked (check detection)
    5. Player                - a side in the game
    6. Match                  - state/record of one game in progress
    7. ChessOrchestrator       - entry point; make_move(from_cell, to_cell)
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Step 4a: Color, Cell, GameStatus   <-- YOUR TURN
#
#   1. Color(Enum)      -> WHITE, BLACK
#   2. Cell (@dataclass, frozen=True so it's hashable -> usable in sets/dict keys)
#        -> x: int, y: int  (0..7 each)
#        -> add an `is_on_board()` helper: 0 <= x <= 7 and 0 <= y <= 7
#   3. GameStatus(Enum) -> IN_PROGRESS, CHECKMATE, STALEMATE
# ---------------------------------------------------------------------------
class Color(Enum):
    WHITE="white"
    BLACK="black"

@dataclass(frozen=True)
class Cell:
    x: int
    y: int

    def is_on_board(self)->bool:
        return 0 <= self.x <=7 and 0 <= self.y <= 7


class GameStatus(Enum):
    IN_PROGRESS = "in_progress"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"

# ---------------------------------------------------------------------------
# Step 4b: Piece + MovementStrategy (ABC) — one concrete strategy first (Rook)
# ---------------------------------------------------------------------------
class MovementStrategy(ABC):
    @abstractmethod
    def get_legal_moves(self,piece:Piece,board: Board)->list:
        pass


    def get_attacked_squares(self,piece:Piece,board:Board)->list[Cell]:
        # By default, the attacked squares are the same as legal moves
        return self.get_legal_moves(piece,board)


@dataclass
class Piece:
    color:Color
    position:Cell
    movement_rule:MovementStrategy
    has_moved: bool=False

class SlidingMovement:
    """Mixin: the shared 'slide outward until blocked' loop used by
    Rook / Bishop / Queen. They differ only in WHICH directions they slide."""

    def _slide(self, piece, board, directions) -> list[Cell]:
        legal_moves = []
        for dx, dy in directions:
            x, y = piece.position.x, piece.position.y
            while True:
                x += dx
                y += dy
                new_cell = Cell(x, y)
                if not new_cell.is_on_board():
                    break
                occupying_piece = board.get_piece_at(new_cell)
                if occupying_piece:
                    if occupying_piece.color != piece.color:
                        legal_moves.append(new_cell)   # capture the enemy...
                    break                              # ...but stop either way
                legal_moves.append(new_cell)           # empty -> keep sliding
        return legal_moves


class RookMovementStrategy(SlidingMovement, MovementStrategy):
    def get_legal_moves(self, piece: Piece, board: Board) -> list[Cell]:
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        return self._slide(piece, board, directions)


# ---------------------------------------------------------------------------
# Step 4c: Board — cells, get_piece_at, is_square_attacked
#
# HOW THE GRID IS REPRESENTED  (read this before touching cells[][] directly)
#
#   self.cells = [[None]*8 for _ in range(8)]   -> a LIST OF LISTS.
#   Indexing applies OUTER first, then INNER:
#
#       cells    = [ row0, row1, row2, ... row7 ]     <- outer list = ROWS  (y)
#                       |
#       cells[3] = [ col0, col1, col2, ... col7 ]     <- inner list = COLS  (x)
#
#   So the convention here is:  row = y , column = x  =>  cells[y][x]
#   (Rows-first is the usual grid convention: it matches how you print a board
#    row by row, and how matrices/numpy are indexed.)
#
#   ** THE GOTCHA — the two orderings are REVERSED:
#         Cell(3, 5)     ->  x=3, y=5     (constructor takes x first)
#         cells[5][3]    ->  y=5, x=3     (lookup takes y first)
#      Writing cells[x][y] by mistake does NOT crash — it silently reads the
#      WRONG square. That's why the flip is done in exactly ONE place:
#         get_piece_at(cell) -> self.cells[cell.y][cell.x]
#      Everywhere else, pass a Cell and never think about it. The only other
#      places touching raw indexes are try_move / undo_move (Step 4e).
#
#   ** Second gotcha: Python negative indexes WRAP instead of erroring.
#      cells[-1][3] happily returns row 7. So callers must check
#      cell.is_on_board() BEFORE calling get_piece_at (all the movement
#      strategies do). A defensive `if not cell.is_on_board(): return None`
#      inside get_piece_at would make it bullet-proof.
# ---------------------------------------------------------------------------
class Board:
    def __init__(self):
        self.cells = [[None for _ in range(8)] for _ in range(8)]  # 8x8 grid: cells[y][x]

    def get_piece_at(self, cell: Cell):
        return self.cells[cell.y][cell.x]

    def is_square_attacked(self, cell: Cell, by_color: Color) -> bool:
        # Check if the square is attacked by any piece of the given color
        for row in self.cells:
            for piece in row:
                if piece and piece.color == by_color:
                    attacked_squares = piece.movement_rule.get_attacked_squares(piece, self)
                    if cell in attacked_squares:
                        return True
        return False


# --- ALTERNATIVE: dict-based board (same interface, different storage) --------
# Tradeoff vs the 2D array above:
#   + iterates only real pieces (~32) instead of scanning all 64 squares
#   + off-board lookups return None naturally (no negative-index wraparound)
#   - less "board-shaped"; harder to print/render as a grid
#   - REQUIRES Cell to be hashable -> that's why Cell is @dataclass(frozen=True)
#
# class Board:
#     def __init__(self):
#         self.pieces: dict[Cell, Piece] = {}     # only occupied squares are stored
#
#     def get_piece_at(self, cell: Cell) -> Optional[Piece]:
#         return self.pieces.get(cell)            # missing key -> None, no bounds bug
#
#     def place(self, piece: Piece) -> None:
#         self.pieces[piece.position] = piece
#
#     def remove(self, cell: Cell) -> None:
#         self.pieces.pop(cell, None)
#
#     def is_square_attacked(self, cell: Cell, by_color: Color) -> bool:
#         for piece in list(self.pieces.values()):        # ~32 iterations, not 64
#             if piece.color == by_color:
#                 if cell in piece.movement_rule.get_attacked_squares(piece, self):
#                     return True
#         return False
# -----------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Step 4d: remaining MovementStrategy concretes (Knight, Bishop, Queen, King, Pawn)
# ---------------------------------------------------------------------------
class PawnMovement(MovementStrategy):
    """The only piece where MOVES and ATTACKS are different sets:
    moves straight forward (onto empty squares only), captures diagonally."""

    def get_legal_moves(self, piece: Piece, board: Board) -> list[Cell]:
        x, y = piece.position.x, piece.position.y
        direction = 1 if piece.color == Color.WHITE else -1
        moves = []

        # 1. one step forward — only onto an EMPTY square (an enemy there BLOCKS, not captures)
        one_step = Cell(x, y + direction)
        if one_step.is_on_board() and board.get_piece_at(one_step) is None:
            moves.append(one_step)

            # 2. two steps forward — only from the start, and only if step 1 was clear
            #    (nested inside step 1 -> can't jump over a blocker)
            two_step = Cell(x, y + 2 * direction)
            if not piece.has_moved and two_step.is_on_board() and board.get_piece_at(two_step) is None:
                moves.append(two_step)

        # 3 & 4. diagonal captures — ONLY if an enemy is actually standing there
        for diagonal in (Cell(x - 1, y + direction), Cell(x + 1, y + direction)):
            if diagonal.is_on_board():
                target = board.get_piece_at(diagonal)
                if target and target.color != piece.color:
                    moves.append(diagonal)

        return moves

    def get_attacked_squares(self, piece, board):
        # Overridden: the diagonals are CONTROLLED whether or not anything is there.
        # (Using get_legal_moves here would miss empty-but-guarded squares -> king
        #  could walk into a pawn's capture square.)
        direction= 1 if piece.color == Color.WHITE else -1
        moves=[]
        for c in [Cell(piece.position.x-1,piece.position.y+direction),Cell(piece.position.x+1,piece.position.y+direction)]:
            if c.is_on_board():
                moves.append(c)
        return moves


class BishopMovementStrategy(SlidingMovement, MovementStrategy):
    def get_legal_moves(self,piece:Piece,board:Board)->list[Cell]:
        directions=[(1,1),(1,-1),(-1,1),(-1,-1)]
        return self._slide(piece,board,directions)

class QueenMovementStrategy(SlidingMovement, MovementStrategy):
    def get_legal_moves(self,piece:Piece,board:Board)->list[Cell]:
        directions=[(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
        return self._slide(piece,board,directions)

class KnightMovementStrategy(MovementStrategy):
    def get_legal_moves(self,piece:Piece,board:Board)->list[Cell]:
        moves=[]
        x,y=piece.position.x,piece.position.y
        knight_offsets=[(2,1),(2,-1),(-2,1),(-2,-1),(1,2),(1,-2),(-1,2),(-1,-2)]
        for dx,dy in knight_offsets:
            new_cell=Cell(x+dx,y+dy)
            if new_cell.is_on_board():
                occupying_piece=board.get_piece_at(new_cell)
                if not occupying_piece or occupying_piece.color!=piece.color:
                    moves.append(new_cell)
        return moves

class KingMovementStrategy(MovementStrategy):
    """8 adjacent squares. NOTE: deliberately does NOT filter out attacked
    squares -- doing so would recurse infinitely (king A asks 'is X attacked?'
    -> loops enemy pieces incl. king B -> king B asks 'is Y attacked?' -> ...).
    The 'never move into check' rule is enforced once, in make_move()."""

    def get_legal_moves(self,piece:Piece,board:Board)->list[Cell]:
        moves=[]
        x,y=piece.position.x,piece.position.y
        king_offsets=[(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
        for dx,dy in king_offsets:
            new_cell=Cell(x+dx,y+dy)
            if new_cell.is_on_board():
                occupying_piece=board.get_piece_at(new_cell)
                if not occupying_piece or occupying_piece.color!=piece.color:
                    moves.append(new_cell)
        return moves


# ---------------------------------------------------------------------------
# Step 4e: Match + ChessOrchestrator — make_move() sequence, checkmate/stalemate
# ---------------------------------------------------------------------------
def find_king(board: Board, color: Color) -> Optional[Piece]:
    """Scan the board for the king of `color`.

    HINT — you need to look at all 64 squares. Board.cells is a list of rows,
    each row a list of 8 entries (a Piece or None). So:
        for row in board.cells:
            for piece in row:
    Then: skip empties (`if piece is None: continue`), skip the wrong color,
    and return the one whose movement_rule is a KingMovementStrategy.
    Test that with: isinstance(piece.movement_rule, KingMovementStrategy)
    Return None if not found (shouldn't happen in a real game).
    """
    for row in board.cells:
        for piece in row:
            if piece is not None and isinstance(piece.movement_rule,KingMovementStrategy) and piece.color==color:
                return piece
    return None


def is_in_check(board: Board, color: Color) -> bool:
    """Is `color`'s king currently attacked?

    HINT — 3 lines. Find that color's king (function above). Work out the
    opponent's color (if color is WHITE then BLACK else WHITE). Then hand both
    to the method Board already has: board.is_square_attacked(<king's position>,
    <opponent color>). Return its result.
    """
    current_king=find_king(board,color)
    opponenet_color=Color.BLACK if current_king.color == Color.WHITE else Color.WHITE
    return board.is_square_attacked(current_king.position,opponenet_color)


def try_move(board: Board, from_cell: Cell, to_cell: Cell):
    """Tentatively apply a move. Returns whatever we need to UNDO it later.

    HINT — 'simulate' just means: do it, look, then put everything back.
    Save these two things first so you can restore them:
        moving  = board.get_piece_at(from_cell)     # the piece being moved
        captured = board.get_piece_at(to_cell)      # whatever was standing there (may be None)
    Then apply the move by writing the grid directly:
        board.cells[to_cell.y][to_cell.x] = moving
        board.cells[from_cell.y][from_cell.x] = None
        moving.position = to_cell                   # the piece tracks its own square!
    Return (moving, captured) so undo_move can reverse it.
    """
    moving=board.get_piece_at(from_cell)
    captured=board.get_piece_at(to_cell)
    board.cells[to_cell.y][to_cell.x]=moving
    board.cells[from_cell.y][from_cell.x]=None
    moving.position=to_cell
    return moving,captured


def undo_move(board: Board, from_cell: Cell, to_cell: Cell, moving: Piece, captured: Optional[Piece]) -> None:
    """Put the board back exactly as it was before try_move.

    HINT — reverse each line of try_move:
        board.cells[from_cell.y][from_cell.x] = moving      # piece goes home
        board.cells[to_cell.y][to_cell.x] = captured        # restore what was there (None is fine)
        moving.position = from_cell                          # fix its own position too
    """
    board.cells[from_cell.y][from_cell.x] = moving
    board.cells[to_cell.y][to_cell.x] = captured
    moving.position = from_cell



def is_move_safe(board: Board, from_cell: Cell, to_cell: Cell, color: Color) -> bool:
    """Would making this move leave MY OWN king in check? (If yes -> illegal.)

    HINT — this is why try_move/undo_move exist. Three steps:
        1. moving, captured = try_move(...)
        2. safe = not is_in_check(board, color)
        3. undo_move(...)  <-- ALWAYS undo, even though you already have the answer
        4. return safe
    Get the order right: compute `safe` BEFORE undoing, return AFTER undoing.
    """
    moving,captured=try_move(board,from_cell,to_cell)
    safe=not is_in_check(board,color)
    undo_move(board,from_cell,to_cell,moving,captured)
    return safe


def has_any_legal_move(board: Board, color: Color) -> bool:
    """Does `color` have even ONE legal move? (Used for checkmate AND stalemate.)

    HINT — loop every square; for each piece of `color`, ask its strategy for
    get_legal_moves(piece, board). For each destination, test is_move_safe(...).
    The moment you find one that's safe -> return True immediately.
    If you finish both loops without finding any -> return False.
    Careful: a piece's legal moves are computed from ITS position, so use
    piece.position as the from_cell.
    """
    for y in range(8):
        for x in range(8):
            cell = Cell(x, y)
            piece = board.get_piece_at(cell)
            if piece and piece.color == color:
                legal_moves = piece.movement_rule.get_legal_moves(piece, board)
                for move in legal_moves:
                    if is_move_safe(board, cell, move, color):
                        return True
    return False


@dataclass
class Player:
    color: Color


@dataclass
class Match:
    """State/record of one game in progress (like Ticket / ShortLink).

    HINT — fields you need: board, players (list), current_turn (a Color,
    starts WHITE), status (a GameStatus, starts IN_PROGRESS).
    Use field(default_factory=...) for the mutable ones!
    """
    board: Board= field(default_factory=Board)
    players: list[Player]=field(default_factory=lambda: [Player(Color.WHITE), Player(Color.BLACK)])
    current_turn: Color=Color.WHITE
    status: GameStatus=GameStatus.IN_PROGRESS


class ChessOrchestrator:
    """Entry point. Runs the 5-step make_move sequence from Step 3."""

    def __init__(self, match: Match):
        self.match = match

    def make_move(self, from_cell: Cell, to_cell: Cell) -> None:
        """The 5 steps you locked in Step 3.

        HINT — go one step at a time, raise ValueError with a clear message
        whenever a rule is broken:

        1. piece = board.get_piece_at(from_cell)
           - if it's None -> raise ("no piece there")
           - if piece.color != match.current_turn -> raise ("not your turn")

        2. legal = piece.movement_rule.get_legal_moves(piece, board)

        3. if to_cell not in legal -> raise ("illegal move for that piece")

        4. if not is_move_safe(board, from_cell, to_cell, piece.color) -> raise
           ("that move leaves your king in check")

        5. COMMIT it for real:
             - try_move(board, from_cell, to_cell)   (and just ignore the return)
             - piece.has_moved = True                 (the pawn double-step depends on this!)
             - handle promotion: if it's a pawn and to_cell.y is 0 or 7,
               swap its movement_rule to QueenMovementStrategy()
             - flip match.current_turn to the other color
             - then work out the new status (helper below)
        """
        piece =self.match.board.get_piece_at(from_cell)
        if piece is None:
            raise ValueError("no piece there")
        if piece.color != self.match.current_turn:
            raise ValueError("not your turn")
        legal = piece.movement_rule.get_legal_moves(piece, self.match.board)
        if to_cell not in legal:
            raise ValueError("illegal move for that piece")
        if not is_move_safe(self.match.board, from_cell, to_cell, piece.color):
            raise ValueError("that move leaves your king in check")
        try_move(self.match.board, from_cell, to_cell)
        piece.has_moved = True
        if isinstance(piece.movement_rule, PawnMovement) and (to_cell.y == 0 or to_cell.y == 7):
            piece.movement_rule = QueenMovementStrategy()
        self.match.current_turn = Color.BLACK if self.match.current_turn == Color.WHITE else Color.WHITE
        self._update_status()


    def _update_status(self) -> None:
        """After a move, is the player-to-move checkmated, stalemated, or fine?

        HINT — this is the elegant bit: BOTH endings mean 'no legal moves left'.
        The only difference is whether they're in check:
            in_check = is_in_check(board, current_turn)
            can_move = has_any_legal_move(board, current_turn)
            if not can_move:
                status = CHECKMATE if in_check else STALEMATE
            else:
                status = IN_PROGRESS
        """
        in_check = is_in_check(self.match.board, self.match.current_turn)
        can_move = has_any_legal_move(self.match.board, self.match.current_turn)
        if not can_move:
            self.match.status = GameStatus.CHECKMATE if in_check else GameStatus.STALEMATE
        else:
            self.match.status = GameStatus.IN_PROGRESS