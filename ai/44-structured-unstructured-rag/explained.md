# RAG over structured and unstructured data — explained

---

## 1. Say this before anything else: you cannot SUM a vector search

The elegant wrong answer is to embed the database rows so everything becomes one RAG pipeline.
Two independent reasons it fails, and the first is structural rather than a tuning problem.

**Aggregation is impossible.** `solution.py §1`: asked how much a customer spent, SQL sums 169
matching rows to 76,471. The top-10 vector hits sum to 5,017 — **7% of the answer**. A similarity
search returns the *k most similar* rows; it has no notion of *all*. You cannot `SUM` it, `GROUP
BY` it, or `JOIN` it, and aggregation is most of what anyone asks a database.

**Numbers go stale instantly.** 45 minutes since the last index build is 6,300 writes the vector
index cannot see. A database answer must be current.

So: **never embed the database. Query it live.**

---

## 2. Routing dominates end-to-end quality

`solution.py §2`:

| Routing accuracy | Retrieval 0.80 | Retrieval 0.92 |
|---|---|---|
| **100%** | **0.80** | 0.92 |
| 90% | 0.73 | 0.86 |
| **80%** | 0.67 | **0.79** |
| 60% | 0.55 | 0.61 |

Perfect routing with *weak* retrieval (0.80) beats 80% routing with *strong* retrieval (0.79).

The reason is that a misrouted question is not degraded — it is **unanswerable**. Semantic search
over a table returns nothing useful; SQL over prose is not expressible. There is no partial credit
to be had, so retrieval quality on the wrong source is irrelevant.

**Spend on the router before you spend on either retriever.** That ordering is the finding.

---

## 3. The layers, each named by the failure it prevents

**Query router / planner** — classify: documents, database, or both — *prevents:* semantic search
over a table and SQL over prose.

**Two retrieval paths** — vector RAG for documents, text-to-SQL for structured, with all the
guards from scenario 21 — *prevents:* one pipeline that does neither job.

**A synthesis step with per-source attribution** — *prevents:* a blended answer nobody can verify.

**Never embed the database; query it live** — *prevents:* stale numbers, the worst failure here.

**Disagreement handling** — surface both — *prevents:* the model silently adjudicating.

**Per-source confidence** — *prevents:* a strong claim resting on the weaker half.

---

## 4. Attribution is what makes a two-source answer usable

Blended:

> Acme is past their refund window.

Attributed:

> Acme's order 4471 shipped on 3 March **[database, live]**.
> The refund window is 30 days from shipment **[policy doc v4, section 2.1]**.
> Today is 8 September, so the window closed on 2 April.

The blended version is unverifiable by construction — a reader cannot tell which half came from
where, so they cannot check either half. This is not presentation. It is the difference between
an answer someone can act on and one they have to take on trust.

---

## 5. When the sources disagree

They will. A policy document and a system of record drift apart, and the gap is often where the
interesting business problem lives.

The model **must not adjudicate**. It does not know whether the policy is aspirational, the
database is misconfigured, or there is a documented exception. Silently picking one is the worst
available behaviour, because it looks like an answer.

Surface both, mark the conflict, and route it to whoever owns the discrepancy. A conflict
detected is a bug found; a conflict resolved by a language model is a bug buried.

---

## 6. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Routing** | Dominates everything, and misrouting has no partial credit. |
| 2 | **Synthesis on disagreement** | The sources will disagree, and the model wants to resolve it. |
| 3 | **Structured freshness** | If anyone caches or embeds the numbers. |
| 4 | **Partial failure** | Two sources fail partially far more often than completely. |
| 5 | **Permissions asymmetry** | Documents and rows have different access models. |

---

## The follow-ups, answered

**1. Why not embed the database rows?**

Because a vector search cannot aggregate and cannot be fresh. Asked for a customer's total spend,
similarity search returns the ten most similar rows — 7% of the true figure — because it has no
concept of *all matching rows*. There is no `SUM`, no `GROUP BY`, no `JOIN`, and those are most of
what people ask a database. Separately, anything you index is a snapshot: 45 minutes of writes are
already invisible, and a wrong number that looks current is the worst failure mode in this system.
Query it live.

**2. A question needs both sources. Walk me through it.**

"Is Acme past their refund window on order 4471?" The planner decomposes it: the refund window is
a **policy** question, and the shipment date is a **database** question. Both run in parallel.
Retrieval returns the policy clause with its section reference; SQL returns the shipped date under
the user's own credentials. Synthesis composes them with the arithmetic shown and each fact
attributed to its source. Note the model performs the date comparison but sources neither fact —
that split is what keeps the answer checkable.

**3. Your router sends 20% to the wrong source. How bad?**

Bad enough to dominate everything else. At 80% routing accuracy with strong retrieval, end-to-end
quality lands below perfect routing with weak retrieval. The reason is the absence of partial
credit: a question sent to the wrong source produces nothing usable, not a worse answer. The
practical consequence is that router accuracy is the first metric to instrument and the first
thing to improve, and it is much cheaper to improve than retrieval — a few hundred labelled
questions and a small classifier will beat a prompt-only router.

**4. The policy says 30 days and the database says 45. What ships?**

Both, marked as a conflict, with each attributed. The model must not choose, because the right
answer depends on facts it does not have — whether the policy was updated and the system not,
whether this customer has a negotiated exception, whether someone misconfigured a field. Ship the
conflict, and route it to the owner of the discrepancy. In practice this becomes one of the more
valuable outputs of the whole system, because these conflicts existed before you built it and
nobody was looking for them.

**5. How does a user verify a blended answer?**

Only if you attribute per source, so each claim carries its provenance: the policy clause with
document version and section, the figure with the query that produced it and the row count, and
the timestamp of the data. Then show the reasoning step that combined them. Without this the
answer is a single unverifiable assertion, and the fact that two sources went into it makes it
*harder* to check, not easier — the user cannot tell which half to doubt.

**6. Which source do you cache, and for how long?**

Cache the **document** side reasonably freely, keyed by question, corpus version and permission
set — policy text changes rarely and the retrieval is expensive. Cache the **structured** side
barely at all, and only with an explicit freshness contract the user can see: "as of 14:05".
Aggregates over closed periods — last quarter's revenue — are safely cacheable because the
underlying data cannot change. Live operational state is not. Getting this wrong reintroduces
exactly the staleness that ruled out embedding the rows.

**7. A question is genuinely ambiguous about which source it needs.**

Route to **both** and let synthesis discard what is irrelevant — the cost of an unnecessary
retrieval is far below the cost of a missed source. Where the ambiguity is about *meaning* rather
than source — "how many customers are at risk" could mean the policy definition or the flag in the
CRM — ask. And log ambiguous questions as a category: a recurring ambiguity usually means a
missing metric definition, which is a fix in the semantic layer rather than in the router.

**8. How do you evaluate this end to end?**

In three separate parts, because an aggregate number hides which one is broken. **Router
accuracy** against a labelled set of questions with known correct sources — the highest-leverage
metric. **Per-path retrieval quality**, evaluated as scenarios 2 and 21 would each be evaluated
independently. **Synthesis correctness** on a set of two-source questions, checking that both
facts appear, that attribution is correct, and — the case people omit — that a planted conflict is
surfaced rather than resolved. That last test is the one that catches the model quietly picking a
side.

**9. What does the answer look like when one source fails?**

Explicitly partial, never silently so. Database down: answer the policy question and state that
live order data is unavailable, without guessing at it. Document store down: give the figures and
say the policy text could not be retrieved, so the rule is not being applied. Both down: refuse
and say which. A two-source system fails partially far more often than it fails completely, so
partial failure is the normal case and deserves a designed answer — the dangerous version is an
answer built on half the evidence that reads as though it had all of it.

---

## One-line summary

Never embed the database — a vector search cannot aggregate and cannot be fresh — so the design is
a router or planner over two genuine retrieval paths, vector RAG for documents and guarded
text-to-SQL for structured, composed with per-source attribution; routing accuracy dominates
end-to-end quality because a misrouted question has no partial credit, and when the sources
disagree the model surfaces both rather than adjudicating.

---

## The trap answer to avoid

Embedding database rows so everything is "one RAG pipeline". It is architecturally tidy and it
cannot answer the questions people ask a database: aggregation is structurally impossible for a
similarity search, and any index is stale the moment it is built. The second trap is treating the
router as a detail and spending the effort on retrieval quality, when the arithmetic says perfect
routing with weak retrieval beats the reverse. The third is letting the model resolve a
disagreement between a policy and a system of record — a conflict detected is a bug found, and a
conflict resolved by a model is a bug buried.
