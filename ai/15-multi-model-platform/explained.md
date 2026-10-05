# A multi-model LLM platform — explained

> Topic 11 covers this from the concept side; scenario 2 covers building the gateway itself.
> This is the **multi-model** problem: choosing between models, and surviving one of them
> changing underneath you.

---

## 1. Say this before anything else: name the failure, not the component

The trap in this scenario is specific and nearly everyone walks into it — **listing components
without naming the failure each one prevents.** A gateway, a router, a cache and a circuit
breaker is a diagram. Saying what each one *stops* is a design.

It also finds bugs. `solution.py §1` takes a plausible five-component list and maps each item to
the failures it actually covers:

| Component | Prevents |
|---|---|
| gateway | unattributable cost |
| router | provider outage |
| cache | tail latency |
| circuit breaker | provider outage, retry amplification |
| retries + backoff | *(nothing named)* |

Three failure modes have **nothing against them**: daily quota exhaustion, capability mismatch,
and model deprecation. Writing the table is what exposes that; a diagram never does.

So the answer is a table, delivered as a table:

| Component | Prevents |
|---|---|
| Unified gateway | call sites coupling to provider SDKs |
| **Capability registry** | routing a task to a model that cannot do it, and silent deprecation |
| Router with a cascade | paying frontier prices for easy work |
| Per-provider circuit breaker | one sick provider consuming every worker |
| **Shared token bucket** | N instances each admitting the full rate |
| Fallback chain, **per feature** | a summariser and a legal answer degrading identically |
| **Validate on receipt** | trusting a model to have honoured its own contract |
| Usage ledger | unattributable cost |
| Per-model eval and version pin | a provider changing the model under you |

The bolded rows are the ones the naive list omitted.

---

## 2. What breaks first: the daily quota

Not capacity. Not the per-minute limit. `solution.py §2`:

- Per-minute limit 6,000, observed peak 4,195 — **30% headroom, green all day.**
- Daily limit 2,000,000. The day wants **3,053,013 — 1.5x.**
- The cap blows at **15:36**, with 504 minutes of the day left.

Every per-minute dashboard is healthy the entire time. The failure is a quota nobody is
watching, and it arrives at roughly the same time every afternoon — which is why "what are the
rate limits" needs **both numbers**, and why the daily one is the one to ask for twice.

The order after that: **tail latency → cost → outage → deprecation.**

---

## 3. A cascade is a bet on the escalation rate

Route cheap first, escalate when the cheap model fails or is unsure. `solution.py §3`, over a
million calls:

| Escalate to mid | Then to frontier | Cascade | Frontier-only | Saving |
|---|---|---|---|---|
| 10% | 10% | £420 | £10,000 | **96%** |
| 30% | 20% | £1,160 | £10,000 | 88% |
| 60% | 40% | £3,320 | £10,000 | 67% |
| 90% | 80% | £8,480 | £10,000 | **15%** |

At a 10% escalation rate the cascade removes almost the whole bill. At 90% it removes almost
nothing *and* you have added an extra call to every single request, so latency is worse for no
saving.

Two consequences: **measure the escalation rate before designing around it**, and **alert on
it**, because a rising escalation rate is a silent cost leak that looks like nothing else.

---

## 4. A fallback that cannot do the task is worse than an outage

`solution.py §4`. Fallback chain ordered by cost — `legacy-13b → mid-70b → frontier` — and four
features:

| Feature | Blind fallback | Can it? | Registry picks |
|---|---|---|---|
| tool-calling agent | legacy-13b | **NO** | mid-70b |
| long-doc summary | legacy-13b | **NO** | frontier |
| field extraction | legacy-13b | **NO** | mid-70b |
| short classification | legacy-13b | yes | legacy-13b |

Three of four break, and the call returns **200**. The agent gets no tool call. The long document
is truncated to the model's context. The JSON comes back as prose.

An outage wearing a success code is worse than an outage, because **nothing pages**. Error rate
is flat, latency is fine, and the feature is broken.

The fix is a **capability registry** — tools, context length, structured output, streaming,
per model — consulted at routing time rather than a chain of names ordered by price.

---

## 5. Degradation is per feature

`solution.py §5`:

| Feature | Quality floor | Ladder |
|---|---|---|
| dashboard summariser | a cheaper model is fine | mid-70b → fast-8b → cached → hide |
| **legal answer** | must not degrade | frontier → **REFUSE** |
| support draft | a human reviews it anyway | mid-70b → fast-8b → template |

One global fallback chain cannot serve these three. The summariser can degrade all the way to
hidden and nobody is harmed. The legal answer must **refuse** rather than answer from a weaker
model, because a confident wrong answer there is the expensive outcome.

"Refuse" is a legitimate rung, and the platform's job is to make the ladder **expressible per
feature** rather than to choose it centrally.

---

## 6. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Daily rate limits** | Green per-minute dashboards, and the day ends at 15:36. |
| 2 | **Tail latency** | One slow provider, and retries amplify it. |
| 3 | **Cost** | Escalation rate drifts and nobody is watching it. |
| 4 | **Provider outage** | Survivable, if the fallback is capability-checked. |
| 5 | **Deprecation** | 90 days notice, and it multiplies the eval surface. |

---

## The follow-ups, answered

**1. Name each component and the failure it prevents.**

That is the table in section 1, and giving it as a table rather than a list is the answer. The
five failure modes people miss are daily quota exhaustion, capability mismatch, model
deprecation, unattributable cost, and retry amplification — and each maps to something specific:
a shared token bucket, a capability registry, per-model eval with a version pin, a usage ledger,
and retries restricted to transport errors only. If a component has no failure next to it, it is
decoration.

**2. What breaks first at scale, and why not capacity?**

Daily rate limits. Capacity is the thing you can buy and the thing your dashboards watch;
provider quotas are neither. In the simulation the per-minute limit has 30% headroom at peak
while the daily cap blows at 15:36 — every graph green, and the afternoon gone. It is also
seasonal in a way capacity is not: the limit does not move, but your traffic grows, so the
breach time creeps earlier week by week until someone notices it is now 14:00.

**3. Your cheap model handles 70%. When does a cascade stop saving money?**

When the escalation rate rises far enough that you are paying for two calls on most requests. At
10% escalation the cascade removes 96% of the bill; at 90% it removes 15% and every request now
has an extra round trip. The break-even depends on the price ratio, so compute it rather than
assuming — and then instrument the escalation rate as a first-class metric, because it drifts.
A prompt change, a corpus change, or a harder traffic mix all raise it silently, and the bill is
where you find out.

**4. You fall back to another provider and the feature silently breaks. How?**

Because the fallback was chosen by price or health, not by capability. The replacement has no
function calling, so the agent gets prose instead of a tool call. Or a 4k context, so the
document is truncated and the summary is confidently about the first page. Or no structured
output, so the JSON parse fails downstream — if you are lucky, and if you are not, it parses into
something wrong. Every one of these returns 200 with a plausible-looking body. The fix is the
capability registry, checked at routing time; the detection is validating on receipt.

**5. Two features share a provider — a summariser and a legal answer. Design the degradation.**

Separately, and that is the point. The summariser gets a long ladder: mid model, cheap model,
last cached answer, and finally hide the panel — every rung is acceptable and the last one is
invisible. The legal answer gets two rungs: the frontier model, or **refuse**. It must not fall
back to a weaker model, because the failure mode there is not a worse answer, it is a confident
wrong answer on something that carries liability. Expressing that per feature is a platform
capability; choosing it is a product decision, and the platform should not make it.

**6. Ten instances, one provider rate limit.**

A shared token bucket in Redis, not a local limiter. Ten instances each configured with the full
provider rate will admit ten times it, and the provider — not you — enforces the difference, as
429s at the worst possible moment. Details that matter: the bucket must be atomic (a Lua script
or `INCR` with expiry, not read-then-write), it should track the **daily** budget as well as the
per-second one, and it needs a local fallback for when Redis is unavailable that fails *closed*
to a conservative per-instance share rather than open.

**7. A provider deprecates your primary model with 90 days notice.**

It is a migration project, and the honest framing is that it multiplies your eval surface for
its duration. Pin the current version so nothing moves under you meanwhile. Stand the candidate
up behind the registry and run the **per-feature** eval suite against it, because a model that is
better on average is routinely worse on one feature. Shadow real traffic and compare. Then cut
over per feature, cheapest-risk first, keeping the old model available until the deadline. The
step people skip is re-running the *cost* model: a newer model at a different price with
different token efficiency can change your cascade economics enough to invalidate the routing
design.

**8. How do you know a model changed underneath you?**

Pin the version and alert on the provider's reported version string changing — that catches the
honest case. For the dishonest case, where the version is unchanged and the behaviour is not, run
a small **canary eval on a schedule**, not only at deploy: the same fifty prompts, daily, with
the scores tracked. A step change with no deploy of yours is the signal. Cheap, and it is the
only thing that catches a silent update, which does happen.

**9. What do you validate on the way back, and why is that not paranoia?**

Schema, before anything downstream sees it. Required fields present, types right, enums within
range, no extra keys, and any invariant you can check cheaply. It is not paranoia because
structured output is a *request*, not a guarantee — and the failure is much more likely on a
fallback path, which is exactly when you are least able to notice. Validation on receipt is also
how you detect capability mismatch at runtime rather than in a support ticket: a spike in schema
failures attributed to one model is the registry telling you it is out of date.

---

## One-line summary

The trap is listing components without naming the failure each prevents, so deliver a table
mapping the two — which is also what exposes the three failure modes a plausible list omits;
then note that daily quotas break before per-minute limits and before capacity, that a cascade
is a bet on an escalation rate you must measure and alert on, that a fallback chosen by price
rather than capability returns 200 while breaking the feature, and that degradation is a
per-feature ladder in which "refuse" is a legitimate rung.

---

## The trap answer to avoid

A component list. "Gateway, router, cache, circuit breaker, retries" sounds like a design and
covers three of the seven failure modes that matter. The mapping is the design, and writing it
down is what finds the gaps — daily quota, capability mismatch and deprecation are the three that
a plausible list reliably misses. The second trap is a single global fallback chain, which
quietly decides that a legal answer and a dashboard summary should degrade the same way.
