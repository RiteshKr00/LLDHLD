# Design scenario 16: PII redaction gateway in front of every LLM call

## The prompt

> "Nothing containing customer PII may reach a third-party model. Design the gateway that
> guarantees it."

*The word doing the work is **guarantees**. They are testing whether you know the difference
between a detector and an enforcement point, and whether you will notice that the retrieved
context is the bigger leak than anything the user typed.*

---

## Clarifying questions to ask FIRST

1. **Which entity types, and under whose jurisdiction?** *(Decides the recogniser set and
   whether a checksum even exists — Aadhaar and a card number have one, a person's name does
   not, and that split drives the whole precision story.)*
2. **Is a local or in-VPC model available for the sensitive path?** *(This is the question that
   decides your p99. With one, "fail closed" means reroute; without one, it means refuse.)*
3. **Does this cover retrieved context, tool outputs and conversation history, or only the
   user's message?** *(It covers all four. If they say "just the user message", the design is
   already wrong — your own corpus is the densest PII in the request.)*
4. **Must the response be able to refer to the redacted entity?** *(Yes means reversible
   tokenisation and a token vault, which is a large, sensitive commitment. No means one-way
   masking and half the design disappears.)*
5. **Is over-redaction acceptable?** *(Almost always yes — get them to say it out loud, because
   it licences a recall-first threshold and pre-empts the "your precision is poor" follow-up.)*
6. **What is the p95 budget for the sync path?** *(Under ~50 ms rules out an LLM detector on
   every call. One answer eliminates the design most candidates reach for.)*

---

## The follow-up bank

1. What physically stops a team importing the provider SDK and bypassing your gateway?
2. Your detector is a regex for 12-digit numbers. What is its precision on real traffic, and
   what do you do about it?
3. Exactly where in the request path does redaction run, and why not earlier?
4. You escalate ambiguous chunks to an LLM extractor. What do you ask it for, and what do you
   never ask it for?
5. The answer has to say the customer's name back to them. How?
6. The detector times out. What happens to the request?
7. A placeholder gets split across two streaming chunks. What does the user see?
8. Where does the token-to-value map live, for how long, and who can read it?
9. Prove to an auditor that no PII reached the provider last quarter.
10. Why not just use a small local model to do the redaction properly?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
