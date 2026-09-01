"""
Expression Evaluator — LLD solution.

Most problems in this repo model COLLABORATING OBJECTS. This one models a
RECURSIVE STRUCTURE — a thing made of smaller things of the same kind.

THREE STAGES, KEPT SEPARATE — that separation IS the design:

    "3 + 4 * (2 - 1)"  --Tokenizer-->  [3][+][4][*][(][2][-][1][)]
                       --Parser----->  (3 + (4 * (2 - 1)))   <- shape decided here
                       --evaluate-->   Decimal("7")          <- meaning applied here

    COMPOSITE   — a leaf and a subtree satisfy the same `Node` interface, so no
                  caller asks which it holds. The proof it is used correctly is
                  the ABSENCE of isinstance checks in evaluate().
    INTERPRETER — each node evaluates ITSELF against an Environment. No central
                  dispatch; the dispatch is Python's method lookup.

DATA VS BEHAVIOUR: node kinds differ by BEHAVIOUR -> subclasses. Operators
differ only by DATA (symbol, precedence, associativity, a lambda) -> ONE
BinaryOpNode + a rule-map, not six AddNode/SubNode classes wearing a costume.

OUT OF SCOPE: no statements, no assignment, no control flow — each turns "an
evaluator" into "a language".
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import FrozenInstanceError, dataclass
from decimal import Decimal, InvalidOperation, Overflow
from enum import Enum, auto
from typing import Callable, Optional


# HINT (to rebuild) — one exception class PER FAILURE MODE, never `return None`.
#   A base carrying the POSITION, then a branch per stage: lex, parse (with
#   unbalanced parens split out), evaluate.
#   ** Why types: they become HTTP codes. Lex/Parse -> 400 (bad syntax),
#      Evaluate -> 422 (valid syntax, impossible value). None collapses them all
#      and then blows up inside arithmetic three frames from the real cause.
class ExpressionError(Exception):
    """Base for everything this module raises."""

    def __init__(self, message: str, position: Optional[int] = None):
        self.message = message
        self.position = position
        super().__init__(message if position is None
                         else f"{message} (at position {position})")


class LexError(ExpressionError):
    """Stage 1: a character that is not part of the language."""


class ParseError(ExpressionError):
    """Stage 2: the tokens do not form a well-formed expression."""


class UnbalancedParenthesesError(ParseError):
    """Its own class: the commonest mistake, and an editor wants the position."""


class EvaluationError(ExpressionError):
    """Stage 3: the tree was fine, the values were not."""


class UndefinedVariableError(EvaluationError):
    """A name with no binding in the environment."""


class UnknownFunctionError(EvaluationError):
    """A call to a name that is in no function table."""


class ArityError(EvaluationError):
    """The right function, the wrong number of arguments."""


class DivisionByZeroError(EvaluationError):
    """NOT None and NOT Decimal('Infinity') — Infinity is a VALID number, so
    1/0 * 0 quietly becomes NaN and a wrong price ships."""


# HINT (to rebuild) — Stage 1's vocabulary: a kind enum and a frozen Token
#   carrying its text and its POSITION (errors are useless without it).
#   ** EOF is a real token, not None: every parser method can then peek() with
#      no length check and still report a position.
#   ** A token records what was WRITTEN, never what it MEANS — '-' is the same
#      token in "3 - 4" and "-4". Meaning is positional, so it is parser work.
class TokenKind(Enum):
    NUMBER = auto()
    IDENT = auto()
    OP = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    pos: int

    def __repr__(self) -> str:
        return f"{self.kind.name}({self.text!r})" if self.text else self.kind.name


# HINT (to rebuild) — the DATA half of the split: an operator is a frozen record
#   (symbol, precedence, associativity, a 2-arg function) in a registry, plus a
#   register function that is the whole extension point.
#   ** Higher precedence binds TIGHTER:  + -  <  * / %  <  ^
#   ** Tokeniser and parser both READ this table, so a new operator at an
#      existing level changes neither. Registration must REFUSE what the parser
#      cannot honour (see Parser) — a loud error beats a silently wrong tree.
PREC_ADDITIVE = 1
PREC_MULTIPLICATIVE = 2
PREC_POWER = 3


@dataclass(frozen=True)
class BinaryOperator:
    symbol: str
    precedence: int
    right_assoc: bool
    apply: Callable[[Decimal, Decimal], Decimal]


def _divide(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        raise DivisionByZeroError(f"division by zero: {a} / {b}")
    return a / b


def _modulo(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        raise DivisionByZeroError(f"modulo by zero: {a} % {b}")
    return a % b


def _power(a: Decimal, b: Decimal) -> Decimal:
    if a == 0 and b < 0:
        raise DivisionByZeroError(f"0 to a negative power is a division by zero: {a} ^ {b}")
    try:
        return a ** b
    except (InvalidOperation, Overflow) as exc:                  # e.g. (-8) ^ 0.5
        raise EvaluationError(f"cannot evaluate {a} ^ {b}: {type(exc).__name__}") from exc


BINARY_OPS: dict[str, BinaryOperator] = {}


def register_binary_operator(op: BinaryOperator) -> None:
    """Add (or replace) a binary operator. This is the whole extension point."""
    if op.right_assoc and op.precedence != PREC_POWER:
        raise ValueError(
            f"{op.symbol!r}: associativity is structural (loop = left, recursion = "
            f"right) and only PREC_POWER is written as a recursion, so a new "
            f"right-associative level needs its own _parse_* method first.")
    BINARY_OPS[op.symbol] = op


for _op in (
    BinaryOperator("+", PREC_ADDITIVE, False, lambda a, b: a + b),
    BinaryOperator("-", PREC_ADDITIVE, False, lambda a, b: a - b),
    BinaryOperator("*", PREC_MULTIPLICATIVE, False, lambda a, b: a * b),
    BinaryOperator("/", PREC_MULTIPLICATIVE, False, _divide),
    BinaryOperator("%", PREC_MULTIPLICATIVE, False, _modulo),
    BinaryOperator("^", PREC_POWER, True, _power),
):
    register_binary_operator(_op)


# Unary '+' and '-' share their SYMBOL with the binary ones. That collision is
# the whole difficulty of unary minus, and it is resolved by position, not text.
UNARY_OPS: dict[str, Callable[[Decimal], Decimal]] = {"-": lambda v: -v, "+": lambda v: +v}


# HINT (to rebuild) — functions are DATA too: a frozen (name, arity, callable)
#   record in a registry, seeded with a few builtins.
#   ** A function is NOT a new node type. One call node holds a name and child
#      Nodes, resolved at evaluate time, so a builtin `max` and a caller's
#      `clamp` are the same class of thing — a table entry.
@dataclass(frozen=True)
class FunctionDef:
    name: str
    arity: int
    apply: Callable[..., Decimal]


BUILTIN_FUNCTIONS: dict[str, FunctionDef] = {
    f.name: f for f in (
        FunctionDef("max", 2, lambda a, b: max(a, b)),
        FunctionDef("min", 2, lambda a, b: min(a, b)),
        FunctionDef("abs", 1, lambda a: abs(a)),
    )
}


# HINT (to rebuild) — the bindings the Interpreter interprets AGAINST: variables
#   and functions, both supplied by the CALLER, both looked up by name.
#   ** Lookups RAISE rather than return None. None forces the caller into
#      check-then-act (`if has(): get()`) — the TOCTOU gap this repo keeps
#      meeting. One dict access in a try/except is atomic: no gap, no lock.
#   ** Binding a float must be REFUSED at this boundary; money is Decimal.
class Environment:
    """Variable bindings + the function table. Supplied by the CALLER."""

    def __init__(self, variables: Optional[dict[str, Decimal | int | str]] = None):
        self._vars: dict[str, Decimal] = {}
        self._funcs: dict[str, FunctionDef] = dict(BUILTIN_FUNCTIONS)
        for name, value in (variables or {}).items():
            self.define(name, value)

    def define(self, name: str, value: Decimal | int | str) -> None:
        # The one type check in the module: a BOUNDARY GUARD, not a dispatch.
        # Composite forbids the dispatch kind, not this kind.
        if isinstance(value, float):
            raise ValueError(
                f"{name}={value!r}: bind money as Decimal or str, never float - "
                f"0.1 + 0.2 != 0.3 in binary floating point and the error compounds.")
        self._vars[name] = Decimal(value)

    def get(self, name: str) -> Decimal:
        try:
            return self._vars[name]              # ONE atomic lookup, no check-then-act
        except KeyError:
            raise UndefinedVariableError(f"undefined variable {name!r}") from None

    def register_function(self, fn: FunctionDef) -> None:
        self._funcs[fn.name] = fn

    def get_function(self, name: str) -> FunctionDef:
        try:
            return self._funcs[name]
        except KeyError:
            raise UnknownFunctionError(f"unknown function {name!r}") from None


# HINT (to rebuild) — the AST: COMPOSITE + INTERPRETER. One ABC with ONE
#   abstract method, evaluate(env), then a subclass per node KIND — leaves
#   (literal, variable) and composites (unary, binary, call).
#   ** The load-bearing detail is the TYPE of a composite's children: `Node`,
#      not `NumberNode`. That is what makes the structure recursive.
#   ** No evaluate() may contain isinstance / type(). If you write one, the tree
#      is not a Composite yet.
#   ** Frozen, and __repr__ prints INFIX with explicit parens so the tree SHAPE
#      is visible — that is what makes associativity provable, not arguable.
class Node(ABC):
    """A leaf and a whole subtree are the SAME TYPE to every caller — that is
    the Composite pattern's entire promise."""

    @abstractmethod
    def evaluate(self, env: Environment) -> Decimal: ...


@dataclass(frozen=True, repr=False)
class NumberNode(Node):
    """LEAF. A literal. Recursion stops here."""

    value: Decimal

    def evaluate(self, env: Environment) -> Decimal:
        return self.value

    def __repr__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, repr=False)
class VariableNode(Node):
    """LEAF. Resolved at EVALUATE time, which is what lets one AST serve many
    environments."""

    name: str

    def evaluate(self, env: Environment) -> Decimal:
        return env.get(self.name)

    def __repr__(self) -> str:
        return self.name


@dataclass(frozen=True, repr=False)
class UnaryOpNode(Node):
    """COMPOSITE with one child, built only where a VALUE was expected — that
    position is the whole difference between negation and subtraction."""

    op: str
    operand: Node

    def evaluate(self, env: Environment) -> Decimal:
        return UNARY_OPS[self.op](self.operand.evaluate(env))

    def __repr__(self) -> str:
        return f"({self.op}{self.operand!r})"


@dataclass(frozen=True, repr=False)
class BinaryOpNode(Node):
    """COMPOSITE with two children - ONE class for EVERY binary operator, since
    operators differ by DATA, not behaviour. Note `left`/`right` are Node."""

    op: str
    left: Node
    right: Node

    def evaluate(self, env: Environment) -> Decimal:
        operator = BINARY_OPS[self.op]
        return operator.apply(self.left.evaluate(env), self.right.evaluate(env))

    def __repr__(self) -> str:
        return f"({self.left!r} {self.op} {self.right!r})"


@dataclass(frozen=True, repr=False)
class FunctionCallNode(Node):
    """COMPOSITE with N children. `args` is a TUPLE, keeping the frozen
    dataclass hashable and the AST genuinely immutable."""

    name: str
    args: tuple[Node, ...]

    def evaluate(self, env: Environment) -> Decimal:
        fn = env.get_function(self.name)
        if len(self.args) != fn.arity:
            raise ArityError(
                f"{self.name}() takes {fn.arity} argument(s), got {len(self.args)}")
        return fn.apply(*[arg.evaluate(env) for arg in self.args])

    def __repr__(self) -> str:
        return f"{self.name}({', '.join(repr(a) for a in self.args)})"


# HINT (to rebuild) — Stage 1: scan the string once, emit a flat token list
#   ending in EOF. One branch per character class: skip space, run out a number
#   ('1.2.3' is a LexError), run out an identifier, punctuation, else the
#   LONGEST matching operator symbol, else a LexError carrying the position.
#   ** Longest-match matters the moment a 2-char operator exists: it is what
#      stops '//' lexing as two divisions.
#   ** Take the symbols FROM the registry, so a new operator changes nothing
#      here. And note this stage never decides whether '-' is unary — it cannot,
#      it has no idea what came before.
class Tokenizer:
    """Stage 1: text -> a flat list of tokens. Assigns no meaning whatsoever."""

    def tokenize(self, source: str) -> list[Token]:
        tokens: list[Token] = []
        symbols = sorted(set(BINARY_OPS) | set(UNARY_OPS), key=len, reverse=True)
        i, n = 0, len(source)
        while i < n:
            ch = source[i]
            if ch.isspace():
                i += 1
                continue
            if ch.isdigit():
                j = i
                while j < n and source[j].isdigit():
                    j += 1
                if j < n and source[j] == ".":
                    j += 1
                    if j >= n or not source[j].isdigit():
                        raise LexError("a decimal point must be followed by a digit", j)
                    while j < n and source[j].isdigit():
                        j += 1
                tokens.append(Token(TokenKind.NUMBER, source[i:j], i))
                i = j
                continue
            if ch.isalpha() or ch == "_":
                j = i
                while j < n and (source[j].isalnum() or source[j] == "_"):
                    j += 1
                tokens.append(Token(TokenKind.IDENT, source[i:j], i))
                i = j
                continue
            if ch in "(),":
                kind = {"(": TokenKind.LPAREN,
                        ")": TokenKind.RPAREN,
                        ",": TokenKind.COMMA}[ch]
                tokens.append(Token(kind, ch, i))
                i += 1
                continue
            for sym in symbols:                       # longest match wins
                if source.startswith(sym, i):
                    tokens.append(Token(TokenKind.OP, sym, i))
                    i += len(sym)
                    break
            else:
                raise LexError(f"unexpected character {ch!r}", i)
        tokens.append(Token(TokenKind.EOF, "", n))
        return tokens


# The grammar, lowest precedence first:
#     additive := multiplicative (('+'|'-') multiplicative)*  |  unary := ('-'|'+') unary | power
#     multiplicative := unary (('*'|'/'|'%') unary)*          |  power := primary ('^' unary)?
#     primary  := NUMBER | IDENT | IDENT '(' args ')' | '(' additive ')'
#
# HINT (to rebuild) — RECURSIVE DESCENT, one method per precedence level:
#   1. PRECEDENCE = CALL DEPTH. A level parses its operands by calling the next
#      TIGHTER level, so precedence is never compared; it is structural.
#   2. ASSOCIATIVITY = LOOP vs RECURSION. Folding in a while-loop is LEFT-assoc,
#      recursing into the same level is RIGHT-assoc. Writing additive as a
#      recursion is THE classic bug: it typechecks, it passes '1 + 2 + 3', and
#      it wrecks every chain of subtractions.
#   3. UNARY MINUS is free here because the two cases live in DIFFERENT METHODS
#      — one runs where a VALUE is expected, the loop where an OPERATOR is.
#   ** '(' re-enters the LOWEST level; nesting is deep but NOT unbounded (~5
#      frames per paren caps it near 190 with an untyped RecursionError).
class Parser:
    """Stage 2: tokens -> AST. Decides SHAPE. Computes no values."""

    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._i = 0

    def parse(self) -> Node:
        node = self._parse_additive()
        tok = self._peek()
        if tok.kind is TokenKind.RPAREN:
            raise UnbalancedParenthesesError("closing ')' with no matching '('", tok.pos)
        if tok.kind is not TokenKind.EOF:
            raise ParseError(f"unexpected {tok.text!r} after a complete expression", tok.pos)
        return node

    def _peek(self) -> Token:
        return self._tokens[min(self._i, len(self._tokens) - 1)]

    def _advance(self) -> Token:
        tok = self._peek()
        if self._i < len(self._tokens) - 1:      # never step past EOF
            self._i += 1
        return tok

    def _at_operator(self, symbols: set[str]) -> bool:
        tok = self._peek()
        return tok.kind is TokenKind.OP and tok.text in symbols

    @staticmethod
    def _operators_at(precedence: int) -> set[str]:
        """Level membership is DATA, read from the registry - which is why a new
        operator at an existing level needs no change in this class."""
        return {sym for sym, op in BINARY_OPS.items() if op.precedence == precedence}

    def _parse_left_assoc(self, precedence: int, tighter: Callable[[], Node]) -> Node:
        """A LOOP that folds leftwards, so every level built with it is
        LEFT-associative: '2 - 3 - 4' becomes ((2 - 3) - 4) = -5."""
        node = tighter()
        symbols = self._operators_at(precedence)
        while self._at_operator(symbols):
            node = BinaryOpNode(self._advance().text, node, tighter())
        return node

    # Precedence = CALL DEPTH: each level parses its operands one level tighter.
    def _parse_additive(self) -> Node:
        return self._parse_left_assoc(PREC_ADDITIVE, self._parse_multiplicative)

    def _parse_multiplicative(self) -> Node:
        return self._parse_left_assoc(PREC_MULTIPLICATIVE, self._parse_unary)

    def _parse_unary(self) -> Node:
        # Reached only where a VALUE is expected, so a '-' here is a negation.
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.text in UNARY_OPS:
            self._advance()
            return UnaryOpNode(tok.text, self._parse_unary())   # handles '- -3'
        return self._parse_power()

    def _parse_power(self) -> Node:
        base = self._parse_primary()
        if self._at_operator(self._operators_at(PREC_POWER)):
            op = self._advance().text
            # RECURSION, not a loop => RIGHT-associative: 2^3^2 = 2^(3^2) = 512.
            # Recursing via _parse_unary rather than _parse_power lets '2 ^ -1' work.
            return BinaryOpNode(op, base, self._parse_unary())
        return base

    def _parse_primary(self) -> Node:
        tok = self._advance()
        if tok.kind is TokenKind.NUMBER:
            return NumberNode(Decimal(tok.text))
        if tok.kind is TokenKind.IDENT:
            if self._peek().kind is TokenKind.LPAREN:
                return self._parse_call(tok)
            return VariableNode(tok.text)
        if tok.kind is TokenKind.LPAREN:
            inner = self._parse_additive()                # back to the LOWEST level
            closing = self._advance()
            if closing.kind is not TokenKind.RPAREN:
                raise UnbalancedParenthesesError(
                    f"'(' opened at position {tok.pos} was never closed", closing.pos)
            return inner
        if tok.kind is TokenKind.EOF:
            raise ParseError("expected an expression, found end of input", tok.pos)
        raise ParseError(f"expected a number, name or '(', found {tok.text!r}", tok.pos)

    def _parse_call(self, name_tok: Token) -> Node:
        self._advance()                                   # consume '('
        args: list[Node] = []
        if self._peek().kind is not TokenKind.RPAREN:
            while True:
                args.append(self._parse_additive())       # an argument is a full expression
                if self._peek().kind is TokenKind.COMMA:
                    self._advance()
                    continue
                break
        closing = self._advance()
        if closing.kind is not TokenKind.RPAREN:
            raise UnbalancedParenthesesError(
                f"call to {name_tok.text!r} opened at position {name_tok.pos} "
                f"was never closed", closing.pos)
        # Arity is NOT checked here: the parser knows no functions, so one AST
        # stays valid against environments with different function tables.
        return FunctionCallNode(name_tok.text, tuple(args))


# HINT (to rebuild) — a thin facade, the only class a caller needs: one method
#   running stages 1+2 to a Node, one running all three to a Decimal.
#   ** Keep the parse step PUBLIC and separate. That buys PARSE ONCE, EVALUATE
#      MANY — a pricing rule parsed at deploy time, evaluated per request
#      against a fresh Environment. Possible only because the AST holds none.
class ExpressionEvaluator:
    """Facade over the three stages."""

    def __init__(self) -> None:
        self._tokenizer = Tokenizer()

    def parse(self, source: str) -> Node:
        return Parser(self._tokenizer.tokenize(source)).parse()

    def evaluate(self, source: str, env: Optional[Environment] = None) -> Decimal:
        return self.parse(source).evaluate(env if env is not None else Environment())


# Demo — every claim above, checked
def _check(ev: ExpressionEvaluator, src: str, want: str,
           env: Optional[Environment] = None) -> None:
    got = ev.evaluate(src, env)
    print(f"  {src:<38} = {str(got):<10} want {want}")
    assert got == Decimal(want), f"{src}: wanted {want}, got {got}"


def _expect(ev: ExpressionEvaluator, src: str, exc: type,
            env: Optional[Environment] = None) -> None:
    try:
        got = ev.evaluate(src, env)
    except ExpressionError as e:
        assert type(e) is exc, f"{src}: wanted {exc.__name__}, got {type(e).__name__}"
        print(f"  {src:<14} -> {type(e).__name__:<26} {e}")
        return
    raise AssertionError(f"{src!r} should have raised {exc.__name__}, returned {got}")


if __name__ == "__main__":
    ev = ExpressionEvaluator()

    print("=== stage 1: tokenise - '-' is ONE kind of token in both places ===")
    for src in ("3 - 4", "3 * -4"):
        print(f"  {src:<10} -> {Tokenizer().tokenize(src)}")
    print("  the scanner cannot tell subtraction from negation. Only POSITION can.")

    print("\n=== stage 2: parse - the tree SHAPE is where precedence is decided ===")
    for src in ("3 + 4 * 2", "(3 + 4) * 2", "max(2 + 3, min(10, 4) * 2)"):
        print(f"  {src:<30} -> {ev.parse(src)!r}")

    print("\n=== stage 3: evaluate - precedence and nested parentheses ===")
    _check(ev, "3 + 4 * (2 - 1)", "7")
    _check(ev, "1 + 2 * 3 - 4 / 2", "5")
    _check(ev, "((1 + 2) * (3 + 4)) - ((10 - 4) / 2)", "18")
    _check(ev, "2 * (3 + (4 * (5 - (1 + 1))))", "30")

    print("\n=== associativity: the shape decides, and a wrong shape is a wrong number ===")
    print(f"  '2 - 3 - 4' parses as {ev.parse('2 - 3 - 4')!r}")
    _check(ev, "2 - 3 - 4", "-5")
    _check(ev, "100 / 10 / 5", "2")
    # The tree a RIGHT-associative parser would build, hand-made and evaluated.
    wrong = BinaryOpNode("-", NumberNode(Decimal(2)),
                         BinaryOpNode("-", NumberNode(Decimal(3)), NumberNode(Decimal(4))))
    print(f"  right-assoc would build {wrong!r} = {wrong.evaluate(Environment())} <- WRONG."
          f" '1 + 2 + 3' hides it; '2 - 3 - 4' exposes it")
    print(f"  '2 ^ 3 ^ 2' parses as {ev.parse('2 ^ 3 ^ 2')!r}   <- '^' is the ONE"
          f" right-associative level")
    _check(ev, "2 ^ 3 ^ 2", "512")

    print("\n=== unary minus: same character, different position, different node ===")
    for src in ("3 * -4", "- -3", "-2 ^ 2", "(-2) ^ 2"):
        print(f"  {src:<10} -> {ev.parse(src)!r:<20} = {ev.evaluate(src)}")
    _check(ev, "-2 ^ 2", "-4")
    _check(ev, "-(3 + 4) * 2", "-14")

    print("\n=== variables resolved from an Environment, at EVALUATE time ===")
    env = Environment({"x": 5, "y": 2, "rate": "0.15"})
    _check(ev, "x * y + 1", "11", env)
    _check(ev, "(x + y) ^ 2", "49", env)
    _check(ev, "abs(y - x) * rate", "0.45", env)

    print("\n=== money: parse ONCE, evaluate MANY (the AST holds no environment) ===")
    rule = ev.parse("price * qty * (1 + tax)")
    for price, qty, tax, want in (("19.99", 3, "0.08", "64.7676"),
                                  ("100.00", 1, "0.185", "118.500")):
        got = rule.evaluate(Environment({"price": price, "qty": qty, "tax": tax}))
        assert got == Decimal(want), (price, qty, tax, got)
        print(f"  {rule!r} @ price={price:<7} tax={tax:<6} -> {got}")

    print("\n=== every error path raises its OWN exception type ===")
    empty = Environment()
    _expect(ev, "3 @ 4", LexError)
    _expect(ev, "1.2.3", LexError)
    _expect(ev, "3 + ", ParseError)
    _expect(ev, "(1 + 2", UnbalancedParenthesesError)
    _expect(ev, "1 + 2)", UnbalancedParenthesesError)
    _expect(ev, "x + 1", UndefinedVariableError, empty)
    _expect(ev, "nope(1)", UnknownFunctionError)
    _expect(ev, "max(1)", ArityError)
    _expect(ev, "10 / (7 - 7)", DivisionByZeroError)
    _expect(ev, "0 ^ -1", DivisionByZeroError)
    try:
        empty.define("tax", 0.15)
    except ValueError as e:
        print(f"  define(0.15)   -> ValueError                  {e}")
    print("  Lex/Parse -> HTTP 400 (bad syntax). Evaluate -> HTTP 422 (valid syntax,")
    print("  impossible value). One `return None` collapses all ten into one.")

    print("\n=== the COMPOSITE proof: no isinstance / type() in ANY evaluate() ===")
    for cls in (NumberNode, VariableNode, UnaryOpNode, BinaryOpNode, FunctionCallNode):
        src = inspect.getsource(cls.evaluate)
        for smell in ("isinstance", "type(", "__class__"):
            assert smell not in src, (cls.__name__, smell)
        body = len([ln for ln in src.splitlines() if ln.strip()])
        print(f"  {cls.__name__ + '.evaluate':<28} {body:>2} lines, zero type checks")
    print("  BinaryOpNode.evaluate neither knows nor cares whether its children are")
    print("  leaves or 400-node subtrees. That is the pattern actually working.")

    print("\n=== ...and the ABC has TEETH: the contract is enforced, not documented ===")

    class ForgotToImplement(Node):
        pass                     # a node type whose author never wrote evaluate()

    for ctor in (Node, ForgotToImplement):
        try:
            ctor()
            raise AssertionError(f"{ctor.__name__}() must not be instantiable")
        except TypeError as e:
            print(f"  {ctor.__name__ + '()':<21}-> TypeError: {e}")
    print("  without @abstractmethod BOTH construct happily, then fail as an")
    print("  AttributeError several frames inside somebody else's recursion.")

    print("\n=== ...and the AST is immutable, so sharing it needs no copy ===")
    frozen_tree = ev.parse("price * qty")
    try:
        frozen_tree.op = "+"
        raise AssertionError("mutating a frozen node must be refused")
    except FrozenInstanceError as e:
        print(f"  BinaryOpNode.op = '+' -> FrozenInstanceError: {e}")
    smells = {w: inspect.getsource(Parser).count(w) for w in ("Lock", "threading")}
    assert sum(smells.values()) == 0, smells
    print(f"  so no evaluation leaves a footprint for the next: N threads share ONE")
    print(f"  AST against N Environments with no locks anywhere {smells}. The")
    print(f"  concurrency NFR is answered by MODELLING, not by locking.")

    print("\n=== extensibility, three tiers - nothing existing is EDITED in any of them ===")
    print("  tier 1: a new FUNCTION = one registry entry, zero code changes")
    ext = Environment({"x": 15})
    ext.register_function(FunctionDef("clamp", 3, lambda v, lo, hi: max(lo, min(hi, v))))
    _check(ev, "clamp(x, 0, 10)", "10", ext)

    print("  tier 2: a new OPERATOR = one registry entry. Tokeniser and parser both")
    print("          read the registry, so neither of them changes.")
    register_binary_operator(
        BinaryOperator("//", PREC_MULTIPLICATIVE, False,
                       lambda a, b: _divide(a, b).to_integral_value(rounding="ROUND_FLOOR")))
    print(f"  '7 // 2 + 1' parses as {ev.parse('7 // 2 + 1')!r}   <- ONE token,"
          f" binding tighter than '+'")
    _check(ev, "7 // 2 + 1", "4")
    try:
        register_binary_operator(BinaryOperator("<-", PREC_ADDITIVE, True, lambda a, b: a))
    except ValueError as e:
        print(f"  a right-assoc operator at the additive level is REFUSED:\n    {e}")

    print("  tier 3: a new SHAPE = one new Node subclass, written here AFTER the")
    print("          library, and composing with it anyway:")

    @dataclass(frozen=True, repr=False)
    class RoundNode(Node):
        child: Node
        places: int

        def evaluate(self, env: Environment) -> Decimal:
            return self.child.evaluate(env).quantize(Decimal(1).scaleb(-self.places))

        def __repr__(self) -> str:
            return f"round({self.child!r}, {self.places})"

    mixed = BinaryOpNode("+", RoundNode(ev.parse("10 / 3"), 2), ev.parse("x"))
    assert mixed.evaluate(Environment({"x": 1})) == Decimal("4.33")
    print(f"  {mixed!r} = {mixed.evaluate(Environment({'x': 1}))}   <- BinaryOpNode"
          f" recursed into a class that did not exist when it was written")

    print("\nAll assertions passed.")
