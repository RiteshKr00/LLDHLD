# Design scenario 17: multi-region serving with data residency

## The prompt

> "EU customer data may not leave the EU. Design LLM serving across three regions."

*This looks like a routing question and is not. The interviewer wants to know whether you
understand what counts as personal data in an LLM stack — because the prompt is the obvious
part, and the embeddings, the cache and the traces are where real systems leak.*

---

## Clarifying questions to ask FIRST

1. **Does residency apply to prompts, embeddings, logs, or all three?** *(All three. Ask
   anyway — the answer tells you whether the person you are talking to has been through an
   audit, and it sets up the embeddings point without you lecturing.)*
2. **Is it residency or sovereignty?** *(Residency: the bytes stay in region. Sovereignty:
   no non-EU legal entity can compel access, which rules out most US-owned clouds regardless
   of where the disk is. Wildly different budgets and vendor lists.)*
3. **Is the same model available in every region, at the same version?** *(Usually not.
   This is the fact that turns one eval suite into three.)*
4. **Is cross-region failover permitted?** *(For regulated tenants, almost never. This
   single answer inverts the standard HA design, so get it early.)*
5. **Which tenants are actually in scope?** *(Rarely all of them. A per-tenant residency
   attribute, not a global mode, is what you want to end up building.)*
6. **Who is the regulator and what is the evidence standard?** *(Decides whether "we
   configured it correctly" is enough, or whether you need a provable audit trail and a
   test in CI that fails the build.)*

---

## The follow-up bank

1. Your EU region loses its LLM provider. What happens to EU traffic?
2. Are embeddings personal data? Argue it, then design for your answer.
3. A US engineer opens a trace to debug an EU customer's bad answer. Is that a breach?
4. The same model ID scores 4 points lower in `eu-west` than `us-east`. What do you do?
5. Where does the semantic cache live, and what is its key?
6. How do you *prove* to an auditor that no EU prompt reached a US endpoint last March?
7. A tenant relocates from US to EU. Migrate them.
8. What does this cost, honestly, versus a single-region deployment?
9. Design the CI test that would have caught the leak before it shipped.

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
