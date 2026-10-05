# Design scenario 13: conversation memory at scale

## The prompt

> "Your assistant needs to remember prior conversations. Design memory for 100k users with
> month-long histories."

*Deliberately vague about the hard part. "Remember" could mean a sliding window or a
GDPR-erasable fact store, and those are different systems.*

---

## Clarifying questions to ask FIRST

1. **Within-session, or across sessions?** *(Within-session is a sliding window and an afternoon's work. Cross-session is the whole design.)*
2. **Remember facts, preferences, or full transcripts?** *(Facts is a structured store you can query and delete. Transcripts is a retrieval index, and a bad one.)*
3. **Is there a right-to-erasure obligation?** *(Yes forces summaries to be derived and regenerable rather than a source of truth — this single answer reshapes the storage model.)*
4. **What's the per-turn latency SLO?** *(Sub-second voice puts memory assembly under ~50 ms and pushes every write off the critical path.)*
5. **Per-user memory, or shared across a team?** *(Shared makes retrieval a permission-scoped query, so authz moves into the ranking path.)*
6. **What's the retention window on raw transcripts?** *(Thirty days plus persistent facts creates a provenance problem: the fact outlives its evidence.)*

---

## The follow-up bank

1. The user says "I'm vegetarian" in January and "I had chicken last night" in March. What does retrieval return in April?
2. A user invokes right to erasure. Walk me through every place their data is, including the derived artefacts.
3. Cost per turn at turn 300 is 30× what it was at turn 10, but every test you have passes. Where's the bug?
4. How do you decide what's worth remembering — and how would you know that decision is wrong?
5. Summarisation is an LLM call. What happens when it fails, and what happens when it silently degrades?
6. How do you evaluate memory quality? Name the metric.
7. Transcripts expire at 30 days but facts persist. What have you just broken?
8. The user asks "what do you know about me?" How do you answer without dumping the fact store?
9. Where does the memory write happen relative to the response, and why there?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
