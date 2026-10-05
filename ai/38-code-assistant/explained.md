# Repo-aware code assistant — explained

---

## 1. The numbers force retrieval, and code retrieval is not prose retrieval

2M lines is roughly **25M tokens**, against a 200k window. Over by **125x**. So retrieval is
mandatory — but the interesting claim is the second one: code retrieval behaves differently from
prose, for five structural reasons, and every fix is in the **index** rather than the prompt.

---

## 2. Say this before anything else: fixed-size chunking is the classic mistake

A prose chunk that starts mid-paragraph is a worse chunk. A code chunk that starts **mid-function
body** is a *useless* one — it has no signature, no name, no imports, and nothing that says what
it belongs to. `solution.py §1`: with 6-line fixed chunks, one in three begins mid-body.

Chunk at **AST boundaries** — function, method, class. A real implementation uses tree-sitter and
gets language-aware boundaries for thirty languages at once.

Two refinements that matter in practice:

- **Include the file path and language in the chunk text.** The model needs to know that this is
  `payments/refund.py` and not `tests/fixtures/refund.py`, and path is often the strongest
  relevance signal you have.
- **A 900-line function** still will not fit. Split at statement boundaries with the signature
  repeated in each part, and mark them as siblings so retrieving one pulls the rest.

---

## 3. The dependency graph is what makes it work

Similarity finds the **call site**. References find the **answer**.

`solution.py §2`: asked "what does `parse_config` do?", vector retrieval returns
`parse_config` — which calls `validate_config`, whose body the model cannot see. One hop of graph
expansion pulls in `validate_config`; two hops reach `MAX_TIMEOUT` and `ConfigError`, and
`MAX_TIMEOUT = 30` is the actual answer to "why does my config keep failing?".

So the index is not just chunks and vectors. It is chunks, vectors, **and a symbol graph** —
definitions, references, imports — with retrieval expanding along edges after the initial
similarity hit. One or two hops; beyond that you pull in the whole repo.

---

## 4. Identifiers are exact tokens

`solution.py §3`, querying `validate_config`:

| File | Vector | BM25 |
|---|---|---|
| `app/config_schema.py` | **0.50** | 0.0 |
| `app/config.py` | 0.40 | **3.0** |

Only `app/config.py` contains the token. Vector search ranks it **second**, behind a file that
shares every word *piece* — `validate`, `config` — and the token nowhere. An embedding sees
`validate_config` as a vaguely config-shaped concept; a lexical index sees a token that is
present or absent.

Identifiers, error codes, file paths and API names are all exact tokens, and they are most of
what a developer types. **BM25 is not optional here**, and this is a stronger version of the
hybrid-retrieval argument than the prose case, because code identifiers are more distinctive and
more common as queries.

---

## 5. Near-duplication is the difference between code and prose corpora

`solution.py §4`, querying `timeout`: **all five** of the top five results are generated protobuf
files, near-identical to each other. They win because generated code is long and repeats the same
tokens, which is exactly what term-frequency ranking rewards.

Real repositories are full of these families — generated clients, vendored dependencies,
migrations, fixtures, snapshots. Two fixes:

- **Collapse the family** to one representative, so a family cannot occupy the whole page.
- **Deprioritise generated and vendored paths** by default. Nobody asks a question hoping for a
  `pb2` file, and the paths are usually identifiable by convention.

This is the failure that shows up first in a real deployment and it is invisible in a demo repo.

---

## 6. Permissions and freshness

**Scope the retrieval, not the answer.** `solution.py §5`: an unscoped index puts
`payroll/salary.py` on the page for a user who cannot read that repo. Filtering after generation
is not a fix, because the private code was already in the prompt — and the model may have
paraphrased it.

**Incremental re-index on commit**, keyed by content hash. 40 commits touching 26 files is 4,680
lines to re-embed against 2M for a full rebuild — **427x cheaper**. Full re-indexing a busy
monorepo is arithmetically impossible, and stale code retrieval is worse than none: it is
confidently out of date.

---

## 7. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Retrieval relevance** | Near-duplication. Generated and vendored code crowds everything. |
| 2 | **Index freshness** | A busy monorepo outruns a full re-index. |
| 3 | **Missing definitions** | Retrieval without graph expansion returns call sites, not answers. |
| 4 | **Permission scoping** | Easy to add late and wrong to add late. |
| 5 | **Unverified suggestions** | Plausible code that does not compile. |

---

## The follow-ups, answered

**1. 2M lines will not fit. What is your retrieval unit?**

A function, method or class — an AST node with its signature intact — plus the file path and
language prepended to the chunk text. Not a fixed line count. The unit needs to be independently
comprehensible, because that is what the model receives, and a fragment beginning mid-body is not.

**2. Why is fixed-size chunking specifically wrong for code?**

Because prose degrades gracefully and code does not. A paragraph split in half is still two
readable half-paragraphs. A function split in half gives you a body with no signature — no name,
no parameters, no return type, no docstring. It cannot be matched to a question about that
function and cannot be understood if retrieved. It is not a lower-quality chunk; it is noise
occupying a slot.

**3. A user asks about a function. What else must you retrieve?**

Its callees' definitions, one or two hops out, so the model can see what it actually does. Its
type definitions. Its tests, which are usually the clearest available documentation of intended
behaviour. Its call sites, if the question is about changing it, because that is where the blast
radius lives. And the file's imports. The retrieved set is a **neighbourhood in the graph**, seeded
by similarity — not a top-k list of similar snippets.

**4. Why is BM25 not optional?**

Because identifiers are exact tokens with no useful semantic neighbourhood. An embedding maps
`validate_config` to a region shared by every config-adjacent symbol, so it ranks a file that
merely sounds similar above the one file that contains the token. Developers query with exact
names constantly — a function, an error string, a config key, a stack-trace frame. Losing exact
match loses the most common query type in the product.

**5. The top 10 are near-identical generated files.**

Three moves. Detect families by content similarity or by path convention, and collapse each to one
representative with a "12 similar files" affordance. Apply a ranking penalty to `generated/`,
`vendor/`, `node_modules/`, migrations and snapshots — configurable, because occasionally someone
does want the generated client. And use MMR or a similar diversity objective at rerank so the page
cannot be filled by one cluster. Measure it: the share of results from a single family is a
relevance metric worth alerting on.

**6. Someone pushes 40 commits. What re-indexes?**

Only the changed chunks, identified by content hash — 4,680 lines rather than 2M. Chunks whose
hash is unchanged keep their embedding. Then update the symbol graph for the changed files and
for anything referencing a symbol whose definition moved, which is the step people forget: a
rename invalidates every chunk that referenced the old name, even though those files did not
change. Track index lag as a metric, because the honest failure mode here is answering confidently
from last Tuesday's code.

**7. A user asks about a repo they cannot read.**

They get results from what they can read, and no indication that anything was withheld — because
"3 results hidden" is itself a leak about what exists. Enforce this **at retrieval**, as a filter
in the query, not as a post-generation check. The distinction matters: post-filtering means the
private code entered the prompt, and the model's answer may already paraphrase it. The permission
set is resolved per request from the source of truth, and it fails closed on an unknown user.

**8. The assistant suggests a change. How do you know it is right?**

You run it. Apply the patch in a sandbox, compile, run the affected tests, and return the result
alongside the suggestion. This is the single largest quality difference between a code assistant
that people trust and one they stop using, and it is why "can we run tests in a sandbox we
control?" is a clarifying question rather than an implementation detail. Where the test suite is
too slow, run the subset touching the changed symbols — the dependency graph already tells you
which those are. A suggestion that compiles and passes tests is a different product from a
suggestion that looks plausible.

**9. A 900-line function that will not fit in one chunk?**

Split at statement boundaries rather than line counts, repeat the signature at the top of each
part so every fragment remains identifiable, and link the parts as siblings so retrieving one
pulls the others up. Also treat it as a signal: a function that does not fit is usually the one
people ask about most and understand least, so it is worth surfacing to the humans as a
refactoring candidate rather than only solving it in the index.

---

## One-line summary

25M tokens forces retrieval, and code retrieval is structurally different from prose: chunk at AST
boundaries because a mid-body fragment is useless rather than merely worse, expand along a symbol
graph because similarity finds the call site while references find the answer, keep BM25 because
identifiers are exact tokens, collapse near-duplicate families because generated code otherwise
owns the page, scope at retrieval rather than after generation, re-index by content hash, and
verify suggested changes by running the tests.

---

## The trap answer to avoid

Describing prose RAG with the word "code" substituted in — fixed-size chunks, one vector index,
top-k by cosine. Each of the five differences bites: chunk boundaries, the dependency graph,
exact-token matching, near-duplication, and permissions. The one that fails soonest in a real
deployment is near-duplication, and it is the one least likely to appear in a demo.
