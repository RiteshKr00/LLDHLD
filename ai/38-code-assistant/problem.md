# Design scenario 24: repo-aware code assistant

## The prompt

> "Build an assistant that answers questions and suggests changes across a 2-million-line
> monorepo."

*The trap is treating code like prose. Fixed-size chunking, a single vector index, and no
notion of what calls what — it looks like RAG and it does not work, because code has structure
that prose does not and near-duplication that prose does not.*

---

## Clarifying questions to ask FIRST

1. **Answering questions, or writing code?** *(Two products. Answering needs retrieval;
   suggesting changes needs a verification loop, and the verification loop is the harder
   half.)*
2. **Is retrieval scoped to what the asking user can already read?** *(It must be. If the
   answer is "the index is global", you have built a way to read private repos through a
   chat box.)*
3. **Can code leave the network?** *(Decides self-hosted versus API before anything else,
   and it is usually the constraint that settles the model choice.)*
4. **How busy is the repo?** *(Commits per hour sets the index-freshness problem. A monorepo
   at 500 commits a day cannot be re-indexed in full.)*
5. **What proportion is generated or vendored?** *(Often most of it. It crowds retrieval and
   nobody wants answers from it.)*
6. **Do the tests run in a sandbox we control?** *(Without that, "suggest a change" cannot be
   verified and the assistant is guessing in public.)*

---

## The follow-up bank

1. 2M lines will not fit in a context window. What is your retrieval unit?
2. Why is fixed-size chunking specifically wrong for code?
3. A user asks about a function. What must you retrieve besides that function?
4. Why is BM25 not optional here?
5. The top 10 results are all near-identical generated files. Fix it.
6. Someone pushes 40 commits. What re-indexes?
7. A user asks about a repo they cannot read. What happens?
8. The assistant suggests a change. How do you know it is right?
9. What do you do about a 900-line function that will not fit in one chunk?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
