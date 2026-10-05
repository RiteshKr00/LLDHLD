# Design scenario 5: document ingestion pipeline, 10M documents

## The prompt

> "We have about ten million documents sitting in S3 and SharePoint. Make them searchable."

*Deliberately small-sounding. At 10M documents the interesting question is not how you embed
a document — it is what happens when the run dies at 60%.*

---

## Clarifying questions to ask FIRST

1. **One-time backfill, or continuous ingest afterwards?** *(Decides whether you write a script
   or a service. At 10M the honest answer is both — and they must be the same code path, or the
   backfill code rots and you rewrite it in nine months.)*
2. **What are the documents?** *(Born-digital PDFs are a parsing problem. Scanned ones are an
   OCR bill roughly 13× larger per document, and OCR is CPU you can buy — embedding quota isn't.)*
3. **Is re-embedding on a model change in scope?** *(It should be. If yes, the pipeline must be
   replayable from any stage, which changes the state model, not just the runtime.)*
4. **How fast must a new document become searchable?** *(Five minutes buys you async
   everything. Five seconds puts ingest in a request path and changes the whole design.)*
5. **What is the deadline for the backfill?** *(Turns "throughput" into a number: 200M
   embeddings inside 72 hours is 772/sec sustained, and that number picks your embedding host.)*
6. **Who owns the embedding quota — is it shared with production traffic?** *(Decides whether
   the backfill needs its own keys or merely a priority lane behind live ingest.)*

---

## The follow-up bank

1. It dies at 60%. What happens?
2. Your embedding provider caps you at 5M tokens/minute. You need 30M. Now what?
3. A 4,000-page scanned PDF enters the pipeline. Describe its journey.
4. The embedding model is replaced. How much of the 55 hours do you pay again?
5. How do you stop the backfill from starving live ingest?
6. 2% of documents fail to parse. Is that acceptable, and what do you do about it?
7. Queues are at-least-once. Why doesn't your index fill with duplicates?
8. How do you know at hour 3 that you'll miss the 72-hour window?
9. Someone re-chunks with a smaller window. What happens to the chunks you already wrote?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
