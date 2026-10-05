# Design scenario 19: zero-downtime embedding-model migration

## The prompt

> "You need to change embedding models across 100M chunks with no search downtime and no
> quality regression. Plan it."

*The word the interviewer is listening for is "in-place", and they are listening for you
**not** to say it. Two embedding models produce incomparable vector spaces, so there is no
migration path that does not run both indexes at once. Everything else follows from that.*

---

## Clarifying questions to ask FIRST

1. **Is this a quality upgrade or a forced move?** *(A deprecation deadline removes the
   option to abort, which changes the whole risk posture. If it is voluntary, "we stopped
   halfway" is a legitimate outcome.)*
2. **Can we afford double storage for the transition?** *(You must, so ask it as a
   confirmation rather than a question. If the answer is genuinely no, the honest reply is
   that a zero-downtime migration is not available.)*
3. **Is a brief recall dip acceptable, and on which tenants?** *(Decides whether you need
   per-tenant progressive cutover or can flip globally.)*
4. **Do the two models have the same dimensionality?** *(Not the point people think it is —
   same dimensions still means incomparable spaces — but it decides whether you can reuse
   the index schema and the storage estimate.)*
5. **What is the labelled set we will judge recall against, and does it exist yet?** *(If
   it does not, building it is the first task, and it lengthens the project by weeks. "No
   quality regression" is unprovable without one.)*
6. **What else reads these vectors?** *(Semantic cache, dedup jobs, clustering, analytics,
   a recommendation feature nobody mentioned. Each is a separate cutover.)*

---

## The follow-up bank

1. Why can you not just re-embed in place, chunk by chunk?
2. The backfill dies at hour 20 of 28. What happens?
3. How do you know the new model is actually better before serving it?
4. Your semantic cache is still warm after cutover. What does the user get?
5. One tenant's recall drops 8% after cutover. What now?
6. What does this cost, and how long does it take?
7. Two code paths, one reading each index. What breaks and how do you find it?
8. When do you delete the old index?
9. Halfway through, the new model is deprecated too. What do you do?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
