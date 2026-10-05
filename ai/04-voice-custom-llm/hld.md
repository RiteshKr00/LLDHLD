# Voice at scale — 50k concurrent calls

## 1. The constraint is different from every other system

Chat can queue. **Voice cannot.** There's a hard real-time budget — roughly sub-second round
trip to feel natural — and it's consumed **serially**:

```
STT finalise → retrieval → LLM first token → TTS first audio → network
```

Every stage is in the critical path. You cannot batch, you cannot queue, and you cannot hide
latency behind a spinner.

## 2. Estimate

50k concurrent calls. If a turn is ~4s of wall clock and a call averages 3 min:

- concurrent **turns** in flight ≈ 50k / (turn cadence ~8s) ≈ **6,250 QPS of LLM turns**
- that is **two orders of magnitude** past the RAG chatbot case
- five paid providers per call → cost is the binding constraint, not compute

Say the cost number out loud. Voice is priced per minute across STT, TTS, avatar, LLM and the
platform. 50k concurrent for an hour is an enormous bill, and **nobody scales this without
per-tenant concurrency caps.**

## 3. Levers

**1 · Stream everything, including into TTS.** Don't wait for a complete LLM response —
feed partial tokens into TTS as they arrive. This is the single biggest perceived-latency win
because time-to-first-audio drops from full-response to first-sentence.

**2 · Regional edge deployment.** Network RTT is a fixed tax you can only fix geographically.
A 200ms cross-continent round trip is a quarter of your budget spent on nothing.

**3 · Autoscale on concurrent sessions, not CPU.** A voice server is mostly waiting; CPU looks
idle while it's fully saturated on connections. Scaling on CPU under-provisions catastrophically.

**4 · Connection-level backpressure with graceful degradation.** When saturated, do **not**
degrade audio quality or add latency — **fall back to text**, which is honest and still
useful. Degrading a real-time voice call is worse than not offering it.

**5 · Warm pools.** Your own cold start killed the first call after each deploy at pilot
scale; at 50k it's a continuous outage. Pre-warm and health-gate before routing traffic.

**6 · Smaller/faster model on the voice path.** Voice answers are short and conversational.
A model tuned for latency beats a bigger one — and a 200ms improvement is worth more here
than a marginal quality gain nobody notices in speech.

## 4. Cost control — where your existing work pays off

Per-call metering across five providers is the **prerequisite** for any of this. With it you
can: per-tenant concurrency caps, per-tenant monthly budgets with a circuit breaker, and
degrade-to-text when a tenant crosses its cap rather than cutting them off.

Say this explicitly: *"Metering is observability; the enforcement layer on top is what I
haven't built, and at this scale it's mandatory."*

## 5. What breaks first, in order

| # | Breaks | Why |
|---|---|---|
| 1 | **Provider concurrency quotas** | STT/TTS/avatar vendors cap concurrent streams before you hit compute limits |
| 2 | **Cost** | a business stop, not a technical one — and it arrives fast |
| 3 | **Tail latency** | p99 turn latency is what users experience as "it's laggy", and averages hide it |
| 4 | **Cold starts / deploys** | any restart during load is a wave of dropped calls |
| 5 | **Retrieval latency** | now inside a sub-second budget, so ANN params become load-bearing |

## 6. Observability specific to voice

**p99 time-to-first-audio** (not average — the tail is the experience) · turn-completion rate ·
barge-in false-positive rate · re-fire rate · dropped-call rate by cause · **cost per minute
per tenant** · STT confidence distribution (a drop means audio quality or accent coverage
problems, not a code bug).
