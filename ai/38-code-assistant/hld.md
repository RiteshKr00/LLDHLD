# The code assistant at monorepo scale

## 1. Numbers first

| Quantity | Value | Note |
|---|---|---|
| Repo | 2M lines ≈ 25M tokens | 125x a 200k window |
| Retrieval unit | one AST node | function, method, class |
| Graph expansion | 1–2 hops | beyond that you pull in the repo |
| Full re-index | 2M lines | impossible per push |
| Incremental, 40 commits | ~4,700 lines | 427x cheaper |
| Generated/vendored share | often the majority | and it crowds retrieval |

## 2. The index is three things

**Chunks + embeddings.** AST nodes, with file path and language prepended to the text.

**A lexical index.** BM25 over the same chunks. Non-negotiable: identifiers are exact tokens.

**A symbol graph.** Definitions, references, imports, and test-to-subject links. This is the
component that distinguishes a code assistant from prose RAG, and it is what turns a retrieved
call site into an answer.

## 3. Retrieval

1. Hybrid first stage — BM25 and vectors, fused.
2. **Family collapse** — one representative per near-duplicate cluster.
3. **Path priors** — deprioritise `generated/`, `vendor/`, migrations, snapshots.
4. **Graph expansion** — pull callee definitions, types, and tests, 1–2 hops.
5. **Permission filter applied at the query**, not afterwards.
6. Rerank, then assemble with paths visible.

Step 5's position in the list is the whole security answer.

## 4. Freshness

Content-hash every chunk. On push, re-embed only changed hashes. Then update the graph for the
changed files **and for anything referencing a symbol that moved** — a rename invalidates
references in files that did not themselves change, which is the case people miss.

Track index lag. Answering confidently from last Tuesday's code is the characteristic failure of
this product.

## 5. Suggesting changes is a different product

Answering questions needs retrieval. Suggesting changes needs a **verification loop**: apply in a
sandbox, compile, run the tests touching the changed symbols — the graph already tells you which
— and return the result with the suggestion. Without it you are shipping plausible text into a
context where plausible-and-wrong is expensive.

Scope the test run by the dependency graph rather than running everything; on a monorepo the full
suite is not a per-suggestion operation.

## 6. What breaks, in order

| # | Breaks | First response |
|---|---|---|
| 1 | Relevance, from near-duplication | Family collapse, path priors, diversity at rerank |
| 2 | Index freshness | Content-hash incremental re-index; alert on lag |
| 3 | Missing definitions | Graph expansion, 1–2 hops |
| 4 | Permission scoping | Filter at retrieval; fail closed on unknown user |
| 5 | Unverified suggestions | Sandbox, compile, targeted tests |

## 7. Observability

Retrieval precision on a judged query set, sliced by query type — identifier lookup, "how does X
work", "where is Y used". **Share of results from a single near-duplicate family**, which is the
early warning for the failure that arrives first. Index lag in minutes. Graph expansion depth
distribution. Permission-filter hit rate, which should be non-zero and stable — a sudden drop
means the filter stopped working. And for the change-suggestion path: compile rate and test-pass
rate of suggested patches, which is the only quality metric that is not a proxy.
