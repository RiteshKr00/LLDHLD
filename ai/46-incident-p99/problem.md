# Design scenario 32: incident — p99 latency blew up after a deploy

## The prompt

> "p99 went from 3s to 25s after a release. p50 is unchanged. Debug it."

*One observation settles the shape of the whole investigation, and saying it first is the test:
**p50 unchanged means this is not capacity.** Adding instances will not help. Something affects a
subset of requests.*

---

## Clarifying questions to ask FIRST — out loud, as triage

1. **Is it one provider, one model, one tenant, one endpoint?** *(Slice before theorising. A
   tail problem is by definition a subset, so find the subset.)*
2. **What is the error taxonomy doing?** *(A timeout spike and a 5xx spike are different
   signals. Aggregated as "errors" they are indistinguishable and both look like nothing.)*
3. **Exactly what shipped?** *(Include config: timeouts, retry policy, pool sizes, feature
   flags. The code diff is often not where it is.)*
4. **Is the tail bimodal or a smooth stretch?** *(A cluster at 25s is a timeout or a retry
   sum. A smooth stretch is contention or a longer prompt.)*
5. **Did throughput change?** *(If requests-per-second fell while p50 held, suspect blocked
   concurrency rather than slow work.)*
6. **Does it reproduce under load in staging?** *(Event-loop and pool problems only appear
   with concurrency, which is why they reach production.)*

---

## The follow-up bank

1. What does an unchanged p50 tell you, and what does it rule out?
2. Give me your triage order.
3. 25 seconds is suspiciously round. What does that suggest?
4. How can a change make things *slower* by removing a timeout?
5. Someone put a blocking call in an `async def`. What does that look like in metrics?
6. Retrieval got better and latency got worse. Explain.
7. Why did the load test not catch this?
8. What should be in the deploy gate?
9. p99 is fine but p99.9 is terrible. Do you care?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
