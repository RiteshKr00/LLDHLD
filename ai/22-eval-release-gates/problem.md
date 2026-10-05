# Design scenario 8: eval and release gates for LLM features in CI

## The prompt

> "Your team ships prompt and model changes several times a week. Build the pipeline that stops
> a bad one reaching users. What does the gate check, and when exactly does it block?"

*The insight to lead with: **prompts and model ids are config, so they bypass code review unless
you build a gate for them.** The most frequent change in an LLM system is the least reviewed.*

---

## Clarifying questions to ask FIRST

1. **Is there a golden set, who owns it, and where does it live?** *(If there isn't one, the
   first two sprints are building it, not the gate. Say so rather than designing around a
   dataset that doesn't exist.)*
2. **Are prompts, model ids, decode params and retrieval config in git — or in a table an admin
   can edit?** *(Decides whether the gate can even be triggered by the change that matters.)*
3. **Who can change a production model, through what surface?** *(One console toggle bypasses
   every gate you build. This is a permissions question before it's a CI question.)*
4. **What does a bad release actually cost — an ugly answer, or a wrong number in a regulated
   document?** *(Sets hard vs soft thresholds, and decides canary-and-watch vs block-and-prove.)*
5. **Is there a deterministic scorer for this task, or only human judgement?** *(Decides whether
   you are building a gate or a report. Only one of those can block a merge.)*
6. **What's the CI budget per PR, in minutes and in dollars?** *(Decides tiering. A 25-minute
   gate gets a `skip-eval` label within a fortnight.)*

---

## The follow-up bank

1. Your golden set is 800 cases. Where did they come from, and how do you keep them
   representative of what users actually send?
2. The composite score moved by 0.4 percent. Ship or block?
3. Why not LLM-as-judge as the gate? Everyone uses it.
4. A hard gate has no data for a third of the cases. What happens?
5. The provider is down and the eval cannot run. Do you block every merge in the company?
6. Offline metrics are up; the canary's thumbs-down rate is up. Which one wins?
7. How do you stop the harness drifting from what production actually does?
8. Someone hotfixes a prompt in the admin UI at 2am to stop an incident. Then what?
9. The gate takes 25 minutes and people have started bypassing it. Fix it.

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
