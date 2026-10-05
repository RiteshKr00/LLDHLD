# Design scenario 20: incident — "the assistant started fabricating"

## The prompt

> "Users report your assistant is confidently making things up. It was fine last week. Walk me
> through the incident, then design what should have caught it."

*This is the incident-response genre. They are testing **method under pressure**, not
architecture. The signal they want is a bisection with a stated order and a reason for the
order — not a list of things that could be wrong.*

---

## Clarifying questions to ask FIRST — out loud, as triage

1. **All tenants or one?** *(One tenant means a scoping or namespace bug. All tenants means a
   shared path. This single answer halves the search space before you touch anything.)*
2. **All surfaces or one?** *(Chat but not voice, or both? Narrows it to a code path.)*
3. **When did it start, precisely?** *(Not "last week" — the hour. Everything downstream is
   correlating against this timestamp.)*
4. **What shipped near then?** *(Include config and prompt changes, which are the most likely
   and the least reviewed. "Nothing shipped" is usually wrong.)*
5. **Is retrieval returning anything at all?** *(Fastest check, most common cause. Ask it
   during triage rather than after.)*
6. **Is it fabricating, or refusing less?** *(A drop in refusals looks like improvement on
   every dashboard you have. It is the same incident wearing a disguise.)*

---

## The follow-up bank

1. Give me your triage order, and justify the order rather than the list.
2. What is your immediate mitigation, before you know the cause?
3. Retrieval returns chunks and the answer is still ungrounded. Where next?
4. How would you have detected this before users did?
5. Why is a *fall* in refusal rate a warning sign?
6. The prompt template changed and nobody reviewed it. Fix the process.
7. How do you prove afterwards which prompt version served a given request?
8. Same symptom, one tenant only. Does your triage order change?
9. You cannot reproduce it in staging. What now?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
