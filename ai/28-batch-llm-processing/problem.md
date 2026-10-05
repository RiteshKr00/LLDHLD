# Design scenario 14: offline batch LLM processing, 10M records overnight

## The prompt

> "Classify and summarise 10 million support tickets. It has to finish inside an 8-hour
> overnight window and cost as little as possible."

*Two constraints pulling opposite ways. Cheap wants the provider's Batch API; the deadline
says you don't control when that returns. The whole answer lives in that tension.*

---

## Clarifying questions to ask FIRST

1. **Hard deadline, or best-effort?** *(Hard makes this a scheduling problem with a cutover
   clock. Best-effort makes it a pure cost problem and the Batch API carries everything.)*
2. **Is partial output useful — can the consumer work with 7M of 10M?** *(Decides whether you
   shard by priority and publish continuously, or must treat the run as atomic.)*
3. **One-off backfill, or nightly?** *(Nightly means the real workload is ~50k tickets, and
   the 10M is a one-time event you must not build a second system for.)*
4. **What's the accuracy bar, and is it the same for the label and the summary?**
   *(Decides whether a cheap model alone clears it, or you need a cascade with an escalation
   rule — and the two fields usually have different bars.)*
5. **Can a record be reprocessed safely — does anything downstream react to a write?**
   *(Decides whether at-least-once is fine or you need exactly-once effects. Resumability is
   worthless if a replay fires 6M webhooks.)*
6. **What is the budget ceiling, per run?** *("As little as possible" is not a number. £2k and
   £30k are different architectures.)*

---

## The follow-up bank

1. The Batch API's SLA is 24 hours and your window is 8. Justify using it at all.
2. The run dies at 62%. What exactly do you restart, and what does the replay cost?
3. It's 02:00. How do you know whether you'll finish by 06:00?
4. 200 records come back as malformed JSON. What happens to those records, and to the run?
5. You dedup on content hash. A ticket is edited after it was processed. Now what?
6. The prompt changes on Tuesday. Is the cache still valid? Is the checkpoint?
7. Where does the retry live, and how do you stop it eating the last hour of the window?
8. At 09:00 the interactive product starts getting 429s. Explain how your batch caused that.
9. Prove the 10M labels are any good without a human reading them.

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
