"""
Scenario 24 - repo-aware code assistant over a 2M-line monorepo.

    python3 solution.py

Five mechanics, each with the failure shown happening FIRST, then the fix:
  1. fixed-size chunking vs AST-aware chunking
  2. retrieving a call site without its definition
  3. identifiers are exact tokens, so vector-only retrieval loses them
  4. near-duplication: generated and vendored code crowding the results
  5. permission-scoped retrieval, and incremental re-index on commit

Toy repo, real arithmetic. Seeded, so reruns match exactly.

What to notice: none of these is a model problem. Code retrieval fails for
structural reasons - boundaries, references, exact tokens, duplication and
permissions - and every fix is in the index rather than the prompt.
"""
import hashlib
import random
import re

random.seed(24)

LINES = 2_000_000
TOKENS_PER_LINE = 12.5
CTX = 200_000


# --------------------------------------------------------------------------- #
# a toy source file
# --------------------------------------------------------------------------- #
SRC = '''\
def parse_config(path):
    raw = read_file(path)
    return validate_config(raw)


def validate_config(raw):
    if "timeout" not in raw:
        raise ConfigError("timeout is required")
    if raw["timeout"] > MAX_TIMEOUT:
        raise ConfigError("timeout too large")
    return raw


class ConfigError(Exception):
    pass
'''

MAX_TIMEOUT_DEF = "MAX_TIMEOUT = 30"


def chunk_fixed(text, size=6):
    """Fixed-size: split every N lines, boundaries wherever they land."""
    lines = text.splitlines()
    return ["\n".join(lines[i:i + size]) for i in range(0, len(lines), size)]


def chunk_ast(text):
    """AST-aware: split at top-level definitions. A real one uses a parser."""
    out, cur = [], []
    for line in text.splitlines():
        if re.match(r"^(def|class)\s", line) and cur:
            out.append("\n".join(cur).rstrip())
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(cur).rstrip())
    return [c for c in out if c.strip()]


def is_complete(chunk):
    """Does this chunk contain at least one whole definition?"""
    if not re.search(r"^(def|class)\s", chunk, re.M):
        return False
    # a definition is whole if the chunk does not end mid-body
    body = chunk.rstrip().splitlines()
    return not (len(body) > 1 and body[-1].startswith(("    if", "    raw", "    return raw" == "")))


# --------------------------------------------------------------------------- #
# 2. the dependency graph
# --------------------------------------------------------------------------- #
DEFS = {"parse_config": "f1", "validate_config": "f2", "ConfigError": "f3",
        "MAX_TIMEOUT": "f4", "read_file": "f5"}
CHUNK_TEXT = {"f1": "def parse_config", "f2": "def validate_config",
              "f3": "class ConfigError", "f4": MAX_TIMEOUT_DEF, "f5": "def read_file"}


def references(chunk_id, text):
    """Symbols this chunk uses but does not define."""
    defined = {s for s, c in DEFS.items() if c == chunk_id}
    used = set(re.findall(r"\b([A-Za-z_]\w*)\b", text))
    return sorted((used & set(DEFS)) - defined)


def expand(seed_ids, texts, depth=1):
    """Pull in the definitions of everything the seed chunks reference."""
    have = set(seed_ids)
    frontier = list(seed_ids)
    for _ in range(depth):
        nxt = []
        for cid in frontier:
            for sym in references(cid, texts[cid]):
                target = DEFS[sym]
                if target not in have:
                    have.add(target)
                    nxt.append(target)
        frontier = nxt
    return sorted(have)


# --------------------------------------------------------------------------- #
# 3 and 4. retrieval
# --------------------------------------------------------------------------- #
# Generated files are LONG and repeat the same tokens, which is precisely why
# they dominate a term-frequency ranking. Modelling them with the same token
# count as hand-written code would hide the effect this section is about.
_PB2 = "serialized descriptor field number timeout timeout timeout timeout options"
REPO = [
    ("app/config.py",       "parse_config validate_config ConfigError timeout", "hand", "core"),
    # shares every word PIECE with the query and contains the token nowhere -
    # the case that separates a lexical index from a semantic one
    ("app/config_schema.py", "validate_schema config_schema validate_fields", "hand", "core"),
    ("app/server.py",       "start_server bind port timeout", "hand", "core"),
    ("vendor/lib/retry.py", "retry backoff timeout attempts", "vendored", "core"),
    ("payroll/salary.py",   "compute_salary band timeout review", "hand", "payroll"),
] + [(f"gen/pb2_{m}.py", _PB2, "generated", "core")
     for m in ("user", "order", "invoice", "payment", "ledger", "audit")]


def subwords(tok):
    """How an embedding sees an identifier: broken into common word pieces."""
    return [p for p in re.split(r"[_\W]+", tok.lower()) if p]


def vec_score(query, doc):
    """Semantic: matches on CONCEPTS, so it cannot distinguish two identifiers
    built from the same word pieces. validate_config and parse_config look
    almost identical to it; to BM25 they are different tokens entirely."""
    q = set(w for t in re.findall(r"[A-Za-z_]\w*", query) for w in subwords(t))
    d = set(w for t in doc[1].split() for w in subwords(t))
    return len(q & d) / (len(q | d) or 1)


def bm25_score(query, doc):
    """Lexical: whole-token match, with term frequency - which is why a long
    repetitive generated file outranks a short hand-written one."""
    q = re.findall(r"[A-Za-z_]\w*", query)
    d = doc[1].split()
    return sum(3.0 * d.count(t) for t in q)


def dedup(results, keep_per_kind=1):
    """Collapse near-duplicate families so they cannot crowd the page."""
    seen, out = {}, []
    for doc in results:
        fam = doc[2] if doc[2] != "hand" else doc[0]
        seen[fam] = seen.get(fam, 0) + 1
        if seen[fam] <= keep_per_kind:
            out.append(doc)
    return out


def visible(results, user_repos):
    return [d for d in results if d[3] in user_repos]


def main():
    print("\nREPO-AWARE CODE ASSISTANT, 2M LINES")
    print("=" * 74)
    toks = int(LINES * TOKENS_PER_LINE)
    print(f"{LINES:,} lines = ~{toks:,} tokens against a {CTX:,}-token window")
    print(f"over by {toks / CTX:.0f}x -> retrieval is mandatory, and code retrieval")
    print("behaves differently from prose\n")
    assert toks > CTX * 100

    # ---------------------------------------------------------------- 1
    print("1. CHUNKING - fixed-size vs AST-aware")
    fixed, ast = chunk_fixed(SRC), chunk_ast(SRC)
    print(f"   fixed-size (6 lines): {len(fixed)} chunks")
    for i, c in enumerate(fixed, 1):
        first = c.strip().splitlines()[0] if c.strip() else "(blank)"
        whole = "whole definition" if re.match(r"^(def|class)\s", c.strip()) else "STARTS MID-BODY"
        print(f"      chunk {i}: {first[:38]:<40}{whole}")
    print(f"   AST-aware: {len(ast)} chunks, each a complete definition")
    for c in ast:
        print(f"      {c.splitlines()[0][:50]}")
    bad = sum(1 for c in fixed if c.strip() and not re.match(r"^(def|class)\s", c.strip()))
    assert bad > 0
    assert all(re.match(r"^(def|class)\s", c.strip()) for c in ast)
    print(f"   -> {bad} of {len(fixed)} fixed chunks begin mid-body. A chunk that starts")
    print("      halfway through a function is not a worse chunk, it is a useless one:")
    print("      it has no signature, no name and no way to be understood alone.\n")

    # ---------------------------------------------------------------- 2
    print("2. THE DEPENDENCY GRAPH - a call site without its definition")
    texts = {"f1": "def parse_config: read_file validate_config",
             "f2": "def validate_config: ConfigError MAX_TIMEOUT",
             "f3": "class ConfigError", "f4": MAX_TIMEOUT_DEF, "f5": "def read_file"}
    seed = ["f1"]
    print(f"   question: 'what does parse_config do?'")
    print(f"   vector retrieval alone returns: {seed}")
    print(f"      -> the model sees a call to validate_config and cannot see its body")
    d1 = expand(seed, texts, depth=1)
    d2 = expand(seed, texts, depth=2)
    print(f"   + graph expansion depth 1: {d1}")
    print(f"   + graph expansion depth 2: {d2}   (reaches MAX_TIMEOUT and ConfigError)")
    assert "f2" in d1 and "f4" in d2 and "f4" not in d1
    print("   -> retrieval must follow REFERENCES, not just similarity. The definition")
    print("      of MAX_TIMEOUT is two hops from the question and is the actual answer")
    print("      to 'why does my config fail?'.\n")

    # ---------------------------------------------------------------- 3
    print("3. IDENTIFIERS ARE EXACT TOKENS")
    q = "validate_config"
    v = sorted(REPO, key=lambda d: (vec_score(q, d), d[0]), reverse=True)
    b = sorted(REPO, key=lambda d: (bm25_score(q, d), d[0]), reverse=True)
    print(f"   query: {q!r}   (subwords an embedding sees: {subwords(q)})")
    print(f"      {'file':<24}{'vector':>8}{'BM25':>8}")
    for d in sorted(REPO, key=lambda d: -vec_score(q, d))[:4]:
        print(f"      {d[0]:<24}{vec_score(q, d):>8.2f}{bm25_score(q, d):>8.1f}")
    exact = [d for d in REPO if "validate_config" in d[1].split()]
    print(f"      only {len(exact)} file actually contains the token: {exact[0][0]}")
    print(f"      vector ranks it #{[d[0] for d in v].index(exact[0][0]) + 1}, "
          f"BM25 ranks it #{[d[0] for d in b].index(exact[0][0]) + 1}")
    assert b[0][0] == "app/config.py"
    decoy = next(d for d in REPO if d[0] == "app/config_schema.py")
    assert bm25_score(q, decoy) == 0          # does not contain the token at all
    assert vec_score(q, decoy) > vec_score(q, REPO[0])   # yet vector prefers it
    print("   -> an identifier appears verbatim or not at all, which is exactly what a")
    print("      lexical index is for. Vector search treats 'validate_config' as a")
    print("      vaguely config-shaped concept and returns four files that are not it.\n")

    # ---------------------------------------------------------------- 4
    print("4. NEAR-DUPLICATION - generated code crowds everything")
    q2 = "timeout"
    ranked = sorted(REPO, key=lambda d: bm25_score(q2, d) + vec_score(q2, d), reverse=True)
    print(f"   query: {q2!r}")
    print(f"      raw top 5:")
    for d in ranked[:5]:
        print(f"         {d[0]:<26}{d[2]}")
    gen = sum(1 for d in ranked[:5] if d[2] == "generated")
    ded = dedup(ranked)
    print(f"      after family dedup:")
    for d in ded[:5]:
        print(f"         {d[0]:<26}{d[2]}")
    assert gen >= 3
    assert sum(1 for d in ded[:5] if d[2] == "generated") <= 1
    print(f"   -> {gen} of the top 5 were generated protobuf files, all near-identical.")
    print("      Code repositories are full of families like this. Collapse the family")
    print("      to one representative, and deprioritise generated and vendored paths")
    print("      by default - nobody asks a question hoping for a pb2 file.\n")

    # ---------------------------------------------------------------- 5
    print("5. PERMISSIONS AND FRESHNESS")
    everyone = {"core"}
    print(f"   a user with access to {everyone} asks about 'timeout':")
    unscoped = [d[0] for d in ded[:6]]          # the page the user would see
    scoped = [d[0] for d in dedup(visible(ranked, everyone))[:6]]
    leaked = set(unscoped) - set(scoped)
    print(f"      unscoped index leaks: {', '.join(sorted(leaked))}")
    print(f"      permission-scoped   : {len(scoped)} results, none from payroll")
    assert "payroll/salary.py" in leaked
    assert all("payroll" not in p for p in scoped)
    print("   -> scope the retrieval, not the answer. Filtering after generation means")
    print("      the private code was already in the prompt.\n")

    commits = 40
    changed = 26
    full_cost = LINES
    inc_cost = changed * 180
    print(f"   {commits} commits touch {changed} files:")
    print(f"      full re-index      {full_cost:>10,} lines")
    print(f"      incremental        {inc_cost:>10,} lines   "
          f"({full_cost / inc_cost:,.0f}x cheaper)")
    assert inc_cost * 100 < full_cost
    print("   -> key chunks by content hash and re-embed only what changed. A busy")
    print("      monorepo makes full re-indexing arithmetically impossible, and stale")
    print("      retrieval on code is worse than none: it is confidently out of date.\n")

    print("WHAT TO NOTICE")
    print("   * every failure here is structural, and every fix is in the INDEX")
    print("   * the dependency graph is what makes code retrieval work - similarity")
    print("     finds the call site, references find the answer")
    print("   * near-duplication is the difference between code and prose corpora, and")
    print("     it is what quietly ruins relevance")
    print("   * scope retrieval by permission, never the answer")
    print("\nOK - scenario 24")


if __name__ == "__main__":
    main()
