# Design scenario 1: a multi-model LLM platform that doesn't fail at scale

## The prompt

> "Design an LLM platform that serves several product features across several model providers,
> and does not fall over."

*The trap here is specific and almost everyone walks into it: **listing components without
naming the failure each one prevents**. A gateway, a router, a cache and a circuit breaker is a
diagram. Saying what each one stops is a design.*

> Topic 11 covers the same ground from the concept side, and scenario 2 covers building the
> gateway itself. This card is the **multi-model** problem: choosing between models, and what
> happens when one of them changes underneath you.

---

## Clarifying questions to ask FIRST

1. **How many features, and do they have different quality floors?** *(A summariser and a
   legal-answer feature cannot share one fallback chain. This is the question that produces
   per-feature degradation instead of a global one.)*
2. **Which providers, and are their capabilities actually equivalent?** *(Function calling,
   context length, structured output, streaming. A fallback to a model that cannot do the task
   is an outage wearing a success code.)*
3. **What are the rate limits — per minute and per day?** *(Ask for both. The daily one is what
   breaks first and it is the one nobody quotes.)*
4. **Is this in the request path or async?** *(Decides whether a retry budget exists at all.)*
5. **Who owns the model choice — us or the feature team?** *(Decides whether the registry is
   enforcement or documentation.)*
6. **What happens when a provider deprecates a model?** *(It will, with about 90 days notice.
   If nobody has an answer, that is the finding.)*

---

## The follow-up bank

1. Name each component and the failure it prevents. Not the component list — the failures.
2. What breaks first at scale, and why that rather than capacity?
3. Your cheap model handles 70% of traffic. When does a cascade stop saving money?
4. You fall back to another provider and the feature silently breaks. How?
5. Two features share a provider. One is a summariser, one is a legal answer. Design the degradation.
6. Ten instances, one provider rate limit. How do you not exceed it?
7. A provider deprecates your primary model with 90 days notice. Walk me through it.
8. How do you know a model changed underneath you?
9. What do you validate on the way back, and why is that not paranoia?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
