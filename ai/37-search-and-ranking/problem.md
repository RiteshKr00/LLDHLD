# Design scenario 23: LLM-powered search and ranking

## The prompt

> "Improve search on a 10M-document site using LLMs. Latency budget: 200ms."

*The budget is the question. A generation call is 200ms–2s on its own, so an LLM cannot be in
the synchronous path at all. Recognising that immediately — and then saying where the LLM
**does** go — is the answer.*

---

## Clarifying questions to ask FIRST

1. **Is 200ms end-to-end or server-side?** *(End-to-end includes network and render, which
   can leave you 80ms. A different system.)*
2. **Head or tail queries dominating?** *(Head means caching solves most of it. Tail means
   the hard relevance work is unavoidable.)*
3. **Is click data available?** *(Your best training signal by a distance, and the thing that
   separates a search engine from a similarity function.)*
4. **What does the current search get wrong?** *(Exact-term misses, paraphrase misses, or
   ordering? Three different fixes, and "use an LLM" is not one of them.)*
5. **What is the success metric?** *(Click-through, dwell, task completion, revenue?
   Optimising the wrong one is how search gets worse while the dashboard improves.)*
6. **How fresh must results be?** *(Decides whether offline enrichment is minutes or hours
   behind, and whether a document can be searchable before it is enriched.)*

---

## The follow-up bank

1. Where exactly does the LLM run, given 200ms?
2. Why not embed everything and use vector search?
3. What is your first-stage retrieval, and why hybrid?
4. How do you rank, once you have 100 candidates?
5. You have no click data yet. How do you bootstrap?
6. A new document is published. When is it findable, and when is it ranked well?
7. How do you know a ranking change is an improvement?
8. Head queries are 40% of traffic. What do you do with that?
9. Business wants sponsored results promoted. Where does that go?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
