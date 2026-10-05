# Design scenario 18: hybrid self-hosted GPU + API inference

## The prompt

> "You're spending too much on API inference. Design a hybrid platform that uses your own GPUs
> where it makes sense."

*Note the phrasing of the last four words — the interviewer has already conceded that
sometimes it does not. They are testing whether you can find the line, or whether you will
answer "self-hosting is cheaper", which is the trap.*

---

## Clarifying questions to ask FIRST

1. **What is the current spend, and on which tasks?** *(A single number is useless. The
   decision is per task, because the crossover is per task.)*
2. **Is anyone on this team going to operate GPUs?** *(The cost that never makes the
   spreadsheet. If the answer is "we'll figure it out", the honest recommendation may be
   to do nothing.)*
3. **Is latency or throughput the constraint?** *(Throughput-bound batch work is the ideal
   self-hosting candidate. Spiky low-latency traffic is the worst, because you pay for the
   peak and idle through the trough.)*
4. **Which tasks genuinely need frontier quality?** *(Those are not candidates at any
   volume. Naming them early stops the conversation drifting into "can we self-host
   everything".)*
5. **How steady is the traffic, hour to hour?** *(Utilisation is what decides this, and
   utilisation is a function of the traffic shape, not the daily total.)*
6. **Is there a compliance or data-locality reason pushing this?** *(If so the economics
   stop being the deciding factor and you should say so rather than inventing a cost case.)*

---

## The follow-up bank

1. At what monthly volume does self-hosting a 7B model start winning? Show the arithmetic.
2. Your GPU sits at 20% utilisation. Is it still cheaper than the API?
3. Which tasks would you move in-house first, and why those?
4. The self-hosted model scores 3 points lower on the task. Do you ship it?
5. A GPU node dies at 2am. What does the user see?
6. How do you stop call sites from knowing where inference happens?
7. Your projection said 60% savings and the bill says 15%. Where did it go?
8. When would you recommend *not* doing this at all?
9. Batch and interactive traffic share the fleet. How do you stop batch starving interactive?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
