# Cost attribution — explained

**Your code:** `digital-twin/server/usageRoutes.ts` — `:6` imports `getRateCard`, `:37-38`
returns it with the report, commented *"so the dashboard can show HOW each cost was
computed."* Plus `usage-finalize.test.ts`, `llm-usage.test.ts`, `elevenlabs-usage.test.ts`,
`vapi-webhook.test.ts`.

---

## Why this is the strongest anti-POC signal you have

Nobody builds per-call cost reconciliation for a demo. Multi-tenancy might be
future-proofing; an audit log might be compliance theatre. **A cost ledger that reconciles
against provider billing only exists because someone is paying real money.** Lead with that
when asked whether the system is production.

---

## The hard part: truth arrives late, out of band

A single voice call touches five paid providers, and their costs arrive on **different
timelines**:

| Source | When you learn the cost |
|---|---|
| LLM tokens | **during** the call — captured from the streaming response |
| TTS characters | at synthesis time |
| STT minutes | at finalisation |
| Avatar minutes | at session end |
| Voice platform | **after** the call, by **webhook** — the authoritative number |

So the ledger must accept **late-arriving truth without double-counting**, and be queryable
before the truth arrives. That's the actual engineering problem — not multiplication.

---

## The four mechanisms, and the reasoning behind each

### 1 · Idempotency keyed on call id
Webhook retries are **normal, not exceptional** — every provider retries on a non-2xx or a
timeout. A handler without an idempotency key is a double-counting bug waiting to happen.
Keying on call id makes redelivery a no-op.

*And the detail:* the call id is **regex-validated before it reaches a SQL `LIKE` dedup** —
because an id that flows into a `LIKE` pattern is an injection surface, and `%` in an
unvalidated id would match unrelated rows.

### 2 · Client-pull fallback with a post-fetch re-check
If the webhook never arrives, you pull the number directly. But that races the webhook — both
could land at once. So after fetching you **re-check** whether the webhook has since arrived,
and reconcile. Belt and braces, because a missing webhook otherwise means a silently
un-costed call.

### 3 · Length-guarded constant-time secret compare
A naive `===` on a secret **short-circuits on the first differing byte**, so response time
leaks how many leading bytes were correct — enough to guess a secret byte-by-byte. Constant
time removes that. The **length guard** matters because some constant-time implementations
throw or leak on mismatched lengths.

### 4 · Fails closed in production if the secret is unset
If the webhook secret isn't configured, the endpoint **refuses (503)** rather than accepting
unverified calls. The alternative — "no secret configured, so skip verification" — is how a
misconfiguration becomes an open endpoint. **Same principle as the tenant resolver: when the
answer is unknown, deny.**

That's the through-line worth naming out loud: *fail closed appears three times in this
codebase — tenant scope, webhook verification, and eval gates. It's a habit, not a one-off.*

---

## One rate card — why it's a design decision

`getRateCard()` is the single source of pricing, and the dashboard renders costs **from that
same function**.

**The failure it prevents:** two copies of pricing always diverge. If the dashboard has its
own rate table, a provider price change updates one and not the other — and you show customers
numbers you aren't charging. One rate card makes that class of bug **impossible**, not
unlikely.

*"The displayed rate is the billed rate"* is the one-line version.

---

## The follow-ups, answered

**"How would you turn this into control?"**
Per-tenant budgets with a circuit breaker. When a tenant crosses its cap, **degrade** — text
instead of voice, or a cheaper model — rather than cutting them off, because a hard cutoff on
a live call is a worse experience than a downgrade. **Metering is the prerequisite;
enforcement is the layer I haven't built.** Say that plainly.

**"Why not just read the provider's billing API monthly?"**
Because it's aggregate and late. You can't attribute a monthly invoice to a tenant, a persona
or a call — so you can't bill through, can't cap, and can't find the runaway. Per-call
attribution is the only granularity that supports any of those.

**"What's the weakness?"**
Two: it's **observability, not enforcement** — I can tell you what a call cost, not stop a
runaway tenant. And the rate card is **hand-maintained**, so a provider price change needs a
manual edit and can silently drift from actual billing until someone notices.

---

## One-line summary
> "Five providers, costs arriving on different timelines with the authoritative number coming
> late by webhook — so the ledger is idempotent by call id, has a pull fallback with a
> post-fetch re-check, verifies the webhook in constant time, fails closed if the secret is
> missing, and prices everything from one rate card the dashboard also renders."

## The trap answer to avoid
Describing it as "we log token usage." Token counting is the easy part. The engineering is
**reconciling late, out-of-band, retried truth from five sources without double-counting.**
