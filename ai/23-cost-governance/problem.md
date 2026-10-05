# Design scenario 9: cost governance across 500 tenants

## The prompt

> "We're spending more on models than we planned, and nobody can tell me who's spending it.
> Build cost governance for the platform. 500 tenants."

*Two halves, and they are different systems. "Who's spending it" is attribution. "More than we
planned" is enforcement. Most candidates build the first, draw a dashboard, and stop — which
is why the interviewer will ask what happens at 3am on a Saturday.*

---

## Clarifying questions to ask FIRST

1. **Do you bill this through to tenants, or is it internal showback?** *(Bill-through makes
   the ledger a financial record — exact, auditable, disputable, no dropped rows. Showback lets
   you trade completeness for availability.)*
2. **Hard ceiling or soft alert?** *(A hard ceiling has to live in the request path, which
   forces you to estimate a call's cost **before** you make it. A soft alert is a batch job
   over a rollup and costs you nothing architecturally.)*
3. **Per tenant, per feature, or both?** *(A tenant budget can't say which feature ate it; a
   feature budget can't stop one tenant. You need the cross-product — and the cross-product is
   where the alerting problem comes from.)*
4. **What is the contractual consequence of refusing a tenant mid-request?** *(Decides whether
   the breaker degrades or refuses, and it differs per feature: cutting a live voice call is
   not the same as queueing a nightly report.)*
5. **How much excess spend per incident are you willing to eat?** *(This is the number that
   sets your detection window. Everything downstream is arithmetic from it.)*
6. **Any self-hosted models?** *(Self-hosted cost is $/GPU-hour, not $/token. Attribution
   becomes an amortisation, and idle capacity has to be charged to somebody.)*

---

## The follow-up bank

1. A tenant hits 100% of budget halfway through generating a response. What happens to *that*
   request?
2. You can't know output tokens before the call. So how do you enforce a hard cap at all?
3. The budget store is down and you can't read spend state. Fail open or fail closed? Defend it.
4. One tenant's spend triples overnight. Walk me through the first ten minutes.
5. 500 tenants × 4 features is 2,000 thresholds. How do you not drown in alerts?
6. Your dashboard says $71k this month; the provider invoice says $78k. Which one is wrong, and
   how do you find out?
7. A prompt change added 2,000 tokens to every call and ran for a week before anyone noticed.
   Prevent it.
8. Where does the cost of a cache hit get attributed? And of a fallback to a pricier provider?
9. Product wants a free tier. What changes in this design?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
