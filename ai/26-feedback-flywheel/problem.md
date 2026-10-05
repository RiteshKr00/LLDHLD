# Design scenario 12: the feedback flywheel

## The prompt

> "You have 600k LLM calls a day and no labelled data. Design the system that turns production
> traffic into an evaluation set that keeps improving."

*The insight to lead with: **this is not a collection problem.** At a 2% implicit-negative rate
you get ~11.5k candidates a day and you can label ~300. Everything interesting in the design is
about choosing which 300, and about not poisoning the set with the other 11,200.*

---

## Clarifying questions to ask FIRST

1. **Which surfaces even have an implicit signal?** *(An edit box and a retry button give you
   rich signal. A voice turn gives you barge-in, abandonment and escalation and nothing else —
   a different design, not a smaller one.)*
2. **Can you store prompt and response text at all, and for how long?** *(Decides whether the
   flywheel runs on redacted text or only on features and hashes. Redaction is a capture-path
   decision, not a cleanup job.)*
3. **Is there a human downstream who corrects the output — an agent, an analyst, a reviewer?**
   *(A downstream correction is delayed ground truth. It's the highest-precision label you will
   ever get for free, and most teams throw it away.)*
4. **What is the labelling budget, in reviewer-hours per week, and who are the reviewers?**
   *(This single number sizes everything upstream. It is the constraint, not the compute.)*
5. **Do you already have deterministic checkers — grounding, schema, citation resolution?**
   *(If yes you have a ~90%-precision signal that needs no user at all, and the user signals
   are supplementary. If no, build those before you build any of this.)*
6. **How often do prompts and models ship?** *(Sets the label expiry window. A label ages out
   with the model version that produced it.)*

---

## The follow-up bank

1. Thumbs-down engagement is 0.07%. What do you use instead, and how do you know it's better?
2. "The user edited the output" — how do you separate *wrong* from *stylistic preference*?
3. You can label 300 cases a day against ~11,500 candidates. Which 300, and why not the worst 300?
4. Your loudest tenant is 4% of traffic and takes a fifth of your labelling budget. What does
   that do to the golden set, and what stops it?
5. Six months in, the golden-set pass rate is 98%. Ship faster, or is something wrong?
6. The offline score improved and the production defect signal got worse. Which one wins, and
   what do you change?
7. Legal says you may not store prompts or responses. Design the flywheel anyway.
8. A reviewer labels 300 cases and half of them came from a prompt version you retired last
   week. What went wrong upstream?
9. How do you stop the golden set silently changing underneath a release comparison?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
