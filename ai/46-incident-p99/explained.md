# The p99 blowout — explained

> Incident genre. The interviewer wants to hear one observation before anything else, and it
> settles the shape of the whole investigation.

---

## 1. Say this first: p50 unchanged means it is not capacity

A capacity problem queues **everything**, so p50 rises with p99. Ours did not move.
`solution.py §1`:

| Scenario | p50 | p95 | p99 |
|---|---|---|---|
| baseline | 1.42 | 3.52 | 4.98 |
| capacity problem | **3.40** | 8.45 | 11.94 |
| a 2% subset stalls | **1.43** | 3.95 | **25.00** |

So: **adding instances will not help.** Something affects a *subset* of requests, and the job is
to find the subset. That single sentence is what is being tested — it eliminates the most common
reflex and points the investigation at slicing rather than scaling.

---

## 2. Triage order

1. **Slice before theorising.** One provider, one model, one tenant, one endpoint? A tail problem
   is by definition a subset.
2. **Timeouts.** Is something now waiting longer before failing? A raised or removed timeout turns
   a fast failure into a slow one.
3. **Retries.** Did the count or backoff change?
4. **A new synchronous call** in the request path — an added validation, a logging write, a
   metrics flush.
5. **Retrieval parameters** — chunk count, `numCandidates`, `ef_search`.
6. **Prompt length** — longer prompts mean longer time-to-first-token, and it hits the tail
   hardest.
7. **Cold starts and connection-pool exhaustion** — a pool sized for the old concurrency.
8. **Event-loop blocking** — a blocking call inside an `async def`.

Note that **three of the five most likely causes are config, not code**. The diff is often not
where it is.

---

## 3. 25 seconds is a suspiciously round number

`solution.py §2`:

| Config | Worst case |
|---|---|
| before: 2 attempts, 3s timeout | 7.0s |
| after: 3 attempts, 8s timeout | **25.0s** |

Both numbers come from configuration, not code. A tail that **clusters** at a round value is
arithmetic rather than contention: multiply attempts by timeout, add the backoff, and see whether
it lands on your p99. If it does, you have found it in two minutes.

A tail that is a **smooth stretch** rather than a cluster is a different family — contention, a
longer prompt, a bigger retrieval — and the distribution shape tells you which before you look at
anything else.

---

## 4. A blocking call in an async handler

`solution.py §3`. 32 req/s, 0.9s of awaited provider time per request, and someone adds 30ms of
CPU work inside the handler:

| Handler | p50 | p95 | p99 |
|---|---|---|---|
| pure async | 0.90 | 0.90 | 0.90 |
| + 30ms of CPU | 1.19 | 2.53 | **2.83** |

p50 moves 33%. p99 moves **215%**.

The reason is that 30ms is not 30ms of added latency — it is 30ms during which **nothing else on
that worker runs**. Awaited I/O overlaps freely; CPU does not. So a small blocking call does not
slow each request a little, it creates a **queue**, and a queue is a tail.

Two details worth carrying:

- Loop utilisation is 96% — under 100%, so capacity planning says it is fine. At 33 req/s (99%)
  p99 becomes 5.34s. **The cliff is not gradual.**
- With perfectly regular arrivals a queue below 100% utilisation never builds at all. It needs
  **bursty** traffic — which is exactly why a constant-rate load test misses this and production
  does not.

---

## 5. Why the dashboard missed it

With 2% of requests stalling at 25s: mean 2.08s, p50 1.43s, p95 **3.95s**, p99 25.00s.

The mean moved 27%, p50 not at all, and **even p95 looks healthy**. A 2% failure rate is invisible
to every percentile below the 98th, which is most dashboards.

---

## 6. What should have caught it

| Gate | Catches it? | Why |
|---|---|---|
| p50 only | no | p50 never moved |
| Mean latency | no | a 2% tail barely moves a mean |
| p95 | no | the stall is above the 95th percentile |
| **p99, per provider and model** | **yes** | fails, and names the slice |
| **Error taxonomy, timeouts separately** | **yes** | timeout count jumps, 5xx flat |
| **Load test measuring the tail under concurrency** | **yes** | the only one that catches the blocking call |

---

## The follow-ups, answered

**1. What does an unchanged p50 tell you?**

That this is not a throughput or capacity problem, and adding instances will not help. Queueing
affects everything, so a capacity issue drags the median with it. An unchanged median with a
blown tail means a *subset* of requests is hitting something the rest are not — a specific
provider, model, tenant, endpoint, or code path. It converts the investigation from "why is
everything slow" to "which requests are different", which is a much smaller question.

**2. Give me your triage order.**

Slice first — provider, model, tenant, endpoint — because a tail is a subset by definition and
finding the subset is often the whole answer. Then check what shipped, **including config**:
timeouts, retry policy, pool sizes, feature flags. Then the specific candidates in rough order of
likelihood: a timeout or retry change, a new synchronous call in the path, retrieval parameters,
prompt length, pool exhaustion, and event-loop blocking. I would also look at the *shape* of the
tail early, because clustered and smooth point at different families.

**3. 25 seconds is suspiciously round. What does that suggest?**

Arithmetic rather than contention. Contention produces a smooth stretch; a cluster at a round
number is almost always attempts × timeout, plus backoff. Three attempts at eight seconds with
two half-second backoffs is exactly 25. So the first thing I check is the retry and timeout
configuration, and if the numbers multiply out to the observed p99 I have found it without
touching a profiler.

**4. How can removing a timeout make things slower?**

Because a timeout is what converts a hang into a fast failure. With a 3s timeout, a wedged
dependency costs 3s and then you fall back. Remove it, or raise it to 30s, and the same wedge
costs 30s — and if there are retries, several multiples of that. Nothing got slower; the failure
just stopped being bounded. This is a common and counter-intuitive regression, and it is why
"we removed a timeout that was firing too often" deserves scrutiny: the timeout firing was a
symptom, and removing it hid the symptom while lengthening the tail.

**5. A blocking call in an `async def`. What does that look like in metrics?**

A tail blowout with an unchanged median, falling throughput, and CPU that looks unremarkable
because the blocking work is small. The signature is that latency degrades **non-linearly with
concurrency** — fine in staging with one request, fine at low traffic, catastrophic at peak. In
the simulation, 30ms of CPU at 96% loop utilisation triples p99 while p50 moves a third. If you
have event-loop lag instrumentation, that is the metric that names it immediately; without it,
the tell is that the regression does not reproduce until you apply concurrent load.

**6. Retrieval got better and latency got worse.**

Almost certainly the recall/latency dial. Someone raised `numCandidates` or `ef_search`, or
increased the number of chunks retrieved. Both improve recall and both cost time — and the chunk
count costs twice, because more chunks means a longer prompt, which means a longer
time-to-first-token. That second effect is the one people miss, and it hits the tail harder than
the median because prompt length varies. The fix is to treat those parameters as a **budgeted
trade** with p99 as the constraint, rather than as a quality setting to be turned up.

**7. Why did the load test not catch this?**

Three usual reasons, and all three are worth stating. It measured the **average**, so a 2% tail
was invisible. It ran at **constant arrival rate**, and a queue below 100% utilisation never
builds with perfectly regular arrivals — you need burstiness, which real traffic has and a
generator's default does not. And it ran at **low concurrency**, so the event-loop blocking never
manifested. A load test that reports mean latency at a steady rate is close to useless for tail
regressions.

**8. What should be in the deploy gate?**

**p99, sliced** by provider, model and endpoint — an aggregate p99 hides a regression confined to
one slice. **Error taxonomy**, with timeouts counted separately from 5xx, since a timeout spike
and a server-error spike are different incidents and are indistinguishable once merged into
"errors". A **canary with tail-latency guardrails**, so a small percentage of traffic reveals it
before everyone gets it. And a **load test that measures the tail under bursty concurrency**,
which is the only gate that catches the async-blocking class at all.

**9. p99 fine, p99.9 terrible. Do you care?**

It depends on what a request is and who is behind it, and the honest answer names the trade. At a
million requests a day, p99.9 is a thousand requests — if each is a user-facing page load, that is
a thousand people having a bad day, and yes. If they are retryable background calls, largely no.
The case where p99.9 matters far more than its share suggests is **fan-out**: if one user action
makes twenty backend calls, then a p99.9 per call is roughly a 2% chance that user sees the worst
case, and the tail becomes the median experience. So I would ask what the fan-out is before
deciding.

---

## One-line summary

An unchanged p50 rules out capacity and means a subset of requests is affected, so slice before
theorising; a tail clustered at a round number is attempts × timeout arithmetic rather than
contention; three of the likely causes are config rather than code; and a blocking call in an
async handler creates a queue rather than added latency, which is invisible without bursty
concurrent load — so the gate is p99 per slice, timeouts taxonomised separately, and a load test
that measures the tail.

---

## The trap answer to avoid

Adding instances. It is the reflex, and the unchanged p50 already ruled it out before you started.
The second trap is going straight to the code diff when three of the five likely causes are
configuration — timeouts, retries, retrieval parameters — and the deploy that changed them may
contain no relevant code at all. The third is trusting a load test that reports mean latency at a
constant arrival rate, which by construction cannot see either the tail or the queueing that
produced it.
