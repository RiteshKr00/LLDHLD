# Design scenario 21: text-to-SQL — "chat with your database"

## The prompt

> "Let business users ask questions of the data warehouse in English. It must not return wrong
> numbers."

*One of the most-asked LLM design questions. The trap is treating it as prompt engineering. It
is schema retrieval, plus a semantic layer, plus validation — and the model is the least
interesting component.*

---

## Clarifying questions to ask FIRST

1. **How many tables, and are they documented?** *(300 tables × 40 columns is 12,000 columns.
   That does not fit in a prompt, which makes this a RAG problem over schema before it is
   anything else.)*
2. **Read-only?** *(It must be. Ask so that the answer is on the record, then design as
   though someone will try anyway.)*
3. **Are there canonical metric definitions, or does every team compute revenue
   differently?** *(This is the highest-value question in the list and most candidates never
   ask it.)*
4. **Is a wrong answer worse than no answer?** *(Yes — this is finance-adjacent. That single
   answer justifies refusing, showing the SQL, and every guard below.)*
5. **Whose permissions does the query run under?** *(If the answer is "a service account",
   the feature is a privilege-escalation path and that is the first thing to fix.)*
6. **Who is accountable when a number reaches a board deck?** *(Decides how much provenance
   you must show alongside the answer, and whether "the assistant said so" is survivable.)*

---

## The follow-up bank

1. 12,000 columns do not fit in a prompt. What do you do?
2. Two teams define "revenue" differently. Whose does the model use?
3. The SQL runs, returns a plausible number, and it is wrong. How do you catch that?
4. A user asks something that would scan 4TB. What happens?
5. Someone asks "delete the test rows". Walk me through what stops it.
6. Whose credentials does the query run under, and why does it matter?
7. How do you cache this safely?
8. What do you show the user alongside the number?
9. The model invents a column that does not exist. Where is that caught?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
