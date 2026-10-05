# Real-time voice at 50k concurrent — explained

> Topic 4 (`04-voice-custom-llm/`) covers the custom-LLM inversion and the credential
> boundary — *how* your server ends up inside the vendor's call loop. This is the scale
> problem: what changes when there are fifty thousand of those loops at once.

---

## 1. The numbers force the design

50,000 concurrent calls. A caller speaks roughly once every 8 seconds, and an average call
runs about 3 minutes.

- **6,250 LLM turns per second.** Two orders of magnitude past a busy RAG chatbot.
- **Five metered vendors per call** — STT, LLM, TTS, avatar, telephony — all billed per
  minute or per token, all with their own concurrency quota.
- **A sub-second round trip**, consumed *serially*, with no stage you can overlap except by
  changing the design.

Say the cost out loud early. At this volume it is not a finance footnote, it is a design
constraint that arrives within hours of the launch.

---

## 2. Say this before anything else: voice cannot queue

Every scaling reflex you have was built for systems that can trade latency for capacity.
Overloaded? Queue it. Slow? Batch it. Failed? Retry it. All three are correct for chat and
all three are wrong here.

A chat user who waits four seconds got a slow answer. A **voice** user who waits four seconds
got *silence*, decided the line was dead, and started talking over the reply. The turn was not
delayed, it was **lost** — and the recovery attempt makes it worse, because now two people are
talking.

That single sentence — *voice cannot queue* — is the thing the interviewer is listening for.
Everything below is a consequence of it.

`solution.py §2` prices it: on a 3-tick spike to 180% of capacity, with enough total capacity
across the window, a queue serves **100%** of chat turns and voice still loses **25%**. And
that is the *favourable* case for queueing. Against a sustained shortfall the queue serves no
more than voice does — it just hides the shortfall in a backlog that grows without bound.

---

## 3. The layers, each named by the failure it prevents

**Stream into TTS, do not wait for the response** — *prevents:* spending your entire budget on
tokens nobody has heard yet. Feed partial LLM output into TTS at the first clause boundary.
`solution.py §3`: this alone removes **700 ms** at p50 and takes a 1,390 ms turn to 690 ms.
Largest single win in the system, and it costs nothing but plumbing.

**Autoscale on concurrent sessions, not CPU** — *prevents:* the autoscaler scaling *in* during
an outage. A voice server is waiting on sockets, not burning cycles. `solution.py §1`: the
CPU-scaled fleet sits at 60% CPU and **125% of its session limit** at the same instant. CPU is
not the saturating resource, so holding it at target tells you nothing.

**Per-tenant concurrency caps** — *prevents:* one tenant's campaign becoming everyone's outage.
`solution.py §4`: with first-come allocation, one tenant takes the entire vendor quota and two
others get **zero**. The cap is not a fairness policy, it is blast-radius control.

**Regional edge deployment** — *prevents:* paying a fifth of your budget for the speed of
light. A cross-continent round trip is ~200 ms of a 1,000 ms budget, spent on nothing. This is
the one lever that is purely geographic; no amount of engineering recovers it.

**Warm pools, health-gated before routing** — *prevents:* every deploy being a wave of dropped
calls. A cold start that cost you one bad call in the pilot is a rolling outage at 50k.

**A smaller, faster model on the voice path** — *prevents:* buying quality nobody can hear.
Spoken answers are short and conversational. 200 ms beats a marginal quality gain that does
not survive text-to-speech.

**Degrade to text, explicitly** — *prevents:* the two worse options. When saturated, do not
degrade audio quality and do not add latency. Both make the product feel broken. Falling back
to text is honest, still useful, and — importantly — a state you can *name* in the UI.

---

## 4. The turn budget is serial, and that is the whole problem

```
STT finalise → retrieval → LLM first token → TTS first audio → network RTT
```

Nothing here overlaps. There is no stage you can move off the critical path without changing
what the system does. Compare it to a web request, where you fan out to four services in
parallel and pay the max, not the sum — here you pay the **sum**, every turn.

At p50 the streamed path is 690 ms and comfortable. At p99 it is **1,620 ms and over budget**
(`solution.py §3`). That gap is the entire operational story of a voice system: the average is
always fine and the tail is what users describe as "laggy".

Retrieval is the stage to look at hardest. At p99 it is **310 ms of a 1,000 ms budget**. That
number, not a principle, is what decides whether RAG stays inside the turn or moves out of it.

---

## 5. What breaks first, in order

| # | Breaks | Why it is first |
|---|---|---|
| 1 | **Vendor concurrency quota** | STT/TTS/avatar cap concurrent streams well before your compute runs out. `solution.py §4`: TTS binds at 20,000 of the 50,000 you need. You cannot deploy your way out of a contract. |
| 2 | **Cost** | Five metered vendors. A business stop, not a technical one, and it arrives in hours. |
| 3 | **p99 turn latency** | The tail *is* the experience. Averages hide it completely. |
| 4 | **Cold starts and deploys** | Any restart under load is a wave of dropped calls. |
| 5 | **Retrieval latency** | Now inside a sub-second budget, so ANN parameters become load-bearing rather than a tuning detail. |

Note that **three of the top five get worse, not better, as you add servers.** That is the
signature of this problem and worth saying explicitly.

---

## The follow-ups, answered

**1. Your autoscaler sees 12% CPU and scales in. Calls start dropping. Explain.**

CPU is not the saturating resource. A voice server holds open sockets and waits — on STT, on
the model, on TTS. At full session capacity it can still look almost idle. The scale-in rule
fires on exactly the condition that is normal here, so it removes capacity during an outage.
Scale on concurrent sessions with headroom, and keep CPU only as a *secondary* alarm for the
case where something is genuinely burning cycles.

**2. Retrieval takes 300 ms at p99. Does it stay in the turn?**

Depends on what is left. At p99 the rest of the streamed path is ~1,310 ms against a 1,000 ms
budget, so no — not as it stands. Three honest options, in order of preference: (a) **prefetch
speculatively** on the partial transcript while the caller is still speaking, so retrieval
overlaps STT instead of following it; (b) **cache aggressively** — voice questions repeat far
more than chat ones; (c) **drop retrieval from the first turn**, answer from the persona brief,
and enrich on the follow-up. What you must not do is leave a 310 ms p99 in a serial chain and
call it fine because the p50 is 90 ms.

**3. The TTS vendor caps you at 20,000 concurrent streams. You need 50,000. Now what?**

Accept first that this is not an engineering problem, and say so. Then: negotiate the quota
(lead time, weeks); add a **second TTS vendor** and route across both, which needs a voice
abstraction you should have anyway; bring a **self-hosted TTS** up for the low-value tiers and
keep the premium vendor for the ones that matter; and until any of that lands, **cap admission**
so you serve 20,000 calls well instead of 50,000 badly. The failure mode to avoid is accepting
all 50,000 and letting the vendor reject a random third of them mid-call.

**4. Why can you not solve a load spike with a queue?**

Because a queue trades latency for capacity, and voice has no latency to trade. The listener
interprets delay as a dropped call and starts talking, so a turn delivered late is worse than
one never delivered — you now have to handle barge-in on a reply nobody wanted. `solution.py §2`
shows the arithmetic: same spike, same capacity, chat recovers fully and voice loses 25%
permanently. What replaces the queue is **admission control** — decide at call setup whether
you can serve this call for its whole duration, and if not, say so before it starts.

**5. You deploy at peak. What happens to the calls in flight?**

With a naive rolling deploy: every terminated pod drops its live calls, mid-sentence. What
should happen is **connection draining** — stop routing new calls to the pod, let existing ones
finish (bounded by a max call length), then terminate. That makes a deploy take as long as your
longest call, which is the actual cost of real-time state and is worth paying. Combine with
warm pools so the replacement is health-gated before it takes traffic. And deploy off-peak
anyway; "we can deploy any time" is not a hill worth dying on for a voice product.

**6. One tenant launches a campaign and consumes 80% of capacity.**

Per-tenant concurrency caps, enforced at admission. `solution.py §4` shows the two worlds: with
first-come allocation one tenant takes the entire quota and the others get zero; with caps
everyone keeps their floor. Set the cap as a **guaranteed floor plus opportunistic burst** —
each tenant is always able to reach its floor, and spare capacity above the sum of floors is
lent out and reclaimed first. Pair it with a per-tenant budget circuit breaker, because the
tenant hitting its concurrency cap is usually also the one about to hit its cost ceiling.

**7. p99 time-to-first-audio doubles but the average is flat. Where do you look first?**

A flat average with a doubled tail means a *subset* of turns changed, not the whole system.
So look for something that partitions traffic: one region, one vendor endpoint, one model
version, one pod that came up without a warm cache, one tenant whose corpus grew and pushed
their ANN search into a slower path. Break p99 down by each of those dimensions in turn — the
one where the tail is concentrated is your answer. Do not start by profiling the median path;
by construction, it did not change.

**8. Cost per minute rises 40% with no traffic change.**

Something in the per-call mix changed. Candidates in the order I would check them: a **model
version bump** on the platform side (silent, and the most common cause); **longer responses**
because a prompt changed, which costs you twice since TTS is billed per character; **retry
storms** against a flaky vendor, invisible in call counts but very visible in vendor bills;
**a fallback path** engaging more often and routing to a pricier model; or the avatar attach
rate rising because a client enabled video. Per-call, per-vendor metering is what makes this a
ten-minute query instead of a week. Without it you are guessing.

**9. Contrast the degradation ladder here with a chat assistant's.**

Chat degrades along **quality**: smaller model, fewer retrieved chunks, no reranking, finally
a canned response. Every rung is invisible and the user still gets an answer. Voice cannot use
that ladder, because the rungs that help chat — waiting, retrying, queueing — are precisely the
ones that break a call. The voice ladder degrades along **modality and admission**: shorten the
answer, drop retrieval, drop the avatar, fall back to text, and finally refuse the call at
setup with an honest message. The last rung is the important one: for chat, refusing service is
the worst outcome; for voice, refusing *before the call starts* is far better than dropping it
halfway through.

---

## One-line summary

Voice is the one system where you cannot trade latency for capacity, so every chat reflex —
queue, batch, retry, scale on CPU — inverts; the budget is serial and sub-second, the real
ceiling is a vendor's concurrency quota rather than your compute, and the only honest response
to overload is to degrade the modality or refuse admission before the call starts.

---

## The trap answer to avoid

Treating it as a chat system with audio on the front. It sounds reasonable — "we'll queue
turns, autoscale on CPU, and retry failures" — and every clause is a production incident. The
tell is reaching for a queue. The second trap is quieter: assuming your own compute is the
constraint, and answering the whole question with horizontal scaling. Three of the top five
failure modes get *worse* as you add servers, and the first one is a contract you cannot deploy
your way out of.
