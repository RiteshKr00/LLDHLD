# Design scenario 26: meeting notes — long audio to actions

## The prompt

> "Turn 60-minute meetings into a summary, decisions and action items. 500 meetings a day."

*Two things to notice out loud. A 60-minute meeting is ~12k tokens, which **fits** — so chunking
is not forced, and choosing single-pass buys global coherence. And the value is not the summary;
it is **attributed, verifiable action items**, which is also where the risk is.*

---

## Clarifying questions to ask FIRST

1. **Real-time or post-hoc?** *(Post-hoc is a batch queue and nobody waits. Real-time is a
   completely different latency problem — see scenario 6.)*
2. **Is speaker attribution required?** *(It changes everything. "Someone said they'd do it"
   is not an action item, so diarisation moves from nice-to-have to load-bearing.)*
3. **Are action items assigned to people?** *(Then you need entity resolution against a
   directory, because "Dave will do it" is useless when there are four Daves.)*
4. **What happens to a wrong action item?** *(Does someone act on it, or is it a draft a
   human confirms? Decides how hard you push on precision versus recall.)*
5. **Are meetings recorded with consent, and what is the retention policy?** *(A transcript
   of every internal meeting is a discovery liability as much as an asset.)*
6. **Audio quality and setup?** *(One conference mic in a room is a different diarisation
   problem from per-participant streams, and it caps everything downstream.)*

---

## The follow-up bank

1. Does a 60-minute transcript need chunking? Justify either answer.
2. Two people talk over each other. What breaks, and what does the user see?
3. The meeting had no action items. What does your system produce?
4. "Dave will send the numbers." Which Dave?
5. Someone disputes a decision the summary recorded. What can you show them?
6. Your prompt improves next month. What happens to last month's meetings?
7. 500 a day at 60 minutes each — what does this cost and how do you schedule it?
8. How do you evaluate a summary, given there is no single right answer?
9. What is the one metric you would put in front of the business?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
