# Design scenario 30: RAG over structured *and* unstructured data

## The prompt

> "Users ask questions needing both the policy documents and the database. One answer."

*The trap is elegant and wrong: embed the database rows so everything is "one RAG pipeline". You
cannot `SUM` a vector search, and the numbers go stale the moment you index them.*

---

## Clarifying questions to ask FIRST

1. **Are questions typically one source or genuinely both?** *(Decides whether the router is
   a classifier or a planner. If most questions are single-source, the router is most of the
   product.)*
2. **Is freshness critical on the structured side?** *(Yes, always — a database answer must
   be current. This is what rules out embedding rows.)*
3. **What happens when the document and the data disagree?** *(They will. Someone must
   decide whether the policy or the system of record wins, and it is not the model.)*
4. **Whose permissions apply to the database side?** *(See scenario 21 — the query runs under
   the user's credentials or you have built a privilege-escalation path.)*
5. **Do canonical metric definitions exist?** *(Same question as text-to-SQL, and the same
   answer: without them the numbers are inconsistent.)*
6. **How is a wrong answer noticed?** *(A blended answer with no per-source attribution is
   unverifiable by construction.)*

---

## The follow-up bank

1. Why not embed the database rows and have one pipeline?
2. A question needs both sources. Walk me through it.
3. Your router sends 20% of questions to the wrong source. How bad is that?
4. The policy document says 30 days and the database says 45. What ships?
5. How does a user verify a blended answer?
6. Which source do you cache, and for how long?
7. A question is genuinely ambiguous about which source it needs. What then?
8. How do you evaluate this end to end?
9. What does the answer look like when one source fails?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
