# Problem 15: Expression Evaluator (LLD)

*Not yet worked through — this problem was added for pattern coverage. Do Steps 1-3 yourself before reading the solution.*

## The prompt (as an interviewer would give it)

> "Design an arithmetic expression evaluator. Given a string like `"3 + 4 * (2 - 1)"`,
> return its value. It should support variables and a few built-in functions,
> and it must be easy to add new operators later."

**Why this one is in the set.** Every other LLD problem here models *collaborating objects*. This one
models a **recursive structure** — a thing made of smaller things of the same kind. Fintech asks it as
"a pricing rule the business can edit without a deploy".

---

## Clarifying questions to ask
_Ask these BEFORE writing any requirement. Each one changes the design._

1. **Operators** — which exactly? `+ - * /` only, or modulo and exponentiation? Unary minus?
2. **Precedence & associativity** — standard maths precedence, left-to-right within a level? Is `^` right-associative?
3. **Numbers** — integers or decimals? Is this ever money?
4. **Variables & functions** — are names and calls like `max(a, b)` in scope? Who supplies the bindings, what happens on a missing name, and can *callers* register functions?
5. **Statements, assignment, control flow** — in scope? *(The scope-cutter: what stops this becoming a programming language.)*
6. **Errors** — divide-by-zero, unbalanced parens, unknown name: sentinel or raise? Must the caller know *which* thing went wrong?
7. **Reuse & concurrency** — parsed once and evaluated many times? Is one parsed expression shared across threads?

---

## Clarifications (locked scope from Q&A)
1. **Operators:** `+ - * / % ^`, plus **unary minus and unary plus**. No comparisons, booleans or bitwise.
2. **Precedence:** unary binds tightest, then `^`, then `* / %`, then `+ -`. **Left-associative everywhere except `^`**, which is right-associative (`2^3^2 = 512`).
3. **Numbers:** decimals, and this **is** used for pricing rules → **`Decimal` everywhere, never `float`**.
4. **Variables & functions:** yes to both, resolved against a caller-supplied **`Environment`** at evaluate time; a missing name is an **error**, never a silent `0`. Fixed-arity built-ins (`max`, `min`, `abs`), and **callers may register their own** — the extension point is a public API, not "edit this dict".
5. **Statements / assignment / control flow: OUT OF SCOPE.** Expressions only. The deliberate scope cut.
6. **Errors:** raise, with a **specific type per failure mode** — the HTTP layer maps type → status code.
7. **Reuse & concurrency: parse once, evaluate many**, one parsed expression shared across threads against **different** environments. So the **AST must not capture the environment**; `evaluate` takes it as a parameter.

---

## Step 1 — Requirements  ← YOUR TURN
_Ask clarifying questions first, then state these back._

### Functional (what it DOES — the verbs)
- **Parse** a source string into an **AST** — precedence, associativity, parens nested to any depth, and unary `-`/`+` distinguished from the binary operators of the same character
- **Evaluate** an AST against an `Environment`, returning a `Decimal`
- Resolve **variables** from the caller-supplied environment; a missing name is an error, never a silent `0`
- Call **functions** with fixed arity, and let callers **register** their own
- **Parse once, evaluate many** — `parse` and `evaluate` are separate public operations

### Non-functional (constraints — the "-ilities")
- **Extensible** — a new operator or function must be *additive*: nothing existing gets edited (Open/Closed)
- **Correctness of money** — `Decimal` throughout; `float` is *rejected* at the boundary, not merely discouraged
- **Thread-safe by construction** — the AST is immutable and holds no environment, so N threads share one tree with **zero locks**

### Explicitly out of scope (say this out loud — it is a senior move)
- **Statements · assignment · control flow · user-defined functions in the language** (each turns an evaluator into a *language*: scoping rules, a call stack, a recursion story) · comparison/boolean/bitwise ops · strings · dates · a REPL · optimisation passes · bytecode

> 📝 **Trap (Step 1):** the pull is feature creep *in the requirements themselves* — "it should probably also do `if`", "maybe assignment so you can name subexpressions". Each is one sentence to say and a week to design. Name the boundary out loud — **expressions in, one value out, no state** — and defend it. The mirror trap is cutting too much: drop *variables* and the entire reason an `Environment` exists goes with them.

---

## Step 2 — Entities  (nouns → classes)
_Format: `Name — single responsibility — key attributes/methods`_

1. **Token** *(frozen dataclass)* + **TokenKind** *(Enum)* — one lexeme and where it came from — `kind, text, pos`; kinds `NUMBER, IDENT, OP, LPAREN, RPAREN, COMMA, EOF`
2. **Tokenizer** — stage 1: text → tokens, assigning **no meaning**
3. **BinaryOperator** / **FunctionDef** *(frozen dataclasses)* + the **`BINARY_OPS` / `UNARY_OPS` / `BUILTIN_FUNCTIONS`** registries — an operator and a function as **DATA** — `(symbol, precedence, right_assoc, apply)` · `(name, arity, apply)`
4. **Environment** — the bindings the interpreter interprets *against*, supplied by the caller
5. **Node** *(ABC — Composite + Interpreter)* — a leaf and a whole subtree are the same type to every caller — `evaluate(env) -> Decimal` *(`@abstractmethod`, and the **only** method)*
6. **NumberNode** / **VariableNode** *(leaves — recursion stops here)* — `value: Decimal` · `name: str`, resolved at **evaluate** time, not parse time
7. **UnaryOpNode** / **BinaryOpNode** / **FunctionCallNode** *(composites, 1 / 2 / N children)* — `op, operand` · `op, left: Node, right: Node` (**one class per binary operator is the mistake**) · `name, args: tuple[Node, ...]`
8. **Parser** — stage 2: tokens → AST, one private method per precedence level
9. **ExpressionEvaluator** — the facade, the only class a caller needs
10. **ExpressionError** and subclasses — `LexError`, `ParseError` → `UnbalancedParenthesesError`, `EvaluationError` → `UndefinedVariableError`, `UnknownFunctionError`, `ArityError`, `DivisionByZeroError`

### The data-vs-behaviour test, applied twice on two axes

| Axis | They differ by | Therefore |
|---|---|---|
| **Node kinds** (number / variable / unary / binary / call) | **BEHAVIOUR** — a constant, a lookup, a recursion into two children, a splat of N args | polymorphic **subclasses**; one `Node` with a `kind` field and an `if kind == …` ladder is behaviour crammed into data |
| **Operators** (`+ - * / % ^`) | **DATA** — all six *evaluate both children then combine*, differing only in symbol, precedence, an associativity flag and a 2-arg function | **one** `BinaryOpNode` + a rule map, **not six classes**; `AddNode`/`SubNode`/`MulNode`/… is data wearing a class costume |

> 📝 **Trap (Step 2):** the tell for the under-engineered version is an **`isinstance` or `type()` check inside any `evaluate`** — if it is there the Composite is not doing its job, and every new node type means editing that ladder. The other tell is `VariableNode` being handed the environment in its **constructor**: that destroys parse-once-evaluate-many and makes the AST unshareable. Note also the YAGNI on the Composite — the textbook version exposes `add_child`/`remove_child`/`children`; `Node` gets **one** method, because the tree is never mutated.

---

## Step 3 — Relationships & APIs
_Signatures before bodies._

| Stage | Input → Output | Owns | Knows nothing about |
|---|---|---|---|
| **1. Tokenise** | `str` → `list[Token]` | character rules, longest-match on symbols | precedence, structure, values |
| **2. Parse** | `list[Token]` → `Node` | precedence, associativity, parens, unary-vs-binary | numbers, variables, functions |
| **3. Evaluate** | `Node` + `Environment` → `Decimal` | arithmetic, name resolution, arity | the original text |

**Why not fuse them?** Read `3 + 4 * 2` left to right, folding as you go: `3 + 4 = 7`, then `7 * 2 = 14`.
The answer is 11. When the scanner reaches `+` it **has not yet seen what binds to the 4**, so it may
not fold — and that forced delay *is* the parse tree. People who "avoid the AST" build one anyway, as
two ad-hoc stacks with no name and no invariants.

```python
class Node(ABC):                 # children are typed `Node`, never `NumberNode` —
    @abstractmethod              # THE recursion. env is a param, never stored.
    def evaluate(self, env: Environment) -> Decimal

class Parser:                    # one private method per precedence level:
    def parse(self) -> Node      #   _parse_additive, _parse_multiplicative,
                                 #   _parse_unary, _parse_power, _parse_primary

class Environment:               # define() rejects float; get() raises, never None
    def define(self, name, value) -> None;    def get(self, name) -> Decimal
    def register_function(self, fn) -> None;  def get_function(self, name)

class ExpressionEvaluator:       # the facade over Tokenizer.tokenize + Parser.parse
    def parse(self, source: str) -> Node
    def evaluate(self, source: str, env: Optional[Environment] = None) -> Decimal

def register_binary_operator(op: BinaryOperator) -> None
```

### Precedence and associativity — recursive descent, one method per level

```
additive       := multiplicative (('+' | '-') multiplicative)*
multiplicative := unary (('*' | '/' | '%') unary)*
unary          := ('-' | '+') unary | power
power          := primary ('^' unary)?
primary        := NUMBER | IDENT | IDENT '(' args ')' | '(' additive ')'
```

- **Precedence = call depth.** A level parses its operands by calling the *next tighter* level, so `_parse_additive` sees `+` only after `_parse_multiplicative` has eaten the whole `4 * 2` — hence `(3 + (4 * 2))`. **No precedence number is ever compared;** precedence is structural.
- **Associativity = loop vs recursion.** A `while` folding into the *left* slot gives `((2 - 3) - 4)` = **−5**, correct; a `return` recursing for the *right* slot gives `(2 - (3 - 4))` = **3**, the bug. Two characters, typechecks, and it **hides** — `1 + 2 + 3` is 6 either way, so only chains of `-` and `/` expose it: `2 - 3 - 4` and `100 / 10 / 5` are the canaries. `^` is the one level deliberately written as a recursion: `2 ^ 3 ^ 2` = `2 ^ 9` = 512, not `8 ^ 2` = 64.
- **Unary minus is positional, and recursive descent resolves it for free.** The tokeniser emits the same `OP('-')` for `3 - 4` and `3 * -4` — it has no idea what came before. But the two positions are different *methods*: where a **value** is expected (`_parse_unary`) it negates, where an **operator** is expected (a level's `while` loop) it subtracts. The rest falls out: `- -3` = 3, `-2 ^ 2` = −4 (the conventional reading), `2 ^ -1` = 0.5. **That is the honest reason to prefer recursive descent over shunting-yard**, which must instead carry a "was the previous token a value?" flag — where the bugs live.

### Errors — one type per failure mode

| Raised | When | Maps to |
|---|---|---|
| `LexError` · `ParseError` · `UnbalancedParenthesesError` | syntax is wrong — `3 @ 4`, `1.2.3`, `3 +`, `3 4`, `(1 + 2`, `max(1, 2` | **400** + the offending position |
| `UndefinedVariableError` · `UnknownFunctionError` · `ArityError` · `DivisionByZeroError` | syntax fine, values not — unbound `x + 1`, `nope(1)`, `max(1)`, `10 / 0`, `0 ^ -1` | **422** |

**Divide-by-zero raises, not `None` and not infinity.** `None` makes every caller test every
intermediate result, and when they forget it surfaces three frames later as `TypeError: unsupported
operand type(s)`. `Decimal('Infinity')` is worse — a *valid number*, so it flows on and a wrong price
ships.

> 📝 **Trap (Step 3):** **(1)** Writing the additive/multiplicative levels as recursions instead of loops — right-associative subtraction, and `1 + 2 + 3` will not catch it. **(2)** Folding the sign into the number literal in the *tokeniser*: then `3 - 4` lexes as `NUMBER(3), NUMBER(-4)` with no operator between them. The sign belongs to the *position*, not the number. **(3)** Checking arity in the **parser** — feels like fail-fast, but it forces the parser to know the function table, breaking parse-once-evaluate-many the moment two environments register different functions.

---

## REST API mapping  (LLD method -> HLD endpoint)

A **library first** — it runs in-process. It becomes a service when the expressions are *business
rules* non-engineers edit: a pricing formula, a fee schedule.

| LLD method | HTTP |
|---|---|
| `parse(source)` | `POST /api/v1/expressions/validate` `{source}` -> **200** `{ast_repr}` · **400** `{error_type, message, position}` |
| `evaluate(source, env)` | `POST /api/v1/expressions/evaluate` `{source, variables}` -> **200** `{value}` · **422** `{error_type}` |
| `parse` at write, `node.evaluate(env)` at read | `POST /api/v1/rules` -> **201**, parsed at authoring time so a broken rule is rejected then, not at 3am · `POST /api/v1/rules/{id}/apply` -> **200**, reusing the stored AST, never re-parsing |
| `register_binary_operator` / `register_function` | **not an endpoint** — these ship with a deploy; letting an HTTP caller define arithmetic is a code-execution hole |

> **The `position` field is why the errors carry one:** a rule-authoring UI underlines the exact
> character; `{"error": "invalid expression"}` cannot. **Untrusted input also needs limits the library
> does not have** — cap source length, nesting depth and exponent size *before* parsing, because
> `9 ^ 9 ^ 9 ^ 9` is nine characters and will not finish. Nesting has a ceiling anyway: one `(` costs
> about five stack frames, so CPython dies near 190 levels deep with an untyped `RecursionError`.

## Notes / decisions (log the "why" here)
- **Composite is the AST; the seam that pays for itself is parse↔evaluate.** `BinaryOpNode.left` is typed `Node`, so a child may be a leaf or a 400-node subtree and no caller can tell. The **absence of `isinstance` in every `evaluate`** is the acceptance test — the demo greps its own source to prove it. **Interpreter** is `Node.evaluate(env)`: the dispatch is method lookup, so a new node type edits no existing code.
- **`register_binary_operator` refuses a right-associative operator outside the power level** — associativity is structural, so a new right-associative level needs its own parser method first. Better a loud `ValueError` at registration than a silently wrong tree at runtime.
- **`Decimal`, never `float`** — `Environment.define` **rejects** `float` rather than coercing it. Coercing hides the bug; `0.1 + 0.2 != 0.3` compounds through a pricing formula. (Same rule as Splitwise.)
- **No locks anywhere.** Nodes are frozen and `evaluate` takes the environment as a *parameter*, so 200 threads share one AST against 200 different environments. The concurrency NFR was answered by **modelling** — as Splitwise answered it by deriving balances instead of storing them.
- **`Environment.get` raises instead of returning `None`** — also a concurrency decision. A nullable getter invites `if env.has(name): env.get(name)`, the **check-then-act (TOCTOU)** gap this repo keeps meeting (`exists→save` in the shortener, `assign→occupy` in parking). Same fix: **push atomicity into the store**.
- **Extensibility, three tiers, nothing existing edited in any of them.** New **function** = one registry entry. New **operator** at an existing level = one registry entry, because the tokeniser reads its symbols and the parser its level membership from that registry. New **shape** = one `Node` subclass, plus a parser method only if it needs *syntax*.

> 📝 **Trap (Step 4 build):** the build traps concentrate in the parser. Guard `_peek`/`_advance` against stepping past `EOF`, or malformed input raises `IndexError` instead of `ParseError`. Check arity in `evaluate`, not `parse`. Make the node dataclasses `frozen` and use a **tuple** for `FunctionCallNode.args` — a list makes the "immutable, shareable across threads" claim false. And write the tests that discriminate: `2 - 3 - 4`, `-2 ^ 2` vs `(-2) ^ 2`, `2 ^ 3 ^ 2`, and one assertion per exception **type** — a blanket `except Exception` passes even if every error collapsed into one class.
