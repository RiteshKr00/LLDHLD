# Design scenario 28: fine-tuning pipeline, end to end

## The prompt

> "You've decided to fine-tune a small model for one high-volume task. Design the pipeline."

*Note "you've decided". The first thing to do is reopen that decision, politely — because if
nobody can say why fine-tuning rather than prompting, that is the finding, and every pipeline
below is effort spent on the wrong thing.*

---

## Clarifying questions to ask FIRST

1. **Why fine-tune rather than prompt?** *(Format, cost or latency are good answers.
   Knowledge is not, and it is the usual one. If nobody can answer, stop here.)*
2. **How much labelled data exists, and who labelled it?** *(Curation is ~80% of the effort.
   "We'll generate it" needs its own plan.)*
3. **Is the base model's licence commercially usable for this?** *(A cheap question with an
   expensive wrong answer.)*
4. **What is the prompted baseline's score on the same eval?** *(If it does not exist yet,
   building it is task one — it is the gate.)*
5. **Who owns the model once it ships?** *(A fine-tune is a codebase, not an artefact. It
   needs an owner, a retraining trigger, and a deprecation plan.)*
6. **How often does the task definition change?** *(A monthly-changing spec makes retraining
   a treadmill, and prompting may win on that alone.)*

---

## The follow-up bank

1. When is fine-tuning the wrong answer?
2. What is the single most common way a fine-tune's numbers get inflated?
3. LoRA or full fine-tuning? Defend it.
4. Your fine-tune scores 4 points above the prompted baseline. Ship it?
5. It is great at the task and worse at everything else. How would you know?
6. How do you make this reproducible six months from now?
7. How do you serve it without changing any call site?
8. It regresses in production. What is your rollback?
9. Where does the effort actually go?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
