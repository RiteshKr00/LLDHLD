# Design scenario 29: internal AI platform for many product teams

## The prompt

> "Ten product teams all want to ship LLM features. Design the platform so they don't each
> rebuild the same thing badly."

*Platform-engineering shaped, and common for senior roles. The technical design is the easy
half. The hard half is adoption, because a platform teams bypass is worse than no platform —
you now have a false sense of central control.*

---

## Clarifying questions to ask FIRST

1. **Can teams call providers directly today?** *(Probably, and that is the problem. It also
   tells you whether you are building greenfield or migrating ten live systems.)*
2. **Who owns the invoice?** *(If the answer is "it comes out of a central budget", nobody is
   incentivised to care, and cost attribution is the first thing to build.)*
3. **Is there a central AI team, or is this a guild?** *(Decides whether you can mandate
   anything, and therefore whether "mandatory gateway" is a real option or a fantasy.)*
4. **What has each team already built?** *(Ten half-platforms exist. Migration is the
   project, not construction.)*
5. **What is the compliance surface?** *(PII handling, residency, audit. Shared middleware is
   the strongest argument for the platform and the easiest to sell.)*
6. **How fast is the fastest team today?** *(Your paved road has to beat that, or it will be
   routed around regardless of policy.)*

---

## The follow-up bank

1. What is the minimum viable platform, and what would you not build first?
2. A team says the gateway is too slow and wants direct access. What do you do?
3. How do you make the paved road genuinely faster than DIY?
4. Who owns cost, and how do you make that real?
5. A team ships on a model you have not approved. What happened, and what changes?
6. How do you migrate ten existing implementations without stopping their roadmaps?
7. What is the escape hatch, and what stops it becoming the main road?
8. How do you know the platform is working?
9. What is the failure mode of a platform team specifically?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
