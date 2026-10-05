# Design scenario 11: prompt and config management platform

## The prompt

> "Prompts and model choices are changed weekly by anyone with dashboard access. Design the
> system that makes that safe without making it slow."

*Two words carry the question: **safe** and **slow**. Safe means reviewed, reversible and
attributable. Slow means a PM waiting on a deploy to change a sentence. Most designs buy one by
selling the other — the answer is the one that refuses to.*

---

## Clarifying questions to ask FIRST

1. **Who changes prompts — engineers through PRs, or PMs through a dashboard?** *(Decides
   whether the gate can live in CI at all. If a console can write to production, CI is
   decoration.)*
2. **Per-tenant overrides, or one prompt for everyone?** *(Decides whether you need a precedence
   order — which is the thing that actually breaks.)*
3. **Is rollback measured in minutes or seconds?** *(Seconds forces immutable versions, a live
   pointer and pushed snapshots. Minutes means a redeploy is acceptable and the whole control
   plane shrinks to a git repo.)*
4. **Does "config" mean the prompt only, or the model id, decode params, tool schema and
   retrieval settings too?** *(Decides the unit of versioning. Version them separately and you
   will ship a combination nobody ever evaluated.)*
5. **Is there a golden set to gate on today, and who owns it?** *(No golden set means sprint one
   is building one, not building the gate.)*
6. **Blast radius of a bad prompt — one tenant, or all of them?** *(Decides canary by traffic
   share versus canary by tenant cohort.)*

---

## The follow-up bank

1. Which prompt actually ran for this request? Walk me through answering that at 3am.
2. A global edit and a tenant override disagree. What is the rule, and where is it written down?
3. Rollback in under a minute — what exactly flips, and how does every pod learn about it?
4. A PM edits a prompt at 6pm on a Friday. What stops it reaching production untested, without
   stopping it reaching production at all?
5. Your eval gate's provider is down. Can anyone ship? Should they?
6. Two pods serve different prompt versions for 40 seconds during a rollout. Bug, or not?
7. Someone adds six few-shot examples. Every test passes. What did it cost?
8. How do you canary a prompt in a multi-turn conversation without a user flipping versions
   mid-thread?
9. Prove to an auditor which prompt produced a given regulated output six months ago.

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
