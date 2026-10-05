# Internal AI platform — explained

---

## 1. The technical design is the easy half

Ten teams × (gateway + cache + eval + secrets + observability) = **ten implementations, nine of
them wrong**. `solution.py §1`: 530 engineer-weeks duplicated against 106 to build it once
properly.

But the saving is not the argument. The argument is this: of the ten eval harnesses in that
sum, **nine would never have been built**. Teams under delivery pressure skip the gate, not the
feature. The platform's value is the nine teams that get a quality gate they would otherwise have
gone without.

---

## 2. Say this before anything else: adoption is the whole problem

**A platform teams bypass is worse than no platform**, because you now have a false sense of
central control *and* no data — the shadow usage is invisible precisely because you built the
thing that was supposed to make it visible.

`solution.py §2` puts numbers on it. A team can DIY a working integration in 8 weeks:

| Platform onboarding | Mandate? | Adoption | Outcome |
|---|---|---|---|
| 12 weeks | no | 0% | 10 bypassed |
| 12 weeks | yes | 70% | 3 bypassed, 7 complied |
| **2 weeks** | **no** | **100%** | 10 adopted, because it is faster |
| 2 weeks | yes | 100% | the mandate is redundant |

A mandate on a slower road buys partial, resentful compliance and a steady stream of exception
requests. **A faster road needs no mandate.** Make the paved road genuinely quicker than DIY and
the policy question stops being interesting.

Concretely, "faster" means: a working, traced, cached, budgeted call in an afternoon, from an SDK
with sane defaults, against a model that is already approved.

---

## 3. The layers, each named by the failure it prevents

**A gateway every team uses** — *prevents:* ten key-management schemes and an unattributable
invoice. Mandatory in the sense that nothing else works without it, not in the sense of a policy
document.

**Golden-path SDK with sane defaults** — timeouts, retries with jitter, streaming, tracing built
in — *prevents:* every team independently relearning exponential backoff.

**Central secrets, per-team keys** — *prevents:* a leaked key with no blast-radius bound.
`solution.py §4`: one shared key means rotating for everyone; per-team keys mean revoking one.

**Per-team cost attribution and budgets** — *prevents:* nobody owning the invoice.

**Shared eval harness as a service** — *prevents:* nine teams with no gate. The highest-value
component and the one teams would never build for themselves.

**A model registry with approved models** — *prevents:* a team shipping on something deprecated
or unvetted.

**Shared PII and guardrail middleware** — *prevents:* ten different interpretations of the same
compliance requirement.

**A paved road, not a wall** — an escape hatch with a review — *prevents:* teams routing around
you silently.

---

## 4. Cost attribution changes the conversation

`solution.py §3`. Today finance sees one number: **£49,640**. With per-team attribution, two
teams are **61% of the bill**.

That is the whole difference. Without attribution the spend is unexplainable and every team is
equally innocent, so the response is a blanket cost-cutting mandate that annoys ten teams and
targets none. With it, the conversation is with two people and it is specific.

Attribution is also the prerequisite for budgets, and budgets are what turn "please be careful"
into a breaker that degrades a team's feature rather than a surprise at month end.

---

## 5. The escape hatch

Three options, and only one works:

- **No escape hatch.** Teams route around you silently. You lose the visibility you built the
  platform to obtain.
- **Escape hatch with no review.** It becomes the main road within two quarters.
- **Escape hatch with a review and a time limit.** Legitimate cases proceed, and — the useful
  part — **every exception request is a feature request with evidence attached.** The review
  queue is your roadmap.

---

## 6. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Adoption** | A bypassed platform is worse than none. |
| 2 | **The platform team's own velocity** | Ten customers, each wanting one thing. |
| 3 | **Cost ownership** | Attribution without budgets changes nothing. |
| 4 | **Model registry drift** | Approved list goes stale, teams route around it. |
| 5 | **Escape-hatch creep** | No review, and it becomes the default. |

---

## The follow-ups, answered

**1. Minimum viable platform, and what would you not build first?**

Build: the **gateway** with per-team keys and cost attribution, and a **thin SDK** with timeouts,
retries and tracing. That is the smallest thing that makes the paved road faster than DIY on day
one, and everything else can be added behind it without teams changing code. Do **not** build
first: a fancy eval UI, a prompt-management product, or a model-routing optimiser. Those are what
platform teams enjoy building and they do not move adoption. Ship the boring middle and earn the
right to the rest.

**2. A team says the gateway is too slow and wants direct access.**

Measure it, because they are usually right about the symptom and wrong about the cause. If the
gateway genuinely adds meaningful latency, that is a bug on my side and I fix it — a well-built
gateway is single-digit milliseconds. If it is the model or the retrieval, direct access will not
help and I show them the trace that proves it. If they need something the gateway does not
support — streaming a modality we do not handle, say — then that is a legitimate escape-hatch
case, time-boxed, and it goes on the roadmap. What I would not do is refuse on policy grounds
without measuring, because that is how a platform team loses credibility permanently.

**3. How do you make the paved road faster than DIY?**

Remove decisions, not just code. A team using the platform should not have to choose a model,
negotiate a provider account, design a retry policy, work out how to trace an LLM call, build an
eval harness, or get a security review — all of that arrives pre-decided and pre-approved. Ship a
template repository that goes from nothing to a traced, cached, budgeted call in an afternoon.
Then measure **time-to-first-successful-call** as the platform's primary metric, because it is the
number that determines adoption and it is the one platform teams never track.

**4. Who owns cost, and how do you make that real?**

The product team owns it, and it is only real when three things exist: a per-team dashboard they
actually see, a budget they agreed to, and a **breaker that degrades their feature** when they
cross it rather than a surprise at month end. Attribution without a budget is a report nobody
reads. A budget without a breaker is a suggestion. The breaker should degrade gracefully — a
cheaper model, a smaller context, a cache-only mode — so crossing a budget is a quality event
rather than an outage, and the team finds out on the day.

**5. A team ships on an unapproved model.**

First, understand why, because it is almost always a gap rather than defiance — the model they
needed was not on the list, and getting it added looked slower than shipping. So the fix is
usually to the **approval process**, not the team. Make adding a model a days-long path with a
clear checklist, publish the criteria, and keep the list genuinely current, because an
out-of-date approved list is the strongest argument for ignoring it. Then make the registry
enforceable at the gateway rather than in a document, so the check is automatic and the
conversation happens before launch instead of after.

**6. How do you migrate ten existing implementations?**

Not all at once, and never as a mandated freeze. Make the gateway API-compatible with what teams
already use — an OpenAI-compatible surface means the migration is a base-URL change and a key
swap for most of them. Then take the two teams who are in most pain and do the migration **for
them**, as the platform team, and use those as the reference. Publish the time saved. The other
eight will come for the cost dashboard and the eval harness once they can see them working
somewhere real. Migration by demonstration is slower to start and much faster to finish than
migration by policy.

**7. What is the escape hatch, and what stops it becoming the main road?**

A documented process: request direct access, state the capability gap, get a time-boxed
exemption with an expiry date. What stops it becoming the main road is the expiry plus the fact
that exempt teams lose the things they actually want — cost attribution, the shared eval harness,
tracing. The hatch should be genuinely available and mildly inconvenient. And the review queue is
the most valuable input the platform team gets: every exception is a feature request with
evidence, and a capability requested three times should simply be built.

**8. How do you know the platform is working?**

**Adoption** as the headline: what fraction of production LLM traffic goes through the gateway,
including an estimate of what does not. Then **time-to-first-successful-call** for a new team,
which predicts adoption before it happens. Then the outcome measures: how many teams have an eval
gate at all — that is the number I would put in front of leadership, because it is the platform's
actual product — cost per team trending, and incidents attributable to a shared component, which
should be low and is the price of centralising. Not: lines of code in the SDK, or number of
features shipped by the platform team.

**9. What is the failure mode of a platform team specifically?**

Building for the platform team rather than the product teams — an elegant abstraction nobody
asked for, while the thing everyone needs sits behind it in the backlog. It is seductive because
platform work has no user in the room to object. The symptom is a roadmap full of internal
refactors and a support channel full of the same three questions. The correction is to make
adoption and time-to-first-call the team's primary metrics, and to spend real time embedded with
product teams, since nothing else surfaces the friction that actually costs you adoption.

---

## One-line summary

Ten teams building the same five components produces nine broken eval harnesses, so the platform
is a mandatory gateway with per-team keys and cost attribution, a golden-path SDK that removes
decisions rather than just code, and a shared eval harness — but the whole problem is adoption,
because a platform teams bypass is worse than none, a mandate on a slower road buys resentful
partial compliance, and a road that is genuinely faster than DIY does not need a mandate at all.

---

## The trap answer to avoid

Designing the components and stopping there. Everyone can list a gateway, a cache and an eval
harness; the interesting question is why ten teams would use them, and the honest answer is only
"because it is faster than not". The related trap is mandating adoption without a speed
advantage, which produces shadow usage — strictly worse than no platform, because you have lost
the visibility you built it to obtain while believing you have gained it.
