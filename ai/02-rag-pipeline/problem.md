# Topic 2: RAG end-to-end

## The prompt

> "You've built a RAG chatbot over company policy documents. Walk me through what happens
> from the moment an employee types a question to the moment the first token appears on
> their screen. Then tell me what you'd change if retrieval quality was bad."

---

## Clarifying questions worth asking back

1. "Do you want the ingest path too, or just query time?"
2. "Are we optimising for latency, cost, or answer quality?" — they're in tension.
3. "Is the corpus static or continuously updated?" — decides reindexing strategy.

---

## The follow-up bank

1. Why `numCandidates = 10 × top_k`?
2. What's your chunk size and overlap, and why?
3. Why no reranking?
4. Why SSE and not WebSockets?
5. An employee asks something not in the policies — what happens?
6. Why not fine-tune the model on the policies instead?
7. How do you know retrieval is working?
8. Same embedding model for the query and the documents — does it matter?
9. What breaks first at 1M users?

Answers in `explained.md`; scaling in `hld.md`.
