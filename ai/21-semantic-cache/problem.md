# Design scenario 7: a semantic cache

## The prompt

> "Most of our LLM spend is people asking the same thing in different words. Put a semantic
> cache in front of it. Don't make anything wrong."

*The second sentence is the whole question. A cache that is only fast is a weekend's work.*

---

## Clarifying questions to ask FIRST

1. **What staleness is acceptable, and does it differ per feature?** *(Decides TTL versus
   event-driven invalidation — and whether some paths may be cached at all.)*
2. **Multi-tenant, and are answers personalised?** *(Decides whether the key carries tenant,
   persona, and the caller's resolved permission set.)*
3. **Are we caching the generated answer, or the retrieval?** *(Different hit rates, and
   wildly different blast radius when it is wrong.)*
4. **What does a wrong answer cost relative to a slow one?** *(Sets the similarity threshold,
   and decides whether the token guard is mandatory or optional.)*
5. **How often does the corpus change?** *(A nightly re-index kills every entry nightly. That
   changes the economics before you write a line of code.)*
6. **Is the response streamed?** *(Decides whether a half-consumed response may be written to
   the cache at all.)*

---

## The follow-up bank

1. Two queries score 0.97 cosine and one of them contains "not". What does your cache do?
2. You re-index the corpus at 03:00. What is in the cache at 03:01?
3. What threshold do you pick, and how did you arrive at that number?
4. A and B are in the same tenant, but B cannot see the finance folder. May they share an entry?
5. Your hit rate is 45% and rising week on week. Is that good?
6. The cache is empty after a deploy and it is 09:00. Now what?
7. Do you cache the generated answer or the retrieved chunks? Defend the choice.
8. Where does the cache sit — before the gateway, or after retrieval?
9. How do you cache a streaming response?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
