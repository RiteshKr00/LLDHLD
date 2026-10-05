# Text-to-SQL — explained

---

## 1. The numbers force the design

300 tables × 40 columns = **12,000 columns**. At roughly 14 tokens each — name, type, a short
description — that is **168,000 tokens** against a 128k window. `solution.py §1`.

The schema does not fit. That single fact settles the architecture: this is a **RAG problem
over schema** before it is a prompting problem. Retrieve the handful of relevant tables, and
the same information costs 3,360 tokens.

---

## 2. Say this before anything else: the dangerous failure is not an error

An error is recoverable, because somebody sees it. The failure that matters here is the query
that **runs, returns a plausible number, and is wrong** — because that number goes into a board
deck and nobody can tell.

`solution.py §2` demonstrates the canonical version, a fan-out join:

```sql
SELECT SUM(o.amount) FROM orders o JOIN line_items li ON li.order_id = o.id
```

The order row is duplicated once per line item, so its amount is counted three times for a
three-item order. Result: **1,075.00 against a true 825.00, inflated 30%**. No error, no
warning, no anomaly anywhere.

This is why the semantic layer and showing the SQL matter more than model quality. A better
model writes this bug less often; it does not stop writing it.

---

## 3. The layers, each named by the failure it prevents

**Schema retrieval** — *prevents:* context overflow, and the model inventing columns because it
never saw the real ones. Embed table and column descriptions; retrieve, then generate.

**A curated semantic layer / metric store** — *prevents:* the model inventing its own definition
of "revenue". The single highest-value component, and the one most candidates never mention.

**Few-shot exemplars of verified query patterns** — *prevents:* structurally wrong joins. Show
it the correct shape for "aggregate a child table then join" and it stops improvising one.

**SQL validation before execution** — *prevents:* both hallucinated schema and catastrophic
writes. Parse it, assert read-only, assert every table and column exists, reject DDL and
stacked statements.

**Cost guard** — *prevents:* one question costing more than the feature saves. `EXPLAIN` first,
refuse above a byte threshold, inject a `LIMIT`.

**Row-level security via the user's credentials** — *prevents:* the assistant becoming a
privilege-escalation path with a friendly interface.

**Show the SQL and the row count** — *prevents:* unverifiable numbers. It also changes the
product: the user can sanity-check the join even if they cannot write one.

**Result caching keyed on (question embedding, schema version)** — *prevents:* paying twice, and
prevents serving pre-migration answers after a schema change.

---

## 4. The semantic layer, concretely

Ask three teams for revenue and you get three defensible numbers. `solution.py §3`, on the same
four orders:

| Definition | Value | What it means |
|---|---|---|
| Sales | 825.00 | gross order value |
| Analytics | 775.00 | net of refunds |
| Finance | 700.00 | net of refunds, shipped orders only |

All three are correct. Without a metric store the model picks one implicitly per query, which
means **the same question returns different numbers on different days** — and that is worse
than being consistently wrong, because it destroys trust in the whole feature.

The metric store also owns the joins, which is what actually kills the fan-out bug: the model
selects a metric rather than writing the SQL that computes it.

---

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Silently wrong joins** | Runs, plausible, wrong. Worse than an error. |
| 2 | **Metric ambiguity** | Same question, different number, different day. |
| 3 | **Cost** | A curious user with a text box is a denial-of-wallet vector. |
| 4 | **Trust, once** | One wrong number in a board deck ends the feature. |
| 5 | **Schema drift** | Retrieval and cache both go stale; nobody notices until answers do. |

---

## The follow-ups, answered

**1. 12,000 columns do not fit in a prompt.**

Retrieve them. Embed each table and column with its description and any known synonyms, and at
query time pull the top few tables by similarity to the question. Six tables is 3,360 tokens
against 168,000 for everything. Two refinements that matter: include foreign-key relationships
for the retrieved tables, or the model cannot join them correctly; and retrieve **conservatively
wide**, because a missing table forces the model to invent a column, which is a much worse
failure than a slightly longer prompt.

**2. Two teams define "revenue" differently. Whose does the model use?**

Neither — that is the wrong question, and saying so is the point. The model should not be
choosing a definition at all. A semantic layer exposes named, owned metrics: `revenue_gross`,
`revenue_net`, `revenue_recognised`, each with a documented definition and a maintainer. The
model's job is to pick the right **metric**, not to write the arithmetic. When the question is
ambiguous the correct behaviour is to ask which one, and to show the definition alongside the
answer. Without this you get the same question returning different numbers on different days.

**3. The SQL runs, returns a plausible number, and it is wrong.**

The main defence is structural: the semantic layer owns the joins, so the model never writes the
fan-out. On top of that, four things catch or expose it. Verified exemplar joins for the common
shapes. **Showing the SQL and the row count** — a user who knows their data spots an order count
of 1,075 against an expected 825. Sanity assertions on known invariants, such as an aggregate
never exceeding the sum of its parts. And a regression suite of question-to-expected-number
pairs, run in CI, which is the only thing that catches this before a user does.

**4. A user asks something that would scan 4TB.**

`EXPLAIN` before execute. `solution.py §5`: an unfiltered scan reports 4TB and roughly £20; the
same query with a partition filter reports 8GB and four pence. Above a byte threshold, refuse
and say why — "that would scan 4TB, please add a date range" is a good product experience, not a
failure. Also inject a `LIMIT` by default, cap per-user daily spend, and route heavy queries to
a separate reservation so one curious user cannot slow the warehouse for everyone.

**5. Someone asks "delete the test rows".**

Four independent layers, and the answer should name all four because any single one can be
bypassed. The connection is **read-only at the database level** — that is the one that actually
matters, because it holds even if everything above it fails. The validator rejects any statement
matching DDL or DML. The parser rejects stacked statements, so `SELECT 1; DROP TABLE orders`
cannot sneak past a prefix check. And the credentials have no write grant to begin with. Note
the ordering: I would not rely on the validator, because it is the layer written by me and
tested by me. The read-only connection is enforced by the database.

**6. Whose credentials does the query run under?**

The **user's**, always — never a service account. If the assistant queries under a privileged
account, then any row-level security you have is bypassed for anyone who can type a question,
and you have built a privilege-escalation path with a friendly interface. This is
non-negotiable and it has a design consequence people miss: the semantic layer and the cache
must both be **permission-aware**, or a cached result computed for an admin gets served to
someone who should not see it.

**7. How do you cache this safely?**

Key on the question embedding, the resolved metric, the **schema version**, and the user's
permission set. Dropping any of those four is a distinct bug: no schema version means serving
pre-migration answers indefinitely; no permission set means cross-user leakage; no resolved
metric means two different questions colliding. Add a TTL short enough to respect the warehouse's
own freshness, and invalidate on schema change rather than waiting for the TTL.

**8. What do you show the user alongside the number?**

The **SQL**, the **row count**, the **metric definition** used, and the **freshness** of the
underlying tables. All four are load-bearing. The SQL lets someone who knows the data spot a bad
join. The row count catches fan-out. The definition prevents an argument two weeks later about
whose revenue this was. The freshness stops someone quoting yesterday's number in today's
meeting. An unverifiable number is not an answer to a finance-adjacent question, however
confident the prose around it.

**9. The model invents a column that does not exist.**

Caught at validation, before execution — `solution.py §4` rejects `orders.revenue` as an unknown
column. Two subtleties worth mentioning. The validator must **resolve aliases**, or `o.revenue`
passes because `o` is a known alias; that is a real bug I hit writing this. And in production
you parse the SQL into an AST rather than regexing it, because regex validation of SQL is
defeatable and a parser is not. But the deeper fix is upstream: the model invents columns mostly
when schema retrieval failed to give it the right table, so a rise in this error is a **retrieval
quality alert**, not just a validation event.

---

## One-line summary

The schema does not fit in a prompt, so this is retrieval over schema plus a semantic layer that
owns metric definitions and joins, with the model's output treated as an untrusted string —
parsed, validated read-only, cost-checked and run under the user's own credentials — and the SQL
and row count shown, because the failure that matters is the query that runs and returns a
plausible wrong number.

---

## The trap answer to avoid

Treating it as prompt engineering — "I'd put the schema in the system prompt and give it good
examples". The schema does not fit, and the failure mode is not a bad prompt. The second trap is
letting the model's SQL run under a **privileged service account**, which turns a reporting
feature into a privilege-escalation path. And the quiet one: never asking whether canonical
metric definitions exist, which is the highest-value question on the list.
